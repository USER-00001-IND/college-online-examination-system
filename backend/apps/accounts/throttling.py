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
- Strict coherent Redis Lua response contract validation (Finding C):
  Admitted [1, 0, 'ADMITTED'], Denied IP [0, TTL, 'IP_LIMIT'], Denied Target [0, TTL, 'TARGET_LIMIT'].
  Any contradictory, malformed, or out-of-bounds response fails closed with ThrottleBackendError.
- Isolated test namespace support (Finding A): injected key builder / prefix for per-run isolation
  in live Redis integration tests without global production settings exposure.
- Strict Redis test endpoint safety checks (Finding B): canonicalization, collision detection,
  and mandatory disposable-instance acknowledgment.
- Supports Redis-backed atomic Lua scripts in production and lock-synchronized transactions in test/dev.
- Never stores raw identifiers, passwords, or secrets in throttle keys (SHA-256 digests used).
"""

import hashlib
import logging
import os
import threading
import time
import urllib.parse
from typing import Callable, List, Optional, Set, Tuple

from django.conf import settings
from django.core.cache import cache

from apps.accounts.audit import sanitize_identifier

logger = logging.getLogger('college.accounts.throttling')

# Process-level reentrant lock for thread-safe atomicity on local-memory / generic caches (dev/test only)
_local_throttle_lock = threading.RLock()

# Coherent response contract valid reason codes
VALID_CONTRACT_REASONS = frozenset({'ADMITTED', 'IP_LIMIT', 'TARGET_LIMIT'})

# Maximum allowable bound for Redis TTL response (sanity upper bound)
AUTH_THROTTLE_MAX_TTL_BOUND = 3600


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
    if ttl <= 0 then ttl = ip_window end
    return {0, ttl, 'IP_LIMIT'}
end

if target_count >= target_limit then
    local ttl = redis.call('TTL', target_key)
    if ttl <= 0 then ttl = target_window end
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


def sanitize_redis_url(url: str) -> str:
    """
    Removes sensitive credentials (passwords/usernames) from Redis connection URLs
    for safe inclusion in logs, test output, and exception messages.
    """
    if not url or not isinstance(url, str):
        return "[EMPTY_OR_INVALID_URL]"
    try:
        parsed = urllib.parse.urlparse(url.strip())
        if parsed.username or parsed.password:
            host = parsed.hostname or ''
            port_str = f":{parsed.port}" if parsed.port else ""
            masked_netloc = f"***:***@{host}{port_str}"
            return urllib.parse.urlunparse(parsed._replace(netloc=masked_netloc))
        return url.strip()
    except Exception:
        return "[UNPARSEABLE_URL]"


def canonicalize_redis_endpoint(raw_url: str) -> Tuple[str, str, int, int]:
    """
    Canonicalizes a Redis connection URL into a normalized (scheme, canonical_host, port, db) tuple.
    Normalizes loopback representations ('localhost', '127.0.0.1', '::1' -> '127.0.0.1'),
    applies default port (6379), default DB (0), and parses Unix domain sockets.

    Raises:
        ValueError if the URL scheme is unsupported, host/path is invalid, or port/db cannot be parsed.
    """
    if not raw_url or not isinstance(raw_url, str) or not raw_url.strip():
        raise ValueError("Redis connection URL cannot be empty.")

    try:
        parsed = urllib.parse.urlparse(raw_url.strip())
    except Exception as exc:
        raise ValueError(f"Malformed URL structure: {exc}") from None

    scheme = (parsed.scheme or '').lower()
    if scheme not in ('redis', 'rediss', 'unix'):
        raise ValueError(f"Unsupported Redis URL scheme '{scheme}'. Must be 'redis', 'rediss', or 'unix'.")

    if scheme == 'unix':
        path = parsed.path
        if not path:
            raise ValueError("Unix socket URL must specify a socket path.")
        query = urllib.parse.parse_qs(parsed.query)
        try:
            db = int(query.get('db', ['0'])[0])
            if db < 0:
                raise ValueError("Redis DB index cannot be negative.")
        except (ValueError, TypeError):
            raise ValueError("Invalid Redis DB index in Unix socket query string.") from None
        return ('unix', path, 0, db)

    host = parsed.hostname
    if not host:
        raise ValueError("Network Redis URL must specify a valid hostname or IP address.")

    host = host.lower()
    if host in ('localhost', '127.0.0.1', '::1'):
        canonical_host = '127.0.0.1'
    else:
        canonical_host = host

    port = parsed.port or 6379

    raw_path = (parsed.path or '').strip('/')
    if not raw_path:
        db = 0
    else:
        try:
            db = int(raw_path)
            if db < 0:
                raise ValueError("Redis DB index cannot be negative.")
        except ValueError:
            raise ValueError(f"Invalid Redis DB index '{raw_path}' in URL path.") from None

    return (scheme, canonical_host, port, db)


def get_configured_application_redis_endpoints() -> List[Tuple[str, str, int, int]]:
    """
    Collects canonicalized endpoints for all configured application Redis instances
    from environment variables (REDIS_URL, CACHE_URL) and Django settings (REDIS_URL, CACHES).
    """
    urls: List[str] = []
    for env_var in ('REDIS_URL', 'CACHE_URL'):
        val = os.environ.get(env_var, '').strip()
        if val:
            urls.append(val)

    for attr in ('REDIS_URL', 'CACHE_URL'):
        val = getattr(settings, attr, None)
        if val and isinstance(val, str) and val.strip():
            urls.append(val.strip())

    caches = getattr(settings, 'CACHES', {})
    if isinstance(caches, dict):
        for cache_cfg in caches.values():
            if isinstance(cache_cfg, dict):
                loc = cache_cfg.get('LOCATION')
                if loc and isinstance(loc, str) and loc.strip():
                    urls.append(loc.strip())
                elif isinstance(loc, (list, tuple)):
                    for item in loc:
                        if isinstance(item, str) and item.strip():
                            urls.append(item.strip())

    endpoints = []
    for u in urls:
        try:
            ep = canonicalize_redis_endpoint(u)
            if ep not in endpoints:
                endpoints.append(ep)
        except ValueError:
            continue
    return endpoints


def validate_test_redis_safety(
    test_url: str,
    app_endpoints: Optional[List[Tuple[str, str, int, int]]] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Validates whether a proposed TEST_REDIS_URL is safe and isolated:
    1. Rejects malformed or unsupported URLs.
    2. Canonicalizes the test endpoint.
    3. Compares against all application Redis endpoints to prevent shared/colliding databases.

    Returns:
        (is_safe, error_or_skip_reason)
    """
    if not test_url or not isinstance(test_url, str) or not test_url.strip():
        return False, "TEST_REDIS_URL is empty or missing."

    try:
        test_ep = canonicalize_redis_endpoint(test_url)
    except ValueError as exc:
        return False, f"Invalid TEST_REDIS_URL ({sanitize_redis_url(test_url)}): {exc}"

    if app_endpoints is None:
        app_endpoints = get_configured_application_redis_endpoints()

    # Compare canonical endpoint identity (host, port, db) against application endpoints
    test_identity = (test_ep[1], test_ep[2], test_ep[3])
    for app_ep in app_endpoints:
        app_identity = (app_ep[1], app_ep[2], app_ep[3])
        if test_identity == app_identity:
            return False, (
                f"TEST_REDIS_URL ({sanitize_redis_url(test_url)}) conflicts with application Redis endpoint "
                f"(host={app_ep[1]}, port={app_ep[2]}, db={app_ep[3]}). "
                "Live integration tests require an isolated, dedicated disposable Redis database."
            )

    return True, None


def validate_and_decode_redis_response(result, max_ttl: int) -> Tuple[bool, int, str]:
    """
    Strictly validates the complete Redis Lua response according to the coherent contract (Finding C):
    - Accepted Form 1 (Admitted): [1, 0, 'ADMITTED']
    - Accepted Form 2 (IP Limited): [0, 1 <= ttl <= max_ttl, 'IP_LIMIT']
    - Accepted Form 3 (Target Limited): [0, 1 <= ttl <= max_ttl, 'TARGET_LIMIT']

    Any contradictory, malformed, out-of-bounds, or unknown response raises ThrottleBackendError.
    """
    # 1. Type and length verification
    if not isinstance(result, (list, tuple)):
        logger.critical(
            "Authentication throttle backend failure [category=%s, type=%s]",
            "INVALID_THROTTLE_RESPONSE_TYPE",
            type(result).__name__,
            exc_info=False,
        )
        raise ThrottleBackendError(f"Invalid throttle response type: {type(result).__name__}")

    if len(result) != 3:
        logger.critical(
            "Authentication throttle backend failure [category=%s, type=%s]",
            "INVALID_THROTTLE_RESPONSE_LENGTH",
            f"len={len(result)}",
            exc_info=False,
        )
        raise ThrottleBackendError(f"Invalid throttle response length: {len(result)}, expected 3.")

    # 2. Admission flag verification
    raw_admitted = result[0]
    if raw_admitted is True:
        admitted = True
    elif raw_admitted is False:
        admitted = False
    elif isinstance(raw_admitted, int) and raw_admitted == 1:
        admitted = True
    elif isinstance(raw_admitted, int) and raw_admitted == 0:
        admitted = False
    else:
        logger.critical(
            "Authentication throttle backend failure [category=%s, type=%s]",
            "INVALID_ADMISSION_FLAG",
            type(raw_admitted).__name__,
            exc_info=False,
        )
        raise ThrottleBackendError(f"Invalid throttle admission flag: {raw_admitted!r}")

    # 3. TTL parsing and validation
    raw_ttl = result[1]
    if isinstance(raw_ttl, bool):
        logger.critical(
            "Authentication throttle backend failure [category=%s, type=%s]",
            "INVALID_TTL_TYPE",
            "bool",
            exc_info=False,
        )
        raise ThrottleBackendError("Invalid throttle TTL type: boolean not permitted.")
    try:
        ttl = int(raw_ttl)
    except (ValueError, TypeError) as exc:
        logger.critical(
            "Authentication throttle backend failure [category=%s, type=%s]",
            "INVALID_TTL_VALUE",
            exc.__class__.__name__,
            exc_info=False,
        )
        raise ThrottleBackendError("Invalid throttle TTL value.") from None

    # 4. Reason decoding and validation (handles Redis bulk bytes and str)
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
        raise ThrottleBackendError(f"Invalid throttle reason type: {type(raw_reason).__name__}")

    if reason not in VALID_CONTRACT_REASONS:
        logger.critical(
            "Authentication throttle backend failure [category=%s, type=%s]",
            "UNKNOWN_REASON_CODE",
            "ValueError",
            exc_info=False,
        )
        raise ThrottleBackendError(f"Unknown throttle reason code: {reason!r}")

    # 5. Coherent Contract Enforcement:
    if admitted:
        if reason != 'ADMITTED':
            logger.critical(
                "Authentication throttle backend failure [category=%s, type=%s]",
                "CONTRADICTORY_RESPONSE_ADMITTED_WITH_DENIAL_REASON",
                reason,
                exc_info=False,
            )
            raise ThrottleBackendError(f"Contradictory throttle response: admitted carrying denial reason '{reason}'.")
        if ttl != 0:
            logger.critical(
                "Authentication throttle backend failure [category=%s, type=%s]",
                "CONTRADICTORY_RESPONSE_ADMITTED_WITH_NONZERO_TTL",
                f"ttl={ttl}",
                exc_info=False,
            )
            raise ThrottleBackendError(f"Contradictory throttle response: admitted carrying nonzero TTL {ttl}.")
    else:
        if reason == 'ADMITTED':
            logger.critical(
                "Authentication throttle backend failure [category=%s, type=%s]",
                "CONTRADICTORY_RESPONSE_DENIED_WITH_ADMITTED_REASON",
                "ADMITTED",
                exc_info=False,
            )
            raise ThrottleBackendError("Contradictory throttle response: denied request carrying 'ADMITTED' reason.")
        if ttl <= 0:
            logger.critical(
                "Authentication throttle backend failure [category=%s, type=%s]",
                "CONTRADICTORY_RESPONSE_DENIED_WITH_NON_POSITIVE_TTL",
                f"ttl={ttl}",
                exc_info=False,
            )
            raise ThrottleBackendError(f"Contradictory throttle response: denied request carrying non-positive TTL {ttl}.")
        if ttl > max_ttl:
            logger.critical(
                "Authentication throttle backend failure [category=%s, type=%s]",
                "TTL_EXCEEDS_MAX_BOUND",
                f"ttl={ttl},max={max_ttl}",
                exc_info=False,
            )
            raise ThrottleBackendError(f"Throttle response TTL {ttl} exceeds maximum allowable bound {max_ttl}.")

    return (admitted, ttl, reason)


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

    Supports test-only namespace injection (key_prefix or key_builder) for live Redis isolation.
    """

    def __init__(
        self,
        ip_limit: Optional[int] = None,
        ip_window: Optional[int] = None,
        target_limit: Optional[int] = None,
        target_window: Optional[int] = None,
        key_prefix: Optional[str] = None,
        key_builder: Optional[Callable[[str, str], str]] = None,
    ):
        self.ip_limit = ip_limit or getattr(settings, 'AUTH_THROTTLE_IP_LIMIT', 15)
        self.ip_window = ip_window or getattr(settings, 'AUTH_THROTTLE_IP_WINDOW', 300)
        self.target_limit = target_limit or getattr(settings, 'AUTH_THROTTLE_TARGET_LIMIT', 5)
        self.target_window = target_window or getattr(settings, 'AUTH_THROTTLE_TARGET_WINDOW', 300)
        self.max_ttl = max(self.ip_window, self.target_window)
        # Test-only injection parameters (Finding A)
        self.key_prefix = key_prefix
        self.key_builder = key_builder

    def _normalize(self, raw_identifier: Optional[str]) -> str:
        """Normalizes identifier by stripping control characters, whitespace, and lowercasing."""
        sanitized = sanitize_identifier(raw_identifier)
        return sanitized.lower()

    def _build_logical_key(self, dimension: str, raw_value: str) -> str:
        """Computes SHA-256 logical key for a throttling dimension."""
        digest = hashlib.sha256(raw_value.encode('utf-8')).hexdigest()
        return f"auth_throttle:{dimension}:{digest}"

    def build_effective_key(self, dimension: str, raw_value: str) -> str:
        """
        Builds the exact effective Redis key for a throttling dimension.
        If a test-injected key_builder is provided, delegates to it.
        If key_prefix is provided (test isolation), prepends it directly to the key.
        Otherwise applies standard cache key transformation.
        """
        if self.key_builder is not None:
            return self.key_builder(dimension, raw_value)
        logical = self._build_logical_key(dimension, raw_value)
        if self.key_prefix:
            return f"{self.key_prefix}{logical}"
        return _make_effective_cache_key(logical)

    def get_effective_keys(self, ip_address: str, raw_identifier: str) -> Tuple[str, str]:
        """
        Returns (effective_ip_key, effective_target_key) that will be accessed/written in Redis.
        Ensures 100% parity between key generation, tracking, and execution.
        """
        normalized_id = self._normalize(raw_identifier)
        compound_val = f"{ip_address}:{normalized_id}"
        return (
            self.build_effective_key('ip', ip_address),
            self.build_effective_key('target', compound_val),
        )

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
        effective_ip_key, effective_target_key = self.get_effective_keys(ip_address, raw_identifier)

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

            admitted, ttl, reason = validate_and_decode_redis_response(result, self.max_ttl)
            return AdmissionResult(admitted, ttl, reason)

        # 2. Concurrency-safe atomic check-and-reserve for generic / test caches (DEV/TEST ONLY)
        with _local_throttle_lock:
            try:
                now = time.time()

                # Evaluate IP limit
                ip_count = cache.get(effective_ip_key) or 0
                if ip_count >= self.ip_limit:
                    start_time = cache.get(f"{effective_ip_key}:start")
                    elapsed = (now - start_time) if start_time else 0
                    retry_after = max(1, min(int(self.ip_window - elapsed), self.max_ttl))
                    return AdmissionResult(False, retry_after, 'IP_LIMIT')

                # Evaluate Target compound limit
                target_count = cache.get(effective_target_key) or 0
                if target_count >= self.target_limit:
                    start_time = cache.get(f"{effective_target_key}:start")
                    elapsed = (now - start_time) if start_time else 0
                    retry_after = max(1, min(int(self.target_window - elapsed), self.max_ttl))
                    return AdmissionResult(False, retry_after, 'TARGET_LIMIT')

                # Both counters are below threshold: atomically reserve one attempt!
                if ip_count == 0:
                    cache.set(effective_ip_key, 1, timeout=self.ip_window)
                    cache.set(f"{effective_ip_key}:start", now, timeout=self.ip_window)
                else:
                    try:
                        cache.incr(effective_ip_key)
                    except Exception:
                        cache.set(effective_ip_key, ip_count + 1, timeout=self.ip_window)

                if target_count == 0:
                    cache.set(effective_target_key, 1, timeout=self.target_window)
                    cache.set(f"{effective_target_key}:start", now, timeout=self.target_window)
                else:
                    try:
                        cache.incr(effective_target_key)
                    except Exception:
                        cache.set(effective_target_key, target_count + 1, timeout=self.target_window)

                return AdmissionResult(True, 0, 'ADMITTED')
            except Exception as exc:
                logger.critical(
                    "Authentication throttle backend failure [category=%s, type=%s]",
                    "LOCAL_CACHE_EVALUATION_FAILED",
                    exc.__class__.__name__,
                    exc_info=False,
                )
                raise ThrottleBackendError("Authentication rate-limiting infrastructure failure.") from None
