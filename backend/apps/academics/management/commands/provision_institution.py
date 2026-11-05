"""
Provision Institution Management Command.
College Online Examination System (PDUAM Amjonga - Gauhati University FYUGP).

Initializes or verifies the single authoritative College record for PDUAM Amjonga
in a controlled, auditable, and idempotent manner.

Operational Guarantees:
- Strict Code Alignment: --code must match settings.INSTITUTION_CODE and schema constraints.
- Identity Verification: Validates that existing active record's name matches trusted provisioning name.
- Idempotency without Overwrite: Never overwrites existing active records or mutates metadata.
- Deactivation Guard: Aborts if an institution is inactive; automatic reactivation is prohibited.
- Single-College Enforcement: Aborts if any foreign college records exist in Table 9.
- Concurrency Resilience: Catches IntegrityError within transaction.atomic(), safely recovering
  without corrupting database connection state.
"""

import re
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import EmailValidator, ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from apps.academics.models import College

INSTITUTION_CODE_MAX_LENGTH = 20
INSTITUTION_CODE_PATTERN = r"^[A-Z0-9_-]+$"
INSTITUTION_CODE_REGEX = re.compile(INSTITUTION_CODE_PATTERN)


class Command(BaseCommand):
    help = "Safely provisions or verifies the single authoritative College record for PDUAM Amjonga."

    def add_arguments(self, parser):
        parser.add_argument(
            "--code",
            default=getattr(settings, "INSTITUTION_CODE", "PDUAM-AMJONGA"),
            help="Internal institution code (must match settings.INSTITUTION_CODE)",
        )
        parser.add_argument(
            "--name",
            required=True,
            help="Full official institution name",
        )
        parser.add_argument(
            "--contact-email",
            required=True,
            help="Verified administrative contact email",
        )
        parser.add_argument(
            "--contact-phone",
            default=None,
            help="Verified administrative contact phone (optional)",
        )
        parser.add_argument(
            "--address",
            default=None,
            help="Campus postal address (optional)",
        )

    def handle(self, *args, **options):
        configured_code = getattr(settings, "INSTITUTION_CODE", "PDUAM-AMJONGA")
        code = str(options["code"]).strip() if options.get("code") else ""
        name = str(options["name"]).strip() if options.get("name") else ""
        contact_email = str(options["contact_email"]).strip() if options.get("contact_email") else ""
        contact_phone = str(options["contact_phone"]).strip() if options.get("contact_phone") else None
        address = str(options["address"]).strip() if options.get("address") else None

        # 1. Require supplied code to match settings.INSTITUTION_CODE and schema constraints
        if code != configured_code:
            raise CommandError(
                f"Supplied code '{code}' does not match configured INSTITUTION_CODE '{configured_code}'."
            )
        if len(code) > INSTITUTION_CODE_MAX_LENGTH:
            raise CommandError(
                f"Institution code '{code}' exceeds maximum length of {INSTITUTION_CODE_MAX_LENGTH} characters."
            )
        if not INSTITUTION_CODE_REGEX.match(code):
            raise CommandError(
                f"Institution code '{code}' contains invalid characters. "
                "Only uppercase alphanumeric characters, hyphens, and underscores are permitted."
            )

        # 2. Reject empty or malformed institution name
        if not name:
            raise CommandError("Institution name cannot be empty or whitespace only.")

        # 3. Reject invalid contact email
        if not contact_email:
            raise CommandError("Contact email cannot be empty.")
        try:
            EmailValidator()(contact_email)
        except DjangoValidationError:
            raise CommandError(f"Invalid contact email address: '{contact_email}'.")

        # 4. Check for foreign College records in Table 9
        foreign_colleges = College.objects.exclude(code=code)
        if foreign_colleges.exists():
            foreign_codes = list(foreign_colleges.values_list("code", flat=True))
            raise CommandError(
                f"Provisioning aborted: {foreign_colleges.count()} foreign college record(s) "
                f"detected in Table 9: {foreign_codes}. Manual reconciliation required."
            )

        # 5. Check if the institution record already exists
        existing = College.objects.filter(code=code).first()
        if existing:
            if existing.code != code:
                raise CommandError(
                    f"Stored institution code '{existing.code}' does not match configured code '{code}'."
                )
            if not existing.is_active:
                raise CommandError(
                    f"Existing institution with code '{code}' is deactivated. "
                    "Automatic reactivation is prohibited. Manual administrative investigation required."
                )
            # Verify stored name agrees with supplied trusted name; never silently accept mismatch or overwrite
            if existing.name.strip() != name:
                raise CommandError(
                    f"Institutional identity mismatch for code '{code}': "
                    f"Stored name '{existing.name}' does not match trusted provisioning name '{name}'. "
                    "Existing records will not be silently overwritten. Manual reconciliation is required."
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Verified existing active institution: '{existing.name}' ({code}) [PK={existing.pk}]"
                )
            )
            return

        # 6. Attempt atomic creation with IntegrityError handling for concurrency
        created = False
        college = None
        try:
            with transaction.atomic():
                college = College.objects.create(
                    code=code,
                    name=name,
                    contact_email=contact_email,
                    contact_phone=contact_phone,
                    address=address,
                    is_active=True,
                )
                created = True
        except IntegrityError:
            # Concurrent insertion caught by unique constraint on code.
            # The transaction.atomic() context rolls back the failed insert (or savepoint if nested),
            # leaving the database connection in a valid state to execute the recovery query.
            college = College.objects.filter(code=code).first()
            if not college:
                raise CommandError("Concurrent provisioning collision occurred; retry required.")
            created = False

        if not created:
            if college.code != code:
                raise CommandError(
                    f"Stored institution code '{college.code}' does not match configured code '{code}'."
                )
            if not college.is_active:
                raise CommandError(
                    f"Existing institution with code '{code}' is deactivated. "
                    "Automatic reactivation is prohibited."
                )
            if college.name.strip() != name:
                raise CommandError(
                    f"Institutional identity mismatch for code '{code}': "
                    f"Stored name '{college.name}' does not match trusted provisioning name '{name}'. "
                    "Existing records will not be silently overwritten. Manual reconciliation is required."
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Verified existing active institution: '{college.name}' ({code}) [PK={college.pk}]"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully provisioned institution: '{college.name}' ({code}) [PK={college.pk}]"
                )
            )
