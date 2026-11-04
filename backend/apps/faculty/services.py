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
    Updates a FacultyProfile under row-level lock.
    Enforces authorization:
    - Faculty members can only update contact fields (phone_number).
    - Administrators can update designation, department, is_examiner, and contact fields.
    - Institutional identity fields (college, user, employee_code) are immutable.
    """
    profile = FacultyProfile.objects.select_for_update().get(pk=profile_id)

    is_admin = (
        acting_user.role in (RoleChoices.ADMIN, RoleChoices.SUPERADMIN)
        or acting_user.is_superuser
        or (hasattr(acting_user, "has_role") and acting_user.has_role("COLLEGE_SUPERADMIN", "EXAM_OFFICER"))
    )

    if not is_admin:
        # Faculty updating their own profile
        if profile.user_id != acting_user.pk:
            raise PermissionDenied("You do not have permission to modify this faculty profile.")

        disallowed_fields = {'college', 'department', 'employee_code', 'designation', 'is_examiner', 'user'}
        attempted = set(validated_data.keys()).intersection(disallowed_fields)
        if attempted:
            raise PermissionDenied(f"Faculty cannot modify institutional fields: {', '.join(sorted(attempted))}.")

    # Immutable fields cannot be modified even by admin
    immutable_fields = {'college', 'user', 'employee_code'}
    for imm in immutable_fields:
        if imm in validated_data and validated_data[imm] != getattr(profile, imm):
            raise ValidationError({imm: f"Field '{imm}' is immutable once assigned."})

    # If department is being updated by admin, verify same college
    if is_admin and 'department' in validated_data:
        new_dept = validated_data['department']
        if new_dept.college_id != profile.college_id:
            raise ValidationError({
                "department": f"Department '{new_dept.code}' belongs to college ID {new_dept.college_id}, not {profile.college_id}."
            })
        profile.department = new_dept

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

    profile.full_clean()
    profile.save()
    return profile
