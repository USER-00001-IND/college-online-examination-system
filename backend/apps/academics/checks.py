"""
Django System Checks for Institutional Integrity.
College Online Examination System (PDUAM Amjonga - Gauhati University FYUGP).

Registers deployment and database integrity checks to verify single-college
compliance without executing queries during AppConfig.ready().
"""

import re
from django.conf import settings
from django.core.checks import Error, Tags, register
from django.db.utils import OperationalError, ProgrammingError

INSTITUTION_CODE_MAX_LENGTH = 20
INSTITUTION_CODE_PATTERN = r"^[A-Z0-9_-]+$"
INSTITUTION_CODE_REGEX = re.compile(INSTITUTION_CODE_PATTERN)


@register(Tags.database, Tags.security, deploy=True)
def check_single_college_integrity(app_configs=None, databases=None, **kwargs):
    """
    Verifies that the database conforms to the single-college deployment architecture.
    Executed explicitly via 'python manage.py check --deploy --database default'.

    Database Access Rules:
    - Never accesses the database when 'databases' argument is absent or None.
    - Never accesses the database when 'default' database connection is not authorized.
    - Fails closed with academics.E004 (Error) if database is unreachable or unmigrated.
    - Validates configured INSTITUTION_CODE format against College.code schema (E001).
    - Returns valid Django CheckMessage objects (academics.E001, E002, E003, E004).
    """
    errors = []

    # Check database routing parameter: skip execution if databases is absent or does not include 'default'
    if not databases or "default" not in databases:
        return errors

    target_code = getattr(settings, "INSTITUTION_CODE", "PDUAM-AMJONGA")
    if not target_code or not str(target_code).strip():
        errors.append(
            Error(
                "INSTITUTION_CODE configuration setting is empty or misconfigured.",
                hint="Set INSTITUTION_CODE='PDUAM-AMJONGA' in settings or environment variables.",
                id="academics.E001",
            )
        )
        return errors

    target_code = str(target_code).strip()
    if len(target_code) > INSTITUTION_CODE_MAX_LENGTH:
        errors.append(
            Error(
                f"INSTITUTION_CODE configuration setting '{target_code}' exceeds maximum length of "
                f"{INSTITUTION_CODE_MAX_LENGTH} characters.",
                hint=f"Configure an INSTITUTION_CODE with {INSTITUTION_CODE_MAX_LENGTH} or fewer characters.",
                id="academics.E001",
            )
        )
        return errors

    if not INSTITUTION_CODE_REGEX.match(target_code):
        errors.append(
            Error(
                f"INSTITUTION_CODE configuration setting '{target_code}' contains invalid characters.",
                hint="Use only uppercase alphanumeric characters, hyphens, and underscores.",
                id="academics.E001",
            )
        )
        return errors

    try:
        from apps.academics.models import College

        authorized = College.objects.filter(code=target_code).first()

        if not authorized:
            errors.append(
                Error(
                    f"Authoritative institution record with code '{target_code}' is missing.",
                    hint="Execute 'python manage.py provision_institution' after migrations.",
                    id="academics.E001",
                )
            )
            return errors

        # Case-sensitive comparison to prevent collation mismatches
        if authorized.code != target_code:
            errors.append(
                Error(
                    f"Stored institution code '{authorized.code}' does not match configured "
                    f"INSTITUTION_CODE '{target_code}'.",
                    hint="Ensure database record code exactly matches configured INSTITUTION_CODE.",
                    id="academics.E001",
                )
            )
            return errors

        if not authorized.is_active:
            errors.append(
                Error(
                    f"Authoritative institution record '{target_code}' is deactivated.",
                    hint="Activate the institution record before serving production traffic.",
                    id="academics.E002",
                )
            )

        secondary_colleges = College.objects.exclude(pk=authorized.pk)
        if secondary_colleges.exists():
            secondary_codes = list(secondary_colleges.values_list("code", flat=True))
            errors.append(
                Error(
                    f"Multi-college integrity violation: {secondary_colleges.count()} foreign "
                    f"college record(s) detected: {secondary_codes}.",
                    hint="Clean up or reconcile secondary records. The system serves exactly one institution.",
                    id="academics.E003",
                )
            )

    except (OperationalError, ProgrammingError) as exc:
        # Table does not exist yet (ProgrammingError) or database is unreachable (OperationalError).
        # Return Error (academics.E004) so that 'check --deploy --database default' fails closed.
        # Safe error type reporting prevents leaking connection strings, credentials, or host IPs.
        error_type = type(exc).__name__
        errors.append(
            Error(
                f"Database table for College is unmigrated or unreachable ({error_type}).",
                hint="Ensure database connectivity and run 'python manage.py migrate' before deployment.",
                id="academics.E004",
            )
        )

    return errors
