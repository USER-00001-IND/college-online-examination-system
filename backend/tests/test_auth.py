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
        from django.core.cache import cache
        cache.clear()

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

        self.csrf_bootstrap_url = reverse('accounts:csrf-bootstrap')
        self.login_url = reverse('accounts:login')
        self.logout_url = reverse('accounts:logout')
        self.user_url = reverse('accounts:current-user')

    def tearDown(self):
        from django.core.cache import cache
        cache.clear()

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
    # Test 13: CSRF Enforcement on Login, Mutations, and Bootstrap (Finding A)
    # --------------------------------------------------------------------------

    def test_csrf_bootstrap_and_login_enforcement(self):
        """
        Comprehensive test for Finding A CSRF enforcement:
        1. Safe GET bootstrap delivers CSRF cookie and token.
        2. Login POST without CSRF token is rejected with 403 Forbidden.
        3. Login POST with invalid CSRF token is rejected with 403 Forbidden.
        4. Login POST with valid CSRF token succeeds with 200 OK and establishes session.
        5. Session authentication functions correctly for protected endpoints.
        6. Logout POST without CSRF token is rejected with 403 Forbidden.
        7. Logout POST with valid CSRF token succeeds and invalidates session.
        """
        client = Client(enforce_csrf_checks=True)

        # 1. CSRF Bootstrap flow via designated safe GET endpoint
        bootstrap_resp = client.get(self.csrf_bootstrap_url)
        self.assertEqual(bootstrap_resp.status_code, status.HTTP_200_OK)
        self.assertIn('csrf_token', bootstrap_resp.json())
        csrf_cookie = bootstrap_resp.cookies.get('csrftoken')
        self.assertIsNotNone(csrf_cookie, "Bootstrap GET must set csrftoken cookie.")
        valid_csrf_token = csrf_cookie.value

        # 2. Login POST without CSRF token must be rejected with 403 Forbidden
        reject_client = Client(enforce_csrf_checks=True)
        resp_no_token = reject_client.post(
            self.login_url,
            {'identifier': 'active_student', 'password': self.password},
            content_type='application/json',
        )
        self.assertEqual(resp_no_token.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp_no_token.json()['error']['code'], 'PERMISSION_DENIED')

        # 3. Login POST with invalid CSRF token must be rejected with 403 Forbidden
        resp_invalid_token = client.post(
            self.login_url,
            {'identifier': 'active_student', 'password': self.password},
            content_type='application/json',
            HTTP_X_CSRFTOKEN='completely_invalid_csrf_token_value',
        )
        self.assertEqual(resp_invalid_token.status_code, status.HTTP_403_FORBIDDEN)

        # 4. Login POST with valid CSRF token must succeed
        login_resp = client.post(
            self.login_url,
            {'identifier': 'active_student', 'password': self.password},
            content_type='application/json',
            HTTP_X_CSRFTOKEN=valid_csrf_token,
        )
        self.assertEqual(login_resp.status_code, status.HTTP_200_OK)
        self.assertIn('sessionid', client.cookies, "Successful login must establish session cookie.")

        # 5. Authenticated session access works
        user_resp = client.get(self.user_url)
        self.assertEqual(user_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(user_resp.json()['user']['username'], 'active_student')

        # 6. Logout without CSRF token must be rejected with 403 Forbidden
        logout_no_csrf = client.post(self.logout_url)
        self.assertEqual(logout_no_csrf.status_code, status.HTTP_403_FORBIDDEN)

        # 7. Logout with valid CSRF token succeeds
        # Refresh/read active CSRF token for the session
        current_csrf = client.cookies.get('csrftoken').value
        logout_success = client.post(self.logout_url, HTTP_X_CSRFTOKEN=current_csrf)
        self.assertEqual(logout_success.status_code, status.HTTP_200_OK)

        # 8. Subsequent requests fail because session was invalidated
        subsequent_resp = client.get(self.user_url)
        self.assertEqual(subsequent_resp.status_code, status.HTTP_401_UNAUTHORIZED)

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
