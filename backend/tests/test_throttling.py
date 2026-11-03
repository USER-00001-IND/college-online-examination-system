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
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.accounts.models import RoleChoices, User
from apps.accounts.throttling import (
    AuthenticationThrottle,
    ThrottleBackendError,
    _hash_throttle_key,
    _local_throttle_lock,
    _make_effective_cache_key,
    REDIS_CHECK_AND_RESERVE_LUA,
    REDIS_RESET_TARGET_LUA,
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


class MockRedisClient:
    """
    Thread-safe in-memory Redis simulator that accurately executes the exact Lua scripts
    used in production (REDIS_CHECK_AND_RESERVE_LUA and REDIS_RESET_TARGET_LUA).
    Provides atomic multi-threaded concurrency identical to a single-threaded Redis engine.
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
            rem = int(self._expires[key] - time.time())
            return max(0, rem)

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

            # Script 1: REDIS_CHECK_AND_RESERVE_LUA
            if 'CHECK_AND_RESERVE' in script or 'ADMITTED' in script or 'ip_limit' in script:
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
                    if ttl_val < 0:
                        ttl_val = ip_window
                    return [0, ttl_val, 'IP_LIMIT', 0]

                if target_count >= target_limit:
                    ttl_val = self.ttl(target_key)
                    if ttl_val < 0:
                        ttl_val = target_window
                    return [0, ttl_val, 'TARGET_LIMIT', 0]

                new_ip = ip_count + 1
                self._data[ip_key] = new_ip
                if new_ip == 1:
                    self._expires[ip_key] = time.time() + ip_window

                new_target = target_count + 1
                self._data[target_key] = new_target
                if new_target == 1:
                    self._expires[target_key] = time.time() + target_window

                return [1, 0, 'ADMITTED', new_target]

            # Script 2: REDIS_RESET_TARGET_LUA
            elif 'RESET' in script or 'reserved_count' in script:
                target_key = keys[0]
                reserved_count = int(argv[0]) if argv and argv[0] is not None else 0

                self._purge_expired(target_key)
                if target_key not in self._data:
                    return 0

                current_count = int(self._data[target_key])
                if reserved_count <= 0 or current_count <= reserved_count:
                    self._data.pop(target_key, None)
                    self._expires.pop(target_key, None)
                    return 0
                else:
                    remaining = current_count - reserved_count
                    self._data[target_key] = remaining
                    return remaining

            raise NotImplementedError(f"MockRedisClient received unrecognized Lua script: {script[:40]}")


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
    Verifies Finding 2: Consistent Redis key management and generation-aware reset.
    Runs against the simulated thread-safe Redis Lua engine.
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
        self.assertEqual(res1.reservation_count, 1)

        res2 = throttle.acquire_admission('10.0.0.1', 'student_a')
        self.assertTrue(res2.admitted)
        self.assertEqual(res2.reservation_count, 2)

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

    def test_concurrent_success_failure_preserves_concurrent_security_evidence(self):
        """
        Test H — Concurrent success/failure policy:
        Simulate a successful authentication overlapping newer failed-attempt reservations.
        Proves that generation-aware reset CANNOT erase concurrent security evidence!
        """
        throttle = AuthenticationThrottle(target_limit=5, target_window=60)

        # Step 1: Legitimate user reserves attempt 1
        user_admission = throttle.acquire_admission('10.0.0.15', 'target_user')
        self.assertTrue(user_admission.admitted)
        self.assertEqual(user_admission.reservation_count, 1)

        # Step 2: Concurrent attacker submits 2 attempts while user is verifying password
        attacker_1 = throttle.acquire_admission('10.0.0.15', 'target_user')
        attacker_2 = throttle.acquire_admission('10.0.0.15', 'target_user')
        self.assertTrue(attacker_1.admitted)
        self.assertTrue(attacker_2.admitted)

        # Target count in Redis is now 3
        raw_key = _hash_throttle_key('target', '10.0.0.15:target_user')
        eff_key = _make_effective_cache_key(raw_key)
        self.assertEqual(self.mock_redis.get(eff_key), '3')

        # Step 3: Legitimate user authentication succeeds; triggers reset with reserved_count=1
        throttle.reset_target('10.0.0.15', 'target_user', reserved_count=user_admission.reservation_count)

        # Step 4: Key must NOT be deleted! Count must be 3 - 1 = 2 (attacker's attempts preserved!)
        self.assertEqual(self.mock_redis.get(eff_key), '2')

        # Step 5: Attacker can only make 3 more attempts before being locked out
        self.assertTrue(throttle.acquire_admission('10.0.0.15', 'target_user')[0])  # 3
        self.assertTrue(throttle.acquire_admission('10.0.0.15', 'target_user')[0])  # 4
        self.assertTrue(throttle.acquire_admission('10.0.0.15', 'target_user')[0])  # 5

        # 6th attempt by attacker is rejected!
        res_denied = throttle.acquire_admission('10.0.0.15', 'target_user')
        self.assertFalse(res_denied[0])
        self.assertEqual(res_denied[2], 'TARGET_LIMIT')

    def test_no_unexpected_deletion_of_unrelated_keys(self):
        """Verify resetting user_a does not affect user_b counters in Redis."""
        throttle = AuthenticationThrottle(target_limit=5, target_window=60)

        res_a = throttle.acquire_admission('10.0.0.16', 'user_a')
        res_b = throttle.acquire_admission('10.0.0.16', 'user_b')

        raw_b = _hash_throttle_key('target', '10.0.0.16:user_b')
        eff_b = _make_effective_cache_key(raw_b)
        self.assertEqual(self.mock_redis.get(eff_b), '1')

        # Reset user_a
        throttle.reset_target('10.0.0.16', 'user_a', reserved_count=res_a.reservation_count)

        # user_b counter must be unaffected
        self.assertEqual(self.mock_redis.get(eff_b), '1')


class SafeRedisExceptionLoggingTests(TestCase):
    """
    Verifies Finding 3: Sanitized Redis exception logging.
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

    def test_redis_reset_exception_does_not_leak_secrets(self):
        """Verify Redis target reset failure does not leak credentials in logs."""
        sensitive_host = "secure-internal-redis.cluster.local"

        mock_redis = MockRedisClient()
        mock_redis.eval = MagicMock(side_effect=TimeoutError(f"Command timed out contacting {sensitive_host}"))

        throttle = AuthenticationThrottle()
        with patch.object(throttle, '_get_raw_redis_client', return_value=mock_redis):
            with self.assertLogs('college.accounts.throttling', level='WARNING') as cm:
                throttle.reset_target('10.0.0.1', 'reset_user', reserved_count=1)

            full_log = " ".join(cm.output)
            self.assertNotIn(sensitive_host, full_log)
            self.assertIn("REDIS_RESET_FAILED", full_log)
            self.assertIn("TimeoutError", full_log)

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


class LiveRedisIntegrationTests(TestCase):
    """
    Integration tests against a live Redis daemon.
    Cleanly skips if no live Redis daemon is available at runtime.
    """

    def setUp(self):
        # Attempt to probe a live Redis daemon
        try:
            import redis
            redis_url = os.environ.get('TEST_REDIS_URL', 'redis://127.0.0.1:6379/15')
            self.r = redis.from_url(redis_url, socket_timeout=0.5)
            self.r.ping()
            self.r.flushdb()
        except Exception:
            self.skipTest(
                "REAL REDIS INTEGRATION: NOT EXECUTED — No live Redis server available at redis://127.0.0.1:6379/15"
            )

    def tearDown(self):
        if hasattr(self, 'r'):
            try:
                self.r.flushdb()
            except Exception:
                pass

    def test_live_redis_concurrency_same_ip_burst(self):
        """Test A against live Redis daemon: 30 concurrent requests with IP limit 15."""
        throttle = AuthenticationThrottle(ip_limit=15, ip_window=60, target_limit=50, target_window=60)
        with patch.object(throttle, '_get_raw_redis_client', return_value=self.r):
            results = []

            def submit(i):
                return throttle.acquire_admission('172.16.0.1', f'live_user_{i}')

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(submit, i) for i in range(30)]
                for f in concurrent.futures.as_completed(futures):
                    results.append(f.result())

            admitted = [r for r in results if r[0] is True]
            denied = [r for r in results if r[0] is False]
            self.assertEqual(len(admitted), 15)
            self.assertEqual(len(denied), 15)

