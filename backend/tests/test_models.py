"""
Tests for Domain A Models, UserManager, and Database Constraints.
College Online Examination System.
"""

from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    AuthEvent,
    AuthEventType,
    EmailVerification,
    RegistrationApproval,
    RegistrationApprovalStatus,
    Role,
    RoleChoices,
    User,
    UserRole,
)


class AccountsModelTests(TestCase):
    """Verifies Domain A models, managers, and integrity constraints."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_user',
            email='admin@gauhati.ac.in',
            password='ValidPassword@123',
            role=RoleChoices.ADMIN,
            is_active=True,
        )

    def test_create_standard_student(self):
        """Verify student creation sets is_active=False by default."""
        student = User.objects.create_user(
            username='student1',
            email='student1@gauhati.ac.in',
            password='ValidPassword@123',
            role=RoleChoices.STUDENT,
        )
        self.assertEqual(student.role, RoleChoices.STUDENT)
        self.assertFalse(student.is_active)
        self.assertFalse(student.is_staff)
        self.assertFalse(student.is_superuser)
        # Password must be securely hashed, never stored in plaintext
        self.assertNotEqual(student.password, 'ValidPassword@123')
        self.assertTrue(any(student.password.startswith(prefix) for prefix in ('pbkdf2_sha256$', 'md5$')))
        self.assertEqual(str(student), 'student1 (STUDENT)')

    def test_create_superuser(self):
        """Verify superuser creation enforces active, staff, and superuser flags."""
        superadmin = User.objects.create_superuser(
            username='rootadmin',
            email='root@gauhati.ac.in',
            password='ValidPassword@123',
        )
        self.assertEqual(superadmin.role, RoleChoices.SUPERADMIN)
        self.assertTrue(superadmin.is_active)
        self.assertTrue(superadmin.is_staff)
        self.assertTrue(superadmin.is_superuser)
        self.assertTrue(superadmin.has_perm('any_permission'))
        self.assertTrue(superadmin.has_module_perms('accounts'))

    def test_create_user_empty_username_or_email_raises_error(self):
        """Verify empty username or email raises ValueError."""
        with self.assertRaises(ValueError):
            User.objects.create_user(username='', email='test@gauhati.ac.in', password='ValidPassword@123')

        with self.assertRaises(ValueError):
            User.objects.create_user(username='testuser', email='', password='ValidPassword@123')

    def test_create_user_invalid_role_raises_error(self):
        """Verify non-existent role raises ValidationError."""
        with self.assertRaises(ValidationError):
            User.objects.create_user(
                username='invalid_role_user',
                email='test@gauhati.ac.in',
                password='ValidPassword@123',
                role='HACKER',
            )

    def test_duplicate_username_constraint(self):
        """Verify username uniqueness constraint."""
        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                username='admin_user',
                email='different@gauhati.ac.in',
                password='ValidPassword@123',
            )

    def test_duplicate_email_constraint(self):
        """Verify email uniqueness constraint."""
        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                username='unique_user',
                email='admin@gauhati.ac.in',
                password='ValidPassword@123',
            )

    def test_user_role_assignment_and_uniqueness(self):
        """Verify UserRole assignment and unique constraint uk_user_role."""
        role = Role.objects.create(code='EXAM_OFFICER', name='Examination Officer')
        user_role = UserRole.objects.create(
            user=self.admin,
            role=role,
            assigned_by=self.admin,
        )
        self.assertEqual(str(user_role), 'admin_user -> EXAM_OFFICER')
        self.assertTrue(self.admin.has_role('EXAM_OFFICER'))

        # Attempt duplicate assignment
        with self.assertRaises(IntegrityError):
            UserRole.objects.create(
                user=self.admin,
                role=role,
                assigned_by=self.admin,
            )

    def test_email_verification_model(self):
        """Verify EmailVerification model creation and representation."""
        student = User.objects.create_user(
            username='verify_student',
            email='verify@gauhati.ac.in',
            password='ValidPassword@123',
        )
        verification = EmailVerification.objects.create(
            user=student,
            token_hash='a' * 64,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        self.assertFalse(verification.is_used)
        self.assertIn('verify_student', str(verification))

    def test_registration_approval_model(self):
        """Verify RegistrationApproval model creation and one-to-one constraint."""
        student = User.objects.create_user(
            username='approval_student',
            email='approval@gauhati.ac.in',
            password='ValidPassword@123',
        )
        approval = RegistrationApproval.objects.create(
            user=student,
            status=RegistrationApprovalStatus.PENDING,
        )
        self.assertEqual(approval.status, RegistrationApprovalStatus.PENDING)
        self.assertIn('approval_student', str(approval))

        # Attempt duplicate registration approval for same user
        with self.assertRaises(IntegrityError):
            RegistrationApproval.objects.create(
                user=student,
                status=RegistrationApprovalStatus.APPROVED,
            )

    def test_auth_event_model_never_stores_passwords(self):
        """Verify AuthEvent model structure and sensitive data protection."""
        event = AuthEvent.objects.create(
            user=self.admin,
            identifier_entered='admin_user',
            event_type=AuthEventType.LOGIN_SUCCESS,
            ip_address='192.168.1.100',
            user_agent='Mozilla/5.0 Test Agent',
        )
        self.assertEqual(event.event_type, AuthEventType.LOGIN_SUCCESS)
        self.assertIn('LOGIN_SUCCESS', str(event))
        self.assertFalse(hasattr(event, 'password'))
        self.assertFalse(hasattr(event, 'password_hash'))
