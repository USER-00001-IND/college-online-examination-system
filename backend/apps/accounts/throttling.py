"""
Authentication Throttling & Brute-Force Defense for College Online Examination System.
Enforces dual-dimension rate limits across client IP addresses and target identifiers.
Uses atomic cache primitives to prevent race conditions in concurrent multi-worker environments.
Never stores raw identifiers, passwords, or secrets in throttle keys.
"""

import hashlib
import time
from typing import Optional, Tuple
from django.conf import settings
from django.core.cache import cache

from apps.accounts.audit import sanitize_identifier


def _hash_throttle_key(dimension: str, raw_value: str) -> str:
    """Computes a SHA-256 digest cache key for a throttling dimension."""
    digest = hashlib.sha256(raw_value.encode('utf-8')).hexdigest()
    return f"auth_throttle:{dimension}:{digest}"


class AuthenticationThrottle:
    """
    Dual-dimension rate limiter for authentication endpoints.
    Protects against automated credential-stuffing and distributed brute-force guessing.
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

    def is_throttled(self, ip_address: str, raw_identifier: str) -> Tuple[bool, int]:
        """
        Evaluates whether an incoming login request exceeds rate limits.
        Checks both the client IP limit and the compound (IP + Target Identifier) limit.

        Returns:
            (is_blocked: bool, retry_after_seconds: int)
        """
        now = time.time()
        normalized_id = self._normalize(raw_identifier)

        # 1. Check IP-level throttle
        ip_key = _hash_throttle_key('ip', ip_address)
        ip_count = cache.get(ip_key)
        if ip_count is not None and ip_count >= self.ip_limit:
            start_time = cache.get(f"{ip_key}:start")
            elapsed = (now - start_time) if start_time else 0
            retry_after = max(1, int(self.ip_window - elapsed))
            return True, retry_after

        # 2. Check compound (IP + Target) throttle to prevent single-account targeted attacks
        compound_val = f"{ip_address}:{normalized_id}"
        target_key = _hash_throttle_key('target', compound_val)
        target_count = cache.get(target_key)
        if target_count is not None and target_count >= self.target_limit:
            start_time = cache.get(f"{target_key}:start")
            elapsed = (now - start_time) if start_time else 0
            retry_after = max(1, int(self.target_window - elapsed))
            return True, retry_after

        return False, 0

    def record_failed_attempt(self, ip_address: str, raw_identifier: str) -> None:
        """
        Atomically records a failed authentication attempt across both dimensions.
        Initializes sliding window timestamps on first attempt.
        """
        now = time.time()
        normalized_id = self._normalize(raw_identifier)

        # Record IP attempt
        ip_key = _hash_throttle_key('ip', ip_address)
        if cache.add(ip_key, 1, timeout=self.ip_window):
            cache.set(f"{ip_key}:start", now, timeout=self.ip_window)
        else:
            try:
                cache.incr(ip_key)
            except Exception:
                cache.set(ip_key, 1, timeout=self.ip_window)

        # Record compound (IP + Target) attempt
        compound_val = f"{ip_address}:{normalized_id}"
        target_key = _hash_throttle_key('target', compound_val)
        if cache.add(target_key, 1, timeout=self.target_window):
            cache.set(f"{target_key}:start", now, timeout=self.target_window)
        else:
            try:
                cache.incr(target_key)
            except Exception:
                cache.set(target_key, 1, timeout=self.target_window)

    def reset_attempts(self, ip_address: str, raw_identifier: str) -> None:
        """
        Clears the compound (IP + Target) attempt counter on successful login.
        Leaves IP counter intact to prevent distributed credential stuffing.
        """
        normalized_id = self._normalize(raw_identifier)
        compound_val = f"{ip_address}:{normalized_id}"
        target_key = _hash_throttle_key('target', compound_val)
        cache.delete(target_key)
        cache.delete(f"{target_key}:start")
