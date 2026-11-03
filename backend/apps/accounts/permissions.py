"""
Role-Based Access Control (RBAC) Permissions for College Online Examination System.
Enforces strict server-side authorization boundaries for Administrator, Faculty, and Student roles.
"""

from rest_framework.permissions import BasePermission
from apps.accounts.models import RoleChoices


class IsAdminUserRole(BasePermission):
    """
    Allows access only to authenticated, active administrators or superusers.
    Faculty and Student roles are strictly rejected.
    """
    message = "Administrator access required."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        if user.is_superuser or user.is_staff:
            return True

        if user.role in (RoleChoices.ADMIN, RoleChoices.SUPERADMIN):
            return True

        return user.has_role('COLLEGE_SUPERADMIN', 'EXAM_OFFICER')


class IsFacultyUserRole(BasePermission):
    """
    Allows access to authenticated, active faculty members, examiners, and administrators.
    Student accounts are strictly rejected.
    """
    message = "Faculty access required."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        if user.is_superuser or user.is_staff:
            return True

        if user.role in (RoleChoices.FACULTY, RoleChoices.ADMIN, RoleChoices.SUPERADMIN):
            return True

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
    """
    message = "College superadministrator access required."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        if user.is_superuser or user.role == RoleChoices.SUPERADMIN:
            return True

        return user.has_role('COLLEGE_SUPERADMIN')
