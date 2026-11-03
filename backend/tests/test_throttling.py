"""
Tests for Authentication Rate Limiting, Brute-Force Throttling, Concurrency, and Production Cache Gates.
College Online Examination System.
"""

import concurrent.futures
import importlib
import os
import time
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.accounts.models import RoleChoices, User
from apps.accounts.throttling import AuthenticationThrottle, ThrottleBackendError
from apps.accounts.views import LoginView


class AuthenticationThrottlingAPITests(TestCase):
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

        # Submit 5 attempts (configured target limit)
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
        # 3 more failed attempts must still be allowed without hitting 429
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


class ProductionCacheSettingsGateTests(TestCase):
    """
    Verifies that the actual production settings module rejects unsafe cache backends
    and requires an explicit Redis backend at startup.
    """

    def setUp(self):
        self.base_prod_env = {
            'SECRET_KEY': 'production-secret-key-that-is-at-least-50-characters-long-and-random',
            'ALLOWED_HOSTS': 'exam.gauhati.ac.in',
            'DB_NAME': 'test_db',
            'DB_USER': 'test_user',
            'DB_PASSWORD': 'test_password',
            'DB_HOST': '127.0.0.1',
            'TRUST_PROXY_SSL_HEADER': 'False',
            'TRUST_PROXY_CLIENT_IP': 'False',
        }

    def test_missing_cache_url_rejected_in_production(self):
        """Verify production startup fails closed if REDIS_URL/CACHE_URL is not provided."""
        env = dict(self.base_prod_env)
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                import config.settings.production
                importlib.reload(config.settings.production)
            self.assertIn("REDIS_URL", str(ctx.exception))

    def test_unsupported_cache_scheme_rejected_in_production(self):
        """Verify non-Redis cache schemes are rejected in production."""
        env = dict(self.base_prod_env)
        env['REDIS_URL'] = 'http://insecure-cache-host:6379'
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                import config.settings.production
                importlib.reload(config.settings.production)
            self.assertIn("Unsupported production cache URL", str(ctx.exception))

    def test_valid_redis_url_accepted_in_production(self):
        """Verify valid redis:// URL is successfully accepted and configures RedisCache."""
        env = dict(self.base_prod_env)
        env['REDIS_URL'] = 'redis://127.0.0.1:6379/1'
        with patch.dict(os.environ, env, clear=True):
            import config.settings.production
            importlib.reload(config.settings.production)
            caches = config.settings.production.CACHES
            self.assertEqual(caches['default']['BACKEND'], 'django.core.cache.backends.redis.RedisCache')
            self.assertEqual(caches['default']['LOCATION'], 'redis://127.0.0.1:6379/1')


class ConcurrentRateLimitingTests(TestCase):
    """
    Verifies concurrency-safe atomic admission under simultaneous multi-threaded bursts.
    Proves that check-and-reserve eliminates race conditions.
    """

    def setUp(self):
        cache.clear()
        self.rf = APIRequestFactory()

    def tearDown(self):
        cache.clear()

    def test_concurrency_same_ip_burst(self):
        """
        Test A — Same-IP burst:
        Submit 30 concurrent admission requests with IP limit = 15.
        Exactly 15 must be admitted, and remaining 15 denied.
        """
        throttle = AuthenticationThrottle(ip_limit=15, ip_window=60, target_limit=50, target_window=60)
        results = []

        def submit_attempt(i):
            return throttle.acquire_admission('192.168.1.50', f'burst_user_{i}')

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(submit_attempt, i) for i in range(30)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        admitted = [r for r in results if r[0] is True]
        denied = [r for r in results if r[0] is False]

        self.assertEqual(len(admitted), 15, f"Expected exactly 15 admitted, got {len(admitted)}")
        self.assertEqual(len(denied), 15, f"Expected exactly 15 denied, got {len(denied)}")
        for r in denied:
            self.assertEqual(r[2], 'IP_LIMIT')

    def test_concurrency_same_identifier_burst(self):
        """
        Test B — Same-identifier burst:
        Submit 20 concurrent admission requests for the same IP and target with target limit = 5.
        Exactly 5 must be admitted, and remaining 15 denied.
        """
        throttle = AuthenticationThrottle(ip_limit=50, ip_window=60, target_limit=5, target_window=60)
        results = []

        def submit_attempt(i):
            return throttle.acquire_admission('192.168.1.60', 'same_target_user')

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(submit_attempt, i) for i in range(20)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        admitted = [r for r in results if r[0] is True]
        denied = [r for r in results if r[0] is False]

        self.assertEqual(len(admitted), 5, f"Expected exactly 5 admitted, got {len(admitted)}")
        self.assertEqual(len(denied), 15, f"Expected exactly 15 denied, got {len(denied)}")
        for r in denied:
            self.assertEqual(r[2], 'TARGET_LIMIT')
            self.assertGreater(r[1], 0)  # retry_after must be positive

    def test_shared_worker_state(self):
        """
        Test C — Shared worker state:
        Two independent limiter instances using the same shared cache observe synchronized counters.
        """
        worker_1_limiter = AuthenticationThrottle(target_limit=5, target_window=60)
        worker_2_limiter = AuthenticationThrottle(target_limit=5, target_window=60)

        # Worker 1 admits 3 attempts
        for _ in range(3):
            admitted, _, _ = worker_1_limiter.acquire_admission('10.0.0.5', 'shared_user')
            self.assertTrue(admitted)

        # Worker 2 must observe the state: admits 2 more
        for _ in range(2):
            admitted, _, _ = worker_2_limiter.acquire_admission('10.0.0.5', 'shared_user')
            self.assertTrue(admitted)

        # 6th attempt via Worker 1 must be denied
        admitted, retry_after, reason = worker_1_limiter.acquire_admission('10.0.0.5', 'shared_user')
        self.assertFalse(admitted)
        self.assertEqual(reason, 'TARGET_LIMIT')

    def test_backend_failure_fails_closed_without_password_check(self):
        """
        Test D — Backend failure:
        When throttle backend fails, request fails closed with HTTP 503.
        Password verification is NEVER executed.
        """
        view = LoginView.as_view()
        request = self.rf.post(
            '/api/v1/auth/login/',
            data={'identifier': 'some_student', 'password': 'Password123!'},
            format='json',
            REMOTE_ADDR='192.168.1.1',
        )

        with patch.object(AuthenticationThrottle, 'acquire_admission', side_effect=ThrottleBackendError("Redis down")):
            with patch.object(User, 'check_password') as mock_check_password:
                response = view(request)
                self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
                self.assertEqual(response.data['error']['code'], 'SERVICE_UNAVAILABLE')
                # Proves password check was NEVER executed
                mock_check_password.assert_not_called()

    def test_sliding_window_expiration(self):
        """
        Test E — Expiration:
        Exhaust limit in short window (1 second). After window expires, subsequent attempt is admitted.
        """
        short_throttle = AuthenticationThrottle(target_limit=2, target_window=1)

        # 2 attempts admitted
        self.assertTrue(short_throttle.acquire_admission('10.0.0.8', 'expiring_user')[0])
        self.assertTrue(short_throttle.acquire_admission('10.0.0.8', 'expiring_user')[0])

        # 3rd attempt denied
        self.assertFalse(short_throttle.acquire_admission('10.0.0.8', 'expiring_user')[0])

        # Wait for 1-second window to expire
        time.sleep(1.1)

        # Subsequent attempt must be admitted
        admitted, _, reason = short_throttle.acquire_admission('10.0.0.8', 'expiring_user')
        self.assertTrue(admitted, f"Expected admitted after expiry, got reason {reason}")

    def test_boundary_condition_single_slot_concurrency(self):
        """
        Test F — Boundary condition:
        When exactly 1 admission slot remains, 10 concurrent threads attempt to reserve it.
        Exactly 1 must succeed; all other 9 must be rejected.
        """
        throttle = AuthenticationThrottle(target_limit=5, target_window=60)

        # Reserve 4 slots
        for _ in range(4):
            admitted, _, _ = throttle.acquire_admission('10.0.0.9', 'boundary_user')
            self.assertTrue(admitted)

        # 1 slot remains: launch 10 simultaneous attempts
        results = []

        def race_for_last_slot(i):
            return throttle.acquire_admission('10.0.0.9', 'boundary_user')

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(race_for_last_slot, i) for i in range(10)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        admitted = [r for r in results if r[0] is True]
        denied = [r for r in results if r[0] is False]

        self.assertEqual(len(admitted), 1, f"Expected exactly 1 admitted for last slot, got {len(admitted)}")
        self.assertEqual(len(denied), 9, f"Expected 9 denied, got {len(denied)}")
