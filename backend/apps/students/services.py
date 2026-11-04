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
from apps.accounts.models import (
    EmailVerification,
    RegistrationApproval,
    RegistrationApprovalStatus,
    RoleChoices,
    User,
)
from apps.students.models import StudentProfile

logger = logging.getLogger('college.students')


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
    Does NOT activate the account; user remains is_active=False until administrative approval.
    """
    if not raw_token or not raw_token.strip():
        raise ValidationError({"token": "Verification token is required."})

    token_hash = hashlib.sha256(raw_token.strip().encode('utf-8')).hexdigest()
    verification = (
        EmailVerification.objects.select_for_update()
        .filter(token_hash=token_hash)
        .first()
    )

    if not verification:
        raise ValidationError({"token": "Invalid verification token."})

    if verification.is_used:
        raise ValidationError({"token": "Verification token has already been used."})

    if timezone.now() > verification.expires_at:
        raise ValidationError({"token": "Verification token has expired (validity is 24 hours)."})

    verification.is_used = True
    verification.verified_at = timezone.now()
    verification.save(update_fields=['is_used', 'verified_at'])

    return verification.user


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
    - APPROVE: Requires verified email. Atomically sets approval status to APPROVED
      and user.is_active = True under row lock.
    - REJECT: Atomically sets status to REJECTED with rejection reason and leaves
      user.is_active = False.
    """
    check_institutional_admin_authority(reviewer)

    action = action.upper().strip()
    if action not in ("APPROVE", "REJECT"):
        raise ValidationError({"action": "Action must be 'APPROVE' or 'REJECT'."})

    approval = (
        RegistrationApproval.objects.select_for_update()
        .filter(pk=approval_id)
        .first()
    )
    if not approval:
        raise ValidationError({"approval": "Registration approval record not found."})

    if approval.status != RegistrationApprovalStatus.PENDING:
        raise ValidationError({
            "status": f"Registration request is already {approval.status} and cannot be reviewed again."
        })

    # Cannot approve self
    if approval.user_id == reviewer.pk:
        raise PermissionDenied("Administrators cannot approve their own registration requests.")

    user = User.objects.select_for_update().get(pk=approval.user_id)

    if action == "APPROVE":
        # Enforce prerequisite: Email must be verified before approval
        is_email_verified = EmailVerification.objects.filter(user=user, is_used=True).exists()
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
    profile = StudentProfile.objects.select_for_update().get(pk=profile_id)

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
