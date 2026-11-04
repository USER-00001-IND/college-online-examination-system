"""
Student Management Service Layer.
Enforces atomic self-registration, cryptographic email verification,
administrator approval workflows, and institutional relationship integrity.
"""

import hashlib
import logging
import secrets
from datetime import timedelta
from typing import Optional, Tuple
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import College, Programme
from apps.academics.services import check_institutional_admin_authority, lock_colleges
from apps.accounts.authorization import check_college_operation_authority
from apps.accounts.models import (
    EmailVerification,
    RegistrationApproval,
    RegistrationApprovalStatus,
    RoleChoices,
    User,
)
from apps.students.models import StudentProfile

logger = logging.getLogger('college.students')


class VerificationEmailDeliveryError(Exception):
    """Raised when dispatching account verification email fails."""
    pass


def send_student_verification_email(*, user: User, raw_token: str) -> None:
    """
    Dispatches an email verification message containing instructions and the raw token.
    Fails closed if the email backend fails or encounters a network error.
    Does not log the raw token.
    """
    from django.conf import settings
    from django.core.mail import send_mail

    subject = "College Online Examination System - Verify Your Student Email Address"
    message = (
        f"Dear {user.get_full_name() or user.username},\n\n"
        f"Thank you for registering for the College Online Examination System.\n\n"
        f"Your account username is: {user.username}\n"
        f"Your verification token is: {raw_token}\n\n"
        f"Please verify your email address by submitting this token to the verification endpoint "
        f"or via the student registration portal within 24 hours.\n\n"
        f"Note: Your account will remain pending administrator approval following email verification.\n\n"
        f"Sincerely,\n"
        f"Academic Administration"
    )
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@college.edu')

    try:
        sent_count = send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=[user.email],
            fail_silently=False,
        )
        if sent_count < 1:
            raise VerificationEmailDeliveryError("Email delivery backend did not accept message for recipient.")
    except Exception as exc:
        logger.error(
            "Failed to dispatch verification email to student user_id=%s (error_type=%s)",
            user.pk,
            type(exc).__name__,
            exc_info=False,
        )
        raise VerificationEmailDeliveryError(
            "Email delivery infrastructure unavailable. Verification email could not be delivered."
        ) from exc


@transaction.atomic
def cleanup_unverified_registration(user_id: int) -> bool:
    """
    Atomically cleans up an unverified student registration after email delivery failure.
    Enforces strict safety preconditions under the Unified Registration Lock Hierarchy (Finding R5-C):
    Level 2: User (select_for_update)
    Level 3: RegistrationApproval (select_for_update)
    Level 4: EmailVerification (select_for_update)
    Level 5: StudentProfile (select_for_update)

    Preconditions verified under lock:
    1. User exists, is inactive (is_active is False), and holds primary role STUDENT.
    2. Registration approval exists and remains pending (status is PENDING).
    3. Email verification token exists, was never consumed or verified (is_used is False, verified_at is None).
    4. Student profile exists and links to the same User.

    If any precondition check fails or any required record is missing,
    refuses deletion and returns False.
    Otherwise, atomically deletes related records and user in reverse dependency order, and returns True.
    """
    try:
        user = User.objects.select_for_update().get(pk=user_id)
    except User.DoesNotExist:
        return False

    if user.is_active:
        logger.warning("Refusing cleanup: User %s is already active.", user_id)
        return False

    if user.role != RoleChoices.STUDENT:
        logger.warning("Refusing cleanup: User %s role is '%s', not STUDENT.", user_id, user.role)
        return False

    # Level 3: Check RegistrationApproval under lock (evaluated query)
    approvals = list(RegistrationApproval.objects.select_for_update().filter(user=user))
    if not approvals or any(app.status != RegistrationApprovalStatus.PENDING for app in approvals):
        logger.warning("Refusing cleanup: User %s registration approval is missing or not pending.", user_id)
        return False

    # Level 4: Check EmailVerification under lock (evaluated query)
    verifications = list(EmailVerification.objects.select_for_update().filter(user=user))
    if not verifications or any(ev.is_used or ev.verified_at is not None for ev in verifications):
        logger.warning("Refusing cleanup: User %s verification token was already consumed or verified.", user_id)
        return False

    # Level 5: Check StudentProfile under lock (evaluated query)
    profiles = list(StudentProfile.objects.select_for_update().filter(user=user))
    if not profiles or any(p.user_id != user.pk for p in profiles):
        logger.warning("Refusing cleanup: User %s student profile is missing or inconsistent.", user_id)
        return False

    # Safe to clean up atomically in reverse dependency order
    StudentProfile.objects.filter(user=user).delete()
    EmailVerification.objects.filter(user=user).delete()
    RegistrationApproval.objects.filter(user=user).delete()
    user.delete()
    logger.info("Atomically cleaned up unverified user %s after email dispatch failure.", user_id)
    return True


@transaction.atomic
def register_student(
    *,
    username: str,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    college: College,
    programme: Programme,
    enrollment_number: str,
    registration_year: int,
    phone_number: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    gender: Optional[str] = None,
    guardian_name: Optional[str] = None,
) -> Tuple[User, StudentProfile, str]:
    """
    Atomically registers a new student account, academic profile, registration
    approval request, and cryptographic email verification token.
    The account is created with role=STUDENT and is_active=False.
    """
    username = username.strip()
    email = email.strip().lower()
    enrollment_number = enrollment_number.strip()

    # 1. Coordinate via College row lock
    college_id = college.pk if hasattr(college, 'pk') else int(college)
    lock_colleges(college_id)
    locked_college = College.objects.get(pk=college_id)

    # 2. Institutional relationship boundary verification
    prog_id = programme.pk if hasattr(programme, 'pk') else int(programme)
    locked_prog = Programme.objects.get(pk=prog_id)
    if locked_prog.college_id != locked_college.pk:
        raise ValidationError({
            "programme": f"Programme '{locked_prog.code}' does not belong to college '{locked_college.code}'."
        })

    # 3. Uniqueness checks before creation
    if User.objects.filter(username=username).exists():
        raise ValidationError({"username": "A user with that username already exists."})
    if User.objects.filter(email=email).exists():
        raise ValidationError({"email": "A user with that email already exists."})
    if StudentProfile.objects.filter(enrollment_number=enrollment_number).exists():
        raise ValidationError({"enrollment_number": f"Enrollment number '{enrollment_number}' is already registered."})

    # 4. Password validation
    dummy_user = User(username=username, email=email)
    validate_password(password, user=dummy_user)

    # 5. Atomic record creation
    user = User(
        username=username,
        email=email,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        role=RoleChoices.STUDENT,
        is_active=False,
        is_staff=False,
        is_superuser=False,
    )
    user.set_password(password)
    user.full_clean()
    user.save()

    profile = StudentProfile(
        user=user,
        college=locked_college,
        programme=locked_prog,
        enrollment_number=enrollment_number,
        registration_year=registration_year,
        current_semester=1,
        phone_number=phone_number.strip() if phone_number else None,
        date_of_birth=date_of_birth,
        gender=gender.strip() if gender else None,
        guardian_name=guardian_name.strip() if guardian_name else None,
    )
    profile.full_clean()
    profile.save()

    approval = RegistrationApproval(
        user=user,
        status=RegistrationApprovalStatus.PENDING,
        submitted_at=timezone.now(),
    )
    approval.full_clean()
    approval.save()

    # 6. Cryptographic email verification token generation
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    verification = EmailVerification(
        user=user,
        token_hash=token_hash,
        expires_at=timezone.now() + timedelta(hours=24),
        is_used=False,
    )
    verification.full_clean()
    verification.save()

    return user, profile, raw_token


@transaction.atomic
def verify_email_token(raw_token: str) -> User:
    """
    Validates a cryptographic email verification token and consumes it atomically.
    Follows Unified Registration Lock Hierarchy: Level 2: User -> Level 4: EmailVerification.
    Does NOT activate the account; user remains is_active=False until administrative approval.
    """
    if not raw_token or not raw_token.strip():
        raise ValidationError({"token": "Verification token is required."})

    token_hash = hashlib.sha256(raw_token.strip().encode('utf-8')).hexdigest()
    candidate = EmailVerification.objects.filter(token_hash=token_hash).values("id", "user_id").first()
    if not candidate:
        raise ValidationError({"token": "Invalid verification token."})

    # Acquire row locks in unified hierarchy order
    user = User.objects.select_for_update().get(pk=candidate["user_id"])
    verification = EmailVerification.objects.select_for_update().get(pk=candidate["id"])

    if verification.is_used:
        raise ValidationError({"token": "Verification token has already been used."})

    if timezone.now() > verification.expires_at:
        raise ValidationError({"token": "Verification token has expired (validity is 24 hours)."})

    verification.is_used = True
    verification.verified_at = timezone.now()
    verification.save(update_fields=['is_used', 'verified_at'])

    return user


@transaction.atomic
def review_student_registration(
    *,
    approval_id: int,
    action: str,
    reviewer: User,
    rejection_reason: Optional[str] = None,
) -> RegistrationApproval:
    """
    Performs administrative review on a pending registration approval.
    Enforces Unified Registration Lock Hierarchy and student identity integrity (Finding R5-B):
    Level 1: College Coordination Lock (if applicable)
    Level 2: User (select_for_update)
    Level 3: RegistrationApproval (select_for_update, single-table query)
    Level 4: EmailVerification (select_for_update)
    Level 5: StudentProfile (select_for_update)

    - APPROVE: Requires verified email. Atomically sets approval status to APPROVED
      and user.is_active = True under row lock.
    - REJECT: Atomically sets status to REJECTED with rejection reason and leaves
      user.is_active = False.
    """
    check_institutional_admin_authority(reviewer)

    action = action.upper().strip()
    if action not in ("APPROVE", "REJECT"):
        raise ValidationError({"action": "Action must be 'APPROVE' or 'REJECT'."})

    # 1. Read candidate identifiers without locking (avoids nullable outer-join locks)
    initial = RegistrationApproval.objects.values("id", "user_id", "status").filter(pk=approval_id).first()
    if not initial:
        raise ValidationError({"approval": "Registration approval record not found."})

    target_user_id = initial["user_id"]

    # Cannot approve self
    if target_user_id == reviewer.pk:
        raise PermissionDenied("Administrators cannot approve their own registration requests.")

    # 2. Acquire locks in strict unified hierarchy
    # Level 2: User lock
    user = User.objects.select_for_update().get(pk=target_user_id)

    # Level 3: RegistrationApproval lock (single-table query, no select_related)
    approval = RegistrationApproval.objects.select_for_update().get(pk=approval_id)

    # Level 4: EmailVerification lock
    email_verifications = list(EmailVerification.objects.select_for_update().filter(user=user))

    # Level 5: StudentProfile lock (evaluated single-table query)
    student_profiles = list(StudentProfile.objects.select_for_update().filter(user=user))

    # 3. Revalidate student identity and relationships under lock (Finding R5-B)
    if user.role != RoleChoices.STUDENT:
        raise ValidationError({
            "user": f"User primary role must be '{RoleChoices.STUDENT}'. Found: '{user.role}'."
        })

    if approval.user_id != user.pk:
        raise ValidationError({
            "approval": "Registration approval record does not belong to the target user."
        })

    if not student_profiles or len(student_profiles) != 1:
        raise ValidationError({
            "student_profile": "A valid linked student profile is required to review a registration."
        })
    student_profile = student_profiles[0]

    if student_profile.user_id != user.pk:
        raise ValidationError({
            "student_profile": "Student profile is not linked to the target user."
        })

    if not student_profile.college_id:
        raise ValidationError({
            "college": "Student profile must be associated with an authoritative college."
        })

    if not student_profile.programme_id or student_profile.programme.college_id != student_profile.college_id:
        raise ValidationError({
            "programme": "Student profile programme does not belong to the student's college."
        })

    # Recheck reviewer institutional authority against authoritative student college
    check_college_operation_authority(reviewer, student_profile.college_id, "review_student_registration")

    if approval.status != RegistrationApprovalStatus.PENDING:
        raise ValidationError({
            "status": f"Registration request is already {approval.status} and cannot be reviewed again."
        })

    if action == "APPROVE":
        # Enforce prerequisite: Email must be verified before approval
        is_email_verified = any(ev.is_used for ev in email_verifications)
        if not is_email_verified:
            raise ValidationError({
                "email": "Cannot approve registration before student completes email verification."
            })

        approval.status = RegistrationApprovalStatus.APPROVED
        approval.reviewed_by = reviewer
        approval.reviewed_at = timezone.now()
        approval.rejection_reason = None
        approval.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'rejection_reason'])

        user.is_active = True
        user.save(update_fields=['is_active'])

    elif action == "REJECT":
        reason = (rejection_reason or "").strip()
        if not reason:
            raise ValidationError({"rejection_reason": "A reason must be provided when rejecting a registration."})

        approval.status = RegistrationApprovalStatus.REJECTED
        approval.reviewed_by = reviewer
        approval.reviewed_at = timezone.now()
        approval.rejection_reason = reason
        approval.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'rejection_reason'])

        user.is_active = False
        user.save(update_fields=['is_active'])

    return approval


@transaction.atomic
def update_student_profile(
    *,
    profile_id: int,
    acting_user: User,
    validated_data: dict,
) -> StudentProfile:
    """
    Updates a StudentProfile under row-level lock.
    Enforces authorization:
    - Students can only update personal contact fields (phone_number, guardian_name).
    - Administrators can update current_semester (within programme duration) and personal fields.
    - Institutional fields (college, user, enrollment_number, registration_year) are immutable.
    """
    initial = StudentProfile.objects.values("college_id", "programme_id").get(pk=profile_id)
    lock_colleges(initial["college_id"])

    locked_prog = Programme.objects.select_for_update().get(pk=initial["programme_id"])
    profile = StudentProfile.objects.select_for_update().get(pk=profile_id)
    profile.programme = locked_prog

    is_admin = (
        acting_user.role in (RoleChoices.ADMIN, RoleChoices.SUPERADMIN)
        or acting_user.is_superuser
        or (hasattr(acting_user, "has_role") and acting_user.has_role("COLLEGE_SUPERADMIN", "EXAM_OFFICER"))
    )

    if not is_admin:
        # Student updating their own profile
        if profile.user_id != acting_user.pk:
            raise PermissionDenied("You do not have permission to modify this profile.")

        # Disallow student altering institutional fields
        disallowed_fields = {'college', 'programme', 'enrollment_number', 'registration_year', 'current_semester', 'user'}
        attempted_disallowed = set(validated_data.keys()).intersection(disallowed_fields)
        if attempted_disallowed:
            raise PermissionDenied(f"Students cannot modify institutional fields: {', '.join(sorted(attempted_disallowed))}.")
    else:
        check_college_operation_authority(acting_user, profile.college_id, "update_student_profile")

    # Apply permitted fields
    if is_admin and 'current_semester' in validated_data:
        proposed_sem = validated_data['current_semester']
        if proposed_sem < 1 or proposed_sem > profile.programme.duration_semesters:
            raise ValidationError({
                "current_semester": (
                    f"Current semester ({proposed_sem}) must be between 1 and "
                    f"{profile.programme.duration_semesters} for programme '{profile.programme.code}'."
                )
            })
        profile.current_semester = proposed_sem

    for field in ('phone_number', 'guardian_name', 'gender', 'date_of_birth'):
        if field in validated_data:
            setattr(profile, field, validated_data[field])

    profile.full_clean()
    profile.save()
    return profile
