"""
Academic Management Service Layer.
Enforces institutional rules, cross-college relational integrity, and atomic multi-entity mutations.
"""

from decimal import Decimal
from typing import Iterable, List, Optional
from django.core.exceptions import ValidationError
from django.db import models, transaction
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
    FacultyAssignmentRole,
    FacultySubjectAssignment,
)
from apps.accounts.models import RoleChoices
from apps.faculty.models import FacultyProfile


def lock_colleges(*college_ids: Optional[int]) -> dict[int, College]:
    """
    Acquires exclusive row locks on College records in deterministic ascending PK order.
    Serves as Level 1 coordination lock across all academic mutations within an institution.
    Eliminates cross-college deadlocks and serializes concurrent academic structure mutations.
    """
    valid_ids = sorted({cid for cid in college_ids if cid is not None})
    if not valid_ids:
        return {}
    locked = {
        c.pk: c
        for c in College.objects.select_for_update().filter(pk__in=valid_ids).order_by("pk")
    }
    for cid in valid_ids:
        if cid not in locked:
            raise ValidationError({"college": f"College ID {cid} not found."})
    return locked


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
    Reloads and exclusively locks the AcademicSession record before verifying institutional ownership.
    """
    candidate_college_id = college.pk if hasattr(college, "pk") else int(college)
    locked_colleges = lock_colleges(candidate_college_id)
    locked_college = locked_colleges[candidate_college_id]

    session_id = session.pk if hasattr(session, "pk") else int(session)
    locked_session = AcademicSession.objects.select_for_update().get(pk=session_id)

    if locked_session.college_id != locked_college.pk:
        raise ValidationError({"session": "Session does not belong to the specified college."})

    # Clear current flag on any other sessions of this authoritative college
    AcademicSession.objects.filter(college=locked_college, is_current=True).exclude(pk=locked_session.pk).update(is_current=False)

    locked_session.is_current = True
    locked_session.save(update_fields=["is_current"])
    return locked_session


def validate_paper_offering_relationships(
    academic_session: AcademicSession,
    semester: Semester,
    subject: Subject,
    subject_category: SubjectCategory,
    credits: Decimal,
    max_marks_internal: Decimal,
    max_marks_external: Decimal,
    pass_marks_external: Decimal,
    *,
    programme: Optional[Programme] = None,
    department: Optional[Department] = None,
) -> None:
    """
    Validates academic hierarchy integrity and cross-college boundaries:
    - Session, Semester Programme, Subject Department, and Subject Category must all belong to the same College.
    - Credits must satisfy non-negative bounds and category credit range [min_credits, max_credits].
    - Marks must be non-negative, and pass_marks_external must not exceed max_marks_external.
    """
    errors = {}
    college_id = academic_session.college_id

    # Authoritative programme resolution
    prog = programme or getattr(semester, "programme", None)
    if prog is None and semester.programme_id:
        prog = Programme.objects.get(pk=semester.programme_id)

    # Authoritative department resolution
    dept = department or getattr(subject, "department", None)
    if dept is None and subject.department_id:
        dept = Department.objects.get(pk=subject.department_id)

    # Cross-college validation against authoritative institutional state
    if prog and prog.college_id != college_id:
        errors["semester"] = "Semester programme does not belong to the same college as the academic session."
    if dept and dept.college_id != college_id:
        errors["subject"] = "Subject department does not belong to the same college as the academic session."
    if subject_category.college_id != college_id:
        errors["subject_category"] = "Subject category does not belong to the same college as the academic session."

    # Semester number vs Programme duration check
    if prog and semester.semester_number > prog.duration_semesters:
        errors["semester"] = (
            f"Semester number ({semester.semester_number}) exceeds programme duration "
            f"({prog.duration_semesters})."
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
    Lock hierarchy:
    1. College (select_for_update in ascending PK order)
    2. Parent academic records (AcademicSession, Semester, Programme, Subject, Department, SubjectCategory)
    3. Authoritative validation
    4. Persistence
    """
    session_id = academic_session.pk
    sem_id = semester.pk
    sub_id = subject.pk
    cat_id = subject_category.pk

    # 1. Identify candidate college IDs from current database state
    candidate_college_ids = set()
    s_cid = AcademicSession.objects.filter(pk=session_id).values_list("college_id", flat=True).first()
    if s_cid:
        candidate_college_ids.add(s_cid)
    sem_cid = Semester.objects.filter(pk=sem_id).values_list("programme__college_id", flat=True).first()
    if sem_cid:
        candidate_college_ids.add(sem_cid)
    sub_cid = Subject.objects.filter(pk=sub_id).values_list("department__college_id", flat=True).first()
    if sub_cid:
        candidate_college_ids.add(sub_cid)
    cat_cid = SubjectCategory.objects.filter(pk=cat_id).values_list("college_id", flat=True).first()
    if cat_cid:
        candidate_college_ids.add(cat_cid)

    # Lock all candidate colleges in ascending PK order
    locked_colleges = lock_colleges(*candidate_college_ids)

    # 2. Exclusively lock parent records under the college lock
    locked_session = AcademicSession.objects.select_for_update().get(pk=session_id)
    locked_sem = Semester.objects.select_for_update().get(pk=sem_id)
    locked_prog = Programme.objects.select_for_update().get(pk=locked_sem.programme_id)
    locked_sub = Subject.objects.select_for_update().get(pk=sub_id)
    locked_dept = Department.objects.select_for_update().get(pk=locked_sub.department_id)
    locked_cat = SubjectCategory.objects.select_for_update().get(pk=cat_id)

    # 3. Verify that all authoritative college owners are covered by acquired locks
    actual_college_ids = {
        locked_session.college_id,
        locked_prog.college_id,
        locked_dept.college_id,
        locked_cat.college_id,
    }
    missing_colleges = {cid for cid in actual_college_ids if cid not in locked_colleges}
    if missing_colleges:
        raise ValidationError({"college": "Academic entity institutional ownership changed concurrently."})

    # Explicitly associate freshly locked related objects
    locked_sem.programme = locked_prog
    locked_sub.department = locked_dept

    # 4. Authoritative validation against locked parent state
    validate_paper_offering_relationships(
        academic_session=locked_session,
        semester=locked_sem,
        programme=locked_prog,
        subject=locked_sub,
        department=locked_dept,
        subject_category=locked_cat,
        credits=credits,
        max_marks_internal=max_marks_internal,
        max_marks_external=max_marks_external,
        pass_marks_external=pass_marks_external,
    )

    clean_code = paper_code.strip()
    if PaperOffering.objects.filter(academic_session=locked_session, paper_code=clean_code).exists():
        raise ValidationError({
            "paper_code": f"Paper offering with code '{clean_code}' already exists for this academic session."
        })

    offering = PaperOffering(
        academic_session=locked_session,
        semester=locked_sem,
        subject=locked_sub,
        subject_category=locked_cat,
        paper_code=clean_code,
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
    Lock hierarchy:
    1. College(s) in ascending PK order
    2. PaperOffering (select_for_update)
    3. Semester (select_for_update)
    4. Existing PaperProgrammeMapping rows (select_for_update, order_by('pk'))
    5. Target Programme rows (select_for_update, order_by('pk'))
    6. Authoritative validation
    7. Persistence
    """
    prog_list = list(programmes)
    college_ids = {paper_offering.academic_session.college_id}
    for p in prog_list:
        college_ids.add(p.college_id)

    # 1. Lock College(s) in ascending PK order
    lock_colleges(*college_ids)

    # 2. Lock PaperOffering
    locked_offering = PaperOffering.objects.select_for_update().get(pk=paper_offering.pk)

    # 3. Lock Semester
    locked_sem = Semester.objects.select_for_update().get(pk=locked_offering.semester_id)

    # 4. Lock existing mappings in deterministic PK order
    existing_mappings = list(
        PaperProgrammeMapping.objects.select_for_update()
        .filter(paper_offering=locked_offering)
        .order_by("pk")
    )

    # 5. Lock all target Programme rows in deterministic ascending PK order
    prog_ids = sorted({p.pk for p in prog_list})
    locked_programmes = {
        p.pk: p
        for p in Programme.objects.select_for_update().filter(pk__in=prog_ids).order_by("pk")
    }

    # 6. Authoritative validation of every target programme against the locked offering and semester
    for p in prog_list:
        locked_p = locked_programmes[p.pk]
        if locked_p.college_id != locked_offering.academic_session.college_id:
            raise ValidationError({
                "programme": (
                    f"Programme '{locked_p.code}' (College ID {locked_p.college_id}) belongs to a "
                    f"different college than PaperOffering '{locked_offering.paper_code}' (College ID {locked_offering.academic_session.college_id})."
                )
            })
        if locked_p.duration_semesters < locked_sem.semester_number:
            raise ValidationError({
                "programme": (
                    f"Programme '{locked_p.code}' duration ({locked_p.duration_semesters} sem) does not "
                    f"cover offering semester ({locked_sem.semester_number})."
                )
            })

    if replace:
        PaperProgrammeMapping.objects.filter(paper_offering=locked_offering).delete()

    mappings = []
    for p in prog_list:
        locked_p = locked_programmes[p.pk]
        mapping, _ = PaperProgrammeMapping.objects.get_or_create(
            paper_offering=locked_offering,
            programme=locked_p,
        )
        mappings.append(mapping)

    if mappings and not locked_offering.is_common_paper:
        locked_offering.is_common_paper = True
        locked_offering.save(update_fields=["is_common_paper"])

    return mappings


@transaction.atomic
def create_paper_programme_mapping(
    *,
    paper_offering_id: int,
    programme_id: int,
) -> PaperProgrammeMapping:
    """
    Safely creates a new PaperProgrammeMapping under strict concurrency control.
    Lock hierarchy:
    1. College(s) in ascending PK order
    2. PaperOffering (select_for_update)
    3. Programme (select_for_update)
    4. Semester (select_for_update)
    5. Authoritative validation
    6. Persistence
    """
    offering_college_id = PaperOffering.objects.values_list("academic_session__college_id", flat=True).get(pk=paper_offering_id)
    prog_college_id = Programme.objects.values_list("college_id", flat=True).get(pk=programme_id)

    # 1. Lock College(s) in deterministic ascending PK order
    lock_colleges(offering_college_id, prog_college_id)

    # 2. Exclusively lock the PaperOffering row
    locked_offering = PaperOffering.objects.select_for_update().get(pk=paper_offering_id)

    # 3. Exclusively lock the target Programme row
    locked_programme = Programme.objects.select_for_update().get(pk=programme_id)

    # 4. Exclusively lock the Semester row
    locked_sem = Semester.objects.select_for_update().get(pk=locked_offering.semester_id)

    # 5. Authoritative validation under lock
    if locked_programme.college_id != locked_offering.academic_session.college_id:
        raise ValidationError({
            "programme": (
                f"Programme '{locked_programme.code}' (College ID {locked_programme.college_id}) belongs to a "
                f"different college than PaperOffering '{locked_offering.paper_code}' (College ID {locked_offering.academic_session.college_id})."
            )
        })

    if locked_programme.duration_semesters < locked_sem.semester_number:
        raise ValidationError({
            "programme": (
                f"Programme '{locked_programme.code}' duration ({locked_programme.duration_semesters} sem) does not "
                f"cover offering semester ({locked_sem.semester_number})."
            )
        })

    # Check uniqueness under lock
    if PaperProgrammeMapping.objects.filter(paper_offering=locked_offering, programme=locked_programme).exists():
        raise ValidationError({"non_field_errors": ["Paper programme mapping already exists."]})

    mapping = PaperProgrammeMapping.objects.create(
        paper_offering=locked_offering,
        programme=locked_programme,
    )

    if not locked_offering.is_common_paper:
        locked_offering.is_common_paper = True
        locked_offering.save(update_fields=["is_common_paper"])

    return mapping


@transaction.atomic
def update_paper_programme_mapping(
    *,
    mapping_id: int,
    validated_data: dict,
) -> PaperProgrammeMapping:
    """
    Safely updates an existing PaperProgrammeMapping under strict concurrency control.
    Lock hierarchy:
    1. College(s) in ascending PK order
    2. Affected PaperOffering rows (select_for_update, order_by('pk'))
    3. PaperProgrammeMapping row (select_for_update)
    4. Target Programme (select_for_update)
    5. Authoritative validation
    6. Persistence
    """
    initial = PaperProgrammeMapping.objects.values(
        "paper_offering_id", "programme_id", "paper_offering__academic_session__college_id", "programme__college_id"
    ).get(pk=mapping_id)
    current_po_id = initial["paper_offering_id"]

    proposed_po = validated_data.get("paper_offering")
    target_po_id = proposed_po.pk if proposed_po else current_po_id

    proposed_prog = validated_data.get("programme")
    target_prog_id = proposed_prog.pk if proposed_prog else initial["programme_id"]

    college_ids = {initial["paper_offering__academic_session__college_id"], initial["programme__college_id"]}
    if proposed_po:
        college_ids.add(proposed_po.academic_session.college_id)
    if proposed_prog:
        college_ids.add(proposed_prog.college_id)

    # 1. Lock College(s) in deterministic ascending PK order
    lock_colleges(*college_ids)

    # 2. Lock affected PaperOffering rows in ascending PK order
    po_ids = sorted({current_po_id, target_po_id})
    locked_pos = {
        po.pk: po
        for po in PaperOffering.objects.select_for_update()
        .filter(pk__in=po_ids)
        .order_by("pk")
    }

    # 3. Lock existing PaperProgrammeMapping row
    locked_mapping = PaperProgrammeMapping.objects.select_for_update().get(pk=mapping_id)

    # 4. Lock target Programme row
    locked_prog = Programme.objects.select_for_update().get(pk=target_prog_id)

    # 5. Authoritative validation under lock
    target_po = locked_pos[target_po_id]
    locked_sem = Semester.objects.select_for_update().get(pk=target_po.semester_id)

    if locked_prog.college_id != target_po.academic_session.college_id:
        raise ValidationError({
            "programme": (
                f"Programme '{locked_prog.code}' (College ID {locked_prog.college_id}) belongs to a "
                f"different college than PaperOffering '{target_po.paper_code}' (College ID {target_po.academic_session.college_id})."
            )
        })

    if locked_prog.duration_semesters < locked_sem.semester_number:
        raise ValidationError({
            "programme": (
                f"Programme '{locked_prog.code}' duration ({locked_prog.duration_semesters} sem) does not "
                f"cover offering semester ({locked_sem.semester_number})."
            )
        })

    if target_po_id != current_po_id or target_prog_id != initial["programme_id"]:
        if PaperProgrammeMapping.objects.filter(
            paper_offering=target_po, programme=locked_prog
        ).exclude(pk=mapping_id).exists():
            raise ValidationError({"non_field_errors": ["Paper programme mapping already exists."]})

    if "paper_offering" in validated_data:
        locked_mapping.paper_offering = target_po
    if "programme" in validated_data:
        locked_mapping.programme = locked_prog

    locked_mapping.full_clean()
    locked_mapping.save()

    if not target_po.is_common_paper:
        target_po.is_common_paper = True
        target_po.save(update_fields=["is_common_paper"])

    return locked_mapping


@transaction.atomic
def delete_paper_programme_mapping(
    *,
    mapping_id: int,
) -> None:
    """
    Safely deletes a PaperProgrammeMapping under strict concurrency control.
    Lock hierarchy: College (select_for_update) -> PaperOffering (select_for_update) -> PaperProgrammeMapping (select_for_update) -> deletion.
    """
    initial = PaperProgrammeMapping.objects.values(
        "paper_offering_id", "paper_offering__academic_session__college_id"
    ).get(pk=mapping_id)

    lock_colleges(initial["paper_offering__academic_session__college_id"])
    locked_offering = PaperOffering.objects.select_for_update().get(pk=initial["paper_offering_id"])
    locked_mapping = PaperProgrammeMapping.objects.select_for_update().get(pk=mapping_id)
    locked_mapping.delete()


@transaction.atomic
def update_paper_offering(
    *,
    paper_offering_id: int,
    validated_data: dict,
) -> PaperOffering:
    """
    Safely updates an existing PaperOffering under strict concurrency control.
    Lock hierarchy:
    1. College (select_for_update in ascending PK order)
    2. PaperOffering (select_for_update)
    3. Associated PaperProgrammeMapping rows (select_for_update, order_by('pk'))
    4. SubjectCategory (select_for_update)
    5. Semester & Programme (select_for_update)
    6. Subject & Department (select_for_update)
    7. AcademicSession (select_for_update)
    8. Authoritative validation
    9. Persistence
    """
    # 1. Identify all candidate colleges from existing and proposed relationships
    candidate_college_ids = set()
    po_rels = PaperOffering.objects.filter(pk=paper_offering_id).values(
        "academic_session__college_id",
        "semester__programme__college_id",
        "subject__department__college_id",
        "subject_category__college_id",
    ).first()
    if po_rels:
        for cid in po_rels.values():
            if cid:
                candidate_college_ids.add(cid)

    if "academic_session" in validated_data and validated_data["academic_session"]:
        candidate_college_ids.add(validated_data["academic_session"].college_id)
    if "semester" in validated_data and validated_data["semester"]:
        sem_obj = validated_data["semester"]
        cid = (
            getattr(sem_obj, "programme", None) and sem_obj.programme.college_id
            or Semester.objects.filter(pk=sem_obj.pk).values_list("programme__college_id", flat=True).first()
        )
        if cid:
            candidate_college_ids.add(cid)
    if "subject" in validated_data and validated_data["subject"]:
        sub_obj = validated_data["subject"]
        cid = (
            getattr(sub_obj, "department", None) and sub_obj.department.college_id
            or Subject.objects.filter(pk=sub_obj.pk).values_list("department__college_id", flat=True).first()
        )
        if cid:
            candidate_college_ids.add(cid)
    if "subject_category" in validated_data and validated_data["subject_category"]:
        candidate_college_ids.add(validated_data["subject_category"].college_id)

    # 1. Lock College(s) in deterministic ascending PK order
    locked_colleges = lock_colleges(*candidate_college_ids)

    # 2. Exclusively lock the PaperOffering row
    locked_offering = PaperOffering.objects.select_for_update().get(pk=paper_offering_id)

    # 3. Exclusively lock associated programme mappings in deterministic PK order
    existing_mappings = list(
        PaperProgrammeMapping.objects.select_for_update()
        .filter(paper_offering=locked_offering)
        .order_by("pk")
    )

    # 4. Exclusively lock the (current or proposed) SubjectCategory row
    cat_id = validated_data.get("subject_category").pk if "subject_category" in validated_data else locked_offering.subject_category_id
    locked_cat = SubjectCategory.objects.select_for_update().get(pk=cat_id)

    # 5. Exclusively lock the (current or proposed) Semester and Programme rows
    sem_id = validated_data.get("semester").pk if "semester" in validated_data else locked_offering.semester_id
    locked_sem = Semester.objects.select_for_update().get(pk=sem_id)
    locked_prog = Programme.objects.select_for_update().get(pk=locked_sem.programme_id)
    locked_sem.programme = locked_prog

    # 6. Exclusively lock the (current or proposed) Subject and Department rows
    sub_id = validated_data.get("subject").pk if "subject" in validated_data else locked_offering.subject_id
    locked_sub = Subject.objects.select_for_update().get(pk=sub_id)
    locked_dept = Department.objects.select_for_update().get(pk=locked_sub.department_id)
    locked_sub.department = locked_dept

    # 7. Exclusively lock the (current or proposed) AcademicSession row
    sess_id = validated_data.get("academic_session").pk if "academic_session" in validated_data else locked_offering.academic_session_id
    locked_session = AcademicSession.objects.select_for_update().get(pk=sess_id)

    # Verify that all authoritative college owners are covered by acquired locks
    actual_college_ids = {
        locked_session.college_id,
        locked_prog.college_id,
        locked_dept.college_id,
        locked_cat.college_id,
    }
    missing_colleges = {cid for cid in actual_college_ids if cid not in locked_colleges}
    if missing_colleges:
        raise ValidationError({"college": "Academic entity institutional ownership changed concurrently."})

    # Determine proposed values (merge validated_data onto locked record)
    proposed_credits = validated_data.get("credits", locked_offering.credits)
    proposed_int_marks = validated_data.get("max_marks_internal", locked_offering.max_marks_internal)
    proposed_ext_marks = validated_data.get("max_marks_external", locked_offering.max_marks_external)
    proposed_pass_marks = validated_data.get("pass_marks_external", locked_offering.pass_marks_external)

    proposed_is_common = (
        validated_data["is_common_paper"]
        if "is_common_paper" in validated_data
        else locked_offering.is_common_paper
    )

    # Common-paper flag check against current mappings
    if existing_mappings:
        if not proposed_is_common:
            raise ValidationError({
                "is_common_paper": (
                    "Cannot set is_common_paper to False while programme mappings exist. "
                    "Remove all programme mappings first."
                )
            })
        proposed_is_common = True

    # Semester change mapping revalidation
    if existing_mappings:
        sem_num = locked_sem.semester_number
        for mapping in existing_mappings:
            prog = mapping.programme
            if prog.college_id != locked_session.college_id:
                raise ValidationError({
                    "semester": (
                        f"Mapped programme '{prog.code}' belongs to College ID {prog.college_id}, "
                        f"which does not match academic session College ID {locked_session.college_id}."
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

    # Revalidate complete proposed academic state under lock
    validate_paper_offering_relationships(
        academic_session=locked_session,
        semester=locked_sem,
        programme=locked_prog,
        subject=locked_sub,
        department=locked_dept,
        subject_category=locked_cat,
        credits=proposed_credits,
        max_marks_internal=proposed_int_marks,
        max_marks_external=proposed_ext_marks,
        pass_marks_external=proposed_pass_marks,
    )

    # Apply explicitly supplied fields onto the locked record
    for field, val in validated_data.items():
        setattr(locked_offering, field, val)

    if "academic_session" in validated_data:
        locked_offering.academic_session = locked_session
    if "semester" in validated_data:
        locked_offering.semester = locked_sem
    if "subject" in validated_data:
        locked_offering.subject = locked_sub
    if "subject_category" in validated_data:
        locked_offering.subject_category = locked_cat

    if existing_mappings:
        locked_offering.is_common_paper = True

    locked_offering.full_clean()
    locked_offering.save()
    return locked_offering


@transaction.atomic
def create_programme(
    *,
    college_id: int,
    validated_data: dict,
) -> Programme:
    """
    Safely creates a new Programme under strict concurrency control.
    Lock hierarchy: College (select_for_update) -> validation -> persistence.
    """
    locked_colleges = lock_colleges(college_id)
    locked_college = locked_colleges[college_id]

    code = validated_data.get("code", "").strip()
    if not code:
        raise ValidationError({"code": "Programme code is required."})

    duration = validated_data.get("duration_semesters", 8)
    if duration < 1:
        raise ValidationError({"duration_semesters": "Duration in semesters must be at least 1."})

    if Programme.objects.filter(college=locked_college, code=code).exists():
        raise ValidationError({"code": f"Programme with code '{code}' already exists for this college."})

    model_degree_default = Programme._meta.get_field("degree_type").default
    degree_type = validated_data.get("degree_type")
    if not degree_type:
        degree_type = model_degree_default

    programme = Programme(
        college=locked_college,
        name=validated_data.get("name", "").strip(),
        code=code,
        duration_semesters=duration,
        degree_type=degree_type,
        is_active=validated_data.get("is_active", True),
    )
    programme.full_clean()
    programme.save()
    return programme


@transaction.atomic
def update_programme(
    *,
    programme_id: int,
    validated_data: dict,
) -> Programme:
    """
    Safely updates a Programme under strict concurrency control.
    Enforces that:
    1. Duration cannot be reduced below any existing Semester's semester_number.
    2. Duration cannot be reduced below any mapped PaperOffering's semester_number.
    3. College cannot be changed if dependent paper offerings or mappings exist.
    """
    initial = Programme.objects.values("college_id").get(pk=programme_id)
    current_college_id = initial["college_id"]
    proposed_college = validated_data.get("college")
    target_college_id = proposed_college.pk if proposed_college else current_college_id

    # 1. Level 1 coordination lock: College(s) in deterministic ascending PK order
    lock_colleges(current_college_id, target_college_id)

    # 2. Exclusively lock the Programme row
    locked_prog = Programme.objects.select_for_update().get(pk=programme_id)

    proposed_duration = validated_data.get("duration_semesters", locked_prog.duration_semesters)
    if proposed_duration < 1:
        raise ValidationError({"duration_semesters": "Duration in semesters must be at least 1."})

    # Check 1: Existing semesters under lock
    max_sem = Semester.objects.filter(programme=locked_prog).aggregate(max_num=models.Max("semester_number"))["max_num"]
    if max_sem is not None and proposed_duration < max_sem:
        raise ValidationError({
            "duration_semesters": (
                f"Cannot reduce programme duration to {proposed_duration}: semester {max_sem} exists for this programme."
            )
        })

    # Check 2: Mapped paper offerings under lock
    max_mapped_sem = PaperProgrammeMapping.objects.filter(programme=locked_prog).aggregate(
        max_sem=models.Max("paper_offering__semester__semester_number")
    )["max_sem"]
    if max_mapped_sem is not None and proposed_duration < max_mapped_sem:
        raise ValidationError({
            "duration_semesters": (
                f"Cannot reduce programme duration to {proposed_duration}: mapped paper offering exists in semester {max_mapped_sem}."
            )
        })

    # Check 3: College change
    if proposed_college and proposed_college.pk != locked_prog.college_id:
        has_offerings = PaperOffering.objects.filter(semester__programme=locked_prog).exists()
        has_mappings = PaperProgrammeMapping.objects.filter(programme=locked_prog).exists()
        if has_offerings or has_mappings:
            raise ValidationError({
                "college": "Cannot change programme college while dependent paper offerings or mappings exist."
            })

    for field, val in validated_data.items():
        setattr(locked_prog, field, val)

    locked_prog.full_clean()
    locked_prog.save()
    return locked_prog


@transaction.atomic
def create_semester(
    *,
    programme_id: int,
    validated_data: dict,
) -> Semester:
    """
    Safely creates a new Semester under strict concurrency control.
    Lock hierarchy: College (select_for_update) -> Programme (select_for_update) -> validation -> persistence.
    """
    prog_college_id = Programme.objects.values_list("college_id", flat=True).get(pk=programme_id)

    # 1. Level 1 coordination lock
    lock_colleges(prog_college_id)

    # 2. Level 2 parent lock
    locked_prog = Programme.objects.select_for_update().get(pk=programme_id)

    # 3. Authoritative validation under lock
    sem_num = validated_data.get("semester_number")
    if sem_num is None or sem_num < 1:
        raise ValidationError({"semester_number": "Semester number must be at least 1."})
    if sem_num > locked_prog.duration_semesters:
        raise ValidationError({
            "semester_number": f"Semester number ({sem_num}) exceeds programme duration ({locked_prog.duration_semesters})."
        })

    if Semester.objects.filter(programme=locked_prog, semester_number=sem_num).exists():
        raise ValidationError({
            "semester_number": f"Semester {sem_num} already exists for programme '{locked_prog.code}'."
        })

    semester = Semester(
        programme=locked_prog,
        semester_number=sem_num,
        name=validated_data.get("name", f"Semester {sem_num}"),
        is_active=validated_data.get("is_active", True),
    )
    semester.full_clean()
    semester.save()
    return semester


@transaction.atomic
def update_semester(
    *,
    semester_id: int,
    validated_data: dict,
) -> Semester:
    """
    Safely updates a Semester under strict concurrency control.
    Lock hierarchy: College -> Programme -> Semester -> validation -> persistence.
    """
    initial = Semester.objects.values("programme_id", "programme__college_id").get(pk=semester_id)
    current_prog_id = initial["programme_id"]
    current_college_id = initial["programme__college_id"]

    proposed_prog = validated_data.get("programme")
    target_prog_id = proposed_prog.pk if proposed_prog else current_prog_id
    target_college_id = proposed_prog.college_id if proposed_prog else current_college_id

    # 1. Level 1 coordination lock
    lock_colleges(current_college_id, target_college_id)

    # 2. Exclusively lock affected Programme rows in ascending PK order
    prog_ids = sorted({current_prog_id, target_prog_id})
    locked_progs = {
        p.pk: p
        for p in Programme.objects.select_for_update().filter(pk__in=prog_ids).order_by("pk")
    }

    # 3. Exclusively lock the Semester row
    locked_sem = Semester.objects.select_for_update().get(pk=semester_id)
    target_prog = locked_progs[target_prog_id]

    proposed_sem_num = validated_data.get("semester_number", locked_sem.semester_number)
    if proposed_sem_num < 1:
        raise ValidationError({"semester_number": "Semester number must be at least 1."})

    # Check 1: Exceeds programme duration
    if proposed_sem_num > target_prog.duration_semesters:
        raise ValidationError({
            "semester_number": (
                f"Semester number ({proposed_sem_num}) exceeds programme duration ({target_prog.duration_semesters})."
            )
        })

    # Check uniqueness if semester_number or programme changed
    if proposed_sem_num != locked_sem.semester_number or target_prog_id != current_prog_id:
        if Semester.objects.filter(programme=target_prog, semester_number=proposed_sem_num).exclude(pk=semester_id).exists():
            raise ValidationError({
                "semester_number": f"Semester {proposed_sem_num} already exists for programme '{target_prog.code}'."
            })

    # Check 2: Mapped programmes of dependent paper offerings
    min_mapped_prog_dur = PaperProgrammeMapping.objects.filter(
        paper_offering__semester=locked_sem
    ).aggregate(min_dur=models.Min("programme__duration_semesters"))["min_dur"]
    if min_mapped_prog_dur is not None and proposed_sem_num > min_mapped_prog_dur:
        raise ValidationError({
            "semester_number": (
                f"Cannot change semester number to {proposed_sem_num}: mapped programme exists with duration {min_mapped_prog_dur}."
            )
        })

    # Check 3: Programme reassignment college mismatch
    if target_prog.college_id != locked_progs[current_prog_id].college_id:
        if PaperOffering.objects.filter(semester=locked_sem).exists():
            raise ValidationError({
                "programme": "Cannot reassign semester to a programme in a different college while dependent paper offerings exist."
            })

    for field, val in validated_data.items():
        setattr(locked_sem, field, val)

    if proposed_prog:
        locked_sem.programme = target_prog

    locked_sem.full_clean()
    locked_sem.save()
    return locked_sem


@transaction.atomic
def create_department(
    *,
    college_id: int,
    validated_data: dict,
) -> Department:
    """
    Safely creates a new Department under strict concurrency control.
    Lock hierarchy: College (select_for_update) -> validation -> persistence.
    """
    locked_colleges = lock_colleges(college_id)
    locked_college = locked_colleges[college_id]

    code = validated_data.get("code", "").strip()
    if not code:
        raise ValidationError({"code": "Department code is required."})

    if Department.objects.filter(college=locked_college, code=code).exists():
        raise ValidationError({"code": f"Department with code '{code}' already exists for this college."})

    dept = Department(
        college=locked_college,
        name=validated_data.get("name", "").strip(),
        code=code,
    )
    dept.full_clean()
    dept.save()
    return dept


@transaction.atomic
def update_department(
    *,
    department_id: int,
    validated_data: dict,
) -> Department:
    """
    Safely updates a Department under strict concurrency control.
    Enforces that:
    1. College cannot be changed while dependent paper offerings reference subjects of this department.
    """
    initial = Department.objects.values("college_id").get(pk=department_id)
    current_college_id = initial["college_id"]
    proposed_college = validated_data.get("college")
    target_college_id = proposed_college.pk if proposed_college else current_college_id

    lock_colleges(current_college_id, target_college_id)
    locked_dept = Department.objects.select_for_update().get(pk=department_id)

    if proposed_college and proposed_college.pk != locked_dept.college_id:
        if PaperOffering.objects.filter(subject__department=locked_dept).exists():
            raise ValidationError({
                "college": "Cannot change department college while dependent paper offerings exist."
            })

    for field, val in validated_data.items():
        setattr(locked_dept, field, val)

    locked_dept.full_clean()
    locked_dept.save()
    return locked_dept


@transaction.atomic
def create_subject(
    *,
    department_id: int,
    validated_data: dict,
) -> Subject:
    """
    Safely creates a new Subject under strict concurrency control.
    Lock hierarchy: College (select_for_update) -> Department (select_for_update) -> validation -> persistence.
    """
    dept_college_id = Department.objects.values_list("college_id", flat=True).get(pk=department_id)
    lock_colleges(dept_college_id)
    locked_dept = Department.objects.select_for_update().get(pk=department_id)

    code = validated_data.get("code", "").strip()
    if not code:
        raise ValidationError({"code": "Subject code is required."})

    if Subject.objects.filter(department=locked_dept, code=code).exists():
        raise ValidationError({"code": f"Subject with code '{code}' already exists for this department."})

    subject = Subject(
        department=locked_dept,
        name=validated_data.get("name", "").strip(),
        code=code,
        description=validated_data.get("description", ""),
        is_active=validated_data.get("is_active", True),
    )
    subject.full_clean()
    subject.save()
    return subject


@transaction.atomic
def update_subject(
    *,
    subject_id: int,
    validated_data: dict,
) -> Subject:
    """
    Safely updates a Subject under strict concurrency control.
    Enforces that:
    1. Department cannot be reassigned to a different college while dependent paper offerings exist.
    """
    initial = Subject.objects.values("department_id", "department__college_id").get(pk=subject_id)
    current_dept_id = initial["department_id"]
    current_college_id = initial["department__college_id"]

    proposed_dept = validated_data.get("department")
    target_dept_id = proposed_dept.pk if proposed_dept else current_dept_id
    target_college_id = proposed_dept.college_id if proposed_dept else current_college_id

    lock_colleges(current_college_id, target_college_id)
    dept_ids = sorted({current_dept_id, target_dept_id})
    locked_depts = {
        d.pk: d
        for d in Department.objects.select_for_update().filter(pk__in=dept_ids).order_by("pk")
    }
    locked_sub = Subject.objects.select_for_update().get(pk=subject_id)
    target_dept = locked_depts[target_dept_id]

    if target_dept.college_id != locked_depts[current_dept_id].college_id:
        if PaperOffering.objects.filter(subject=locked_sub).exists():
            raise ValidationError({
                "department": "Cannot reassign subject to a department in a different college while dependent paper offerings exist."
            })

    for field, val in validated_data.items():
        setattr(locked_sub, field, val)

    if proposed_dept:
        locked_sub.department = target_dept

    locked_sub.full_clean()
    locked_sub.save()
    return locked_sub


@transaction.atomic
def create_subject_category(
    *,
    college_id: int,
    validated_data: dict,
) -> SubjectCategory:
    """
    Safely creates a new SubjectCategory under strict concurrency control.
    Lock hierarchy: College (select_for_update) -> validation -> persistence.
    """
    locked_colleges = lock_colleges(college_id)
    locked_college = locked_colleges[college_id]

    code = validated_data.get("code", "").strip()
    if not code:
        raise ValidationError({"code": "Subject category code is required."})

    min_credits = validated_data.get("min_credits", Decimal("2.0"))
    max_credits = validated_data.get("max_credits", Decimal("4.0"))

    if min_credits < Decimal("0.0"):
        raise ValidationError({"min_credits": "Minimum credits cannot be negative."})
    if max_credits < min_credits:
        raise ValidationError({"max_credits": "Maximum credits cannot be less than minimum credits."})

    if SubjectCategory.objects.filter(college=locked_college, code=code).exists():
        raise ValidationError({"code": f"Subject category with code '{code}' already exists for this college."})

    cat = SubjectCategory(
        college=locked_college,
        name=validated_data.get("name", "").strip(),
        code=code,
        description=validated_data.get("description", ""),
        min_credits=min_credits,
        max_credits=max_credits,
        is_active=validated_data.get("is_active", True),
    )
    cat.full_clean()
    cat.save()
    return cat


@transaction.atomic
def update_subject_category(
    *,
    category_id: int,
    validated_data: dict,
) -> SubjectCategory:
    """
    Safely updates a SubjectCategory under strict concurrency control.
    Enforces that:
    1. min_credits cannot be increased above any dependent PaperOffering's credits.
    2. max_credits cannot be decreased below any dependent PaperOffering's credits.
    3. College cannot be changed while dependent paper offerings exist.
    """
    initial = SubjectCategory.objects.values("college_id").get(pk=category_id)
    current_college_id = initial["college_id"]
    proposed_college = validated_data.get("college")
    target_college_id = proposed_college.pk if proposed_college else current_college_id

    lock_colleges(current_college_id, target_college_id)
    locked_cat = SubjectCategory.objects.select_for_update().get(pk=category_id)

    proposed_min = validated_data.get("min_credits", locked_cat.min_credits)
    proposed_max = validated_data.get("max_credits", locked_cat.max_credits)

    if proposed_min < Decimal("0.0"):
        raise ValidationError({"min_credits": "Minimum credits cannot be negative."})
    if proposed_max < proposed_min:
        raise ValidationError({"max_credits": "Maximum credits cannot be less than minimum credits."})

    min_offering_credits = PaperOffering.objects.filter(subject_category=locked_cat).aggregate(
        min_c=models.Min("credits")
    )["min_c"]
    if min_offering_credits is not None and proposed_min > min_offering_credits:
        raise ValidationError({
            "min_credits": (
                f"Cannot increase min_credits to {proposed_min}: existing paper offering exists with {min_offering_credits} credits."
            )
        })

    max_offering_credits = PaperOffering.objects.filter(subject_category=locked_cat).aggregate(
        max_c=models.Max("credits")
    )["max_c"]
    if max_offering_credits is not None and proposed_max < max_offering_credits:
        raise ValidationError({
            "max_credits": (
                f"Cannot decrease max_credits to {proposed_max}: existing paper offering exists with {max_offering_credits} credits."
            )
        })

    if proposed_college and proposed_college.pk != locked_cat.college_id:
        if PaperOffering.objects.filter(subject_category=locked_cat).exists():
            raise ValidationError({
                "college": "Cannot change subject category college while dependent paper offerings exist."
            })

    for field, val in validated_data.items():
        setattr(locked_cat, field, val)

    locked_cat.full_clean()
    locked_cat.save()
    return locked_cat


@transaction.atomic
def create_academic_session(
    *,
    college_id: int,
    validated_data: dict,
) -> AcademicSession:
    """
    Safely creates a new AcademicSession under strict concurrency control.
    Lock hierarchy: College (select_for_update) -> validation -> persistence.
    """
    locked_colleges = lock_colleges(college_id)
    locked_college = locked_colleges[college_id]

    start_date = validated_data.get("start_date")
    end_date = validated_data.get("end_date")
    validate_academic_session_dates(start_date, end_date)

    name = validated_data.get("name", "").strip()
    if not name:
        raise ValidationError({"name": "Academic session name is required."})

    if AcademicSession.objects.filter(college=locked_college, name=name).exists():
        raise ValidationError({"name": f"Academic session '{name}' already exists for this college."})

    session = AcademicSession(
        college=locked_college,
        name=name,
        start_date=start_date,
        end_date=end_date,
        is_current=False,
    )
    session.full_clean()
    session.save()
    return session


@transaction.atomic
def update_academic_session(
    *,
    session_id: int,
    validated_data: dict,
) -> AcademicSession:
    """
    Safely updates an AcademicSession under strict concurrency control.
    Enforces that:
    1. start_date must strictly precede end_date.
    2. College cannot be changed while dependent paper offerings exist.
    """
    initial = AcademicSession.objects.values("college_id").get(pk=session_id)
    current_college_id = initial["college_id"]
    proposed_college = validated_data.get("college")
    target_college_id = proposed_college.pk if proposed_college else current_college_id

    lock_colleges(current_college_id, target_college_id)
    locked_session = AcademicSession.objects.select_for_update().get(pk=session_id)

    proposed_start = validated_data.get("start_date", locked_session.start_date)
    proposed_end = validated_data.get("end_date", locked_session.end_date)
    validate_academic_session_dates(proposed_start, proposed_end)

    if proposed_college and proposed_college.pk != locked_session.college_id:
        if locked_session.is_current:
            raise ValidationError({
                "college": "A current academic session cannot be reassigned to another college."
            })
        if PaperOffering.objects.filter(academic_session=locked_session).exists():
            raise ValidationError({
                "college": "Cannot change academic session college while dependent paper offerings exist."
            })

    for field, val in validated_data.items():
        if field != "is_current":
            setattr(locked_session, field, val)

    locked_session.full_clean()
    locked_session.save()
    return locked_session


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


@transaction.atomic
def assign_faculty_to_paper(
    *,
    acting_user,
    faculty,
    paper_offering,
    role: str = FacultyAssignmentRole.TEACHER,
) -> FacultySubjectAssignment:
    """
    Atomically creates a FacultySubjectAssignment (Table 20).
    Enforces:
    1. Administrator authorization.
    2. College row lock coordination.
    3. Same-college boundary between faculty and paper offering session.
    4. Examiner eligibility if internal or external examiner role is selected.
    5. Assignment uniqueness.
    """
    check_institutional_admin_authority(acting_user)

    faculty_id = faculty.pk if hasattr(faculty, "pk") else int(faculty)
    offering_id = paper_offering.pk if hasattr(paper_offering, "pk") else int(paper_offering)

    candidate_offering = PaperOffering.objects.select_related("academic_session").get(pk=offering_id)
    target_college_id = candidate_offering.academic_session.college_id

    # 1. Level 1 College Coordination Lock
    lock_colleges(target_college_id)

    # 2. Reload entities under lock
    locked_faculty = FacultyProfile.objects.select_for_update().get(pk=faculty_id)
    locked_offering = PaperOffering.objects.select_for_update().get(pk=offering_id)

    # 3. Same-college boundary validation
    if locked_faculty.college_id != target_college_id:
        raise ValidationError({
            "faculty": (
                f"Faculty college ID {locked_faculty.college_id} does not match "
                f"paper offering college ID {target_college_id}."
            )
        })

    # 4. Examiner eligibility validation
    if role in (FacultyAssignmentRole.INTERNAL_EXAMINER, FacultyAssignmentRole.EXTERNAL_EXAMINER):
        if not locked_faculty.is_examiner:
            raise ValidationError({
                "faculty": f"Faculty member '{locked_faculty.employee_code}' is not marked as eligible for examiner roles."
            })

    # 5. Check uniqueness
    if FacultySubjectAssignment.objects.filter(
        faculty=locked_faculty,
        paper_offering=locked_offering,
        role=role,
    ).exists():
        raise ValidationError({
            "non_field_errors": (
                f"Faculty '{locked_faculty.employee_code}' is already assigned to paper "
                f"'{locked_offering.paper_code}' with role '{role}'."
            )
        })

    assignment = FacultySubjectAssignment(
        faculty=locked_faculty,
        paper_offering=locked_offering,
        role=role,
    )
    assignment.full_clean()
    assignment.save()

    return assignment


@transaction.atomic
def delete_faculty_assignment(
    *,
    acting_user,
    assignment_id: int,
) -> None:
    """Atomically deletes a FacultySubjectAssignment under lock."""
    check_institutional_admin_authority(acting_user)

    assignment = FacultySubjectAssignment.objects.select_for_update().get(pk=assignment_id)
    assignment.delete()

