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
    - Read (GET, HEAD, OPTIONS): Permitted for students (scoped to self), faculty, and admins.
    - Write (POST, PUT, PATCH, DELETE): Strictly restricted to institutional administrators.
    """
    message = "You do not have permission to access or modify academic enrollment records."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        if request.method in SAFE_METHODS:
            return True

        # Write operations require institutional administrator authority
        if user.role in (RoleChoices.ADMIN, RoleChoices.SUPERADMIN) or user.is_superuser:
            return True

        if hasattr(user, 'has_role') and user.has_role('COLLEGE_SUPERADMIN', 'EXAM_OFFICER'):
            return True

        return False

    def has_object_permission(self, request, view, obj) -> bool:
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        if request.method in SAFE_METHODS:
            if user.role == RoleChoices.STUDENT:
                return obj.student.user_id == user.pk
            return True

        # Write operations require institutional administrator authority
        if user.role in (RoleChoices.ADMIN, RoleChoices.SUPERADMIN) or user.is_superuser:
            return True

        if hasattr(user, 'has_role') and user.has_role('COLLEGE_SUPERADMIN', 'EXAM_OFFICER'):
            return True

        return False
