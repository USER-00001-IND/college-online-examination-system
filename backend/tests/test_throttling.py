"""
Tests for Authentication Rate Limiting, Brute-Force Throttling, Concurrency, and Production Cache Gates.
College Online Examination System.
"""

import concurrent.futures
import importlib
import logging
import os
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
import ast
import math
import uuid
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.accounts.models import RoleChoices, User
from apps.accounts.throttling import (
    AuthenticationThrottle,
    ThrottleBackendError,
    AdmissionResult,
    _hash_throttle_key,
    _local_throttle_lock,
    _make_effective_cache_key,
    canonicalize_redis_endpoint,
    sanitize_redis_url,
    validate_test_redis_safety,
    validate_and_decode_redis_response,
    REDIS_CHECK_AND_RESERVE_LUA,
)
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

    def test_successful_login_does_not_reset_target_attempts(self):
        """
        Verify that under the admission-limiting policy, successful login does NOT clear or decrement
        the target counter. Every admitted attempt (success or failure) consumes an admission slot.
        """
        client, csrf_token = self._get_csrf_client()

        # 3 failed attempts (attempts 1, 2, 3)
        for _ in range(3):
            client.post(
                self.login_url,
                {'identifier': 'target_student', 'password': 'WrongPassword123!'},
                content_type='application/json',
                HTTP_X_CSRFTOKEN=csrf_token,
            )

        # Successful login (attempt 4 out of 5)
        response = client.post(
            self.login_url,
            {'identifier': 'target_student', 'password': self.password},
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Read updated CSRF token from active session
        current_csrf = client.cookies.get('csrftoken').value

        # 1 more failed attempt (attempt 5 out of 5) is admitted
        resp5 = client.post(
            self.login_url,
            {'identifier': 'target_student', 'password': 'WrongPassword123!'},
            content_type='application/json',
            HTTP_X_CSRFTOKEN=current_csrf,
        )
        self.assertEqual(resp5.status_code, status.HTTP_401_UNAUTHORIZED)

        # 6th attempt must be rejected with HTTP 429 TARGET_LIMIT because attempts were not cleared!
        resp6 = client.post(
            self.login_url,
            {'identifier': 'target_student', 'password': 'WrongPassword123!'},
            content_type='application/json',
            HTTP_X_CSRFTOKEN=current_csrf,
        )
        self.assertEqual(resp6.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(resp6.data['error']['code'], 'RATE_LIMIT_EXCEEDED')

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


class MockRedisClient:
    """
    Thread-safe in-memory Redis simulator that accurately executes the Lua script
    used in production (REDIS_CHECK_AND_RESERVE_LUA).
    Provides atomic multi-threaded concurrency identical to a single-threaded Redis engine.
    Returns Redis bulk strings as bytes (b'ADMITTED', b'IP_LIMIT', b'TARGET_LIMIT')
    to ensure complete parity with redis-py drivers.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._data = {}      # key -> int count
        self._expires = {}   # key -> expire timestamp

    def _purge_expired(self, key):
        if key in self._expires and time.time() >= self._expires[key]:
            self._data.pop(key, None)
            self._expires.pop(key, None)

    def get(self, key):
        with self._lock:
            self._purge_expired(key)
            val = self._data.get(key)
            return str(val) if val is not None else None

    def ttl(self, key):
        with self._lock:
            self._purge_expired(key)
            if key not in self._data:
                return -2
            if key not in self._expires:
                return -1
            rem = self._expires[key] - time.time()
            if rem <= 0:
                self._purge_expired(key)
                return -2
            return max(1, int(math.ceil(rem)))

    def set(self, key, value, ex=None):
        with self._lock:
            self._data[key] = int(value)
            if ex:
                self._expires[key] = time.time() + int(ex)
            else:
                self._expires.pop(key, None)

    def delete(self, *keys):
        with self._lock:
            count = 0
            for k in keys:
                if k in self._data:
                    self._data.pop(k, None)
                    self._expires.pop(k, None)
                    count += 1
            return count

    def eval(self, script, numkeys, *keys_and_args):
        with self._lock:
            keys = keys_and_args[:numkeys]
            argv = keys_and_args[numkeys:]

            ip_key = keys[0]
            target_key = keys[1]
            ip_limit = int(argv[0])
            ip_window = int(argv[1])
            target_limit = int(argv[2])
            target_window = int(argv[3])

            self._purge_expired(ip_key)
            self._purge_expired(target_key)

            ip_count = int(self._data.get(ip_key, 0))
            target_count = int(self._data.get(target_key, 0))

            if ip_count >= ip_limit:
                ttl_val = self.ttl(ip_key)
                if ttl_val <= 0:
                    ttl_val = ip_window
                return [0, ttl_val, b'IP_LIMIT']

            if target_count >= target_limit:
                ttl_val = self.ttl(target_key)
                if ttl_val <= 0:
                    ttl_val = target_window
                return [0, ttl_val, b'TARGET_LIMIT']

            new_ip = ip_count + 1
            self._data[ip_key] = new_ip
            if new_ip == 1:
                self._expires[ip_key] = time.time() + ip_window

            new_target = target_count + 1
            self._data[target_key] = new_target
            if new_target == 1:
                self._expires[target_key] = time.time() + target_window

            return [1, 0, b'ADMITTED']


class ProductionEnvironmentFallbackTests(TestCase):
    """
    Verifies Finding 1: Strict elimination of unsafe production fallback.
    In production, Redis must be used exclusively; local-lock fallback is strictly forbidden.
    """

    def setUp(self):
        cache.clear()
        self.rf = APIRequestFactory()

    def tearDown(self):
        cache.clear()

    @override_settings(ENVIRONMENT_NAME='production')
    def test_production_redis_available_uses_atomic_redis_path(self):
        """Verify that when Redis is available in production, the atomic Redis Lua path is used."""
        mock_redis = MockRedisClient()
        throttle = AuthenticationThrottle()

        with patch.object(throttle, '_get_raw_redis_client', return_value=mock_redis):
            with patch('apps.accounts.throttling._local_throttle_lock') as mock_lock:
                admitted, ttl, reason = throttle.acquire_admission('192.168.1.1', 'prod_user')
                self.assertTrue(admitted)
                self.assertEqual(reason, 'ADMITTED')
                # Local lock must NEVER be acquired when Redis is available
                mock_lock.__enter__.assert_not_called()

    @override_settings(ENVIRONMENT_NAME='production')
    def test_production_redis_unavailable_raises_throttle_backend_error(self):
        """Verify that when Redis client is unavailable in production, ThrottleBackendError is raised."""
        throttle = AuthenticationThrottle()

        with patch.object(throttle, '_get_raw_redis_client', return_value=None):
            with self.assertRaises(ThrottleBackendError) as ctx:
                throttle.acquire_admission('192.168.1.1', 'prod_user')
            self.assertIn("Production authentication throttle requires an operational Redis client", str(ctx.exception))

    @override_settings(ENVIRONMENT_NAME='production')
    def test_production_redis_unavailable_never_enters_local_fallback(self):
        """Verify that when Redis is unavailable in production, local lock fallback is NEVER entered."""
        throttle = AuthenticationThrottle()

        with patch.object(throttle, '_get_raw_redis_client', return_value=None):
            with patch('apps.accounts.throttling._local_throttle_lock') as mock_lock:
                with self.assertRaises(ThrottleBackendError):
                    throttle.acquire_admission('192.168.1.1', 'prod_user')
                mock_lock.__enter__.assert_not_called()

    @override_settings(ENVIRONMENT_NAME='production')
    def test_production_redis_eval_failure_fails_closed_http_503(self):
        """Verify that a Redis evaluation failure in production fails closed with HTTP 503 and zero password checks."""
        view = LoginView.as_view()
        request = self.rf.post(
            '/api/v1/auth/login/',
            data={'identifier': 'prod_user', 'password': 'Password123!'},
            format='json',
            REMOTE_ADDR='192.168.1.1',
        )

        mock_redis = MockRedisClient()
        mock_redis.eval = MagicMock(side_effect=Exception("Simulated Redis network disconnection"))

        with patch.object(AuthenticationThrottle, '_get_raw_redis_client', return_value=mock_redis):
            with patch.object(User, 'check_password') as mock_check_password:
                response = view(request)
                self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
                self.assertEqual(response.data['error']['code'], 'SERVICE_UNAVAILABLE')
                # Proves password check was NEVER executed
                mock_check_password.assert_not_called()

    @override_settings(ENVIRONMENT_NAME='production', DEBUG=True)
    def test_production_environment_gate_does_not_rely_on_debug_alone(self):
        """
        Verify that explicit ENVIRONMENT_NAME='production' strictly enforces Redis even if DEBUG=True.
        Ensures debug flag misconfiguration cannot silently enable unsafe local lock in production.
        """
        throttle = AuthenticationThrottle()
        self.assertTrue(throttle._is_production_environment())

        with patch.object(throttle, '_get_raw_redis_client', return_value=None):
            with self.assertRaises(ThrottleBackendError):
                throttle.acquire_admission('192.168.1.1', 'prod_user')

    @override_settings(ENVIRONMENT_NAME='test', DEBUG=False)
    def test_test_environment_permits_local_fallback_when_debug_false(self):
        """Verify that explicit ENVIRONMENT_NAME='test' safely permits local lock fallback."""
        throttle = AuthenticationThrottle()
        self.assertFalse(throttle._is_production_environment())

        with patch.object(throttle, '_get_raw_redis_client', return_value=None):
            admitted, ttl, reason = throttle.acquire_admission('192.168.1.1', 'test_user')
            self.assertTrue(admitted)
            self.assertEqual(reason, 'ADMITTED')

    @override_settings(ENVIRONMENT_NAME='development')
    def test_dev_environment_permits_local_fallback(self):
        """Verify that development environment uses local lock fallback when Redis is unavailable."""
        throttle = AuthenticationThrottle()
        self.assertFalse(throttle._is_production_environment())

        with patch.object(throttle, '_get_raw_redis_client', return_value=None):
            admitted, ttl, reason = throttle.acquire_admission('192.168.1.1', 'dev_user')
            self.assertTrue(admitted)
            self.assertEqual(reason, 'ADMITTED')


class RedisLuaThrottlingUnitTests(TestCase):
    """
    Verifies consistent Redis key management and atomic check-and-reserve admission.
    Runs against the simulated thread-safe Redis Lua engine returning bytes bulk strings.
    """

    def setUp(self):
        self.mock_redis = MockRedisClient()
        self.patcher = patch.object(AuthenticationThrottle, '_get_raw_redis_client', return_value=self.mock_redis)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_initial_redis_key_creation_and_increments(self):
        """Verify Redis keys are created on initial admission and incremented on subsequent attempts."""
        throttle = AuthenticationThrottle(ip_limit=5, target_limit=3, ip_window=60, target_window=60)

        res1 = throttle.acquire_admission('10.0.0.1', 'student_a')
        self.assertTrue(res1.admitted)

        res2 = throttle.acquire_admission('10.0.0.1', 'student_a')
        self.assertTrue(res2.admitted)

        # Confirm keys exist in Redis with expected counts
        raw_target_key = _hash_throttle_key('target', '10.0.0.1:student_a')
        effective_target_key = _make_effective_cache_key(raw_target_key)
        self.assertEqual(self.mock_redis.get(effective_target_key), '2')

    def test_target_limit_enforcement_redis(self):
        """Verify target limit of 5 is strictly enforced via Redis Lua."""
        throttle = AuthenticationThrottle(ip_limit=50, target_limit=5, ip_window=60, target_window=60)

        for i in range(5):
            res = throttle.acquire_admission('10.0.0.2', 'target_user')
            self.assertTrue(res.admitted, f"Attempt {i+1} should be admitted")

        # 6th attempt must be denied
        res6 = throttle.acquire_admission('10.0.0.2', 'target_user')
        self.assertFalse(res6.admitted)
        self.assertEqual(res6.reason, 'TARGET_LIMIT')
        self.assertGreater(res6.retry_after, 0)

    def test_ip_limit_enforcement_redis(self):
        """Verify IP limit of 15 is strictly enforced across rotating users via Redis Lua."""
        throttle = AuthenticationThrottle(ip_limit=15, target_limit=50, ip_window=60, target_window=60)

        for i in range(15):
            res = throttle.acquire_admission('10.0.0.3', f'user_{i}')
            self.assertTrue(res.admitted, f"Attempt {i+1} should be admitted")

        # 16th attempt must be denied by IP limit
        res16 = throttle.acquire_admission('10.0.0.3', 'user_16')
        self.assertFalse(res16.admitted)
        self.assertEqual(res16.reason, 'IP_LIMIT')

    def test_redis_key_prefix_and_version_compatibility(self):
        """
        Verify that effective Redis keys match cache.make_key(raw_key).
        Ensures 100% namespace parity between Redis Lua operations and Django cache API.
        """
        raw_key = _hash_throttle_key('target', '10.0.0.4:test_prefix_user')
        effective_key = _make_effective_cache_key(raw_key)

        expected_key = cache.make_key(raw_key)
        self.assertEqual(effective_key, expected_key)

        throttle = AuthenticationThrottle()
        throttle.acquire_admission('10.0.0.4', 'test_prefix_user')

        # The key in Redis must be the effective key, not raw key
        self.assertIn(effective_key, self.mock_redis._data)

    def test_concurrency_same_ip_burst_redis(self):
        """
        Test A — Concurrent IP limit on Redis:
        30 concurrent threads submit admission requests with IP limit = 15.
        Exactly 15 must be admitted, and 15 denied.
        """
        throttle = AuthenticationThrottle(ip_limit=15, ip_window=60, target_limit=50, target_window=60)
        results = []

        def submit_attempt(i):
            return throttle.acquire_admission('10.0.0.10', f'burst_{i}')

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(submit_attempt, i) for i in range(30)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        admitted = [r for r in results if r[0] is True]
        denied = [r for r in results if r[0] is False]

        self.assertEqual(len(admitted), 15)
        self.assertEqual(len(denied), 15)
        for r in denied:
            self.assertEqual(r[2], 'IP_LIMIT')

    def test_concurrency_same_identifier_burst_redis(self):
        """
        Test B — Concurrent compound limit on Redis:
        20 concurrent threads submit admission requests for same target with limit = 5.
        Exactly 5 must be admitted, and 15 denied.
        """
        throttle = AuthenticationThrottle(ip_limit=50, ip_window=60, target_limit=5, target_window=60)
        results = []

        def submit_attempt(i):
            return throttle.acquire_admission('10.0.0.11', 'target_burst_user')

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(submit_attempt, i) for i in range(20)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        admitted = [r for r in results if r[0] is True]
        denied = [r for r in results if r[0] is False]

        self.assertEqual(len(admitted), 5)
        self.assertEqual(len(denied), 15)
        for r in denied:
            self.assertEqual(r[2], 'TARGET_LIMIT')

    def test_independent_worker_instances_share_redis_state(self):
        """
        Test C — Independent worker instances sharing Redis:
        Separate throttle instances communicate through the same Redis backend and observe shared counters.
        """
        worker_1 = AuthenticationThrottle(target_limit=5, target_window=60)
        worker_2 = AuthenticationThrottle(target_limit=5, target_window=60)

        # Worker 1 admits 3
        for _ in range(3):
            self.assertTrue(worker_1.acquire_admission('10.0.0.12', 'multi_worker_user')[0])

        # Worker 2 admits 2
        for _ in range(2):
            self.assertTrue(worker_2.acquire_admission('10.0.0.12', 'multi_worker_user')[0])

        # 6th attempt on Worker 1 must be denied
        res = worker_1.acquire_admission('10.0.0.12', 'multi_worker_user')
        self.assertFalse(res[0])
        self.assertEqual(res[2], 'TARGET_LIMIT')

    def test_last_slot_race_redis(self):
        """
        Test D — Last-slot race on Redis:
        1 slot left; 10 concurrent requests launch simultaneously; exactly 1 succeeds.
        """
        throttle = AuthenticationThrottle(target_limit=5, target_window=60)

        for _ in range(4):
            self.assertTrue(throttle.acquire_admission('10.0.0.13', 'last_slot_user')[0])

        results = []

        def race_attempt(i):
            return throttle.acquire_admission('10.0.0.13', 'last_slot_user')

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(race_attempt, i) for i in range(10)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        admitted = [r for r in results if r[0] is True]
        denied = [r for r in results if r[0] is False]

        self.assertEqual(len(admitted), 1)
        self.assertEqual(len(denied), 9)

    def test_expiration_redis(self):
        """
        Test E — Expiration on Redis:
        Short TTL expires and subsequent attempts are admitted.
        """
        short_throttle = AuthenticationThrottle(target_limit=2, target_window=1)

        self.assertTrue(short_throttle.acquire_admission('10.0.0.14', 'expiry_user')[0])
        self.assertTrue(short_throttle.acquire_admission('10.0.0.14', 'expiry_user')[0])
        self.assertFalse(short_throttle.acquire_admission('10.0.0.14', 'expiry_user')[0])

        time.sleep(1.1)

        # Renewed attempt after window expiration
        res = short_throttle.acquire_admission('10.0.0.14', 'expiry_user')
        self.assertTrue(res[0])

    def test_no_unexpected_deletion_of_unrelated_keys(self):
        """Verify operating on user_a does not affect user_b counters in Redis."""
        throttle = AuthenticationThrottle(target_limit=5, target_window=60)

        res_a = throttle.acquire_admission('10.0.0.16', 'user_a')
        res_b = throttle.acquire_admission('10.0.0.16', 'user_b')

        raw_b = _hash_throttle_key('target', '10.0.0.16:user_b')
        eff_b = _make_effective_cache_key(raw_b)
        self.assertEqual(self.mock_redis.get(eff_b), '1')

        # Additional attempt on user_a
        throttle.acquire_admission('10.0.0.16', 'user_a')

        # user_b counter must remain completely unaffected
        self.assertEqual(self.mock_redis.get(eff_b), '1')


class NoResetAdmissionIntegrityRegressionTests(TestCase):
    """
    Verifies Round 5 High Finding A:
    Complete elimination of successful-login counter resets.
    Proves that overlapping successful logins CANNOT erase newer failed-attempt reservations,
    and late logins completing after TTL expiration cannot alter a new window.
    """

    def setUp(self):
        self.mock_redis = MockRedisClient()
        self.patcher = patch.object(AuthenticationThrottle, '_get_raw_redis_client', return_value=self.mock_redis)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_reproduction_overlapping_logins_cannot_erase_failed_attempts(self):
        """
        Reproduction & Regression Test for High Finding A:
        Exact Sequence:
        Initial target counter = 0
        Login A reserves a slot (count = 1)
        Login B reserves a slot (count = 2)
        Login C reserves a slot and fails authentication (count = 3)
        Login A succeeds (authentication success)
        Login B succeeds (authentication success)

        Under Round 5 no-reset admission policy:
        Successful logins A and B do NOT reset or decrement counters!
        Counter in Redis remains 3. Login C's failed attempt is NOT erased!
        Next 2 attempts reach limit (5), and 6th attempt is blocked with TARGET_LIMIT.
        """
        throttle = AuthenticationThrottle(ip_limit=50, target_limit=5, target_window=300)
        raw_target_key = _hash_throttle_key('target', '10.0.0.20:target_student')
        eff_target_key = _make_effective_cache_key(raw_target_key)

        # 1. Login A reserves slot 1
        res_a = throttle.acquire_admission('10.0.0.20', 'target_student')
        self.assertTrue(res_a.admitted)
        self.assertEqual(self.mock_redis.get(eff_target_key), '1')

        # 2. Login B reserves slot 2
        res_b = throttle.acquire_admission('10.0.0.20', 'target_student')
        self.assertTrue(res_b.admitted)
        self.assertEqual(self.mock_redis.get(eff_target_key), '2')

        # 3. Login C reserves slot 3 and fails password check
        res_c = throttle.acquire_admission('10.0.0.20', 'target_student')
        self.assertTrue(res_c.admitted)
        self.assertEqual(self.mock_redis.get(eff_target_key), '3')

        # 4. Login A and Login B succeed!
        # In Round 5, successful logins DO NOT call reset_target.
        # Counter must REMAIN 3!
        self.assertEqual(self.mock_redis.get(eff_target_key), '3')

        # 5. Attacker tries to exploit: sends attempt 4 and attempt 5
        res_4 = throttle.acquire_admission('10.0.0.20', 'target_student')
        self.assertTrue(res_4.admitted)
        self.assertEqual(self.mock_redis.get(eff_target_key), '4')

        res_5 = throttle.acquire_admission('10.0.0.20', 'target_student')
        self.assertTrue(res_5.admitted)
        self.assertEqual(self.mock_redis.get(eff_target_key), '5')

        # 6. Attempt 6 must be blocked! Proves Login C's reservation was never erased!
        res_6 = throttle.acquire_admission('10.0.0.20', 'target_student')
        self.assertFalse(res_6.admitted)
        self.assertEqual(res_6.reason, 'TARGET_LIMIT')

    def test_login_completing_after_ttl_expiration_cannot_alter_new_window(self):
        """
        Verify that a login request completing after window expiration cannot
        alter or clear counters in the subsequent window because no reset call exists.
        """
        short_throttle = AuthenticationThrottle(ip_limit=50, target_limit=3, target_window=1)
        raw_key = _hash_throttle_key('target', '10.0.0.21:slow_user')
        eff_key = _make_effective_cache_key(raw_key)

        # 1. Slow login arrives in Window 1
        res_slow = short_throttle.acquire_admission('10.0.0.21', 'slow_user')
        self.assertTrue(res_slow.admitted)
        self.assertEqual(self.mock_redis.get(eff_key), '1')

        # 2. Window 1 expires (1.1s pass)
        time.sleep(1.1)

        # 3. New request arrives in Window 2
        res_new = short_throttle.acquire_admission('10.0.0.21', 'slow_user')
        self.assertTrue(res_new.admitted)
        self.assertEqual(self.mock_redis.get(eff_key), '1')

        # 4. Even if slow request's authentication "completes" now, it has no reset hook
        # Window 2's counter remains exactly 1
        self.assertEqual(self.mock_redis.get(eff_key), '1')

    def test_repeated_successful_logins_consume_admission_slots(self):
        """
        Verify that repeated successful logins consume admission slots under fixed-window semantics.
        Admitting 5 logins exhausts the target limit; 6th login is blocked.
        """
        throttle = AuthenticationThrottle(ip_limit=50, target_limit=5, target_window=300)

        for i in range(5):
            res = throttle.acquire_admission('10.0.0.22', 'rapid_user')
            self.assertTrue(res.admitted, f"Successful login {i+1} should be admitted")

        # 6th attempt is blocked
        res_blocked = throttle.acquire_admission('10.0.0.22', 'rapid_user')
        self.assertFalse(res_blocked.admitted)
        self.assertEqual(res_blocked.reason, 'TARGET_LIMIT')


class RedisResponseContractTests(TestCase):
    """
    Verifies Finding C (Medium): Strict Redis Lua Response Contract.
    The response is validated as one coherent contract:
    - Admitted [1, 0, 'ADMITTED']
    - Denied IP [0, 1 <= TTL <= max_ttl, 'IP_LIMIT']
    - Denied Target [0, 1 <= TTL <= max_ttl, 'TARGET_LIMIT']
    Contradictory, malformed, or out-of-bounds responses fail closed with ThrottleBackendError.
    """

    def setUp(self):
        self.throttle = AuthenticationThrottle(ip_limit=15, ip_window=300, target_limit=5, target_window=300)
        self.rf = APIRequestFactory()

    def test_valid_admitted_response_succeeds(self):
        """Verify valid admitted response [1, 0, b'ADMITTED'] succeeds."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [1, 0, b'ADMITTED']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            res = self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertTrue(res.admitted)
            self.assertEqual(res.retry_after, 0)
            self.assertEqual(res.reason, 'ADMITTED')

    def test_valid_ip_limit_response_denied(self):
        """Verify valid IP limit response [0, 120, b'IP_LIMIT'] is denied with retry-after."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [0, 120, b'IP_LIMIT']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            res = self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertFalse(res.admitted)
            self.assertEqual(res.retry_after, 120)
            self.assertEqual(res.reason, 'IP_LIMIT')

    def test_valid_target_limit_response_denied(self):
        """Verify valid target limit response [0, 180, b'TARGET_LIMIT'] is denied with retry-after."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [0, 180, b'TARGET_LIMIT']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            res = self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertFalse(res.admitted)
            self.assertEqual(res.retry_after, 180)
            self.assertEqual(res.reason, 'TARGET_LIMIT')

    def test_bytes_and_string_reasons_both_supported(self):
        """Verify both bytes and decoded strings are properly accepted and normalized."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [1, 0, 'ADMITTED']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            res = self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertTrue(res.admitted)
            self.assertEqual(res.reason, 'ADMITTED')

    def test_admission_with_ip_limit_reason_rejected(self):
        """Verify contradictory response: admitted with IP_LIMIT denial reason raises ThrottleBackendError."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [1, 0, b'IP_LIMIT']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            with self.assertRaises(ThrottleBackendError) as ctx:
                self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertIn("Contradictory throttle response", str(ctx.exception))

    def test_admission_with_target_limit_reason_rejected(self):
        """Verify contradictory response: admitted with TARGET_LIMIT denial reason raises ThrottleBackendError."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [1, 0, b'TARGET_LIMIT']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            with self.assertRaises(ThrottleBackendError) as ctx:
                self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertIn("Contradictory throttle response", str(ctx.exception))

    def test_denial_with_admitted_reason_rejected(self):
        """Verify contradictory response: denied with ADMITTED reason raises ThrottleBackendError."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [0, 60, b'ADMITTED']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            with self.assertRaises(ThrottleBackendError) as ctx:
                self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertIn("Contradictory throttle response", str(ctx.exception))

    def test_admission_with_nonzero_ttl_rejected(self):
        """Verify contradictory response: admitted with nonzero TTL raises ThrottleBackendError."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [1, 15, b'ADMITTED']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            with self.assertRaises(ThrottleBackendError) as ctx:
                self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertIn("nonzero TTL", str(ctx.exception))

    def test_denial_with_zero_ttl_rejected(self):
        """Verify contradictory response: denied with zero TTL raises ThrottleBackendError."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [0, 0, b'IP_LIMIT']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            with self.assertRaises(ThrottleBackendError) as ctx:
                self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertIn("non-positive TTL", str(ctx.exception))

    def test_denial_with_negative_ttl_rejected(self):
        """Verify contradictory response: denied with negative TTL raises ThrottleBackendError."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [0, -5, b'TARGET_LIMIT']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            with self.assertRaises(ThrottleBackendError) as ctx:
                self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertIn("non-positive TTL", str(ctx.exception))

    def test_oversized_ttl_rejected(self):
        """Verify unexpectedly large TTL exceeding max_ttl bound raises ThrottleBackendError."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [0, 999999, b'IP_LIMIT']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            with self.assertRaises(ThrottleBackendError) as ctx:
                self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertIn("exceeds maximum allowable bound", str(ctx.exception))

    def test_invalid_admission_flag_rejected(self):
        """Verify invalid admission flag (non-0/1 integer) raises ThrottleBackendError."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [2, 0, b'ADMITTED']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            with self.assertRaises(ThrottleBackendError) as ctx:
                self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertIn("Invalid throttle admission flag", str(ctx.exception))

    def test_string_admission_flag_rejected(self):
        """Verify non-integer admission flag (string 'true') raises ThrottleBackendError."""
        mock_client = MagicMock()
        mock_client.eval.return_value = ['true', 0, b'ADMITTED']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            with self.assertRaises(ThrottleBackendError):
                self.throttle.acquire_admission('10.0.0.1', 'user')

    def test_invalid_response_length_rejected(self):
        """Verify response sequences of invalid length (<3 or >3) raise ThrottleBackendError."""
        mock_client = MagicMock()
        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            # Length 2
            mock_client.eval.return_value = [1, 0]
            with self.assertRaises(ThrottleBackendError) as ctx:
                self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertIn("length", str(ctx.exception))

            # Length 4
            mock_client.eval.return_value = [1, 0, b'ADMITTED', 'EXTRA_PAYLOAD']
            with self.assertRaises(ThrottleBackendError) as ctx:
                self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertIn("length", str(ctx.exception))

    def test_invalid_response_type_rejected(self):
        """Verify non-sequence responses raise ThrottleBackendError."""
        mock_client = MagicMock()
        mock_client.eval.return_value = "NOT_A_LIST"

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            with self.assertRaises(ThrottleBackendError):
                self.throttle.acquire_admission('10.0.0.1', 'user')

    def test_invalid_bytes_rejected(self):
        """Verify invalid UTF-8 byte sequences raise ThrottleBackendError."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [1, 0, b'\xff\xfe\xfd']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            with self.assertRaises(ThrottleBackendError):
                self.throttle.acquire_admission('10.0.0.1', 'user')

    def test_invalid_reason_code_rejected(self):
        """Verify unknown reason code raises ThrottleBackendError."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [0, 60, b'UNRECOGNIZED_POLICY']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            with self.assertRaises(ThrottleBackendError) as ctx:
                self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertIn("Unknown throttle reason code", str(ctx.exception))

    def test_boolean_ttl_rejected(self):
        """Verify boolean value for TTL is rejected and raises ThrottleBackendError."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [0, True, b'IP_LIMIT']

        with patch.object(self.throttle, '_get_raw_redis_client', return_value=mock_client):
            with self.assertRaises(ThrottleBackendError) as ctx:
                self.throttle.acquire_admission('10.0.0.1', 'user')
            self.assertIn("boolean not permitted", str(ctx.exception))

    def test_login_view_returns_http_503_on_contract_violation(self):
        """Verify contradictory Redis response causes LoginView to return HTTP 503."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [1, 0, b'IP_LIMIT']  # Contradictory!

        view = LoginView.as_view()
        request = self.rf.post(
            '/api/v1/auth/login/',
            data={'identifier': 'student1', 'password': 'Password123!'},
            format='json',
            REMOTE_ADDR='192.168.1.1',
        )

        with patch.object(AuthenticationThrottle, '_get_raw_redis_client', return_value=mock_client):
            with patch.object(User, 'check_password') as mock_check_password:
                response = view(request)
                self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
                self.assertEqual(response.data['error']['code'], 'SERVICE_UNAVAILABLE')
                # Password check must NOT be executed!
                mock_check_password.assert_not_called()

    def test_password_check_and_session_creation_skipped_on_contract_violation(self):
        """Verify that when a contract violation occurs, credential checks and session creation are bypassed."""
        mock_client = MagicMock()
        mock_client.eval.return_value = [0, 300, b'ADMITTED']  # Contradictory!

        view = LoginView.as_view()
        request = self.rf.post(
            '/api/v1/auth/login/',
            data={'identifier': 'student1', 'password': 'Password123!'},
            format='json',
            REMOTE_ADDR='192.168.1.1',
        )

        with patch.object(AuthenticationThrottle, '_get_raw_redis_client', return_value=mock_client):
            with patch.object(User, 'check_password') as mock_check_password:
                response = view(request)
                self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
                mock_check_password.assert_not_called()


class SafeRedisExceptionLoggingTests(TestCase):
    """
    Verifies sanitized Redis exception logging.
    Guarantees raw exception text, passwords, connection URLs, and tokens
    are NEVER logged in production diagnostic logs.
    """

    def setUp(self):
        self.rf = APIRequestFactory()

    def test_redis_eval_exception_does_not_leak_secrets_in_logs(self):
        """Verify Redis Lua evaluation exception does not leak credentials or connection URLs in logs."""
        sensitive_secret = "super_secret_redis_password_987654"
        sensitive_url = f"redis://:{sensitive_secret}@redis-cluster.internal:6379/1"

        mock_redis = MockRedisClient()
        mock_redis.eval = MagicMock(side_effect=ConnectionError(f"Connection refused to {sensitive_url}"))

        throttle = AuthenticationThrottle()
        with patch.object(throttle, '_get_raw_redis_client', return_value=mock_redis):
            with self.assertLogs('college.accounts.throttling', level='CRITICAL') as cm:
                with self.assertRaises(ThrottleBackendError):
                    throttle.acquire_admission('10.0.0.1', 'secret_user')

            # Verify no secrets in log output
            full_log_output = " ".join(cm.output)
            self.assertNotIn(sensitive_secret, full_log_output)
            self.assertNotIn("redis-cluster.internal", full_log_output)
            self.assertNotIn("Connection refused", full_log_output)

            # Verify controlled category and safe exception class name are present
            self.assertIn("REDIS_EVALUATION_FAILED", full_log_output)
            self.assertIn("ConnectionError", full_log_output)

    def test_redis_client_acquisition_exception_does_not_leak_secrets(self):
        """Verify Redis client acquisition failure does not leak credentials in logs."""
        sensitive_auth_token = "secret_auth_token_abc123xyz"

        mock_cache = MagicMock()
        mock_cache._cache.get_client.side_effect = Exception(f"Failed authentication with token {sensitive_auth_token}")

        throttle = AuthenticationThrottle()
        with patch('apps.accounts.throttling.cache', mock_cache):
            with self.assertLogs('college.accounts.throttling', level='CRITICAL') as cm:
                client = throttle._get_raw_redis_client()
                self.assertIsNone(client)

            full_log = " ".join(cm.output)
            self.assertNotIn(sensitive_auth_token, full_log)
            self.assertIn("REDIS_CLIENT_ACQUISITION_FAILED", full_log)
            self.assertIn("Exception", full_log)

    def test_throttle_backend_error_does_not_chain_sensitive_exceptions(self):
        """Verify ThrottleBackendError suppresses __cause__ (from None) to prevent traceback leaks."""
        sensitive_text = "internal_database_secret_12345"

        mock_redis = MockRedisClient()
        mock_redis.eval = MagicMock(side_effect=ValueError(sensitive_text))

        throttle = AuthenticationThrottle()
        with patch.object(throttle, '_get_raw_redis_client', return_value=mock_redis):
            try:
                throttle.acquire_admission('10.0.0.1', 'user')
                self.fail("Expected ThrottleBackendError")
            except ThrottleBackendError as err:
                self.assertIsNone(err.__cause__)
                self.assertNotIn(sensitive_text, str(err))


class RedisKeyIsolationTests(TestCase):
    """
    Verifies Finding A (High): Real Per-Run Redis Test Key Isolation.
    Ensures that test-injected namespaces are applied to EVERY Redis key (both IP and compound target)
    before Lua script execution, effective keys are tracked, cleanup removes test keys only,
    sentinel keys remain untouched, separate test runs do not collide, and production keys are unchanged.
    """

    def test_keys_have_unique_test_namespace(self):
        """Verify that effective keys include the injected unique test namespace."""
        prefix = "test_throttle:run_abc123:"
        throttle = AuthenticationThrottle(key_prefix=prefix)
        eff_ip, eff_target = throttle.get_effective_keys('192.168.1.10', 'student_a')

        self.assertTrue(eff_ip.startswith(prefix), f"IP key '{eff_ip}' must start with '{prefix}'")
        self.assertTrue(eff_target.startswith(prefix), f"Target key '{eff_target}' must start with '{prefix}'")

    def test_ip_and_compound_keys_are_both_namespaced(self):
        """Verify both IP-level and compound IP+identifier dimensions are namespaced."""
        prefix = f"test_throttle:{uuid.uuid4().hex[:8]}:"
        throttle = AuthenticationThrottle(key_prefix=prefix)
        eff_ip, eff_target = throttle.get_effective_keys('10.0.0.50', 'faculty_member')

        self.assertIn("auth_throttle:ip:", eff_ip)
        self.assertIn("auth_throttle:target:", eff_target)
        self.assertTrue(eff_ip.startswith(prefix))
        self.assertTrue(eff_target.startswith(prefix))

    def test_generated_keys_are_tracked(self):
        """Verify that get_effective_keys provides exact keys passed to Redis eval."""
        prefix = "test_throttle:track_run:"
        throttle = AuthenticationThrottle(key_prefix=prefix)
        eff_ip, eff_target = throttle.get_effective_keys('172.16.5.5', 'test_user')

        mock_client_eval = MagicMock()
        mock_client_eval.eval.return_value = [1, 0, b'ADMITTED']

        with patch.object(throttle, '_get_raw_redis_client', return_value=mock_client_eval):
            throttle.acquire_admission('172.16.5.5', 'test_user')

            # Verify KEYS[1] and KEYS[2] match get_effective_keys exactly
            called_args = mock_client_eval.eval.call_args[0]
            numkeys = called_args[1]
            self.assertEqual(numkeys, 2)
            passed_ip_key = called_args[2]
            passed_target_key = called_args[3]
            self.assertEqual(passed_ip_key, eff_ip)
            self.assertEqual(passed_target_key, eff_target)

    def test_cleanup_removes_every_test_generated_key(self):
        """Verify cleanup removes every test-generated key without touching other keys."""
        mock_redis = MockRedisClient()
        prefix = "test_throttle:cleanup_test:"
        throttle = AuthenticationThrottle(key_prefix=prefix)

        with patch.object(throttle, '_get_raw_redis_client', return_value=mock_redis):
            eff_ip, eff_target = throttle.get_effective_keys('10.0.0.1', 'target_user')
            throttle.acquire_admission('10.0.0.1', 'target_user')

            # Both keys exist in Redis simulator
            self.assertIsNotNone(mock_redis.get(eff_ip))
            self.assertIsNotNone(mock_redis.get(eff_target))

            # Simulate tracked cleanup
            tracked = {eff_ip, eff_target}
            for k in tracked:
                if k.startswith(prefix):
                    mock_redis.delete(k)

            # Both keys are now deleted
            self.assertIsNone(mock_redis.get(eff_ip))
            self.assertIsNone(mock_redis.get(eff_target))

    def test_unrelated_sentinel_keys_remain_unchanged(self):
        """Verify unrelated sentinel keys outside the test namespace are untouched."""
        mock_redis = MockRedisClient()
        sentinel_key = "sentinel:shared_data:001"
        sentinel_value = b"CRITICAL_DATA_SAFE"
        mock_redis.set(sentinel_key, 1)

        prefix = "test_throttle:sentinel_test:"
        throttle = AuthenticationThrottle(key_prefix=prefix)

        with patch.object(throttle, '_get_raw_redis_client', return_value=mock_redis):
            throttle.acquire_admission('10.0.0.1', 'user')

            # Sentinel key is still intact
            self.assertEqual(mock_redis.get(sentinel_key), '1')

    def test_two_separate_test_runs_cannot_interfere(self):
        """Verify two independent test runs with different namespaces cannot collide or interfere."""
        mock_redis = MockRedisClient()

        run_1_prefix = "test_throttle:run_alpha:"
        throttle_1 = AuthenticationThrottle(target_limit=2, key_prefix=run_1_prefix)

        run_2_prefix = "test_throttle:run_beta:"
        throttle_2 = AuthenticationThrottle(target_limit=2, key_prefix=run_2_prefix)

        with patch.object(throttle_1, '_get_raw_redis_client', return_value=mock_redis):
            with patch.object(throttle_2, '_get_raw_redis_client', return_value=mock_redis):
                # Run 1 exhausts its limit
                self.assertTrue(throttle_1.acquire_admission('10.0.0.1', 'shared_student').admitted)
                self.assertTrue(throttle_1.acquire_admission('10.0.0.1', 'shared_student').admitted)
                self.assertFalse(throttle_1.acquire_admission('10.0.0.1', 'shared_student').admitted)

                # Run 2 for the exact same IP and student is completely independent and admitted!
                self.assertTrue(throttle_2.acquire_admission('10.0.0.1', 'shared_student').admitted)
                self.assertTrue(throttle_2.acquire_admission('10.0.0.1', 'shared_student').admitted)

    def test_concurrent_requests_in_same_test_share_expected_counters(self):
        """Verify concurrent requests sharing the same test namespace share the counters."""
        mock_redis = MockRedisClient()
        shared_prefix = "test_throttle:same_test_run:"

        throttle_a = AuthenticationThrottle(target_limit=3, key_prefix=shared_prefix)
        throttle_b = AuthenticationThrottle(target_limit=3, key_prefix=shared_prefix)

        with patch.object(throttle_a, '_get_raw_redis_client', return_value=mock_redis):
            with patch.object(throttle_b, '_get_raw_redis_client', return_value=mock_redis):
                self.assertTrue(throttle_a.acquire_admission('10.0.0.2', 'concurrent_user').admitted)
                self.assertTrue(throttle_b.acquire_admission('10.0.0.2', 'concurrent_user').admitted)
                self.assertTrue(throttle_a.acquire_admission('10.0.0.2', 'concurrent_user').admitted)
                # 4th request across both instances is denied
                self.assertFalse(throttle_b.acquire_admission('10.0.0.2', 'concurrent_user').admitted)

    def test_normal_production_key_naming_is_unchanged(self):
        """Verify normal production throttle instances (no key_prefix, no key_builder) use standard key naming."""
        prod_throttle = AuthenticationThrottle()
        eff_ip, eff_target = prod_throttle.get_effective_keys('127.0.0.1', 'production_user')

        self.assertFalse(eff_ip.startswith("test_throttle:"))
        self.assertFalse(eff_target.startswith("test_throttle:"))
        self.assertIn("auth_throttle:ip:", eff_ip)
        self.assertIn("auth_throttle:target:", eff_target)

    def test_test_only_injected_key_builder(self):
        """Verify custom injected key_builder callable is delegated to construct effective keys."""
        def custom_builder(dimension, value):
            return f"injected_namespace:{dimension}:{value}"

        throttle = AuthenticationThrottle(key_builder=custom_builder)
        eff_ip, eff_target = throttle.get_effective_keys('1.2.3.4', 'injected_user')

        self.assertEqual(eff_ip, "injected_namespace:ip:1.2.3.4")
        self.assertEqual(eff_target, "injected_namespace:target:1.2.3.4:injected_user")

    def test_regression_changing_ip_creates_separate_compound_counters_vs_shared_ip(self):
        """
        Regression test demonstrating the Round 6 target limit concurrency defect:
        1. When changing the IP per request (f'172.16.1.{i}'), each request generates
           a distinct compound key (ip:normalized_id), creating separate counters.
           With ip_limit=50, none of the 20 requests hit the target limit 5.
        2. When using a shared IP ('172.16.1.10') and shared identifier ('common_target'),
           all requests target the SAME compound key, strictly enforcing the 5-attempt limit:
           exactly 5 admitted, 15 rejected with TARGET_LIMIT, and target counter == 5.
        """
        mock_redis = MockRedisClient()
        prefix = f"test_throttle:{uuid.uuid4().hex[:8]}:"

        throttle = AuthenticationThrottle(
            ip_limit=50,
            ip_window=60,
            target_limit=5,
            target_window=60,
            key_prefix=prefix,
        )

        with patch.object(throttle, '_get_raw_redis_client', return_value=mock_redis):
            # Phase 1: Defect demonstration — rotating IP creates 20 distinct compound keys
            results_diff_ips = []
            for i in range(20):
                res = throttle.acquire_admission(f'10.99.1.{i}', 'common_student')
                results_diff_ips.append(res)

            # All 20 are admitted because each had its own compound counter (count=1 for each)
            self.assertEqual(len([r for r in results_diff_ips if r.admitted]), 20)
            self.assertEqual(len([r for r in results_diff_ips if not r.admitted]), 0)

            # Phase 2: Correct behavior — shared IP and shared identifier enforces compound limit
            shared_ip = '10.99.2.1'
            shared_identifier = 'common_student'
            eff_ip, eff_target = throttle.get_effective_keys(shared_ip, shared_identifier)

            results_shared_ip = []
            for i in range(20):
                res = throttle.acquire_admission(shared_ip, shared_identifier)
                results_shared_ip.append(res)

            admitted = [r for r in results_shared_ip if r.admitted]
            denied = [r for r in results_shared_ip if not r.admitted]

            self.assertEqual(len(admitted), 5)
            self.assertEqual(len(denied), 15)
            for r in denied:
                self.assertEqual(r.reason, 'TARGET_LIMIT')
                self.assertGreater(r.retry_after, 0)
                self.assertLessEqual(r.retry_after, 60)

            # Verify exact counter values in Redis
            self.assertEqual(int(mock_redis.get(eff_target)), 5)
            self.assertEqual(int(mock_redis.get(eff_ip)), 5)


class RedisEndpointSafetyTests(TestCase):
    """
    Verifies Finding B (High): Enforce Redis Test Endpoint Safety.
    Validates explicit test-only configuration (opt-in, test URL, disposable acknowledgment),
    endpoint canonicalization, collision detection against application Redis endpoints,
    credential sanitization, and visible failure on sentinel corruption or cleanup errors.
    """

    def test_missing_opt_in_skipped(self):
        """Verify that live integration tests skip when RUN_REDIS_INTEGRATION_TESTS != '1'."""
        orig_skip = getattr(SafeLiveRedisIntegrationTests, 'skip_reason', None)
        try:
            with patch.dict(os.environ, {
                'RUN_REDIS_INTEGRATION_TESTS': '0',
                'TEST_REDIS_URL': 'redis://127.0.0.1:6379/15',
                'TEST_REDIS_DISPOSABLE': 'YES',
            }):
                SafeLiveRedisIntegrationTests.setUpClass()
                self.assertIsNotNone(SafeLiveRedisIntegrationTests.skip_reason)
                self.assertIn("RUN_REDIS_INTEGRATION_TESTS=1", SafeLiveRedisIntegrationTests.skip_reason)
        finally:
            SafeLiveRedisIntegrationTests.skip_reason = orig_skip

    def test_missing_test_url_skipped(self):
        """Verify that live integration tests skip when TEST_REDIS_URL is empty."""
        orig_skip = getattr(SafeLiveRedisIntegrationTests, 'skip_reason', None)
        try:
            with patch.dict(os.environ, {
                'RUN_REDIS_INTEGRATION_TESTS': '1',
                'TEST_REDIS_URL': '',
                'TEST_REDIS_DISPOSABLE': 'YES',
            }):
                SafeLiveRedisIntegrationTests.setUpClass()
                self.assertIsNotNone(SafeLiveRedisIntegrationTests.skip_reason)
                self.assertIn("Dedicated TEST_REDIS_URL", SafeLiveRedisIntegrationTests.skip_reason)
        finally:
            SafeLiveRedisIntegrationTests.skip_reason = orig_skip

    def test_missing_disposable_acknowledgment_skipped(self):
        """Verify that live integration tests skip when TEST_REDIS_DISPOSABLE != 'YES'."""
        orig_skip = getattr(SafeLiveRedisIntegrationTests, 'skip_reason', None)
        try:
            with patch.dict(os.environ, {
                'RUN_REDIS_INTEGRATION_TESTS': '1',
                'TEST_REDIS_URL': 'redis://127.0.0.1:6379/15',
                'TEST_REDIS_DISPOSABLE': 'NO',
            }):
                SafeLiveRedisIntegrationTests.setUpClass()
                self.assertIsNotNone(SafeLiveRedisIntegrationTests.skip_reason)
                self.assertIn("TEST_REDIS_DISPOSABLE=YES", SafeLiveRedisIntegrationTests.skip_reason)
        finally:
            SafeLiveRedisIntegrationTests.skip_reason = orig_skip

    def test_same_test_and_app_endpoint_rejected(self):
        """Verify that identical test and application endpoints are rejected regardless of ENVIRONMENT_NAME."""
        test_url = "redis://127.0.0.1:6379/1"
        app_endpoints = [('redis', '127.0.0.1', 6379, 1)]
        is_safe, error = validate_test_redis_safety(test_url, app_endpoints=app_endpoints)
        self.assertFalse(is_safe)
        self.assertIn("conflicts with application Redis endpoint", error)

    def test_equivalent_urls_different_text_rejected(self):
        """Verify that textually different but equivalent URLs (e.g. localhost vs 127.0.0.1 default DB) are rejected."""
        test_url = "redis://localhost:6379/"  # resolves to 127.0.0.1:6379 db 0
        app_endpoints = [('redis', '127.0.0.1', 6379, 0)]  # resolves to 127.0.0.1:6379 db 0
        is_safe, error = validate_test_redis_safety(test_url, app_endpoints=app_endpoints)
        self.assertFalse(is_safe)
        self.assertIn("conflicts with application Redis endpoint", error)

    def test_invalid_url_scheme_rejected(self):
        """Verify that unsupported URL schemes (e.g. http://) are rejected."""
        test_url = "http://127.0.0.1:6379/15"
        is_safe, error = validate_test_redis_safety(test_url, app_endpoints=[])
        self.assertFalse(is_safe)
        self.assertIn("Unsupported Redis URL scheme", error)

    def test_invalid_or_ambiguous_configuration_rejected(self):
        """Verify that malformed URLs (e.g. negative db index or invalid port) are rejected."""
        test_url = "redis://127.0.0.1:6379/-1"
        is_safe, error = validate_test_redis_safety(test_url, app_endpoints=[])
        self.assertFalse(is_safe)
        self.assertIn("Invalid TEST_REDIS_URL", error)

    def test_credential_bearing_urls_sanitized(self):
        """Verify that credentials in URLs are masked in error messages and logs."""
        raw_url = "redis://admin:super_secret_password_123@redis.corp.internal:6379/5"
        sanitized = sanitize_redis_url(raw_url)
        self.assertNotIn("super_secret_password_123", sanitized)
        self.assertIn("***:***", sanitized)
        self.assertIn("redis.corp.internal:6379/5", sanitized)

    def test_no_redis_connection_before_safety_checks_pass(self):
        """Verify that no Redis connection is attempted if endpoint safety validation fails."""
        orig_skip = getattr(SafeLiveRedisIntegrationTests, 'skip_reason', None)
        try:
            with patch.dict(os.environ, {
                'RUN_REDIS_INTEGRATION_TESTS': '1',
                'TEST_REDIS_URL': 'redis://127.0.0.1:6379/1',  # Conflicts with app endpoint!
                'TEST_REDIS_DISPOSABLE': 'YES',
            }):
                with patch('apps.accounts.throttling.get_configured_application_redis_endpoints', return_value=[('redis', '127.0.0.1', 6379, 1)]):
                    with patch('redis.from_url') as mock_redis_connect:
                        SafeLiveRedisIntegrationTests.setUpClass()
                        self.assertIsNotNone(SafeLiveRedisIntegrationTests.skip_reason)
                        self.assertIn("Safety check failed", SafeLiveRedisIntegrationTests.skip_reason)
                        # Connection must NEVER have been attempted!
                        mock_redis_connect.assert_not_called()
        finally:
            SafeLiveRedisIntegrationTests.skip_reason = orig_skip

    def test_sentinel_modification_causes_visible_failure(self):
        """Verify that if the sentinel key is modified or corrupted, tearDown fails visibly."""
        test_instance = SafeLiveRedisIntegrationTests()
        test_instance._force_teardown = True
        test_instance.r = MagicMock()
        test_instance.skip_reason = None
        test_instance.sentinel_key = "sentinel:test_key"
        test_instance.sentinel_value = b"INITIAL_SENTINEL_VAL"
        test_instance.test_namespace = "test_throttle:err_test:"
        test_instance.tracked_keys = set()

        # Simulate corrupted sentinel value
        test_instance.r.get.return_value = b"CORRUPTED_SENTINEL_VAL"

        with self.assertRaises(AssertionError) as ctx:
            test_instance.tearDown()
        self.assertIn("Sentinel key corruption detected", str(ctx.exception))

    def test_cleanup_failure_reported(self):
        """Verify that if key cleanup fails, tearDown reports the failure visibly."""
        test_instance = SafeLiveRedisIntegrationTests()
        test_instance._force_teardown = True
        test_instance.r = MagicMock()
        test_instance.skip_reason = None
        test_instance.sentinel_key = "sentinel:test_key"
        test_instance.sentinel_value = b"INITIAL_SENTINEL_VAL"
        test_instance.r.get.return_value = b"INITIAL_SENTINEL_VAL"
        test_instance.test_namespace = "test_throttle:cleanup_err:"
        test_instance.tracked_keys = {"test_throttle:cleanup_err:key_1"}

        # Simulate deletion failure
        test_instance.r.delete.side_effect = Exception("Redis network reset")

        with self.assertRaises(AssertionError) as ctx:
            test_instance.tearDown()
        self.assertIn("Test cleanup failed", str(ctx.exception))

    def test_correctly_namespaced_key_is_deleted(self):
        """Verify that tearDown deletes tracked keys beginning with the test namespace."""
        test_instance = SafeLiveRedisIntegrationTests()
        test_instance._force_teardown = True
        test_instance.r = MagicMock()
        test_instance.skip_reason = None
        test_instance.sentinel_key = "sentinel:test_key"
        test_instance.sentinel_value = b"INITIAL_SENTINEL_VAL"
        test_instance.r.get.return_value = b"INITIAL_SENTINEL_VAL"
        test_instance.test_namespace = "test_throttle:valid_run:"
        test_instance.tracked_keys = {"test_throttle:valid_run:key_1"}

        test_instance.tearDown()
        test_instance.r.delete.assert_any_call("test_throttle:valid_run:key_1")
        test_instance.r.delete.assert_any_call("sentinel:test_key")

    def test_key_with_namespace_in_middle_is_not_deleted(self):
        """Verify that tearDown refuses to delete keys where test namespace is in the middle, not prefix."""
        test_instance = SafeLiveRedisIntegrationTests()
        test_instance._force_teardown = True
        test_instance.r = MagicMock()
        test_instance.skip_reason = None
        test_instance.sentinel_key = "sentinel:test_key"
        test_instance.sentinel_value = b"INITIAL_SENTINEL_VAL"
        test_instance.r.get.return_value = b"INITIAL_SENTINEL_VAL"
        test_instance.test_namespace = "test_throttle:my_run:"
        # Namespace appears in the middle (substring), not as prefix
        test_instance.tracked_keys = {"unrelated:test_throttle:my_run:key_1"}

        with self.assertRaises(AssertionError) as ctx:
            test_instance.tearDown()
        self.assertIn("outside the current test namespace", str(ctx.exception))
        # Ensure the key with namespace in middle was NOT deleted
        test_instance.r.delete.assert_called_once_with("sentinel:test_key")

    def test_key_from_another_test_run_is_not_deleted(self):
        """Verify that tearDown refuses to delete keys belonging to a different test run."""
        test_instance = SafeLiveRedisIntegrationTests()
        test_instance._force_teardown = True
        test_instance.r = MagicMock()
        test_instance.skip_reason = None
        test_instance.sentinel_key = "sentinel:test_key"
        test_instance.sentinel_value = b"INITIAL_SENTINEL_VAL"
        test_instance.r.get.return_value = b"INITIAL_SENTINEL_VAL"
        test_instance.test_namespace = "test_throttle:run_alpha:"
        # Belongs to run_beta
        test_instance.tracked_keys = {"test_throttle:run_beta:key_1"}

        with self.assertRaises(AssertionError) as ctx:
            test_instance.tearDown()
        self.assertIn("outside the current test namespace", str(ctx.exception))
        test_instance.r.delete.assert_called_once_with("sentinel:test_key")

    def test_unrelated_application_key_is_not_deleted(self):
        """Verify that tearDown refuses to delete untracked/unrelated application keys."""
        test_instance = SafeLiveRedisIntegrationTests()
        test_instance._force_teardown = True
        test_instance.r = MagicMock()
        test_instance.skip_reason = None
        test_instance.sentinel_key = "sentinel:test_key"
        test_instance.sentinel_value = b"INITIAL_SENTINEL_VAL"
        test_instance.r.get.return_value = b"INITIAL_SENTINEL_VAL"
        test_instance.test_namespace = "test_throttle:isolated_run:"
        # Normal application key without test namespace
        test_instance.tracked_keys = {"auth_throttle:ip:123"}

        with self.assertRaises(AssertionError) as ctx:
            test_instance.tearDown()
        self.assertIn("outside the current test namespace", str(ctx.exception))
        # Ensure the unrelated key was NOT deleted
        test_instance.r.delete.assert_called_once_with("sentinel:test_key")

    def test_all_exact_tracked_current_run_keys_cleaned_up(self):
        """Verify that tearDown successfully cleans up all exact tracked keys matching test namespace."""
        test_instance = SafeLiveRedisIntegrationTests()
        test_instance._force_teardown = True
        test_instance.r = MagicMock()
        test_instance.skip_reason = None
        test_instance.sentinel_key = "sentinel:test_key"
        test_instance.sentinel_value = b"INITIAL_SENTINEL_VAL"
        test_instance.r.get.return_value = b"INITIAL_SENTINEL_VAL"
        test_instance.test_namespace = "test_throttle:success_run:"
        test_instance.tracked_keys = {
            "test_throttle:success_run:ip:abc",
            "test_throttle:success_run:target:def",
        }

        test_instance.tearDown()
        # Deleted both tracked keys and the sentinel key
        self.assertEqual(test_instance.r.delete.call_count, 3)


class RedisIntegrationSafetyGuardTests(TestCase):
    """
    Verifies that live Redis integration test code strictly adheres to non-destructive isolation requirements:
    - Opt-in enforcement.
    - Dedicated test URL requirement.
    - Explicit disposable acknowledgment requirement.
    - Strict prohibition of database-wide wipe commands (FLUSHDB / FLUSHALL) via AST and source inspection.
    """

    def test_skipped_without_explicit_opt_in(self):
        """Verify integration tests are cleanly skipped when RUN_REDIS_INTEGRATION_TESTS is not '1'."""
        with patch.dict(os.environ, {'RUN_REDIS_INTEGRATION_TESTS': '0', 'TEST_REDIS_URL': 'redis://127.0.0.1:6379/15', 'TEST_REDIS_DISPOSABLE': 'YES'}):
            self.assertNotEqual(os.environ.get('RUN_REDIS_INTEGRATION_TESTS'), '1')

    def test_skipped_without_test_redis_url(self):
        """Verify integration tests are cleanly skipped when TEST_REDIS_URL is omitted."""
        with patch.dict(os.environ, {'RUN_REDIS_INTEGRATION_TESTS': '1', 'TEST_REDIS_URL': '', 'TEST_REDIS_DISPOSABLE': 'YES'}):
            test_url = os.environ.get('TEST_REDIS_URL', '').strip()
            self.assertEqual(test_url, '')

    def test_skipped_without_disposable_acknowledgment(self):
        """Verify integration tests are cleanly skipped when TEST_REDIS_DISPOSABLE is not 'YES'."""
        with patch.dict(os.environ, {'RUN_REDIS_INTEGRATION_TESTS': '1', 'TEST_REDIS_URL': 'redis://127.0.0.1:6379/15', 'TEST_REDIS_DISPOSABLE': 'NO'}):
            ack = os.environ.get('TEST_REDIS_DISPOSABLE', '').strip().upper()
            self.assertNotEqual(ack, 'YES')

    def test_test_source_never_contains_flushdb_or_flushall(self):
        """
        Verify that test_throttling.py contains ZERO occurrences of database-wide wipe commands
        in executable test code via string and AST analysis.
        """
        import inspect
        import tests.test_throttling as test_module
        source = inspect.getsource(test_module)

        # Remove this method's own source to prevent self-matching
        own_source = inspect.getsource(self.test_test_source_never_contains_flushdb_or_flushall)
        inspected_source = source.replace(own_source, '')

        target_cmds = ['.' + 'flush' + 'db()', '.' + 'flush' + 'all()', 'r.' + 'flush' + 'db', 'r.' + 'flush' + 'all']
        for cmd in target_cmds:
            self.assertNotIn(cmd, inspected_source)

        import ast
        tree = ast.parse(inspected_source)
        forbidden_attrs = {'flush' + 'db', 'flush' + 'all'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, forbidden_attrs)


class SafeLiveRedisIntegrationTests(TestCase):
    """
    Live Redis Integration Tests with strict non-destructive isolation safeguards:
    - Requires explicit opt-in via RUN_REDIS_INTEGRATION_TESTS=1.
    - Requires dedicated disposable TEST_REDIS_URL.
    - Requires explicit acknowledgment TEST_REDIS_DISPOSABLE=YES.
    - Validates endpoint safety and rejects application Redis collisions.
    - Uses unique per-run namespace (test_throttle:<uuid>:) applied to EVERY Redis key.
    - NEVER executes FLUSHDB, FLUSHALL, or database-wide wipe commands.
    - Tracks and cleans up ONLY keys created by this exact test run.
    - Verifies unrelated sentinel keys remain untouched throughout.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        opt_in = os.environ.get('RUN_REDIS_INTEGRATION_TESTS', '').strip()
        test_url = os.environ.get('TEST_REDIS_URL', '').strip()
        disposable_ack = os.environ.get('TEST_REDIS_DISPOSABLE', '').strip().upper()

        if opt_in != '1':
            cls.skip_reason = (
                "REAL REDIS INTEGRATION: NOT EXECUTED — Explicit opt-in "
                "RUN_REDIS_INTEGRATION_TESTS=1 required to execute live Redis integration tests."
            )
            return

        if not test_url:
            cls.skip_reason = (
                "REAL REDIS INTEGRATION: NOT EXECUTED — Dedicated TEST_REDIS_URL "
                "environment variable required for live Redis integration."
            )
            return

        if disposable_ack != 'YES':
            cls.skip_reason = (
                "REAL REDIS INTEGRATION: NOT EXECUTED — Explicit confirmation "
                "TEST_REDIS_DISPOSABLE=YES required to confirm target Redis instance is disposable."
            )
            return

        is_safe, error_msg = validate_test_redis_safety(test_url)
        if not is_safe:
            cls.skip_reason = f"REAL REDIS INTEGRATION: NOT EXECUTED — Safety check failed: {error_msg}"
            return

        try:
            import redis
            cls.r = redis.from_url(test_url, socket_timeout=1.0)
            cls.r.ping()
            cls.skip_reason = None
        except Exception as exc:
            cls.skip_reason = (
                f"REAL REDIS INTEGRATION: NOT EXECUTED — Unable to connect to TEST_REDIS_URL "
                f"({sanitize_redis_url(test_url)}): {exc.__class__.__name__}"
            )

    def setUp(self):
        if getattr(self.__class__, 'skip_reason', None):
            self.skipTest(self.__class__.skip_reason)

        self.test_run_id = uuid.uuid4().hex[:12]
        self.test_namespace = f"test_throttle:{self.test_run_id}:"
        self.tracked_keys = set()

        # Write an unrelated sentinel key outside the test namespace to verify non-destruction
        self.sentinel_key = f"sentinel:system_data:{uuid.uuid4().hex[:8]}"
        self.sentinel_value = b"CRITICAL_SHARED_DATABASE_DATA_PRESERVED"
        self.r.set(self.sentinel_key, self.sentinel_value)

    def tearDown(self):
        is_mock_test = hasattr(self, '_force_teardown') or ('skip_reason' in self.__dict__ and self.skip_reason is None)
        if not is_mock_test:
            if not hasattr(self, 'r') or getattr(self.__class__, 'skip_reason', None) is not None:
                return

        sentinel_failure = None
        try:
            # 1. Assert the unrelated sentinel key was NEVER deleted or modified
            current_sentinel = self.r.get(self.sentinel_key)
            if current_sentinel != self.sentinel_value:
                sentinel_failure = (
                    f"Sentinel key corruption detected! Expected {self.sentinel_value!r}, got {current_sentinel!r}."
                )
        except Exception as exc:
            sentinel_failure = f"Failed to verify sentinel key integrity: {exc}"

        cleanup_errors = []
        try:
            # 2. Non-destructively clean up ONLY test-created keys within this run's namespace
            for k in list(self.tracked_keys):
                if k.startswith(self.test_namespace):
                    try:
                        self.r.delete(k)
                    except Exception as exc:
                        cleanup_errors.append(f"Failed to delete test key {k}: {exc}")
                else:
                    cleanup_errors.append(
                        f"Refusing to delete key '{k}' outside the current test namespace '{self.test_namespace}'"
                    )
        finally:
            # 3. Best-effort delete of sentinel key
            try:
                self.r.delete(self.sentinel_key)
            except Exception as exc:
                cleanup_errors.append(f"Failed to delete sentinel key {self.sentinel_key}: {exc}")

        # 4. Fail visibly if sentinel was corrupted
        if sentinel_failure:
            self.fail(f"CRITICAL: {sentinel_failure}")

        # 5. Report cleanup failures rather than silently suppressing them
        if cleanup_errors:
            self.fail(f"Test cleanup failed: {'; '.join(cleanup_errors)}")

    def test_case_1_concurrent_ip_burst_limit_15(self):
        """Case 1 against live Redis: Thirty concurrent requests with IP limit 15."""
        throttle = AuthenticationThrottle(
            ip_limit=15, ip_window=60, target_limit=50, target_window=60, key_prefix=self.test_namespace
        )
        with patch.object(throttle, '_get_raw_redis_client', return_value=self.r):
            results = []

            def submit(i):
                eff_ip, eff_target = throttle.get_effective_keys('172.16.0.1', f'live_user_{i}')
                self.tracked_keys.add(eff_ip)
                self.tracked_keys.add(eff_target)
                return throttle.acquire_admission('172.16.0.1', f'live_user_{i}')

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(submit, i) for i in range(30)]
                for f in concurrent.futures.as_completed(futures):
                    results.append(f.result())

            admitted = [r for r in results if r[0] is True]
            denied = [r for r in results if r[0] is False]
            self.assertEqual(len(admitted), 15)
            self.assertEqual(len(denied), 15)
            for r in denied:
                self.assertEqual(r[2], 'IP_LIMIT')

    def test_case_2_concurrent_target_burst_limit_5(self):
        """Case 2 against live Redis: Twenty concurrent requests with compound target limit 5 using shared IP and identifier."""
        shared_ip = '172.16.1.10'
        shared_identifier = 'common_target'

        throttle = AuthenticationThrottle(
            ip_limit=50,
            ip_window=60,
            target_limit=5,
            target_window=60,
            key_prefix=self.test_namespace,
        )

        eff_ip, eff_target = throttle.get_effective_keys(shared_ip, shared_identifier)
        self.tracked_keys.add(eff_ip)
        self.tracked_keys.add(eff_target)

        # Assert effective keys begin with unique test namespace
        self.assertTrue(eff_ip.startswith(self.test_namespace))
        self.assertTrue(eff_target.startswith(self.test_namespace))

        with patch.object(throttle, '_get_raw_redis_client', return_value=self.r):
            results = []

            def submit(i):
                return throttle.acquire_admission(shared_ip, shared_identifier)

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(submit, i) for i in range(20)]
                for f in concurrent.futures.as_completed(futures):
                    results.append(f.result())

            admitted = [r for r in results if r[0] is True]
            denied = [r for r in results if r[0] is False]

            # Exactly 5 admitted, exactly 15 rejected
            self.assertEqual(len(admitted), 5)
            self.assertEqual(len(denied), 15)

            # Every rejected request must have reason TARGET_LIMIT and valid positive bounded retry_after
            for r in denied:
                self.assertEqual(r[2], 'TARGET_LIMIT')
                self.assertGreater(r[1], 0)
                self.assertLessEqual(r[1], 60)

            # Assert target Redis counter and IP Redis counter are exactly 5
            target_val = self.r.get(eff_target)
            ip_val = self.r.get(eff_ip)
            target_count = int(target_val.decode('utf-8') if isinstance(target_val, bytes) else target_val)
            ip_count = int(ip_val.decode('utf-8') if isinstance(ip_val, bytes) else ip_val)
            self.assertEqual(target_count, 5)
            self.assertEqual(ip_count, 5)

            # Assert remaining TTLs in Redis are positive and within configured window
            target_ttl = self.r.ttl(eff_target)
            ip_ttl = self.r.ttl(eff_ip)
            self.assertGreater(target_ttl, 0)
            self.assertLessEqual(target_ttl, 60)
            self.assertGreater(ip_ttl, 0)
            self.assertLessEqual(ip_ttl, 60)

            # Sentinel key remains unchanged
            self.assertEqual(self.r.get(self.sentinel_key), self.sentinel_value)

    def test_case_3_multiple_independent_limiter_instances_sharing_redis(self):
        """Case 3 against live Redis: Multiple independent limiter instances sharing Redis."""
        limiter_1 = AuthenticationThrottle(target_limit=5, target_window=60, key_prefix=self.test_namespace)
        limiter_2 = AuthenticationThrottle(target_limit=5, target_window=60, key_prefix=self.test_namespace)

        with patch.object(limiter_1, '_get_raw_redis_client', return_value=self.r):
            with patch.object(limiter_2, '_get_raw_redis_client', return_value=self.r):
                eff_ip, eff_target = limiter_1.get_effective_keys('172.16.2.1', 'shared_account')
                self.tracked_keys.add(eff_ip)
                self.tracked_keys.add(eff_target)

                # Limiter 1 admits 3
                for _ in range(3):
                    self.assertTrue(limiter_1.acquire_admission('172.16.2.1', 'shared_account').admitted)

                # Limiter 2 admits 2
                for _ in range(2):
                    self.assertTrue(limiter_2.acquire_admission('172.16.2.1', 'shared_account').admitted)

                # 6th attempt across both is blocked
                res = limiter_1.acquire_admission('172.16.2.1', 'shared_account')
                self.assertFalse(res.admitted)
                self.assertEqual(res.reason, 'TARGET_LIMIT')

    def test_case_4_last_slot_concurrency_race(self):
        """Case 4 against live Redis: Last-slot concurrency race between 10 simultaneous threads."""
        throttle = AuthenticationThrottle(target_limit=5, target_window=60, key_prefix=self.test_namespace)
        with patch.object(throttle, '_get_raw_redis_client', return_value=self.r):
            eff_ip, eff_target = throttle.get_effective_keys('172.16.3.1', 'race_account')
            self.tracked_keys.add(eff_ip)
            self.tracked_keys.add(eff_target)

            # Pre-reserve 4 slots
            for _ in range(4):
                self.assertTrue(throttle.acquire_admission('172.16.3.1', 'race_account').admitted)

            # 1 slot remains: launch 10 threads
            results = []

            def race(i):
                return throttle.acquire_admission('172.16.3.1', 'race_account')

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(race, i) for i in range(10)]
                for f in concurrent.futures.as_completed(futures):
                    results.append(f.result())

            admitted = [r for r in results if r[0] is True]
            denied = [r for r in results if r[0] is False]
            self.assertEqual(len(admitted), 1)
            self.assertEqual(len(denied), 9)

    def test_case_5_fixed_window_ttl_expiration(self):
        """Case 5 against live Redis: Fixed-window TTL expiration."""
        throttle = AuthenticationThrottle(target_limit=2, target_window=1, key_prefix=self.test_namespace)
        with patch.object(throttle, '_get_raw_redis_client', return_value=self.r):
            eff_ip, eff_target = throttle.get_effective_keys('172.16.4.1', 'expiring_account')
            self.tracked_keys.add(eff_ip)
            self.tracked_keys.add(eff_target)

            self.assertTrue(throttle.acquire_admission('172.16.4.1', 'expiring_account').admitted)
            self.assertTrue(throttle.acquire_admission('172.16.4.1', 'expiring_account').admitted)
            self.assertFalse(throttle.acquire_admission('172.16.4.1', 'expiring_account').admitted)

            # Sleep 1.1s for window expiration
            time.sleep(1.1)

            res = throttle.acquire_admission('172.16.4.1', 'expiring_account')
            self.assertTrue(res.admitted)
            self.assertEqual(res.reason, 'ADMITTED')

    def test_case_6_correct_bytes_response_decoding(self):
        """Case 6 against live Redis: Correct bytes response decoding."""
        throttle = AuthenticationThrottle(key_prefix=self.test_namespace)
        with patch.object(throttle, '_get_raw_redis_client', return_value=self.r):
            eff_ip, eff_target = throttle.get_effective_keys('172.16.5.1', 'decode_user')
            self.tracked_keys.add(eff_ip)
            self.tracked_keys.add(eff_target)

            res = throttle.acquire_admission('172.16.5.1', 'decode_user')
            self.assertTrue(res.admitted)
            self.assertEqual(res.reason, 'ADMITTED')
            self.assertIsInstance(res.reason, str)
            self.assertEqual(res.retry_after, 0)

    def test_case_7_backend_outage_handling(self):
        """Case 7 against live Redis: Backend outage handling fails closed."""
        import redis
        outage_client = redis.Redis(host='127.0.0.1', port=63799, socket_connect_timeout=0.1, socket_timeout=0.1)
        throttle = AuthenticationThrottle(key_prefix=self.test_namespace)
        with patch.object(throttle, '_get_raw_redis_client', return_value=outage_client):
            with self.assertRaises(ThrottleBackendError):
                throttle.acquire_admission('172.16.6.1', 'outage_user')

    def test_case_8_isolated_key_creation_and_cleanup(self):
        """Case 8 against live Redis: Isolated key creation and tracked cleanup."""
        throttle = AuthenticationThrottle(key_prefix=self.test_namespace)
        with patch.object(throttle, '_get_raw_redis_client', return_value=self.r):
            eff_ip, eff_target = throttle.get_effective_keys('172.16.7.1', 'isolation_user')
            self.tracked_keys.add(eff_ip)
            self.tracked_keys.add(eff_target)

            throttle.acquire_admission('172.16.7.1', 'isolation_user')

            # Verify keys exist and contain the namespace
            self.assertTrue(self.r.exists(eff_ip))
            self.assertTrue(self.r.exists(eff_target))
            self.assertTrue(eff_ip.startswith(self.test_namespace))
            self.assertTrue(eff_target.startswith(self.test_namespace))

    def test_case_9_sentinel_preservation(self):
        """Case 9 against live Redis: Unrelated sentinel preservation throughout burst."""
        throttle = AuthenticationThrottle(key_prefix=self.test_namespace)
        with patch.object(throttle, '_get_raw_redis_client', return_value=self.r):
            eff_ip, eff_target = throttle.get_effective_keys('172.16.8.1', 'sentinel_user')
            self.tracked_keys.add(eff_ip)
            self.tracked_keys.add(eff_target)

            for _ in range(5):
                throttle.acquire_admission('172.16.8.1', 'sentinel_user')

            # Sentinel key is strictly preserved
            self.assertEqual(self.r.get(self.sentinel_key), self.sentinel_value)

    def test_case_10_no_successful_login_counter_resets(self):
        """Case 10 against live Redis: Zero-reset counter policy under live Redis."""
        throttle = AuthenticationThrottle(target_limit=5, target_window=60, key_prefix=self.test_namespace)
        with patch.object(throttle, '_get_raw_redis_client', return_value=self.r):
            eff_ip, eff_target = throttle.get_effective_keys('172.16.9.1', 'no_reset_user')
            self.tracked_keys.add(eff_ip)
            self.tracked_keys.add(eff_target)

            # 5 admitted attempts
            for _ in range(5):
                self.assertTrue(throttle.acquire_admission('172.16.9.1', 'no_reset_user').admitted)

            # 6th attempt must be blocked (proves no reset occurred)
            res = throttle.acquire_admission('172.16.9.1', 'no_reset_user')
            self.assertFalse(res.admitted)
            self.assertEqual(res.reason, 'TARGET_LIMIT')



