"""
Permissions for Student Management Domain.
Enforces that students can only access and update their own academic profile,
while administrators retain authorized management oversight.
Privilege escalation via is_staff=True is strictly prevented.
"""

from rest_framework.permissions import BasePermission
from apps.accounts.models import RoleChoices


class IsStudentSelfOrAdmin(BasePermission):
    """
    Object-level permission allowing students to access only their own profile,
    and institutional administrators full management access.
    Faculty and unrelated accounts are strictly rejected.
    """
    message = "You do not have permission to access or modify this student profile."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        # Student accounts are permitted (object-level checks will restrict to self)
        if user.role == RoleChoices.STUDENT:
            return True

        # Faculty accounts are strictly rejected from student profile management
        if user.role == RoleChoices.FACULTY:
            return False

        # Administrator access
        if user.role in (RoleChoices.ADMIN, RoleChoices.SUPERADMIN) or user.is_superuser:
            return True

        if hasattr(user, 'has_role') and user.has_role('COLLEGE_SUPERADMIN', 'EXAM_OFFICER'):
            return True

        return False

    def has_object_permission(self, request, view, obj) -> bool:
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        # Faculty accounts strictly denied
        if user.role == RoleChoices.FACULTY:
            return False

        # Administrator access
        if user.role in (RoleChoices.ADMIN, RoleChoices.SUPERADMIN) or user.is_superuser:
            return True

        if hasattr(user, 'has_role') and user.has_role('COLLEGE_SUPERADMIN', 'EXAM_OFFICER'):
            return True

        # Student accounts can only access their own profile
        if user.role == RoleChoices.STUDENT:
            if hasattr(obj, 'user_id'):
                return obj.user_id == user.pk
            if hasattr(obj, 'user'):
                return obj.user == user
            return obj == user

        return False
