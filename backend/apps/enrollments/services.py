"""
Student Academic Record Ledger Service Layer.
Enforces institutional college boundaries, row-level concurrency control,
and administrative authorization for student programme admission records (Table 18).
"""

import logging
from typing import Optional
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.academics.models import AcademicSession, College, Programme
from apps.academics.services import check_institutional_admin_authority, lock_colleges
from apps.accounts.models import User
from apps.enrollments.models import AcademicRecordStatus, StudentAcademicRecord
from apps.students.models import StudentProfile

logger = logging.getLogger('college.enrollments')


@transaction.atomic
def create_student_academic_record(
    *,
    acting_user: User,
    student: StudentProfile,
    programme: Programme,
    academic_session: AcademicSession,
    admission_date,
    status: str = AcademicRecordStatus.ACTIVE,
) -> StudentAcademicRecord:
    """
    Atomically creates a new StudentAcademicRecord under College row lock.
    Enforces same-college boundaries between student, programme, and session.
    Strictly restricted to institutional administrators.
    """
    check_institutional_admin_authority(acting_user)

    student_id = student.pk if hasattr(student, 'pk') else int(student)
    programme_id = programme.pk if hasattr(programme, 'pk') else int(programme)
    session_id = academic_session.pk if hasattr(academic_session, 'pk') else int(academic_session)

    # 1. Fetch uncommitted references to identify target college
    candidate_student = StudentProfile.objects.select_related('college').get(pk=student_id)
    target_college_id = candidate_student.college_id

    # 2. Acquire Level 1 College Coordination Lock
    lock_colleges(target_college_id)

    # 3. Reload entities under lock
    locked_student = StudentProfile.objects.select_for_update().get(pk=student_id)
    locked_prog = Programme.objects.select_for_update().get(pk=programme_id)
    locked_session = AcademicSession.objects.select_for_update().get(pk=session_id)

    # 4. Cross-college boundary verification
    if locked_prog.college_id != target_college_id:
        raise ValidationError({
            "programme": (
                f"Programme '{locked_prog.code}' belongs to college ID {locked_prog.college_id}, "
                f"which does not match student college ID {target_college_id}."
            )
        })

    if locked_session.college_id != target_college_id:
        raise ValidationError({
            "academic_session": (
                f"Academic session '{locked_session.name}' belongs to college ID {locked_session.college_id}, "
                f"which does not match student college ID {target_college_id}."
            )
        })

    # 5. Check uniqueness constraint
    if StudentAcademicRecord.objects.filter(
        student=locked_student,
        programme=locked_prog,
        academic_session=locked_session,
    ).exists():
        raise ValidationError({
            "non_field_errors": (
                f"Student '{locked_student.enrollment_number}' already has an academic record "
                f"for programme '{locked_prog.code}' in session '{locked_session.name}'."
            )
        })

    record = StudentAcademicRecord(
        student=locked_student,
        programme=locked_prog,
        academic_session=locked_session,
        admission_date=admission_date,
        status=status,
    )
    record.full_clean()
    record.save()

    return record


@transaction.atomic
def update_student_academic_record(
    *,
    record_id: int,
    acting_user: User,
    validated_data: dict,
) -> StudentAcademicRecord:
    """
    Updates an existing StudentAcademicRecord under row-level lock.
    Only status and admission_date may be updated; student, programme,
    and session linkages are immutable once established.
    Strictly restricted to institutional administrators.
    """
    check_institutional_admin_authority(acting_user)

    record = StudentAcademicRecord.objects.select_for_update().get(pk=record_id)

    # Immutable fields verification
    immutable_fields = {'student', 'programme', 'academic_session'}
    for imm in immutable_fields:
        if imm in validated_data and validated_data[imm] != getattr(record, imm):
            raise ValidationError({imm: f"Field '{imm}' cannot be modified once an academic record is created."})

    if 'status' in validated_data:
        record.status = validated_data['status']
    if 'admission_date' in validated_data:
        record.admission_date = validated_data['admission_date']

    record.full_clean()
    record.save()
    return record
