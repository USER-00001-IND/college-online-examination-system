"""
Tests for Role-Based Access Control (RBAC) Permissions and Cross-Role Isolation.
College Online Examination System.
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, RoleChoices, User, UserRole
from apps.accounts.permissions import (
    IsAdminUserRole,
    IsCollegeSuperAdmin,
    IsFacultyUserRole,
    IsStudentUserRole,
)


class RoleBasedAccessControlTests(TestCase):
    """
    Verifies that Administrator, Faculty, and Student roles are strictly compartmentalized,
    and that cross-role access is denied across all endpoints.
    """

    def setUp(self):
        self.client = APIClient()
        self.password = 'StrongAuthPassword@2026'

        # Student user
        self.student = User.objects.create_user(
            username='student_eva',
            email='student.eva@gauhati.ac.in',
            password=self.password,
            role=RoleChoices.STUDENT,
            is_active=True,
        )

        # Faculty user
        self.faculty = User.objects.create_user(
            username='faculty_ramesh',
            email='faculty.ramesh@gauhati.ac.in',
            password=self.password,
            role=RoleChoices.FACULTY,
            is_active=True,
        )

        # Admin user
        self.admin = User.objects.create_user(
            username='admin_officer',
            email='admin.officer@gauhati.ac.in',
            password=self.password,
            role=RoleChoices.ADMIN,
            is_active=True,
        )

        # Superadmin user
        self.superadmin = User.objects.create_superuser(
            username='super_principal',
            email='principal@gauhati.ac.in',
            password=self.password,
        )

        self.admin_url = reverse('accounts:test-admin-only')
        self.faculty_url = reverse('accounts:test-faculty-only')
        self.student_url = reverse('accounts:test-student-only')

    # --------------------------------------------------------------------------
    # Test 6: Administrator Permissions
    # --------------------------------------------------------------------------

    def test_admin_permissions_allow_admin_deny_others(self):
        """Verify Admin endpoint allows Admin and Superadmin, but denies Faculty and Student."""
        # Admin succeeds
        self.client.force_login(self.admin)
        response = self.client.get(self.admin_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Superadmin succeeds
        self.client.force_login(self.superadmin)
        response = self.client.get(self.admin_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Faculty denied (403)
        self.client.force_login(self.faculty)
        response = self.client.get(self.admin_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error']['code'], 'PERMISSION_DENIED')

        # Student denied (403)
        self.client.force_login(self.student)
        response = self.client.get(self.admin_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error']['code'], 'PERMISSION_DENIED')

    # --------------------------------------------------------------------------
    # Test 7: Faculty Permissions
    # --------------------------------------------------------------------------

    def test_faculty_permissions_allow_faculty_and_admin_deny_student(self):
        """Verify Faculty endpoint allows Faculty, Admin, and Superadmin, but denies Student."""
        # Faculty succeeds
        self.client.force_login(self.faculty)
        response = self.client.get(self.faculty_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Admin succeeds
        self.client.force_login(self.admin)
        response = self.client.get(self.faculty_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Superadmin succeeds
        self.client.force_login(self.superadmin)
        response = self.client.get(self.faculty_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Student denied (403)
        self.client.force_login(self.student)
        response = self.client.get(self.faculty_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error']['code'], 'PERMISSION_DENIED')

    # --------------------------------------------------------------------------
    # Test 8: Student Permissions
    # --------------------------------------------------------------------------

    def test_student_permissions_allow_student_deny_faculty_and_admin(self):
        """Verify Student endpoint allows Student, but isolates from Faculty and Admin."""
        # Student succeeds
        self.client.force_login(self.student)
        response = self.client.get(self.student_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Faculty denied (403)
        self.client.force_login(self.faculty)
        response = self.client.get(self.student_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error']['code'], 'PERMISSION_DENIED')

        # Admin denied (403)
        self.client.force_login(self.admin)
        response = self.client.get(self.student_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error']['code'], 'PERMISSION_DENIED')

    # --------------------------------------------------------------------------
    # Test 9: Complete Cross-Role Access Matrix
    # --------------------------------------------------------------------------

    def test_cross_role_access_matrix(self):
        """Matrix test enforcing exhaustive cross-role rejection."""
        matrix = [
            (self.student, self.admin_url, status.HTTP_403_FORBIDDEN),
            (self.student, self.faculty_url, status.HTTP_403_FORBIDDEN),
            (self.student, self.student_url, status.HTTP_200_OK),
            (self.faculty, self.admin_url, status.HTTP_403_FORBIDDEN),
            (self.faculty, self.faculty_url, status.HTTP_200_OK),
            (self.faculty, self.student_url, status.HTTP_403_FORBIDDEN),
            (self.admin, self.admin_url, status.HTTP_200_OK),
            (self.admin, self.faculty_url, status.HTTP_200_OK),
            (self.admin, self.student_url, status.HTTP_403_FORBIDDEN),
        ]

        for user, endpoint, expected_status in matrix:
            self.client.force_login(user)
            response = self.client.get(endpoint)
            self.assertEqual(
                response.status_code,
                expected_status,
                f"User {user.username} with role {user.role} requesting {endpoint} expected {expected_status} but got {response.status_code}",
            )

    # --------------------------------------------------------------------------
    # Test 10: Granular Role Assignment & Escalation Prevention
    # --------------------------------------------------------------------------

    def test_granular_role_assignment_grants_access(self):
        """Verify granular UserRole assignment elevates capability safely without mutating base role."""
        exam_officer_role = Role.objects.create(code='EXAM_OFFICER', name='Exam Officer')

        # Normal faculty without granular role cannot access admin endpoint
        self.client.force_login(self.faculty)
        response = self.client.get(self.admin_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Assign EXAM_OFFICER role to faculty
        UserRole.objects.create(
            user=self.faculty,
            role=exam_officer_role,
            assigned_by=self.superadmin,
        )

        # Now faculty has EXAM_OFFICER role and can access admin endpoint
        self.assertTrue(self.faculty.has_role('EXAM_OFFICER'))
        response = self.client.get(self.admin_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --------------------------------------------------------------------------
    # Finding B: Separation of is_staff from Institutional RBAC Authorization
    # --------------------------------------------------------------------------

    def test_is_staff_flag_alone_does_not_grant_admin_or_faculty_access(self):
        """
        Verify that is_staff=True does NOT escalate privileges.
        - STUDENT with is_staff=True cannot access admin or faculty endpoints.
        - FACULTY with is_staff=True cannot access admin endpoints.
        """
        staff_student = User.objects.create_user(
            username='staff_student',
            email='staff.student@gauhati.ac.in',
            password=self.password,
            role=RoleChoices.STUDENT,
            is_active=True,
            is_staff=True,
        )

        staff_faculty = User.objects.create_user(
            username='staff_faculty',
            email='staff.faculty@gauhati.ac.in',
            password=self.password,
            role=RoleChoices.FACULTY,
            is_active=True,
            is_staff=True,
        )

        admin_no_staff = User.objects.create_user(
            username='admin_no_staff',
            email='admin.nostaff@gauhati.ac.in',
            password=self.password,
            role=RoleChoices.ADMIN,
            is_active=True,
            is_staff=False,
        )

        # 1. STUDENT with is_staff=True: strictly denied admin and faculty endpoints
        self.client.force_login(staff_student)
        res = self.client.get(self.admin_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.get(self.faculty_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        # Permitted student endpoint
        res = self.client.get(self.student_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 2. FACULTY with is_staff=True: permitted faculty, strictly denied admin
        self.client.force_login(staff_faculty)
        res = self.client.get(self.admin_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.get(self.faculty_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 3. ADMIN without is_staff: approved admin access
        self.client.force_login(admin_no_staff)
        res = self.client.get(self.admin_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_unrelated_granular_role_does_not_grant_privileged_access(self):
        """Verify unrelated granular roles (e.g. INVIGILATOR) do not grant admin access."""
        invigilator_role = Role.objects.create(code='INVIGILATOR', name='Invigilator')
        UserRole.objects.create(
            user=self.faculty,
            role=invigilator_role,
            assigned_by=self.superadmin,
        )

        self.client.force_login(self.faculty)
        response = self.client.get(self.admin_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_student_cannot_be_escalated_via_granular_role(self):
        """
        Verify primary role STUDENT is hard-barred from privileged endpoints even if assigned
        the exact institutional 'EXAM_OFFICER' role code (Finding B & Round 3 correction).
        """
        exam_officer_role, _ = Role.objects.get_or_create(
            code='EXAM_OFFICER',
            defaults={'name': 'Exam Officer'},
        )
        UserRole.objects.create(
            user=self.student,
            role=exam_officer_role,
            assigned_by=self.superadmin,
        )

        # 1. UserRole is linked and student.has_role('EXAM_OFFICER') returns True
        self.assertTrue(self.student.has_role('EXAM_OFFICER'))

        self.client.force_login(self.student)

        # 2. Administrator endpoint access remains strictly 403 Forbidden
        response = self.client.get(self.admin_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error']['code'], 'PERMISSION_DENIED')

        # 3. Faculty endpoint access remains strictly 403 Forbidden
        response = self.client.get(self.faculty_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error']['code'], 'PERMISSION_DENIED')

        # 4. College superadministrator permission remains denied
        class DummyRequest:
            def __init__(self, user):
                self.user = user

        self.assertFalse(IsCollegeSuperAdmin().has_permission(DummyRequest(self.student), None))

        # 5. The ordinary student endpoint remains accessible
        response = self.client.get(self.student_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_inactive_and_anonymous_users_strictly_denied(self):
        """Verify inactive and unauthenticated users receive 401 on protected endpoints."""
        inactive_admin = User.objects.create_user(
            username='inactive_admin',
            email='inactive.admin@gauhati.ac.in',
            password=self.password,
            role=RoleChoices.ADMIN,
            is_active=False,
        )

        # Anonymous access -> 401
        self.client.logout()
        res = self.client.get(self.admin_url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

        # Inactive user access -> 401 (inactive accounts cannot authenticate sessions)
        self.client.force_login(inactive_admin)
        res = self.client.get(self.admin_url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_is_college_super_admin_permission(self):
        """Verify IsCollegeSuperAdmin permission class isolation."""
        permission = IsCollegeSuperAdmin()

        class DummyRequest:
            def __init__(self, user):
                self.user = user

        self.assertFalse(permission.has_permission(DummyRequest(self.student), None))
        self.assertFalse(permission.has_permission(DummyRequest(self.faculty), None))
        self.assertFalse(permission.has_permission(DummyRequest(self.admin), None))
        self.assertTrue(permission.has_permission(DummyRequest(self.superadmin), None))
