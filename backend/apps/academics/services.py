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
    Lock order: PaperOffering -> associated programme mappings -> validation -> persistence.
    Ensures:
    1. Lock-order discipline: acquires select_for_update() on PaperOffering row first.
    2. Acquires select_for_update() on existing PaperProgrammeMapping rows in deterministic PK order.
    3. All programmes pre-validated BEFORE modifying any database records.
    4. Cross-college isolation and duration coverage verified via validate_paper_programme_mapping.
    5. Transaction atomicity: failed replacement preserves existing mappings.
    6. Invariant: is_common_paper flag is maintained and persisted atomically.
    """
    # Exclusively lock the PaperOffering row first to prevent race conditions with concurrent updates
    locked_offering = PaperOffering.objects.select_for_update().get(pk=paper_offering.pk)
    # Lock existing programme mappings in deterministic PK order
    existing_mappings = list(
        PaperProgrammeMapping.objects.select_for_update()
        .filter(paper_offering=locked_offering)
        .order_by("pk")
    )
    prog_list = list(programmes)

    # Pre-validate all programmes before performing any deletions or mutations
    for prog in prog_list:
        validate_paper_programme_mapping(locked_offering, prog)

    if replace:
        PaperProgrammeMapping.objects.filter(paper_offering=locked_offering).delete()

    mappings = []
    for prog in prog_list:
        mapping, _ = PaperProgrammeMapping.objects.get_or_create(
            paper_offering=locked_offering,
            programme=prog,
        )
        mappings.append(mapping)

    # Invariant: If mappings exist, offering must be marked as common paper
    if mappings and not locked_offering.is_common_paper:
        locked_offering.is_common_paper = True
        locked_offering.save(update_fields=["is_common_paper"])

    return mappings


@transaction.atomic
def update_paper_offering(
    *,
    paper_offering_id: int,
    validated_data: dict,
) -> PaperOffering:
    """
    Safely updates an existing PaperOffering under strict concurrency control.
    Lock order: PaperOffering -> associated programme mappings -> validation -> persistence.

    Guarantees:
    1. Acquires select_for_update() on the PaperOffering row first.
    2. Loads authoritative persisted database state while holding the lock.
    3. Acquires select_for_update() on associated PaperProgrammeMapping rows in deterministic PK order.
    4. Merges only explicitly supplied fields from validated_data onto the locked record.
    5. Preserves concurrent changes to any fields not explicitly included in validated_data.
    6. Validates the common-paper invariant against current persisted mappings.
    7. Revalidates existing programme mappings against the proposed semester (duration coverage and college isolation).
    8. Revalidates complete proposed academic state via validate_paper_offering_relationships.
    9. Persists the freshly locked object, never a stale serializer instance.
    """
    # 1. Exclusively lock the PaperOffering row
    locked_offering = PaperOffering.objects.select_for_update().get(pk=paper_offering_id)

    # 2. Exclusively lock associated programme mappings in deterministic PK order
    existing_mappings = list(
        PaperProgrammeMapping.objects.select_for_update()
        .filter(paper_offering=locked_offering)
        .select_related("programme")
        .order_by("pk")
    )

    # 3. Determine proposed values (merge validated_data onto locked record)
    proposed_session = validated_data.get("academic_session", locked_offering.academic_session)
    proposed_semester = validated_data.get("semester", locked_offering.semester)
    proposed_subject = validated_data.get("subject", locked_offering.subject)
    proposed_category = validated_data.get("subject_category", locked_offering.subject_category)
    proposed_credits = validated_data.get("credits", locked_offering.credits)
    proposed_int_marks = validated_data.get("max_marks_internal", locked_offering.max_marks_internal)
    proposed_ext_marks = validated_data.get("max_marks_external", locked_offering.max_marks_external)
    proposed_pass_marks = validated_data.get("pass_marks_external", locked_offering.pass_marks_external)

    # If is_common_paper was explicitly supplied, use it; otherwise preserve current database state
    proposed_is_common = (
        validated_data["is_common_paper"]
        if "is_common_paper" in validated_data
        else locked_offering.is_common_paper
    )

    # 4. Invariant: Common-paper flag check against current mappings
    if existing_mappings:
        if not proposed_is_common:
            raise ValidationError({
                "is_common_paper": (
                    "Cannot set is_common_paper to False while programme mappings exist. "
                    "Remove all programme mappings first."
                )
            })
        proposed_is_common = True

    # 5. Invariant: Semester change mapping revalidation
    if existing_mappings:
        sem_num = proposed_semester.semester_number
        for mapping in existing_mappings:
            prog = mapping.programme
            if prog.college_id != proposed_session.college_id:
                raise ValidationError({
                    "semester": (
                        f"Mapped programme '{prog.code}' belongs to College ID {prog.college_id}, "
                        f"which does not match academic session College ID {proposed_session.college_id}."
                    )
                })
            if prog.duration_semesters < sem_num:
                raise ValidationError({
                    "semester": (
                        f"Cannot move paper offering to semester {sem_num}: mapped programme "
                        f"'{prog.code}' duration ({prog.duration_semesters} sem) does not cover "
                        f"proposed semester ({sem_num}). Remove or update incompatible programme mappings first."
                    )
                })

    # 6. Revalidate complete proposed academic state
    validate_paper_offering_relationships(
        academic_session=proposed_session,
        semester=proposed_semester,
        subject=proposed_subject,
        subject_category=proposed_category,
        credits=proposed_credits,
        max_marks_internal=proposed_int_marks,
        max_marks_external=proposed_ext_marks,
        pass_marks_external=proposed_pass_marks,
    )

    # 7. Apply explicitly supplied fields onto the locked record
    for field, val in validated_data.items():
        setattr(locked_offering, field, val)

    # Ensure invariant is strictly reflected on the object
    if existing_mappings:
        locked_offering.is_common_paper = True

    locked_offering.full_clean()
    locked_offering.save()
    return locked_offering


def check_institutional_admin_authority(user) -> None:
    """Validates that acting user is authenticated, active, and holds administrator privileges."""
    if user is None or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        raise PermissionDenied("Authenticated active user required for institutional configuration.")

    user_role = getattr(user, "role", None)
    if user_role in (RoleChoices.STUDENT, RoleChoices.FACULTY):
        raise PermissionDenied("Student and faculty accounts cannot modify institutional configuration.")

    is_admin = (
        user_role in (RoleChoices.ADMIN, RoleChoices.SUPERADMIN)
        or getattr(user, "is_superuser", False)
        or (hasattr(user, "has_role") and user.has_role("COLLEGE_SUPERADMIN", "EXAM_OFFICER"))
    )
    if not is_admin:
        raise PermissionDenied("Administrator privileges required for institutional configuration.")


def check_institutional_superadmin_authority(user, message: Optional[str] = None) -> None:
    """Validates that acting user holds superadministrator privileges for sensitive operations."""
    check_institutional_admin_authority(user)
    user_role = getattr(user, "role", None)
    is_superadmin = (
        user_role == RoleChoices.SUPERADMIN
        or getattr(user, "is_superuser", False)
        or (hasattr(user, "has_role") and user.has_role("COLLEGE_SUPERADMIN"))
    ) and user_role not in (RoleChoices.STUDENT, RoleChoices.FACULTY)
    if not is_superadmin:
        raise PermissionDenied(
            message or "Superadministrator privileges required for sensitive institutional configuration."
        )


@transaction.atomic
def set_institutional_config(
    *,
    college: College,
    config_key: str,
    config_value: str,
    data_type: str = ConfigDataType.STRING,
    is_sensitive: bool = False,
    description: Optional[str] = None,
    user,
) -> InstitutionalConfig:
    """
    Creates or updates an institutional configuration key with type validation and mandatory RBAC checks.
    Lock order: College -> InstitutionalConfig -> authorization recheck -> validation -> persistence.
    """
    check_institutional_admin_authority(user)

    # 1. Lock College row first (coordination point for all configuration mutations in this college)
    locked_college = College.objects.select_for_update().get(pk=college.pk)

    # 2. Lock InstitutionalConfig row under college lock if exists
    key_clean = config_key.strip()
    existing = InstitutionalConfig.objects.select_for_update().filter(
        college=locked_college, config_key=key_clean
    ).first()
    existing_sensitive = existing.is_sensitive if existing else False

    # 3. Authorization recheck under lock
    if is_sensitive or existing_sensitive:
        check_institutional_superadmin_authority(
            user,
            message="Superadministrator privileges required for sensitive institutional configuration."
        )

    if existing:
        config = existing
        config.config_value = config_value
        config.data_type = data_type
        config.is_sensitive = is_sensitive
        if description is not None:
            config.description = description
        config.updated_by = user
    else:
        config = InstitutionalConfig(
            college=locked_college,
            config_key=key_clean,
            config_value=config_value,
            data_type=data_type,
            is_sensitive=is_sensitive,
            description=description,
            updated_by=user,
        )

    config.full_clean()
    config.save()
    return config


@transaction.atomic
def create_institutional_config(
    *,
    college_id: int,
    validated_data: dict,
    user,
) -> InstitutionalConfig:
    """
    Creates an institutional configuration under consistent row locks:
    College lock -> InstitutionalConfig check under lock -> authorization recheck -> validation -> persistence.
    """
    check_institutional_admin_authority(user)

    # 1. Lock College row first
    locked_college = College.objects.select_for_update().get(pk=college_id)

    # 2. Check under lock if key already exists
    key_clean = validated_data["config_key"].strip()
    existing = InstitutionalConfig.objects.select_for_update().filter(
        college=locked_college, config_key=key_clean
    ).first()

    existing_sensitive = existing.is_sensitive if existing else False
    proposed_sensitive = validated_data.get("is_sensitive", False)

    # 3. Authorization recheck
    if existing_sensitive or proposed_sensitive:
        check_institutional_superadmin_authority(
            user,
            message="Superadministrator privileges required to create sensitive institutional configuration."
        )

    if existing:
        raise ValidationError({
            "config_key": f"Institutional config with key '{key_clean}' already exists for this college."
        })

    config = InstitutionalConfig(
        college=locked_college,
        config_key=key_clean,
        config_value=validated_data["config_value"],
        data_type=validated_data.get("data_type", ConfigDataType.STRING),
        is_sensitive=proposed_sensitive,
        description=validated_data.get("description"),
        updated_by=user,
    )
    config.full_clean()
    config.save()
    return config


@transaction.atomic
def update_institutional_config(
    *,
    config_id: int,
    validated_data: dict,
    user,
) -> InstitutionalConfig:
    """
    Updates an institutional configuration under consistent row locks:
    College lock -> InstitutionalConfig lock -> authorization recheck -> validation -> persistence.
    """
    check_institutional_admin_authority(user)

    # 1. Fetch college_id
    initial = InstitutionalConfig.objects.values("college_id").get(pk=config_id)

    # 2. Lock College row first
    locked_college = College.objects.select_for_update().get(pk=initial["college_id"])

    # 3. Lock InstitutionalConfig row under college lock
    locked_config = InstitutionalConfig.objects.select_for_update().get(
        pk=config_id, college=locked_college
    )

    existing_sensitive = locked_config.is_sensitive
    proposed_sensitive = validated_data.get("is_sensitive", existing_sensitive)

    # 4. Authorization recheck: both existing and proposed sensitivity under lock
    if existing_sensitive or proposed_sensitive:
        check_institutional_superadmin_authority(
            user,
            message="Superadministrator privileges required to modify sensitive institutional configuration."
        )

    # 5. Apply explicitly supplied fields
    for field in ("config_key", "config_value", "data_type", "is_sensitive", "description"):
        if field in validated_data:
            setattr(locked_config, field, validated_data[field])

    locked_config.updated_by = user
    locked_config.full_clean()
    locked_config.save()
    return locked_config


@transaction.atomic
def delete_institutional_config(
    *,
    config_id: int,
    user,
) -> None:
    """
    Deletes an institutional configuration under consistent row locks:
    College lock -> InstitutionalConfig lock -> authorization recheck -> deletion.
    """
    check_institutional_admin_authority(user)

    # 1. Fetch college_id
    initial = InstitutionalConfig.objects.values("college_id").get(pk=config_id)

    # 2. Lock College row first
    locked_college = College.objects.select_for_update().get(pk=initial["college_id"])

    # 3. Lock InstitutionalConfig row under college lock
    locked_config = InstitutionalConfig.objects.select_for_update().get(
        pk=config_id, college=locked_college
    )

    # 4. Authoritative sensitivity check under lock
    if locked_config.is_sensitive:
        check_institutional_superadmin_authority(
            user,
            message="Superadministrator privileges required to delete sensitive institutional configuration."
        )

    locked_config.delete()
