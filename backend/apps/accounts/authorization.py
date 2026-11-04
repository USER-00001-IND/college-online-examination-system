"""
Centralized Institutional Authorization Service.
Enforces multi-college scoping for administrative operations (Chunk 06 Round 3 - Finding R3-A).

Rules:
1. Superadministrators (user.role == SUPERADMIN or user.is_superuser) have system-wide authority across all colleges.
2. Ordinary Administrators (user.role == ADMIN or granular roles COLLEGE_SUPERADMIN, EXAM_OFFICER)
   have authority strictly bounded to their assigned college(s).
3. If an ordinary administrator's institutional scope cannot be determined from established data,
   fail closed (no access granted).
4. Student and Faculty accounts NEVER possess institutional administrator authority regardless of is_staff.
5. Client-supplied query parameters (e.g. ?college=2) NEVER widen access beyond authorized scope.
"""

from typing import Optional, Set
from django.core.exceptions import PermissionDenied
from apps.accounts.models import RoleChoices


def get_actor_authorized_college_ids(actor) -> Optional[Set[int]]:
    """
    Resolves the set of college IDs the actor is authorized to manage.
    Returns:
    - None: System-wide authority (Superadministrator / is_superuser) - all colleges permitted.
    - Set[int]: Explicit authorized college IDs for institutional administrator.
    - Set(): No authorized college scope (ambiguous, student, faculty, or inactive) - fail closed.
    """
    if not actor or not getattr(actor, 'is_authenticated', False) or not getattr(actor, 'is_active', False):
        return set()

    # Students and Faculty accounts NEVER have institutional administrator authority
    if actor.role in (RoleChoices.STUDENT, RoleChoices.FACULTY):
        return set()

    # Explicitly authorized Superadministrators have system-wide authority
    if actor.role == RoleChoices.SUPERADMIN or getattr(actor, 'is_superuser', False):
        return None

    # Ordinary Administrators
    is_admin = (
        actor.role == RoleChoices.ADMIN
        or (hasattr(actor, 'has_role') and actor.has_role('COLLEGE_SUPERADMIN', 'EXAM_OFFICER'))
    )
    if is_admin:
        # Check established college linkage
        # 1. Direct runtime attribute or property (e.g. set via session/context or user.college / user.college_id)
        if hasattr(actor, 'college_id') and actor.college_id:
            return {int(actor.college_id)}
        if hasattr(actor, 'college') and actor.college:
            cid = actor.college.pk if hasattr(actor.college, 'pk') else int(actor.college)
            return {cid}
        # 2. Linked FacultyProfile (if user also has faculty profile)
        if hasattr(actor, 'faculty_profile') and actor.faculty_profile and getattr(actor.faculty_profile, 'college_id', None):
            return {int(actor.faculty_profile.college_id)}

        # Ambiguous institutional scope: in the approved schema, accounts_user has no college_id column.
        # Fail closed for ordinary administrators without established college scope.
        return set()

    return set()


def check_college_operation_authority(actor, college_id, operation: Optional[str] = None) -> None:
    """
    Verifies that the actor has authoritative institutional administrative access to target college_id.
    Raises PermissionDenied if the actor lacks explicit authority or if scope is ambiguous.
    """
    if college_id is None:
        raise PermissionDenied("Target college must be specified for institutional authorization.")

    target_id = int(college_id.pk if hasattr(college_id, "pk") else college_id)

    authorized_colleges = get_actor_authorized_college_ids(actor)
    if authorized_colleges is None:
        # Superadministrator: system-wide authority granted
        return

    op_str = f" for '{operation}'" if operation else ""
    if not authorized_colleges:
        # Ambiguous or non-existent institutional scope
        raise PermissionDenied(
            f"Administrator institutional scope is ambiguous or unassigned{op_str}. "
            f"Operation on College ID {target_id} denied."
        )

    if target_id not in authorized_colleges:
        raise PermissionDenied(
            f"Administrator does not have authority over College ID {target_id}{op_str}."
        )
