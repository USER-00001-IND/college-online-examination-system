"""
Permissions for Faculty Management Domain.
Enforces that faculty can only access and update their own profile,
while administrators retain authorized management oversight.
Privilege escalation via is_staff=True is strictly prevented.
"""

from rest_framework.permissions import BasePermission
from apps.accounts.models import RoleChoices


class IsFacultySelfOrAdmin(BasePermission):
    """
    Object-level permission allowing faculty members to view and update only their own profile,
    and institutional administrators full management access.
    Student accounts and unauthenticated users are strictly rejected.
    """
    message = "You do not have permission to access or modify this faculty profile."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        # Student accounts are strictly barred
        if user.role == RoleChoices.STUDENT:
            return False

        # Faculty accounts are permitted for self-service
        if user.role == RoleChoices.FACULTY:
            return True

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

        # Student accounts strictly barred
        if user.role == RoleChoices.STUDENT:
            return False

        # Administrator access
        if user.role in (RoleChoices.ADMIN, RoleChoices.SUPERADMIN) or user.is_superuser:
            return True

        if hasattr(user, 'has_role') and user.has_role('COLLEGE_SUPERADMIN', 'EXAM_OFFICER'):
            return True

        # Faculty accounts can only access their own profile
        if user.role == RoleChoices.FACULTY:
            if hasattr(obj, 'user_id'):
                return obj.user_id == user.pk
            if hasattr(obj, 'user'):
                return obj.user == user
            return obj == user

        return False
