"""
Permissions for Enrollments Domain.
Controls access to StudentAcademicRecord (Table 18).
Students have read-only access to their own academic admission records.
Administrators have full management privileges.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission
from apps.accounts.models import RoleChoices


class IsStudentAcademicRecordPermission(BasePermission):
    """
    Role-based permission for student academic records:
    - Students: Read-only access strictly scoped to their own records.
    - Faculty: Strictly denied access to private student academic records.
    - Administrators: Full management privileges.
    """
    message = "You do not have permission to access or modify academic enrollment records."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        # Faculty accounts are strictly denied access to student academic records
        if user.role == RoleChoices.FACULTY:
            return False

        if request.method in SAFE_METHODS:
            # Students are permitted for list/detail; queryset/object-level check restricts to self
            if user.role == RoleChoices.STUDENT:
                return True

            # Administrators permitted
            if user.role in (RoleChoices.ADMIN, RoleChoices.SUPERADMIN) or user.is_superuser:
                return True
            if hasattr(user, 'has_role') and user.has_role('COLLEGE_SUPERADMIN', 'EXAM_OFFICER'):
                return True
            return False

        # Write operations require institutional administrator authority
        if user.role == RoleChoices.STUDENT:
            return False

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

        if request.method in SAFE_METHODS:
            if user.role == RoleChoices.STUDENT:
                return obj.student.user_id == user.pk
            if user.role in (RoleChoices.ADMIN, RoleChoices.SUPERADMIN) or user.is_superuser:
                return True
            if hasattr(user, 'has_role') and user.has_role('COLLEGE_SUPERADMIN', 'EXAM_OFFICER'):
                return True
            return False

        # Write operations require institutional administrator authority
        if user.role in (RoleChoices.ADMIN, RoleChoices.SUPERADMIN) or user.is_superuser:
            return True

        if hasattr(user, 'has_role') and user.has_role('COLLEGE_SUPERADMIN', 'EXAM_OFFICER'):
            return True

        return False
