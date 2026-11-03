"""
Authentication Throttling & Brute-Force Defense for College Online Examination System.

Architecture & Policy:
- Authentication Admission Limiter enforcing dual-dimension fixed-window limits across
  client IP addresses and compound client IP + target identifiers.
- Check-and-reserve admission semantics executed atomically BEFORE password verification.
- Every admitted login attempt (successful or unsuccessful) consumes one admission slot.
- Successful authentications DO NOT delete, decrement, or reset counters; counters expire
  naturally according to their fixed-window TTLs, ensuring concurrent failed-attempt evidence
  is never erased by overlapping successful logins.
- Supports Redis-backed atomic Lua scripts in production and lock-synchronized transactions in test/dev.
- Never stores raw identifiers, passwords, or secrets in throttle keys (SHA-256 digests used).
"""

import hashlib
import logging
import threading
import time
from typing import Optional, Tuple

from django.conf import settings
from django.core.cache import cache

from apps.accounts.audit import sanitize_identifier

logger = logging.getLogger('college.accounts.throttling')

# Process-level reentrant lock for thread-safe atomicity on local-memory / generic caches (dev/test only)
_local_throttle_lock = threading.RLock()


class AdmissionResult(tuple):
    """
    Result of an authentication admission acquisition.
    Maintains backward compatibility with 3-element tuple unpacking: (admitted, retry_after, reason).
    """
    def __new__(cls, admitted: bool, retry_after: int, reason: str):
        obj = super().__new__(cls, (admitted, retry_after, reason))
        obj.admitted = admitted
        obj.retry_after = retry_after
        obj.reason = reason
        return obj

    def __repr__(self):
        return f"AdmissionResult(admitted={self.admitted}, retry_after={self.retry_after}, reason='{self.reason}')"


# Redis Lua Script for Atomic Check-and-Reserve
# KEYS[1]: ip_key (effective key including cache prefix/version)
# KEYS[2]: target_key (effective key including cache prefix/version)
# ARGV[1]: ip_limit
# ARGV[2]: ip_window
# ARGV[3]: target_limit
# ARGV[4]: target_window
# Returns: {admitted (0/1), ttl, reason}
REDIS_CHECK_AND_RESERVE_LUA = """
local ip_key = KEYS[1]
local target_key = KEYS[2]
local ip_limit = tonumber(ARGV[1])
local ip_window = tonumber(ARGV[2])
local target_limit = tonumber(ARGV[3])
local target_window = tonumber(ARGV[4])

local ip_val = redis.call('GET', ip_key)
local ip_count = tonumber(ip_val or '0')

local target_val = redis.call('GET', target_key)
local target_count = tonumber(target_val or '0')

if ip_count >= ip_limit then
    local ttl = redis.call('TTL', ip_key)
    if ttl < 0 then ttl = ip_window end
    return {0, ttl, 'IP_LIMIT'}
end

if target_count >= target_limit then
    local ttl = redis.call('TTL', target_key)
    if ttl < 0 then ttl = target_window end
    return {0, ttl, 'TARGET_LIMIT'}
end

local new_ip = redis.call('INCR', ip_key)
if new_ip == 1 then
    redis.call('EXPIRE', ip_key, ip_window)
end

local new_target = redis.call('INCR', target_key)
if new_target == 1 then
    redis.call('EXPIRE', target_key, target_window)
end

return {1, 0, 'ADMITTED'}
"""


class ThrottleBackendError(Exception):
    """Raised when the rate-limiting cache infrastructure fails, returns invalid data, or is unavailable."""
    pass


def _hash_throttle_key(dimension: str, raw_value: str) -> str:
    """Computes a SHA-256 digest logical cache key for a throttling dimension."""
    digest = hashlib.sha256(raw_value.encode('utf-8')).hexdigest()
    return f"auth_throttle:{dimension}:{digest}"


def _make_effective_cache_key(raw_key: str) -> str:
    """
    Transforms a logical throttle key into the effective Redis/cache key
    by applying Django's configured cache key prefix and version.
    Guarantees 100% namespace parity between raw Redis operations and Django cache API.
    """
    if hasattr(cache, 'make_key'):
        return cache.make_key(raw_key)
    return raw_key


class AuthenticationThrottle:
    """
    Dual-dimension rate limiter for authentication endpoints.
    Atomically checks and reserves an attempt before password verification.
    """

    def __init__(
        self,
        ip_limit: Optional[int] = None,
        ip_window: Optional[int] = None,
        target_limit: Optional[int] = None,
        target_window: Optional[int] = None,
    ):
        self.ip_limit = ip_limit or getattr(settings, 'AUTH_THROTTLE_IP_LIMIT', 15)
        self.ip_window = ip_window or getattr(settings, 'AUTH_THROTTLE_IP_WINDOW', 300)
        self.target_limit = target_limit or getattr(settings, 'AUTH_THROTTLE_TARGET_LIMIT', 5)
        self.target_window = target_window or getattr(settings, 'AUTH_THROTTLE_TARGET_WINDOW', 300)

    def _normalize(self, raw_identifier: Optional[str]) -> str:
        """Normalizes identifier by stripping control characters, whitespace, and lowercasing."""
        sanitized = sanitize_identifier(raw_identifier)
        return sanitized.lower()

    def _is_production_environment(self) -> bool:
        """
        Determines whether the application is running in a production environment.
        Checks explicit ENVIRONMENT_NAME setting first, followed by strict defense checks.
        Never relies on DEBUG alone.
        """
        env_name = str(getattr(settings, 'ENVIRONMENT_NAME', '')).lower()
        if env_name == 'production':
            return True
        if env_name in ('development', 'dev', 'test', 'testing'):
            return False
        # Defense-in-depth: if ENVIRONMENT_NAME is unconfigured or unknown, check non-debug status
        return not bool(getattr(settings, 'DEBUG', True))

    def _get_raw_redis_client(self):
        """Attempts to obtain the raw redis client from Django's cache backend."""
        try:
            # Django 5.0 RedisCache
            internal_cache = getattr(cache, '_cache', None)
            if internal_cache and hasattr(internal_cache, 'get_client'):
                return internal_cache.get_client()
            # django-redis or connection proxy
            client = getattr(cache, 'client', None)
            if client and hasattr(client, 'get_client'):
                return client.get_client()
        except Exception as exc:
            logger.critical(
                "Authentication throttle backend failure [category=%s, type=%s]",
                "REDIS_CLIENT_ACQUISITION_FAILED",
                exc.__class__.__name__,
                exc_info=False,
            )
            return None
        return None

    def acquire_admission(
        self,
        ip_address: str,
        raw_identifier: str,
    ) -> AdmissionResult:
        """
        Atomically checks limits and reserves an admission attempt BEFORE password verification.

        Returns:
            AdmissionResult(admitted: bool, retry_after: int, reason: str)
            Where reason is 'ADMITTED', 'IP_LIMIT', or 'TARGET_LIMIT'.

        Raises:
            ThrottleBackendError if the rate-limiting infrastructure fails or returns invalid responses.
        """
        normalized_id = self._normalize(raw_identifier)
        raw_ip_key = _hash_throttle_key('ip', ip_address)
        compound_val = f"{ip_address}:{normalized_id}"
        raw_target_key = _hash_throttle_key('target', compound_val)

        is_prod = self._is_production_environment()
        redis_client = self._get_raw_redis_client()

        # In production, an operational Redis backend is MANDATORY. Never fall back to local lock!
        if is_prod and redis_client is None:
            logger.critical(
                "Authentication throttle backend failure [category=%s, type=%s]",
                "REDIS_CLIENT_UNAVAILABLE",
                "NoneType",
                exc_info=False,
            )
            raise ThrottleBackendError("Production authentication throttle requires an operational Redis client.")

        # 1. Execute atomic Redis Lua script if Redis client is available
        if redis_client is not None:
            effective_ip_key = _make_effective_cache_key(raw_ip_key)
            effective_target_key = _make_effective_cache_key(raw_target_key)
            try:
                result = redis_client.eval(
                    REDIS_CHECK_AND_RESERVE_LUA,
                    2,
                    effective_ip_key,
                    effective_target_key,
                    self.ip_limit,
                    self.ip_window,
                    self.target_limit,
                    self.target_window,
                )
            except Exception as exc:
                logger.critical(
                    "Authentication throttle backend failure [category=%s, type=%s]",
                    "REDIS_EVALUATION_FAILED",
                    exc.__class__.__name__,
                    exc_info=False,
                )
                raise ThrottleBackendError("Authentication rate-limiting infrastructure failure.") from None

            # Validate response structure
            if not isinstance(result, (list, tuple)) or len(result) < 3:
                logger.critical(
                    "Authentication throttle backend failure [category=%s, type=%s]",
                    "INVALID_THROTTLE_RESPONSE_STRUCTURE",
                    type(result).__name__,
                    exc_info=False,
                )
                raise ThrottleBackendError("Invalid throttle backend response structure.")

            # Validate admission flag
            raw_admitted = result[0]
            if raw_admitted not in (0, 1, True, False):
                logger.critical(
                    "Authentication throttle backend failure [category=%s, type=%s]",
                    "INVALID_ADMISSION_FLAG",
                    type(raw_admitted).__name__,
                    exc_info=False,
                )
                raise ThrottleBackendError("Invalid throttle admission flag.")
            admitted = bool(raw_admitted)

            # Validate and parse TTL
            try:
                ttl = int(result[1])
                if ttl < 0:
                    ttl = self.ip_window
            except (ValueError, TypeError) as exc:
                logger.critical(
                    "Authentication throttle backend failure [category=%s, type=%s]",
                    "INVALID_TTL_VALUE",
                    exc.__class__.__name__,
                    exc_info=False,
                )
                raise ThrottleBackendError("Invalid throttle TTL value.") from None

            # Decode and validate reason code (supports bytes and str)
            raw_reason = result[2]
            if isinstance(raw_reason, (bytes, bytearray)):
                try:
                    reason = raw_reason.decode('utf-8')
                except UnicodeDecodeError as exc:
                    logger.critical(
                        "Authentication throttle backend failure [category=%s, type=%s]",
                        "REASON_DECODE_FAILED",
                        exc.__class__.__name__,
                        exc_info=False,
                    )
                    raise ThrottleBackendError("Unable to decode throttle backend reason.") from None
            elif isinstance(raw_reason, str):
                reason = raw_reason
            else:
                logger.critical(
                    "Authentication throttle backend failure [category=%s, type=%s]",
                    "INVALID_REASON_TYPE",
                    type(raw_reason).__name__,
                    exc_info=False,
                )
                raise ThrottleBackendError("Invalid throttle reason type.")

            VALID_REASONS = {'ADMITTED', 'IP_LIMIT', 'TARGET_LIMIT'}
            if reason not in VALID_REASONS:
                logger.critical(
                    "Authentication throttle backend failure [category=%s, type=%s]",
                    "UNKNOWN_REASON_CODE",
                    "ValueError",
                    exc_info=False,
                )
                raise ThrottleBackendError("Unknown throttle reason code.")

            return AdmissionResult(admitted, ttl, reason)

        # 2. Concurrency-safe atomic check-and-reserve for generic / test caches (DEV/TEST ONLY)
        with _local_throttle_lock:
            try:
                now = time.time()

                # Evaluate IP limit
                ip_count = cache.get(raw_ip_key) or 0
                if ip_count >= self.ip_limit:
                    start_time = cache.get(f"{raw_ip_key}:start")
                    elapsed = (now - start_time) if start_time else 0
                    retry_after = max(1, int(self.ip_window - elapsed))
                    return AdmissionResult(False, retry_after, 'IP_LIMIT')

                # Evaluate Target compound limit
                target_count = cache.get(raw_target_key) or 0
                if target_count >= self.target_limit:
                    start_time = cache.get(f"{raw_target_key}:start")
                    elapsed = (now - start_time) if start_time else 0
                    retry_after = max(1, int(self.target_window - elapsed))
                    return AdmissionResult(False, retry_after, 'TARGET_LIMIT')

                # Both counters are below threshold: atomically reserve one attempt!
                if ip_count == 0:
                    cache.set(raw_ip_key, 1, timeout=self.ip_window)
                    cache.set(f"{raw_ip_key}:start", now, timeout=self.ip_window)
                else:
                    try:
                        cache.incr(raw_ip_key)
                    except Exception:
                        cache.set(raw_ip_key, ip_count + 1, timeout=self.ip_window)

                if target_count == 0:
                    cache.set(raw_target_key, 1, timeout=self.target_window)
                    cache.set(f"{raw_target_key}:start", now, timeout=self.target_window)
                else:
                    try:
                        cache.incr(raw_target_key)
                    except Exception:
                        cache.set(raw_target_key, target_count + 1, timeout=self.target_window)

                return AdmissionResult(True, 0, 'ADMITTED')
            except Exception as exc:
                logger.critical(
                    "Authentication throttle backend failure [category=%s, type=%s]",
                    "LOCAL_CACHE_EVALUATION_FAILED",
                    exc.__class__.__name__,
                    exc_info=False,
                )
                raise ThrottleBackendError("Authentication rate-limiting infrastructure failure.") from None
