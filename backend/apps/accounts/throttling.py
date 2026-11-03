"""
Authentication Throttling & Brute-Force Defense for College Online Examination System.
Enforces dual-dimension rate limits across client IP addresses and target identifiers.
Uses atomic check-and-reserve admission before password verification to eliminate TOCTOU races.
Supports Redis-backed atomic Lua scripts in production and lock-synchronized transactions in test/dev.
Never stores raw identifiers, passwords, or secrets in throttle keys.
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

# Process-level reentrant lock for thread-safe atomicity on local-memory / generic caches
_local_throttle_lock = threading.RLock()

# Redis Lua Script for Atomic Check-and-Reserve
# KEYS[1]: ip_key
# KEYS[2]: target_key
# ARGV[1]: ip_limit
# ARGV[2]: ip_window
# ARGV[3]: target_limit
# ARGV[4]: target_window
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
    """Raised when the rate-limiting cache infrastructure fails or is unavailable."""
    pass


def _hash_throttle_key(dimension: str, raw_value: str) -> str:
    """Computes a SHA-256 digest cache key for a throttling dimension."""
    digest = hashlib.sha256(raw_value.encode('utf-8')).hexdigest()
    return f"auth_throttle:{dimension}:{digest}"


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
        except Exception:
            return None
        return None

    def acquire_admission(
        self,
        ip_address: str,
        raw_identifier: str,
    ) -> Tuple[bool, int, str]:
        """
        Atomically checks limits and reserves an admission attempt BEFORE password verification.

        Returns:
            (admitted: bool, retry_after_seconds: int, reason: str)
            Where reason is 'ADMITTED', 'IP_LIMIT', or 'TARGET_LIMIT'.

        Raises:
            ThrottleBackendError if the rate-limiting infrastructure fails.
        """
        normalized_id = self._normalize(raw_identifier)
        ip_key = _hash_throttle_key('ip', ip_address)
        compound_val = f"{ip_address}:{normalized_id}"
        target_key = _hash_throttle_key('target', compound_val)

        # 1. Try atomic Redis Lua execution if connected to Redis
        redis_client = self._get_raw_redis_client()
        if redis_client is not None:
            try:
                result = redis_client.eval(
                    REDIS_CHECK_AND_RESERVE_LUA,
                    2,
                    ip_key,
                    target_key,
                    self.ip_limit,
                    self.ip_window,
                    self.target_limit,
                    self.target_window,
                )
                admitted = bool(result[0])
                ttl = int(result[1])
                reason = str(result[2])
                return admitted, ttl, reason
            except Exception as exc:
                logger.critical("CRITICAL: Redis throttle Lua evaluation failed: %s", exc)
                raise ThrottleBackendError(f"Redis throttling failure: {exc}") from exc

        # 2. Concurrency-safe atomic check-and-reserve for generic / test caches
        with _local_throttle_lock:
            try:
                now = time.time()

                # Evaluate IP limit
                ip_count = cache.get(ip_key) or 0
                if ip_count >= self.ip_limit:
                    start_time = cache.get(f"{ip_key}:start")
                    elapsed = (now - start_time) if start_time else 0
                    retry_after = max(1, int(self.ip_window - elapsed))
                    return False, retry_after, 'IP_LIMIT'

                # Evaluate Target compound limit
                target_count = cache.get(target_key) or 0
                if target_count >= self.target_limit:
                    start_time = cache.get(f"{target_key}:start")
                    elapsed = (now - start_time) if start_time else 0
                    retry_after = max(1, int(self.target_window - elapsed))
                    return False, retry_after, 'TARGET_LIMIT'

                # Both counters are below threshold: atomically reserve one attempt!
                if ip_count == 0:
                    cache.set(ip_key, 1, timeout=self.ip_window)
                    cache.set(f"{ip_key}:start", now, timeout=self.ip_window)
                else:
                    try:
                        cache.incr(ip_key)
                    except Exception:
                        cache.set(ip_key, ip_count + 1, timeout=self.ip_window)

                if target_count == 0:
                    cache.set(target_key, 1, timeout=self.target_window)
                    cache.set(f"{target_key}:start", now, timeout=self.target_window)
                else:
                    try:
                        cache.incr(target_key)
                    except Exception:
                        cache.set(target_key, target_count + 1, timeout=self.target_window)

                return True, 0, 'ADMITTED'
            except Exception as exc:
                logger.critical("CRITICAL: Local throttle cache evaluation failed: %s", exc)
                raise ThrottleBackendError(f"Throttling infrastructure failure: {exc}") from exc

    def reset_target(self, ip_address: str, raw_identifier: str) -> None:
        """
        Clears the compound (IP + Target) counter upon successful authentication.
        Leaves IP-level counter intact to prevent distributed credential stuffing.
        """
        try:
            normalized_id = self._normalize(raw_identifier)
            compound_val = f"{ip_address}:{normalized_id}"
            target_key = _hash_throttle_key('target', compound_val)
            cache.delete(target_key)
            cache.delete(f"{target_key}:start")
        except Exception as exc:
            logger.warning("Failed to reset target throttle key: %s", exc)
