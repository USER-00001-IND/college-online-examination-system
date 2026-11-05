"""
Institutional Resolution and Single-College Integrity Utilities.
College Online Examination System (PDUAM Amjonga - Gauhati University FYUGP).

Provides:
- Two-tier institutional resolution: runtime request-scoped resolver and deployment preflight verifier.
- Strict fail-closed semantics for missing, deactivated, or contaminated institutional states.
- Request-scoped caching without cross-request state leakage.
- Zero hardcoded primary key assumptions (dynamic College.pk accommodation).
- Strict code validation conforming to College.code (Table 9) schema constraints.
"""

import re
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from apps.academics.models import College

INSTITUTION_CODE_MAX_LENGTH = 20
INSTITUTION_CODE_PATTERN = r"^[A-Z0-9_-]+$"
INSTITUTION_CODE_REGEX = re.compile(INSTITUTION_CODE_PATTERN)


class InstitutionalConfigurationError(ImproperlyConfigured):
    """Raised when the authoritative institution record is missing or misconfigured."""
    pass


class InstitutionalDeactivatedError(ImproperlyConfigured):
    """Raised when the authoritative institution record exists but is deactivated."""
    pass


class InstitutionalIntegrityError(ImproperlyConfigured):
    """Raised when multi-college contamination (secondary active or inactive records) or identity mismatch is detected."""
    pass


def validate_institution_code(code: str) -> str:
    """
    Validates institution code according to the College model (Table 9) schema constraints:
    - Non-empty string
    - Maximum 20 characters
    - Uppercase alphanumeric characters, hyphens, and underscores only

    Returns the stripped code or raises InstitutionalConfigurationError.
    """
    if not code or not str(code).strip():
        raise InstitutionalConfigurationError(
            "INSTITUTION_CODE setting is empty or misconfigured."
        )
    cleaned = str(code).strip()
    if len(cleaned) > INSTITUTION_CODE_MAX_LENGTH:
        raise InstitutionalConfigurationError(
            f"INSTITUTION_CODE '{cleaned}' exceeds maximum length of {INSTITUTION_CODE_MAX_LENGTH} characters."
        )
    if not INSTITUTION_CODE_REGEX.match(cleaned):
        raise InstitutionalConfigurationError(
            f"INSTITUTION_CODE '{cleaned}' contains unsupported characters. "
            "Only uppercase alphanumeric characters, hyphens, and underscores are permitted."
        )
    return cleaned


def get_current_institution(request=None) -> College:
    """
    Authoritatively resolves the singleton College record for PDUAM Amjonga.

    Security & Architectural Guarantees:
    1. Resolves exclusively through the unique College.code configured in settings.INSTITUTION_CODE.
    2. Enforces schema validation on INSTITUTION_CODE (non-empty, max 20 chars, uppercase format).
    3. Verifies that the record exists and is_active=True.
    4. Enforces exact case-sensitive code agreement between configuration and database.
    5. Fails closed: raises InstitutionalConfigurationError if missing or invalid.
    6. Fails closed: raises InstitutionalDeactivatedError if deactivated.
    7. Never creates database records automatically.
    8. Never falls back to arbitrary College records or first().
    9. Never assumes College.pk == 1 or any hardcoded primary key.
    10. Supports request-scoped caching without cross-request state leakage.
        Note: Request-scoped cache is for read efficiency and is not a substitute for
        authoritative row revalidation inside locking transaction blocks.
    """
    target_code = validate_institution_code(getattr(settings, "INSTITUTION_CODE", "PDUAM-AMJONGA"))

    # Request-scoped cache inspection (strictly per-request; never global/process-wide)
    if request is not None and hasattr(request, "_cached_current_institution"):
        cached = getattr(request, "_cached_current_institution")
        if cached is not None and getattr(cached, "code", None) == target_code:
            if not getattr(cached, "is_active", False):
                raise InstitutionalDeactivatedError(
                    f"Authoritative institution '{target_code}' is deactivated. "
                    "All academic operations are suspended."
                )
            return cached

    # Query the authoritative institution record by unique code
    authorized = College.objects.filter(code=target_code).first()

    if not authorized:
        raise InstitutionalConfigurationError(
            f"Authoritative institution record with code '{target_code}' is missing. "
            "Execute 'python manage.py provision_institution' to initialize."
        )

    # Ensure exact case-sensitive code agreement
    if authorized.code != target_code:
        raise InstitutionalIntegrityError(
            f"Institutional code mismatch: database code '{authorized.code}' does not match "
            f"configured code '{target_code}'."
        )

    if not authorized.is_active:
        raise InstitutionalDeactivatedError(
            f"Authoritative institution '{target_code}' is deactivated. "
            "All academic operations are suspended."
        )

    # Attach to request object for request-scoped caching
    if request is not None:
        request._cached_current_institution = authorized

    return authorized


def verify_single_college_integrity() -> None:
    """
    Verifies that the database conforms strictly to single-college deployment architecture.
    Detects:
    - Missing authoritative PDUAM record.
    - Code mismatch between configuration and database record.
    - Deactivated authoritative PDUAM record.
    - Any secondary active College records.
    - Any secondary inactive College records.

    This function does NOT delete or modify records.
    It is intended for deployment preflight checks and health monitoring.
    Note: Application-level checks cannot prevent direct out-of-band raw SQL inserts;
    strict database-level singleton enforcement requires a schema constraint (Option B).
    """
    target_code = validate_institution_code(getattr(settings, "INSTITUTION_CODE", "PDUAM-AMJONGA"))

    authorized = College.objects.filter(code=target_code).first()

    if not authorized:
        raise InstitutionalConfigurationError(
            f"Single-college integrity check failed: Authoritative institution '{target_code}' is missing."
        )

    # Ensure exact case-sensitive code agreement
    if authorized.code != target_code:
        raise InstitutionalIntegrityError(
            f"Single-college integrity check failed: database code '{authorized.code}' does not match "
            f"configured code '{target_code}'."
        )

    if not authorized.is_active:
        raise InstitutionalDeactivatedError(
            f"Single-college integrity check failed: Authoritative institution '{target_code}' is deactivated."
        )

    secondary_colleges = College.objects.exclude(pk=authorized.pk)
    if secondary_colleges.exists():
        secondary_codes = list(secondary_colleges.values_list("code", flat=True))
        raise InstitutionalIntegrityError(
            f"Multi-college integrity violation: {secondary_colleges.count()} foreign college "
            f"record(s) detected in Table 9: {secondary_codes}. System is single-college only."
        )
