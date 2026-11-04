"""
Faculty Management Service Layer.
Enforces administrative provisioning, department boundary integrity,
and field-level role-based mutation permissions for faculty profiles.
"""

import logging
from typing import Optional
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.academics.models import College, Department
from apps.academics.services import check_institutional_admin_authority, lock_colleges
from apps.accounts.authorization import check_college_operation_authority
from apps.accounts.models import RoleChoices, User
from apps.faculty.models import FacultyProfile

logger = logging.getLogger('college.faculty')


@transaction.atomic
def create_faculty_profile(
    *,
    acting_user: User,
    username: str,
    email: str,
    first_name: str,
    last_name: str,
    college: College,
    department: Department,
    employee_code: str,
    designation: str = 'Assistant Professor',
    phone_number: Optional[str] = None,
    is_examiner: bool = True,
) -> FacultyProfile:
    """
    Atomically provisions a new faculty member account and associated FacultyProfile.
    The account is created in an inactive state with an unusable password.
    Strictly restricted to institutional administrators.
    """
    check_institutional_admin_authority(acting_user)

    username = username.strip()
    email = email.strip().lower()
    employee_code = employee_code.strip()

    # 1. Coordinate via College row lock
    college_id = college.pk if hasattr(college, 'pk') else int(college)
    check_college_operation_authority(acting_user, college_id, "create_faculty_profile")
    lock_colleges(college_id)
    locked_college = College.objects.get(pk=college_id)

    # 2. Institutional relationship boundary verification
    dept_id = department.pk if hasattr(department, 'pk') else int(department)
    locked_dept = Department.objects.get(pk=dept_id)
    if locked_dept.college_id != locked_college.pk:
        raise ValidationError({
            "department": f"Department '{locked_dept.code}' does not belong to college '{locked_college.code}'."
        })

    # 3. Uniqueness validations
    if User.objects.filter(username=username).exists():
        raise ValidationError({"username": "A user with that username already exists."})
    if User.objects.filter(email=email).exists():
        raise ValidationError({"email": "A user with that email already exists."})
    if FacultyProfile.objects.filter(employee_code=employee_code).exists():
        raise ValidationError({"employee_code": f"Employee code '{employee_code}' is already registered."})

    # 4. Atomic record creation with unusable password and inactive state
    user = User(
        username=username,
        email=email,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        role=RoleChoices.FACULTY,
        is_active=False,
        is_staff=False,
        is_superuser=False,
    )
    user.set_unusable_password()
    user.full_clean()
    user.save()

    profile = FacultyProfile(
        user=user,
        college=locked_college,
        department=locked_dept,
        employee_code=employee_code,
        designation=designation.strip() if designation else 'Assistant Professor',
        phone_number=phone_number.strip() if phone_number else None,
        is_examiner=bool(is_examiner),
    )
    profile.full_clean()
    profile.save()

    return profile


@transaction.atomic
def update_faculty_profile(
    *,
    profile_id: int,
    acting_user: User,
    validated_data: dict,
) -> FacultyProfile:
    """
    Updates a FacultyProfile under strict academic coordination lock hierarchy (Finding R3-B):
    1. Read minimum candidate identifiers without locking child rows.
    2. Determine existing and proposed institutional owners.
    3. Acquire College coordination locks in ascending PK order.
    4. Acquire Department locks in consistent order.
    5. Reload and lock FacultyProfile under lock.
    6. Verify that College locks cover authoritative ownership.
    7. Recheck administrator authorization for target institution.
    8. Resolve proposed department and validate compatibility.
    9. Validate examiner assignment dependencies.
    10. Apply update and persist atomically.
    """
    # 1. Read minimum candidate identifiers without locking child rows
    initial = FacultyProfile.objects.values("college_id", "department_id", "user_id").get(pk=profile_id)
    current_college_id = initial["college_id"]
    current_dept_id = initial["department_id"]

    is_admin = (
        acting_user.role in (RoleChoices.ADMIN, RoleChoices.SUPERADMIN)
        or acting_user.is_superuser
        or (hasattr(acting_user, "has_role") and acting_user.has_role("COLLEGE_SUPERADMIN", "EXAM_OFFICER"))
    )

    if not is_admin:
        if initial["user_id"] != acting_user.pk:
            raise PermissionDenied("You do not have permission to modify this faculty profile.")
        disallowed_fields = {'college', 'department', 'employee_code', 'designation', 'is_examiner', 'user'}
        attempted = set(validated_data.keys()).intersection(disallowed_fields)
        if attempted:
            raise PermissionDenied(f"Faculty cannot modify institutional fields: {', '.join(sorted(attempted))}.")

    proposed_dept = validated_data.get("department") if is_admin else None
    if proposed_dept:
        dept_id = proposed_dept.pk if hasattr(proposed_dept, "pk") else int(proposed_dept)
        dept_college_id = Department.objects.values_list("college_id", flat=True).get(pk=dept_id)
        candidate_college_ids = {current_college_id, dept_college_id}
        candidate_dept_ids = {current_dept_id, dept_id}
    else:
        dept_id = None
        candidate_college_ids = {current_college_id}
        candidate_dept_ids = {current_dept_id}

    # 2. Acquire required College coordination locks in deterministic ascending PK order
    lock_colleges(*sorted(candidate_college_ids))

    # 3. Acquire relevant Department locks in deterministic ascending PK order (materialized dictionary)
    locked_departments = {
        dept.pk: dept
        for dept in Department.objects.select_for_update().filter(pk__in=sorted(candidate_dept_ids)).order_by("pk")
    }

    # 4. Reload the FacultyProfile under lock
    profile = FacultyProfile.objects.select_for_update().get(pk=profile_id)

    # 5. Revalidate that relevant College locks cover authoritative ownership
    if profile.college_id not in candidate_college_ids:
        raise ValidationError("Authoritative college ownership changed concurrently.")

    # 6. Recheck administrator authorization for target institution
    if is_admin:
        check_college_operation_authority(acting_user, profile.college_id, "update_faculty_profile")

    # 7 & 8. Resolve proposed department from locked instances and validate department-to-college compatibility
    if is_admin and proposed_dept:
        locked_dept = locked_departments.get(dept_id)
        if not locked_dept:
            raise ValidationError({"department": "Target department does not exist."})
        if locked_dept.college_id != profile.college_id:
            raise ValidationError({
                "department": f"Department '{locked_dept.code}' belongs to college ID {locked_dept.college_id}, not {profile.college_id}."
            })
        profile.department = locked_dept

    # Immutable fields cannot be modified even by admin
    immutable_fields = {'college', 'user', 'employee_code'}
    for imm in immutable_fields:
        if imm in validated_data and validated_data[imm] != getattr(profile, imm):
            raise ValidationError({imm: f"Field '{imm}' is immutable once assigned."})

    # 9. Validate examiner assignment dependencies
    if is_admin:
        if 'designation' in validated_data:
            profile.designation = validated_data['designation'].strip()
        if 'is_examiner' in validated_data:
            new_is_examiner = bool(validated_data['is_examiner'])
            if not new_is_examiner and profile.is_examiner:
                from apps.academics.models import FacultyAssignmentRole, FacultySubjectAssignment
                if FacultySubjectAssignment.objects.filter(
                    faculty=profile,
                    role__in=[FacultyAssignmentRole.INTERNAL_EXAMINER, FacultyAssignmentRole.EXTERNAL_EXAMINER],
                ).exists():
                    raise ValidationError({
                        "is_examiner": (
                            f"Cannot revoke examiner eligibility for faculty member '{profile.employee_code}' "
                            f"while active examiner assignments exist. Reassign or delete examiner assignments first."
                        )
                    })
            profile.is_examiner = new_is_examiner

    if 'phone_number' in validated_data:
        profile.phone_number = validated_data['phone_number'].strip() if validated_data['phone_number'] else None

    # 10. Persist atomically
    profile.full_clean()
    profile.save()
    return profile
