"""
Tests for Authentication APIs, Session Management, Enumeration Resistance, and CSRF Protection.
College Online Examination System.
"""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import Client, TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import AuthEvent, AuthEventType, RoleChoices, User


class AuthenticationAPITests(TestCase):
    """Verifies login, logout, session management, CSRF enforcement, and audit logs."""

    def setUp(self):
        self.client = APIClient()
        self.password = 'SecurePassword@2026'

        # Active student
        self.student = User.objects.create_user(
            username='active_student',
            email='active.student@gauhati.ac.in',
            password=self.password,
            role=RoleChoices.STUDENT,
            is_active=True,
        )

        # Inactive student (pending email verification or approval)
        self.inactive_student = User.objects.create_user(
            username='inactive_student',
            email='inactive.student@gauhati.ac.in',
            password=self.password,
            role=RoleChoices.STUDENT,
            is_active=False,
        )

        # Active faculty
        self.faculty = User.objects.create_user(
            username='active_faculty',
            email='faculty@gauhati.ac.in',
            password=self.password,
            role=RoleChoices.FACULTY,
            is_active=True,
        )

        self.login_url = reverse('accounts:login')
        self.logout_url = reverse('accounts:logout')
        self.user_url = reverse('accounts:current-user')

    # --------------------------------------------------------------------------
    # Test 1: Successful Login with Username & Email
    # --------------------------------------------------------------------------

    def test_login_success_with_username(self):
        """Verify successful login using username."""
        response = self.client.post(
            self.login_url,
            {'identifier': 'active_student', 'password': self.password},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('user', response.data)
        self.assertEqual(response.data['user']['username'], 'active_student')
        self.assertEqual(response.data['user']['role'], 'STUDENT')

        # Verify auth event was recorded
        event = AuthEvent.objects.filter(user=self.student, event_type=AuthEventType.LOGIN_SUCCESS).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.identifier_entered, 'active_student')

    def test_login_success_with_email(self):
        """Verify successful login using email (case-insensitive)."""
        response = self.client.post(
            self.login_url,
            {'identifier': 'ACTIVE.STUDENT@GAUHATI.AC.IN', 'password': self.password},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['email'], 'active.student@gauhati.ac.in')

        event = AuthEvent.objects.filter(user=self.student, event_type=AuthEventType.LOGIN_SUCCESS).first()
        self.assertIsNotNone(event)

    # --------------------------------------------------------------------------
    # Test 2 & 3: Password Rejection & Enumeration Resistance
    # --------------------------------------------------------------------------

    def test_incorrect_password_rejection(self):
        """Verify incorrect password returns 401 with generic message."""
        response = self.client.post(
            self.login_url,
            {'identifier': 'active_student', 'password': 'WrongPassword@999'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['error']['code'], 'AUTHENTICATION_FAILED')
        self.assertEqual(response.data['error']['message'], 'Invalid username/email or password.')

        event = AuthEvent.objects.filter(user=self.student, event_type=AuthEventType.LOGIN_FAILED).first()
        self.assertIsNotNone(event)

    def test_unknown_account_rejection_enumeration_resistant(self):
        """Verify non-existent user returns exact same generic error as wrong password."""
        response = self.client.post(
            self.login_url,
            {'identifier': 'nonexistent_user', 'password': 'SomePassword@123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['error']['code'], 'AUTHENTICATION_FAILED')
        self.assertEqual(response.data['error']['message'], 'Invalid username/email or password.')

        event = AuthEvent.objects.filter(identifier_entered='nonexistent_user', event_type=AuthEventType.LOGIN_FAILED).first()
        self.assertIsNotNone(event)
        self.assertIsNone(event.user)

    # --------------------------------------------------------------------------
    # Test 4: Inactive Account Rejection
    # --------------------------------------------------------------------------

    def test_inactive_account_rejection(self):
        """Verify inactive account is rejected with ACCOUNT_INACTIVE code."""
        response = self.client.post(
            self.login_url,
            {'identifier': 'inactive_student', 'password': self.password},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['error']['code'], 'ACCOUNT_INACTIVE')
        self.assertIn('inactive', response.data['error']['message'].lower())

        event = AuthEvent.objects.filter(user=self.inactive_student, event_type=AuthEventType.LOGIN_FAILED).first()
        self.assertIsNotNone(event)

    # --------------------------------------------------------------------------
    # Test 5: Anonymous Access to Protected Endpoints Denied (401)
    # --------------------------------------------------------------------------

    def test_anonymous_access_denied(self):
        """Verify unauthenticated requests to protected endpoints return 401."""
        response = self.client.get(self.user_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['error']['code'], 'AUTHENTICATION_REQUIRED')

        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # --------------------------------------------------------------------------
    # Test 11 & 12: Logout Flushes Session & Invalidation
    # --------------------------------------------------------------------------

    def test_logout_flushes_session(self):
        """Verify logging out clears session and prevents subsequent access."""
        # Log in
        self.client.force_login(self.student)
        response = self.client.get(self.user_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Log out
        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Logged out successfully.')

        # Verify logout event was logged
        event = AuthEvent.objects.filter(user=self.student, event_type=AuthEventType.LOGOUT).first()
        self.assertIsNotNone(event)

        # Subsequent request with now-cleared session must fail
        response = self.client.get(self.user_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # --------------------------------------------------------------------------
    # Test 13: CSRF Enforcement on State-Changing Requests
    # --------------------------------------------------------------------------

    def test_csrf_enforcement_on_mutations(self):
        """Verify CSRF token is strictly enforced for authenticated state-changing requests."""
        # 1. State-changing POST to logout without CSRF token must fail with 403 Forbidden
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.student)
        response = csrf_client.post(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('csrf', response.data['error']['message'].lower())

        # 2. Login via standard test client and retrieve CSRF cookie
        std_client = Client(enforce_csrf_checks=True)
        login_resp = std_client.post(
            self.login_url,
            {'identifier': 'active_student', 'password': self.password},
            content_type='application/json',
        )
        self.assertEqual(login_resp.status_code, status.HTTP_200_OK)
        csrf_token = login_resp.cookies.get('csrftoken')
        self.assertIsNotNone(csrf_token, "Login response must set csrftoken cookie.")

        # 3. POST to logout with valid CSRF token header must succeed
        response = std_client.post(
            self.logout_url,
            HTTP_X_CSRFTOKEN=csrf_token.value,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --------------------------------------------------------------------------
    # Test 14: Password Hashing & Validation
    # --------------------------------------------------------------------------

    def test_password_validation_and_hashing(self):
        """Verify password validation rejects weak passwords and hashes with secure algorithms."""
        from django.contrib.auth.hashers import identify_hasher, make_password

        # Short password (<8 characters)
        with self.assertRaises(DjangoValidationError):
            validate_password('short')

        # Entirely numeric password
        with self.assertRaises(DjangoValidationError):
            validate_password('1234567890')

        # Similar to username
        with self.assertRaises(DjangoValidationError):
            validate_password('active_student', user=self.student)

        # Stored password is a cryptographic hash, never plaintext
        self.assertNotEqual(self.student.password, self.password)
        hasher = identify_hasher(self.student.password)
        self.assertIn(hasher.algorithm, ['md5', 'pbkdf2_sha256'])

        # Verify PBKDF2-SHA256 hasher availability and format
        pbkdf2_hash = make_password('SecurePassword@2026', hasher='pbkdf2_sha256')
        self.assertTrue(pbkdf2_hash.startswith('pbkdf2_sha256$'))

    # --------------------------------------------------------------------------
    # Test 15: No Passwords Stored in AuthEvent
    # --------------------------------------------------------------------------

    def test_no_passwords_stored_in_auth_events(self):
        """Verify that password strings never appear in accounts_auth_event."""
        secret_password = 'SecretNeverToLog@2026'
        self.client.post(
            self.login_url,
            {'identifier': 'active_student', 'password': secret_password},
            format='json',
        )

        for event in AuthEvent.objects.all():
            self.assertNotIn(secret_password, event.identifier_entered)
            self.assertNotIn(secret_password, event.ip_address)
            self.assertNotIn(secret_password, event.user_agent or '')
