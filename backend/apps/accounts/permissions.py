"""
Role-Based Access Control (RBAC) Permissions for College Online Examination System.
Enforces strict server-side authorization boundaries for Administrator, Faculty, and Student roles.

Finding B Correction:
Django's `is_staff` flag is separated from institutional RBAC authorization.
`is_staff=True` alone NEVER grants institutional administrator or faculty privileges.
Student accounts are strictly prevented from privilege escalation regardless of staff flags.
"""

from rest_framework.permissions import BasePermission
from apps.accounts.models import RoleChoices


class IsAdminUserRole(BasePermission):
    """
    Allows access only to authenticated, active administrators or superadministrators.
    Faculty and Student accounts are strictly rejected, regardless of is_staff flag.
    Never grants administrative access solely because is_staff=True.
    """
    message = "Administrator access required."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        # Student accounts are strictly barred from administrative endpoints
        if user.role == RoleChoices.STUDENT:
            return False

        # Superadministrators have legitimate institutional administrative authority
        if user.role == RoleChoices.SUPERADMIN or user.is_superuser:
            return True

        # Primary Administrator role
        if user.role == RoleChoices.ADMIN:
            return True

        # Approved granular institutional administrative roles only
        return user.has_role('COLLEGE_SUPERADMIN', 'EXAM_OFFICER')


class IsFacultyUserRole(BasePermission):
    """
    Allows access to authenticated, active faculty members, examiners, and administrators.
    Student accounts are strictly rejected, regardless of is_staff flag.
    Never grants faculty access solely because is_staff=True.
    """
    message = "Faculty access required."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        # Student accounts are strictly barred from faculty endpoints
        if user.role == RoleChoices.STUDENT:
            return False

        # Superadministrators and Administrators have institutional oversight
        if user.role in (RoleChoices.SUPERADMIN, RoleChoices.ADMIN) or user.is_superuser:
            return True

        # Primary Faculty role
        if user.role == RoleChoices.FACULTY:
            return True

        # Approved granular institutional faculty/examiner roles only
        return user.has_role('FACULTY', 'HEAD_EXAMINER', 'EXAMINER')


class IsStudentUserRole(BasePermission):
    """
    Allows access only to authenticated, active students.
    Administrative and Faculty accounts are strictly rejected from student-specific workspaces.
    """
    message = "Student access required."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        return user.role == RoleChoices.STUDENT


class IsCollegeSuperAdmin(BasePermission):
    """
    Allows access exclusively to superadministrators with institutional governance authority.
    Student and Faculty accounts are strictly rejected.
    """
    message = "College superadministrator access required."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        # Student and Faculty accounts are strictly barred from superadmin endpoints
        if user.role in (RoleChoices.STUDENT, RoleChoices.FACULTY):
            return False

        if user.role == RoleChoices.SUPERADMIN or user.is_superuser:
            return True

        return user.has_role('COLLEGE_SUPERADMIN')
