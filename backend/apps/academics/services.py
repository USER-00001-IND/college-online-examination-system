"""
Academic Management Service Layer.
Enforces institutional rules, cross-college relational integrity, and atomic multi-entity mutations.
"""

from decimal import Decimal
from typing import Iterable, List, Optional
from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from apps.academics.models import (
    AcademicSession,
    College,
    ConfigDataType,
    Department,
    InstitutionalConfig,
    PaperOffering,
    PaperProgrammeMapping,
    Programme,
    Semester,
    Subject,
    SubjectCategory,
)
from apps.accounts.models import RoleChoices


def validate_academic_session_dates(start_date, end_date) -> None:
    """Validates that academic session start date strictly precedes end date."""
    if not start_date or not end_date:
        raise ValidationError("Both start_date and end_date are required.")
    if start_date >= end_date:
        raise ValidationError({"end_date": "Academic session start_date must precede end_date."})


@transaction.atomic
def set_current_academic_session(college: College, session: AcademicSession) -> AcademicSession:
    """
    Atomically designates a session as current for a college, clearing current status
    from any other sessions in that college.
    Acquires an exclusive row lock on the College record to serialize concurrent switches.
    """
    # Exclusively lock the College record to coordinate concurrent session activation under MySQL InnoDB
    locked_college = College.objects.select_for_update().get(pk=college.pk)

    if session.college_id != locked_college.pk:
        raise ValidationError({"session": "Session does not belong to the specified college."})

    # Clear current flag on any other sessions of this college
    AcademicSession.objects.filter(college=locked_college, is_current=True).exclude(pk=session.pk).update(is_current=False)
    session.is_current = True
    session.save(update_fields=["is_current"])
    return session


def validate_paper_offering_relationships(
    academic_session: AcademicSession,
    semester: Semester,
    subject: Subject,
    subject_category: SubjectCategory,
    credits: Decimal,
    max_marks_internal: Decimal,
    max_marks_external: Decimal,
    pass_marks_external: Decimal,
) -> None:
    """
    Validates academic hierarchy integrity and cross-college boundaries:
    - Session, Semester Programme, Subject Department, and Subject Category must all belong to the same College.
    - Credits must satisfy non-negative bounds and category credit range [min_credits, max_credits].
    - Marks must be non-negative, and pass_marks_external must not exceed max_marks_external.
    """
    errors = {}
    college_id = academic_session.college_id

    # Cross-college validation
    if semester.programme.college_id != college_id:
        errors["semester"] = "Semester programme does not belong to the same college as the academic session."
    if subject.department.college_id != college_id:
        errors["subject"] = "Subject department does not belong to the same college as the academic session."
    if subject_category.college_id != college_id:
        errors["subject_category"] = "Subject category does not belong to the same college as the academic session."

    # Semester number vs Programme duration check
    if semester.semester_number > semester.programme.duration_semesters:
        errors["semester"] = (
            f"Semester number ({semester.semester_number}) exceeds programme duration "
            f"({semester.programme.duration_semesters})."
        )

    # Numeric bounds
    if credits < Decimal("0.0"):
        errors["credits"] = "Credits cannot be negative."
    elif credits < subject_category.min_credits or credits > subject_category.max_credits:
        errors["credits"] = (
            f"Credits ({credits}) must fall within category '{subject_category.code}' "
            f"range [{subject_category.min_credits}, {subject_category.max_credits}]."
        )

    if max_marks_internal < Decimal("0.0"):
        errors["max_marks_internal"] = "Internal marks cannot be negative."
    if max_marks_external < Decimal("0.0"):
        errors["max_marks_external"] = "External marks cannot be negative."
    if pass_marks_external < Decimal("0.0"):
        errors["pass_marks_external"] = "Pass marks cannot be negative."
    elif max_marks_external >= Decimal("0.0") and pass_marks_external > max_marks_external:
        errors["pass_marks_external"] = "Pass marks cannot exceed maximum external marks."

    if errors:
        raise ValidationError(errors)


@transaction.atomic
def create_paper_offering(
    *,
    academic_session: AcademicSession,
    semester: Semester,
    subject: Subject,
    subject_category: SubjectCategory,
    paper_code: str,
    title: str,
    credits: Decimal,
    is_common_paper: bool = False,
    max_marks_internal: Decimal = Decimal("20.00"),
    max_marks_external: Decimal = Decimal("80.00"),
    pass_marks_external: Decimal = Decimal("28.00"),
    is_active: bool = True,
) -> PaperOffering:
    """
    Creates a new PaperOffering after comprehensive relational integrity validation.
    """
    validate_paper_offering_relationships(
        academic_session=academic_session,
        semester=semester,
        subject=subject,
        subject_category=subject_category,
        credits=credits,
        max_marks_internal=max_marks_internal,
        max_marks_external=max_marks_external,
        pass_marks_external=pass_marks_external,
    )

    offering = PaperOffering(
        academic_session=academic_session,
        semester=semester,
        subject=subject,
        subject_category=subject_category,
        paper_code=paper_code.strip(),
        title=title.strip(),
        credits=credits,
        is_common_paper=is_common_paper,
        max_marks_internal=max_marks_internal,
        max_marks_external=max_marks_external,
        pass_marks_external=pass_marks_external,
        is_active=is_active,
    )
    offering.full_clean()
    offering.save()
    return offering


def validate_paper_programme_mapping(paper_offering: PaperOffering, programme: Programme) -> None:
    """
    Centralized validation of paper-programme mapping invariants:
    1. Cross-college isolation: Programme and PaperOffering must belong to the same College.
    2. Duration coverage: Programme duration must be >= semester number of the PaperOffering.
    """
    college_id = paper_offering.academic_session.college_id
    if programme.college_id != college_id:
        raise ValidationError({
            "programme": (
                f"Programme '{programme.code}' (College ID {programme.college_id}) belongs to a "
                f"different college than PaperOffering '{paper_offering.paper_code}' (College ID {college_id})."
            )
        })

    sem_num = paper_offering.semester.semester_number
    if programme.duration_semesters < sem_num:
        raise ValidationError({
            "programme": (
                f"Programme '{programme.code}' duration ({programme.duration_semesters} sem) does not "
                f"cover offering semester ({sem_num})."
            )
        })


@transaction.atomic
def map_paper_to_programmes(
    paper_offering: PaperOffering,
    programmes: Iterable[Programme],
    *,
    replace: bool = False,
) -> List[PaperProgrammeMapping]:
    """
    Maps a common paper offering to multiple eligible degree programmes.
    Ensures:
    1. All programmes pre-validated BEFORE modifying any database records.
    2. Cross-college isolation and duration coverage verified via validate_paper_programme_mapping.
    3. Transaction atomicity: failed replacement preserves existing mappings.
    4. is_common_paper flag is maintained.
    """
    prog_list = list(programmes)

    # Pre-validate all programmes before performing any deletions or mutations
    for prog in prog_list:
        validate_paper_programme_mapping(paper_offering, prog)

    if replace:
        PaperProgrammeMapping.objects.filter(paper_offering=paper_offering).delete()

    mappings = []
    for prog in prog_list:
        mapping, _ = PaperProgrammeMapping.objects.get_or_create(
            paper_offering=paper_offering,
            programme=prog,
        )
        mappings.append(mapping)

    # Ensure offering is marked as common paper if mapped
    if mappings and not paper_offering.is_common_paper:
        paper_offering.is_common_paper = True
        paper_offering.save(update_fields=["is_common_paper"])

    return mappings


@transaction.atomic
def set_institutional_config(
    *,
    college: College,
    config_key: str,
    config_value: str,
    data_type: str = ConfigDataType.STRING,
    is_sensitive: bool = False,
    description: Optional[str] = None,
    user=None,
    enforce_authorization: bool = True,
) -> InstitutionalConfig:
    """
    Creates or updates an institutional configuration key with type validation and RBAC checks.
    """
    key_clean = config_key.strip()
    existing = InstitutionalConfig.objects.filter(college=college, config_key=key_clean).first()
    existing_sensitive = existing.is_sensitive if existing else False

    if enforce_authorization and user is not None:
        if is_sensitive or existing_sensitive:
            is_superadmin = (
                user.is_authenticated
                and (
                    user.role == RoleChoices.SUPERADMIN
                    or user.is_superuser
                    or (hasattr(user, "has_role") and user.has_role("COLLEGE_SUPERADMIN"))
                )
                and user.role != RoleChoices.STUDENT
                and user.role != RoleChoices.FACULTY
            )
            if not is_superadmin:
                raise PermissionDenied(
                    "Superadministrator privileges required for sensitive institutional configuration."
                )

    if existing:
        config = existing
        config.config_value = config_value
        config.data_type = data_type
        config.is_sensitive = is_sensitive
        if description is not None:
            config.description = description
        if user and user.is_authenticated:
            config.updated_by = user
    else:
        config = InstitutionalConfig(
            college=college,
            config_key=key_clean,
            config_value=config_value,
            data_type=data_type,
            is_sensitive=is_sensitive,
            description=description,
            updated_by=user if (user and user.is_authenticated) else None,
        )

    config.full_clean()
    config.save()
    return config
