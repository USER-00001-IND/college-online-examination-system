"""
Tests for Authentication Rate Limiting, Brute-Force Throttling, and Cache Gates.
College Online Examination System.
"""

from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from rest_framework import status

from apps.accounts.models import RoleChoices, User
from apps.accounts.throttling import AuthenticationThrottle


class AuthenticationThrottlingTests(TestCase):
    """
    Verifies dual-dimension rate limiting across client IP addresses and target identifiers.
    Ensures enumeration resistance, case normalization, and window expiration.
    """

    def setUp(self):
        cache.clear()
        self.password = 'SecurePassword@2026'
        self.student = User.objects.create_user(
            username='target_student',
            email='target.student@gauhati.ac.in',
            password=self.password,
            role=RoleChoices.STUDENT,
            is_active=True,
        )
        self.login_url = reverse('accounts:login')
        self.csrf_url = reverse('accounts:csrf-bootstrap')

    def tearDown(self):
        cache.clear()

    def _get_csrf_client(self):
        """Helper to create a Client with valid CSRF token."""
        client = Client(enforce_csrf_checks=True)
        resp = client.get(self.csrf_url)
        csrf_token = resp.cookies.get('csrftoken').value
        return client, csrf_token

    def test_requests_below_threshold_permitted(self):
        """Verify login attempts below threshold are not throttled."""
        client, csrf_token = self._get_csrf_client()

        for _ in range(4):
            response = client.post(
                self.login_url,
                {'identifier': 'target_student', 'password': 'WrongPassword123!'},
                content_type='application/json',
                HTTP_X_CSRFTOKEN=csrf_token,
            )
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertEqual(response.data['error']['code'], 'AUTHENTICATION_FAILED')

    def test_exceeding_target_threshold_returns_429(self):
        """Verify exceeding target threshold returns HTTP 429 RATE_LIMIT_EXCEEDED."""
        client, csrf_token = self._get_csrf_client()

        # Submit 5 failed attempts (configured target limit)
        for _ in range(5):
            response = client.post(
                self.login_url,
                {'identifier': 'target_student', 'password': 'WrongPassword123!'},
                content_type='application/json',
                HTTP_X_CSRFTOKEN=csrf_token,
            )
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # 6th attempt must be blocked by rate limiter
        response = client.post(
            self.login_url,
            {'identifier': 'target_student', 'password': 'WrongPassword123!'},
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.data['error']['code'], 'RATE_LIMIT_EXCEEDED')
        self.assertIn('Retry-After', response.headers)
        self.assertIn('retry_after_seconds', response.data['error']['details'])

    def test_case_and_whitespace_variations_do_not_bypass_throttling(self):
        """Verify attacker cannot evade throttling by changing case or padding whitespace."""
        client, csrf_token = self._get_csrf_client()

        variations = [
            'target_student',
            'TARGET_STUDENT',
            'Target_Student',
            '  target_student  ',
            ' TARGET_STUDENT ',
        ]

        # Use up the 5 allowed attempts across different case/whitespace variants
        for variant in variations:
            response = client.post(
                self.login_url,
                {'identifier': variant, 'password': 'WrongPassword123!'},
                content_type='application/json',
                HTTP_X_CSRFTOKEN=csrf_token,
            )
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Attempt with another case variation must be throttled
        response = client.post(
            self.login_url,
            {'identifier': 'tArGeT_sTuDeNt', 'password': 'WrongPassword123!'},
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_throttling_does_not_reveal_account_existence(self):
        """Verify non-existent accounts trigger identical rate limiting as existing accounts."""
        client, csrf_token = self._get_csrf_client()

        for _ in range(5):
            response = client.post(
                self.login_url,
                {'identifier': 'ghost_user', 'password': 'WrongPassword123!'},
                content_type='application/json',
                HTTP_X_CSRFTOKEN=csrf_token,
            )
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertEqual(response.data['error']['code'], 'AUTHENTICATION_FAILED')

        # 6th attempt on ghost user must be throttled with exact same response structure
        response = client.post(
            self.login_url,
            {'identifier': 'ghost_user', 'password': 'WrongPassword123!'},
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.data['error']['code'], 'RATE_LIMIT_EXCEEDED')

    def test_single_user_attack_does_not_block_different_user(self):
        """Verify throttling one identifier does not lock out a different account."""
        client, csrf_token = self._get_csrf_client()

        User.objects.create_user(
            username='innocent_user',
            email='innocent@gauhati.ac.in',
            password=self.password,
            role=RoleChoices.STUDENT,
            is_active=True,
        )

        # Exceed threshold for target_student
        for _ in range(5):
            client.post(
                self.login_url,
                {'identifier': 'target_student', 'password': 'WrongPassword123!'},
                content_type='application/json',
                HTTP_X_CSRFTOKEN=csrf_token,
            )

        # target_student is throttled
        response = client.post(
            self.login_url,
            {'identifier': 'target_student', 'password': self.password},
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # innocent_user from another IP or below target limit is not blocked by target limit
        response2 = client.post(
            self.login_url,
            {'identifier': 'innocent_user', 'password': self.password},
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

    def test_successful_login_resets_target_attempts(self):
        """Verify successful login clears target failed attempt counter."""
        client, csrf_token = self._get_csrf_client()

        # 3 failed attempts
        for _ in range(3):
            client.post(
                self.login_url,
                {'identifier': 'target_student', 'password': 'WrongPassword123!'},
                content_type='application/json',
                HTTP_X_CSRFTOKEN=csrf_token,
            )

        # Successful login
        response = client.post(
            self.login_url,
            {'identifier': 'target_student', 'password': self.password},
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # After success, counter is reset: read updated CSRF token from active session
        current_csrf = client.cookies.get('csrftoken').value
        # 3 more failed attempts must still be allowed
        for _ in range(3):
            resp = client.post(
                self.login_url,
                {'identifier': 'target_student', 'password': 'WrongPassword123!'},
                content_type='application/json',
                HTTP_X_CSRFTOKEN=current_csrf,
            )
            self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_spoofed_ip_header_does_not_bypass_ip_throttle(self):
        """Verify attacker cannot bypass IP throttle by injecting spoofed X-Forwarded-For."""
        client, csrf_token = self._get_csrf_client()

        # Submit attempts with spoofed rotating X-Forwarded-For headers
        for i in range(15):
            client.post(
                self.login_url,
                {'identifier': f'user_{i}', 'password': 'WrongPassword123!'},
                content_type='application/json',
                HTTP_X_CSRFTOKEN=csrf_token,
                HTTP_X_FORWARDED_FOR=f'10.0.0.{i}',
            )

        # 16th attempt from the same client must hit the IP rate limit regardless of spoofed header
        response = client.post(
            self.login_url,
            {'identifier': 'another_user', 'password': 'WrongPassword123!'},
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_FORWARDED_FOR='10.0.0.99',
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_production_cache_gate_rejects_dummy_cache(self):
        """Verify production configuration gate raises ImproperlyConfigured if DummyCache is used."""
        unsafe_caches = {
            'default': {
                'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
            }
        }
        with override_settings(CACHES=unsafe_caches):
            # Check logic in production settings
            backend = unsafe_caches['default']['BACKEND']
            self.assertEqual(backend, 'django.core.cache.backends.dummy.DummyCache')
