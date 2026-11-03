"""
Academic Management Service Layer.
Enforces institutional rules, cross-college relational integrity, and atomic multi-entity mutations.
"""

from decimal import Decimal
from typing import Iterable, List, Optional
from django.core.exceptions import ValidationError
from django.db import transaction

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
    """
    if session.college_id != college.id:
        raise ValidationError({"session": "Session does not belong to the specified college."})

    AcademicSession.objects.filter(college=college, is_current=True).exclude(pk=session.pk).update(is_current=False)
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
    1. Cross-college isolation: All programmes must belong to paper_offering's college.
    2. Duration validation: Programme duration must be >= semester number of the offering.
    3. is_common_paper flag is maintained.
    """
    college_id = paper_offering.academic_session.college_id
    mappings = []

    if replace:
        PaperProgrammeMapping.objects.filter(paper_offering=paper_offering).delete()

    for prog in programmes:
        if prog.college_id != college_id:
            raise ValidationError({
                "programmes": f"Programme '{prog.code}' belongs to a different college institution."
            })
        if prog.duration_semesters < paper_offering.semester.semester_number:
            raise ValidationError({
                "programmes": (
                    f"Programme '{prog.code}' duration ({prog.duration_semesters} sem) does not "
                    f"cover offering semester ({paper_offering.semester.semester_number})."
                )
            })

        mapping, created = PaperProgrammeMapping.objects.get_or_create(
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
) -> InstitutionalConfig:
    """
    Creates or updates an institutional configuration key with type validation.
    """
    config, _ = InstitutionalConfig.objects.get_or_create(
        college=college,
        config_key=config_key.strip(),
        defaults={
            "config_value": config_value,
            "data_type": data_type,
            "is_sensitive": is_sensitive,
            "description": description,
            "updated_by": user if (user and user.is_authenticated) else None,
        },
    )
    if not _:
        config.config_value = config_value
        config.data_type = data_type
        config.is_sensitive = is_sensitive
        if description is not None:
            config.description = description
        if user and user.is_authenticated:
            config.updated_by = user

    config.full_clean()
    config.save()
    return config
