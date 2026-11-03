"""
Audit Metadata Validation and Integrity Services for Accounts Domain.
College Online Examination System.

Enforces strict client IP validation via Python's ipaddress module, control-character
sanitization to prevent log and CRLF injection, and defensive audit event persistence policies.
"""

import ipaddress
import logging
import re
from typing import Optional
from django.conf import settings
from django.utils import timezone

from apps.accounts.models import AuthEvent, User

logger = logging.getLogger('college.accounts.audit')

# Regex pattern matching ASCII control characters (\x00 to \x1f and \x7f)
CONTROL_CHARS_REGEX = re.compile(r'[\x00-\x1f\x7f]')


class AuditPersistenceError(Exception):
    """Raised when a security-critical authentication audit event cannot be durably recorded."""
    pass


def get_validated_client_ip(request) -> Optional[str]:
    """
    Extracts and strictly validates the client IP address.

    Security Specification (Round 3 Correction):
    1. Independent Trust Boundary: Does NOT rely on TRUST_PROXY_SSL_HEADER.
       Only inspects HTTP_X_FORWARDED_FOR if TRUST_PROXY_CLIENT_IP is explicitly True.
    2. Strict Validation: Uses Python's ipaddress.ip_address() to validate syntax.
       Malformed, spoofed, or injected non-IP strings are strictly rejected.
    3. Safe Fallback: When proxy trust is disabled or forwarded values are invalid,
       falls back to validated REMOTE_ADDR.
    4. Fail-Closed on Missing/Invalid Address: Never invents an authentic loopback
       address ('127.0.0.1') when REMOTE_ADDR is missing or malformed. Returns None
       so callers can enforce fail-closed security.
    """
    trust_proxy = getattr(settings, 'TRUST_PROXY_CLIENT_IP', False)
    candidate_ip: Optional[str] = None

    if trust_proxy:
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded and isinstance(forwarded, str):
            first_hop = forwarded.split(',')[0].strip()
            try:
                ip_obj = ipaddress.ip_address(first_hop)
                candidate_ip = str(ip_obj)
            except ValueError:
                logger.warning("Rejected syntactically invalid X-Forwarded-For IP address.")
                candidate_ip = None

    if candidate_ip is None:
        remote_addr = request.META.get('REMOTE_ADDR')
        if remote_addr and isinstance(remote_addr, str):
            clean_remote = remote_addr.strip()
            try:
                ip_obj = ipaddress.ip_address(clean_remote)
                candidate_ip = str(ip_obj)
            except ValueError:
                logger.warning("Rejected syntactically invalid REMOTE_ADDR IP address.")
                candidate_ip = None
        else:
            candidate_ip = None

    if candidate_ip is None:
        return None

    return candidate_ip[:45]


def sanitize_identifier(raw_identifier: Optional[str]) -> str:
    """
    Normalizes and sanitizes user-supplied authentication identifiers.
    Strips control characters, newlines, and whitespace to prevent log and database injection.
    Enforces the accounts_auth_event.identifier_entered length limit (254 chars).
    NEVER logs passwords or raw secrets.
    """
    if not raw_identifier or not isinstance(raw_identifier, str):
        return ''

    # Remove all ASCII control characters (CRLF, tabs, null bytes, escape codes)
    sanitized = CONTROL_CHARS_REGEX.sub('', raw_identifier).strip()
    return sanitized[:254]


def sanitize_user_agent(request) -> str:
    """
    Extracts and sanitizes the client User-Agent string.
    Removes ASCII control characters and limits length to 255 chars.
    """
    ua = request.META.get('HTTP_USER_AGENT', '')
    if not isinstance(ua, str):
        return ''

    sanitized = CONTROL_CHARS_REGEX.sub('', ua).strip()
    return sanitized[:255]


def record_auth_event(
    user: Optional[User],
    raw_identifier: str,
    event_type: str,
    request,
    raise_on_failure: bool = False,
) -> Optional[AuthEvent]:
    """
    Persists an authentication audit event to accounts_auth_event.

    Audit Persistence Policy:
    - For security-critical success events (e.g. LOGIN_SUCCESS, LOGOUT), raise_on_failure=True
      is enforced so that session creation aborts if the audit log cannot be created.
    - For failure events (e.g. LOGIN_FAILED), raise_on_failure=False logs a critical error
      without masking the primary failure or leaking database exceptions to clients.
    """
    ip_address = get_validated_client_ip(request) or 'UNKNOWN'
    identifier_entered = sanitize_identifier(raw_identifier)
    user_agent = sanitize_user_agent(request)

    try:
        event = AuthEvent.objects.create(
            user=user,
            identifier_entered=identifier_entered,
            event_type=event_type,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=timezone.now(),
        )
        return event
    except Exception as exc:
        logger.critical(
            "CRITICAL: Failed to persist AuthEvent [event_type=%s, ip=%s, error=%s]",
            event_type,
            ip_address,
            exc.__class__.__name__,
        )
        if raise_on_failure:
            raise AuditPersistenceError(
                f"Failed to record mandatory authentication audit event: {exc.__class__.__name__}"
            ) from exc
        return None
