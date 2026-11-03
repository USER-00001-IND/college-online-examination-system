"""
Academic Management RBAC Permissions.
Enforces institutional role boundaries:
- Admin / SuperAdmin: Full management of academic hierarchy and configuration.
- Faculty: Read-only access to academic catalogue; no write permissions.
- Student: Read-only access to academic catalogue; no write permissions.
- Anonymous: Denied (HTTP 401).
- is_staff=True alone NEVER bypasses RBAC boundaries.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission
from apps.accounts.models import RoleChoices
from apps.accounts.permissions import IsAdminUserRole, IsCollegeSuperAdmin


class IsAcademicAdminOrReadOnly(BasePermission):
    """
    Allows read access (GET, HEAD, OPTIONS) to any active, authenticated institutional user
    (Administrator, Faculty, or Student).
    Mutations (POST, PUT, PATCH, DELETE) require administrative privileges (IsAdminUserRole).
    Anonymous users are denied with 401.
    """
    message = "Administrator privileges required to modify academic records."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        if request.method in SAFE_METHODS:
            # All authenticated roles can read the academic catalogue
            return True

        # Mutation operations strictly require administrator RBAC authority
        admin_perm = IsAdminUserRole()
        return admin_perm.has_permission(request, view)


class IsInstitutionalConfigPermission(BasePermission):
    """
    Access control for Institutional Configuration (Table 21).
    - Read: Institutional Administrators and Superadministrators only. Students and Faculty denied.
    - Write: Institutional Administrators and Superadministrators only.
    - Sensitive Configs: Superadministrators only.
    """
    message = "Administrator access required for institutional configuration."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        # Students and Faculty accounts are strictly prohibited from viewing institutional config
        if user.role in (RoleChoices.STUDENT, RoleChoices.FACULTY):
            return False

        admin_perm = IsAdminUserRole()
        return admin_perm.has_permission(request, view)

    def has_object_permission(self, request, view, obj) -> bool:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not user.is_active:
            return False

        admin_perm = IsAdminUserRole()
        if not admin_perm.has_permission(request, view):
            return False

        # If object is sensitive and client attempts mutation, require Superadmin privileges
        if getattr(obj, "is_sensitive", False) and request.method not in SAFE_METHODS:
            superadmin_perm = IsCollegeSuperAdmin()
            return superadmin_perm.has_permission(request, view)

        return True
