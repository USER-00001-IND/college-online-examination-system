"""
Stage B1 Acceptance and Security Unit Tests.
College Online Examination System (PDUAM Amjonga - Gauhati University FYUGP).

Tests strictly the Stage B1 Institutional Foundation:
- settings.INSTITUTION_CODE configuration & schema validation (Table 9)
- get_current_institution() resolver, dynamic PK, fail-closed handling, request caching
- verify_single_college_integrity() single-college preflight verifier
- check_single_college_integrity Django system checks (database access rules, E001-E004)
- Fail-closed deployment preflight on database unreachable / unmigrated (E004 -> SystemCheckError)
- provision_institution management command (validation, idempotency, concurrency, identity verification)
- Zero dependencies on unfinished B2/B3 ViewSets or serializers.
"""

import os
import subprocess
import sys
import tempfile
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.core.checks import Error
from django.core.management import call_command, CommandError
from django.core.management.base import SystemCheckError
from django.db import connections, IntegrityError
from django.db.utils import OperationalError, ProgrammingError
from django.test import override_settings, RequestFactory, TestCase, TransactionTestCase

from apps.academics.checks import check_single_college_integrity
from apps.academics.models import College
from apps.academics.utils import (
    get_current_institution,
    InstitutionalConfigurationError,
    InstitutionalDeactivatedError,
    InstitutionalIntegrityError,
    validate_institution_code,
    verify_single_college_integrity,
)


class StageB1InstitutionResolverTests(TestCase):
    """
    Tests for get_current_institution resolver and single-college integrity verifier.
    """

    def setUp(self):
        self.factory = RequestFactory()

    def test_01_institution_code_configured_in_settings(self):
        """Verifies INSTITUTION_CODE defaults to PDUAM-AMJONGA and is present in settings."""
        self.assertTrue(hasattr(settings, "INSTITUTION_CODE"))
        self.assertEqual(settings.INSTITUTION_CODE, "PDUAM-AMJONGA")

    def test_02_dynamic_institution_resolution_without_hardcoded_pk(self):
        """
        Verifies that get_current_institution resolves dynamically via code
        and accommodates non-default primary keys (e.g. pk=105).
        """
        college = College.objects.create(
            id=105,
            name="Pandit Deendayal Upadhyaya Adarsha Mahavidyalaya",
            code="PDUAM-AMJONGA",
            contact_email="admin@example.edu",
            is_active=True,
        )
        resolved = get_current_institution()
        self.assertEqual(resolved.pk, 105)
        self.assertEqual(resolved.code, "PDUAM-AMJONGA")
        self.assertEqual(resolved.name, "Pandit Deendayal Upadhyaya Adarsha Mahavidyalaya")

    def test_03_request_scoped_resolver_caching(self):
        """
        Verifies that passing a request object caches the resolved instance
        on request._cached_current_institution, avoiding redundant queries.
        """
        College.objects.create(
            id=42,
            name="PDUAM Amjonga",
            code="PDUAM-AMJONGA",
            contact_email="admin@example.edu",
            is_active=True,
        )
        request = self.factory.get("/")

        # First call: executes query and sets cache attribute
        with self.assertNumQueries(1):
            inst1 = get_current_institution(request)
        self.assertEqual(inst1.pk, 42)
        self.assertTrue(hasattr(request, "_cached_current_institution"))

        # Second call on same request: zero queries (uses request cache)
        with self.assertNumQueries(0):
            inst2 = get_current_institution(request)
        self.assertEqual(inst1, inst2)

    def test_04_missing_institution_fails_closed(self):
        """Verifies that resolver raises InstitutionalConfigurationError when record is missing."""
        self.assertEqual(College.objects.count(), 0)
        with self.assertRaises(InstitutionalConfigurationError) as ctx:
            get_current_institution()
        self.assertIn("PDUAM-AMJONGA", str(ctx.exception))
        self.assertIn("missing", str(ctx.exception).lower())

    def test_05_inactive_institution_fails_closed(self):
        """Verifies that resolver raises InstitutionalDeactivatedError when record is deactivated."""
        College.objects.create(
            name="PDUAM Amjonga",
            code="PDUAM-AMJONGA",
            contact_email="admin@example.edu",
            is_active=False,
        )
        with self.assertRaises(InstitutionalDeactivatedError) as ctx:
            get_current_institution()
        self.assertIn("deactivated", str(ctx.exception).lower())

    def test_06_additional_active_college_detection(self):
        """Verifies that verify_single_college_integrity detects secondary active college records."""
        College.objects.create(
            name="PDUAM Amjonga",
            code="PDUAM-AMJONGA",
            contact_email="admin@example.edu",
            is_active=True,
        )
        College.objects.create(
            name="Rogue College",
            code="ROGUE-COLLEGE",
            contact_email="rogue@example.edu",
            is_active=True,
        )
        with self.assertRaises(InstitutionalIntegrityError) as ctx:
            verify_single_college_integrity()
        self.assertIn("ROGUE-COLLEGE", str(ctx.exception))
        self.assertIn("Multi-college integrity violation", str(ctx.exception))

    def test_07_additional_inactive_college_detection(self):
        """Verifies that verify_single_college_integrity detects secondary inactive college records."""
        College.objects.create(
            name="PDUAM Amjonga",
            code="PDUAM-AMJONGA",
            contact_email="admin@example.edu",
            is_active=True,
        )
        College.objects.create(
            name="Inactive Secondary",
            code="INACTIVE-COLLEGE",
            contact_email="inactive@example.edu",
            is_active=False,
        )
        with self.assertRaises(InstitutionalIntegrityError) as ctx:
            verify_single_college_integrity()
        self.assertIn("INACTIVE-COLLEGE", str(ctx.exception))

    def test_18_request_scoped_caching_does_not_leak_between_requests(self):
        """Verifies that request-scoped cache does not leak across different request instances."""
        College.objects.create(
            id=10,
            name="PDUAM Amjonga",
            code="PDUAM-AMJONGA",
            contact_email="admin@example.edu",
            is_active=True,
        )
        request_a = self.factory.get("/path-a")
        request_b = self.factory.get("/path-b")

        inst_a = get_current_institution(request_a)
        self.assertTrue(hasattr(request_a, "_cached_current_institution"))
        self.assertFalse(hasattr(request_b, "_cached_current_institution"))

        # Query executes for request_b because cache is strictly request-isolated
        with self.assertNumQueries(1):
            inst_b = get_current_institution(request_b)
        self.assertEqual(inst_a.pk, inst_b.pk)

    def test_19_institution_code_validation_empty_or_whitespace(self):
        """Verifies that empty or whitespace INSTITUTION_CODE raises InstitutionalConfigurationError."""
        for invalid_val in ["", "   ", None]:
            with override_settings(INSTITUTION_CODE=invalid_val):
                with self.assertRaises(InstitutionalConfigurationError) as ctx:
                    get_current_institution()
                self.assertIn("empty or misconfigured", str(ctx.exception).lower())

    def test_20_institution_code_validation_exceeding_max_length(self):
        """Verifies that INSTITUTION_CODE exceeding 20 characters raises InstitutionalConfigurationError."""
        long_code = "A" * 21
        with override_settings(INSTITUTION_CODE=long_code):
            with self.assertRaises(InstitutionalConfigurationError) as ctx:
                get_current_institution()
            self.assertIn("exceeds maximum length of 20", str(ctx.exception))

    def test_21_institution_code_validation_invalid_character_format(self):
        """Verifies that INSTITUTION_CODE with lowercase, spaces, or symbols raises InstitutionalConfigurationError."""
        for invalid_code in ["pduam-amjonga", "PDUAM AMJONGA", "PDUAM@AMJONGA!", "PDUAM.AMJONGA"]:
            with override_settings(INSTITUTION_CODE=invalid_code):
                with self.assertRaises(InstitutionalConfigurationError) as ctx:
                    get_current_institution()
                self.assertIn("unsupported characters", str(ctx.exception))

    def test_22_institution_code_case_sensitive_mismatch_detection(self):
        """Verifies that case-sensitive mismatch between database and config raises InstitutionalIntegrityError."""
        College.objects.create(
            name="PDUAM Amjonga",
            code="PDUAM-AMJONGA",
            contact_email="admin@example.edu",
            is_active=True,
        )
        # Even if DB collation is case-insensitive, Python exact comparison detects mismatch
        with patch.object(College.objects, "filter") as mock_filter:
            mismatched_college = College(
                id=1,
                name="PDUAM Amjonga",
                code="pduam-amjonga",  # lowercase in DB
                contact_email="admin@example.edu",
                is_active=True,
            )
            mock_filter.return_value.first.return_value = mismatched_college
            with self.assertRaises(InstitutionalIntegrityError) as ctx:
                get_current_institution()
            self.assertIn("Institutional code mismatch", str(ctx.exception))


class StageB1DjangoSystemCheckTests(TestCase):
    """
    Tests for check_single_college_integrity Django system check.
    """

    def test_08_django_system_check_registration_and_error_messages(self):
        """Verifies system check produces academics.E001, E002, E003 for relevant conditions."""
        # 1. Missing institution -> E001
        errors = check_single_college_integrity(databases=["default"])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "academics.E001")

        # 2. Inactive institution -> E002
        pduam = College.objects.create(
            name="PDUAM Amjonga",
            code="PDUAM-AMJONGA",
            contact_email="admin@example.edu",
            is_active=False,
        )
        errors_inactive = check_single_college_integrity(databases=["default"])
        self.assertEqual(len(errors_inactive), 1)
        self.assertEqual(errors_inactive[0].id, "academics.E002")

        # 3. Secondary college -> E003
        pduam.is_active = True
        pduam.save()
        College.objects.create(
            name="Foreign College",
            code="FOREIGN-COLLEGE",
            contact_email="foreign@example.edu",
            is_active=True,
        )
        errors_multi = check_single_college_integrity(databases=["default"])
        self.assertEqual(len(errors_multi), 1)
        self.assertEqual(errors_multi[0].id, "academics.E003")

    def test_11_system_check_performs_no_database_query_when_databases_none(self):
        """
        Verifies that check_single_college_integrity executes ZERO database queries
        when databases is None or not provided (prevents queries during app boot).
        """
        with self.assertNumQueries(0):
            messages = check_single_college_integrity(databases=None)
        self.assertEqual(messages, [])

    def test_12_system_check_performs_no_database_query_when_default_not_authorized(self):
        """
        Verifies that check_single_college_integrity executes ZERO database queries
        when the default database connection is not authorized in databases list.
        """
        with self.assertNumQueries(0):
            messages = check_single_college_integrity(databases=["replica_db", "analytics_db"])
        self.assertEqual(messages, [])

    def test_23_system_check_detects_invalid_institution_code_settings(self):
        """Verifies system check returns academics.E001 for empty, long, or malformed settings."""
        # Empty
        with override_settings(INSTITUTION_CODE=""):
            errors = check_single_college_integrity(databases=["default"])
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].id, "academics.E001")
            self.assertIn("empty or misconfigured", errors[0].msg)

        # Exceeding 20 chars
        with override_settings(INSTITUTION_CODE="A" * 21):
            errors = check_single_college_integrity(databases=["default"])
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].id, "academics.E001")
            self.assertIn("exceeds maximum length", errors[0].msg)

        # Invalid format
        with override_settings(INSTITUTION_CODE="pduam-invalid"):
            errors = check_single_college_integrity(databases=["default"])
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].id, "academics.E001")
            self.assertIn("invalid characters", errors[0].msg)

    def test_24_system_check_operational_error_produces_e004(self):
        """
        Verifies that database connectivity failures (OperationalError) produce academics.E004
        as a proper Django Error (severity level 40), NOT a Warning.
        """
        with patch.object(College.objects, "filter", side_effect=OperationalError("Connection refused")):
            errors = check_single_college_integrity(databases=["default"])
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], Error)
            self.assertEqual(errors[0].id, "academics.E004")
            self.assertEqual(errors[0].level, 40)
            self.assertIn("unreachable", errors[0].msg.lower())
            self.assertIn("OperationalError", errors[0].msg)

    def test_25_system_check_programming_error_produces_e004(self):
        """
        Verifies that unmigrated tables (ProgrammingError) produce academics.E004
        as a proper Django Error (severity level 40), NOT a Warning.
        """
        with patch.object(College.objects, "filter", side_effect=ProgrammingError("Table doesn't exist")):
            errors = check_single_college_integrity(databases=["default"])
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], Error)
            self.assertEqual(errors[0].id, "academics.E004")
            self.assertEqual(errors[0].level, 40)
            self.assertIn("unmigrated", errors[0].msg.lower())
            self.assertIn("ProgrammingError", errors[0].msg)

    def test_26_system_check_e004_does_not_expose_database_credentials(self):
        """
        Security verification: Verifies that database exception strings containing passwords
        or host IPs are NOT leaked into check error messages.
        """
        sensitive_msg = "Access denied for user 'admin'@'10.0.0.5' (using password: YES, pass='secret123')"
        with patch.object(College.objects, "filter", side_effect=OperationalError(sensitive_msg)):
            errors = check_single_college_integrity(databases=["default"])
            self.assertEqual(len(errors), 1)
            self.assertNotIn("secret123", errors[0].msg)
            self.assertNotIn("10.0.0.5", errors[0].msg)
            self.assertNotIn("password: YES", errors[0].msg)
            self.assertIn("OperationalError", errors[0].msg)

    def test_27_call_command_check_deploy_raises_system_check_error_on_operational_error(self):
        """
        Critical regression test: Verifies that 'check --deploy --database default'
        raises SystemCheckError (nonzero exit) when the database is unreachable.
        """
        with patch.object(College.objects, "filter", side_effect=OperationalError("Connection lost")):
            with self.assertRaises(SystemCheckError) as ctx:
                call_command("check", deploy=True, databases=["default"], tags=["database", "security"])
            self.assertIn("academics.E004", str(ctx.exception))

    def test_28_call_command_check_deploy_raises_system_check_error_on_programming_error(self):
        """
        Critical regression test: Verifies that 'check --deploy --database default'
        raises SystemCheckError (nonzero exit) when College table is unmigrated.
        """
        with patch.object(College.objects, "filter", side_effect=ProgrammingError("no such table")):
            with self.assertRaises(SystemCheckError) as ctx:
                call_command("check", deploy=True, databases=["default"], tags=["database", "security"])
            self.assertIn("academics.E004", str(ctx.exception))

    def test_32_ordinary_system_checks_do_not_execute_institution_integrity_check(self):
        """
        Deployment-only verification: Verifies that ordinary non-deployment checks
        (deploy=False) do NOT execute check_single_college_integrity, avoiding bootstrap deadlocks.
        """
        # Even when database is completely empty (unprovisioned), ordinary check passes cleanly
        self.assertEqual(College.objects.count(), 0)

        out_default = StringIO()
        call_command("check", stdout=out_default)
        self.assertIn("System check identified no issues", out_default.getvalue())

        out_db = StringIO()
        call_command("check", databases=["default"], stdout=out_db)
        self.assertIn("System check identified no issues", out_db.getvalue())

    def test_33_deployment_checks_with_database_default_execute_institution_integrity_check(self):
        """
        Deployment-only verification: Verifies that 'check --deploy --database default'
        DOES execute check_single_college_integrity and fails closed when unprovisioned.
        """
        self.assertEqual(College.objects.count(), 0)
        with self.assertRaises(SystemCheckError) as ctx:
            call_command("check", deploy=True, databases=["default"], tags=["database", "security"])
        self.assertIn("academics.E001", str(ctx.exception))

    def test_34_other_management_commands_do_not_experience_bootstrap_deadlock(self):
        """
        Verifies that standard management commands (diffsettings, showmigrations)
        do not experience an unintended bootstrap deadlock on unprovisioned database.
        """
        self.assertEqual(College.objects.count(), 0)

        out_diff = StringIO()
        call_command("diffsettings", stdout=out_diff)
        self.assertIn("INSTITUTION_CODE", out_diff.getvalue())

        out_mig = StringIO()
        call_command("showmigrations", "academics", stdout=out_mig)
        self.assertIn("academics", out_mig.getvalue())


class StageB1FreshDatabaseLifecycleTests(TestCase):
    """
    Tests the complete fresh-database lifecycle in an isolated subprocess:
    - Runs in an isolated subprocess with database settings configured BEFORE Django initializes
    - Uses a newly created temporary SQLite database outside existing pytest database
    - Demonstrates that the database starts with no application tables
    - Executes actual Django migrations
    - Verifies the College table was created
    - Verifies deployment preflight fails before institutional provisioning (academics.E001)
    - Executes the provisioning command with test-only contact details
    - Verifies deployment preflight succeeds after provisioning
    - Inserts a secondary College record into the isolated database
    - Verifies deployment preflight fails with academics.E003
    - Cleans up the temporary database safely
    - Ensures the existing pytest database is untouched
    """

    def test_35_fresh_database_migration_provisioning_and_preflight_lifecycle(self):
        """Demonstrates complete fresh DB lifecycle in an isolated subprocess without override_settings."""
        # 12. Record existing pytest database state before spawning subprocess
        initial_pytest_college_count = College.objects.count()

        # 2. Use a newly created temporary SQLite database, outside the existing pytest database
        temp_db_fd, temp_db_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(temp_db_fd)
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)

        subprocess_script = """
import os, sys, sqlite3
temp_db = sys.argv[1]

# 1. Configure settings BEFORE Django initializes
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.test'
from django.conf import settings
settings.DATABASES['default'] = {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': temp_db,
}

# 3. Demonstrate that the database starts with no application tables
conn = sqlite3.connect(temp_db)
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables_before = [r[0] for r in cursor.fetchall()]
conn.close()
assert 'academics_college' not in tables_before, f"Expected no academics_college, found: {tables_before}"
print(f"STEP_3_INITIAL_TABLES_COUNT={len(tables_before)}")

# Initialize Django with the isolated database configured
import django
django.setup()

from django.core.management import call_command
from django.core.management.base import SystemCheckError
from io import StringIO

# 4. Execute actual Django migrations
print("STEP_4_RUNNING_MIGRATIONS")
call_command('migrate', verbosity=0)

# 5. Verify the College table was created
conn = sqlite3.connect(temp_db)
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='academics_college';")
table_created = cursor.fetchone()
conn.close()
assert table_created is not None, "academics_college table was not created by migrate!"
print("STEP_5_COLLEGE_TABLE_CREATED_VERIFIED")

# 6. Verify deployment preflight fails before institutional provisioning
try:
    call_command('check', deploy=True, databases=['default'], tags=['database', 'security'])
    raise AssertionError("Preflight should have failed before provisioning!")
except SystemCheckError as e:
    assert 'academics.E001' in str(e), f"Expected academics.E001, got: {e}"
    print("STEP_6_PREFLIGHT_FAILS_BEFORE_PROVISIONING_VERIFIED")

# 7. Execute the provisioning command with test-only contact details
out_prov = StringIO()
call_command(
    'provision_institution',
    code='PDUAM-AMJONGA',
    name='Pandit Deendayal Upadhyaya Adarsha Mahavidyalaya',
    contact_email='admin@example.edu',
    contact_phone='+91-9876543210',
    address='Amjonga, Dudhnoi, Goalpara, Assam - 783124',
    stdout=out_prov,
)
assert 'Successfully provisioned institution' in out_prov.getvalue(), "Provisioning failed!"
print("STEP_7_PROVISIONING_EXECUTED")

# 8. Verify deployment preflight succeeds after provisioning
out_check = StringIO()
call_command('check', deploy=True, databases=['default'], tags=['database'], stdout=out_check)
assert 'System check identified no issues' in out_check.getvalue(), "Preflight check failed after provisioning!"
print("STEP_8_PREFLIGHT_SUCCEEDS_AFTER_PROVISIONING_VERIFIED")

# 9. Insert a secondary College record into the isolated database
from apps.academics.models import College
College.objects.create(
    name='Rogue Secondary College',
    code='ROGUE-01',
    contact_email='rogue@example.edu',
    is_active=True,
)
print("STEP_9_SECONDARY_COLLEGE_INSERTED")

# 10. Verify deployment preflight fails with academics.E003
try:
    call_command('check', deploy=True, databases=['default'], tags=['database', 'security'])
    raise AssertionError("Preflight should have failed with secondary college!")
except SystemCheckError as e:
    assert 'academics.E003' in str(e), f"Expected academics.E003, got: {e}"
    print("STEP_10_PREFLIGHT_FAILS_WITH_E003_VERIFIED")

print("SUBPROCESS_LIFECYCLE_SUCCESS")
"""

        env = os.environ.copy()
        env["PYTHONPATH"] = "backend"

        try:
            result = subprocess.run(
                [sys.executable, "-c", subprocess_script, temp_db_path],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Assert process succeeded without errors
            self.assertEqual(result.returncode, 0, f"Subprocess failed with stderr: {result.stderr}")
            self.assertIn("STEP_3_INITIAL_TABLES_COUNT=0", result.stdout)
            self.assertIn("STEP_4_RUNNING_MIGRATIONS", result.stdout)
            self.assertIn("STEP_5_COLLEGE_TABLE_CREATED_VERIFIED", result.stdout)
            self.assertIn("STEP_6_PREFLIGHT_FAILS_BEFORE_PROVISIONING_VERIFIED", result.stdout)
            self.assertIn("STEP_7_PROVISIONING_EXECUTED", result.stdout)
            self.assertIn("STEP_8_PREFLIGHT_SUCCEEDS_AFTER_PROVISIONING_VERIFIED", result.stdout)
            self.assertIn("STEP_9_SECONDARY_COLLEGE_INSERTED", result.stdout)
            self.assertIn("STEP_10_PREFLIGHT_FAILS_WITH_E003_VERIFIED", result.stdout)
            self.assertIn("SUBPROCESS_LIFECYCLE_SUCCESS", result.stdout)

        finally:
            # 11. Clean up the temporary database safely
            if os.path.exists(temp_db_path):
                os.remove(temp_db_path)

        # 12. Ensure the existing pytest database is untouched
        self.assertEqual(
            College.objects.count(),
            initial_pytest_college_count,
            "Pytest runner database was modified by isolated lifecycle test!",
        )


class StageB1ProvisionInstitutionCommandTests(TestCase):
    """
    Tests for provision_institution management command.
    """

    def test_09_idempotent_institution_provisioning(self):
        """
        Verifies that running provision_institution initializes the institution,
        and running it a second time is cleanly idempotent without duplicates.
        """
        self.assertEqual(College.objects.count(), 0)

        out1 = StringIO()
        call_command(
            "provision_institution",
            code="PDUAM-AMJONGA",
            name="Pandit Deendayal Upadhyaya Adarsha Mahavidyalaya",
            contact_email="admin@example.edu",
            contact_phone="+91-9876543210",
            address="Amjonga, Dudhnoi, Goalpara, Assam",
            stdout=out1,
        )
        self.assertEqual(College.objects.count(), 1)
        college = College.objects.get(code="PDUAM-AMJONGA")
        self.assertTrue(college.is_active)
        self.assertIn("Successfully provisioned", out1.getvalue())

        # Second execution with identical trusted name: idempotent verification
        out2 = StringIO()
        call_command(
            "provision_institution",
            code="PDUAM-AMJONGA",
            name="Pandit Deendayal Upadhyaya Adarsha Mahavidyalaya",
            contact_email="admin@example.edu",
            stdout=out2,
        )
        self.assertEqual(College.objects.count(), 1)
        self.assertIn("Verified existing active institution", out2.getvalue())

    def test_10_provisioning_rejection_when_foreign_college_records_exist(self):
        """Verifies that provisioning aborts if foreign college records exist in Table 9."""
        College.objects.create(
            name="Existing Other College",
            code="OTHER-COLLEGE",
            contact_email="other@example.edu",
            is_active=True,
        )
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "provision_institution",
                code="PDUAM-AMJONGA",
                name="PDUAM Amjonga",
                contact_email="admin@example.edu",
            )
        self.assertIn("Provisioning aborted", str(ctx.exception))
        self.assertIn("foreign college record(s)", str(ctx.exception))
        self.assertIn("OTHER-COLLEGE", str(ctx.exception))

    def test_13_provisioning_rejects_code_differing_from_settings(self):
        """Verifies that provisioning rejects any supplied code that differs from settings.INSTITUTION_CODE."""
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "provision_institution",
                code="WRONG-CODE",
                name="PDUAM Amjonga",
                contact_email="admin@example.edu",
            )
        self.assertIn("does not match configured INSTITUTION_CODE", str(ctx.exception))

    def test_14_provisioning_does_not_reactivate_inactive_institution(self):
        """
        Mandatory requirement: If an existing institution record is inactive,
        provisioning MUST abort and NOT automatically reactivate it.
        """
        College.objects.create(
            name="PDUAM Amjonga",
            code="PDUAM-AMJONGA",
            contact_email="admin@example.edu",
            is_active=False,
        )
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "provision_institution",
                code="PDUAM-AMJONGA",
                name="PDUAM Amjonga",
                contact_email="admin@example.edu",
            )
        self.assertIn("is deactivated", str(ctx.exception))
        self.assertIn("Automatic reactivation is prohibited", str(ctx.exception))

        # Confirm state was NOT altered
        college = College.objects.get(code="PDUAM-AMJONGA")
        self.assertFalse(college.is_active)

    def test_15_provisioning_handles_uniqueness_conflicts_safely(self):
        """
        Verifies that concurrent provisioning collisions resulting in IntegrityError
        are handled safely via transaction.atomic() rollback without breaking connection state.
        Note: Unit tests simulate concurrency via ORM mocking in SQLite; production MySQL
        enforces this via row-level unique index locking on academics_college.code.
        """
        committed_college = College.objects.create(
            code="PDUAM-AMJONGA",
            name="Pandit Deendayal Upadhyaya Adarsha Mahavidyalaya",
            contact_email="admin@example.edu",
            is_active=True,
        )

        filter_call_count = 0
        original_filter = College.objects.filter

        def mock_filter(*args, **kwargs):
            nonlocal filter_call_count
            filter_call_count += 1
            if filter_call_count == 1:
                # Step 5 initial check: simulate race window where record is not yet committed
                return original_filter(pk=-1)
            # Step 6 recovery check: return actual committed record
            return original_filter(*args, **kwargs)

        out = StringIO()
        with patch.object(College.objects, "filter", side_effect=mock_filter):
            with patch.object(College.objects, "create", side_effect=IntegrityError("Duplicate entry")):
                call_command(
                    "provision_institution",
                    code="PDUAM-AMJONGA",
                    name="Pandit Deendayal Upadhyaya Adarsha Mahavidyalaya",
                    contact_email="admin@example.edu",
                    stdout=out,
                )

        self.assertIn("Verified existing active institution", out.getvalue())
        self.assertIn("PDUAM-AMJONGA", out.getvalue())

    def test_16_ordinary_django_management_commands_remain_operational(self):
        """
        Verifies that Stage B1 system check registration does not break standard
        management commands (e.g. 'check', 'diffsettings').
        """
        # check without database argument executes without errors or DB queries
        out_check = StringIO()
        call_command("check", stdout=out_check)
        self.assertIn("System check identified no issues", out_check.getvalue())

        out_diff = StringIO()
        call_command("diffsettings", stdout=out_diff)
        self.assertIn("INSTITUTION_CODE", out_diff.getvalue())

    def test_17_provisioning_rejects_invalid_or_missing_information(self):
        """Verifies that provisioning rejects empty name or invalid email address."""
        # Empty name
        with self.assertRaises(CommandError) as ctx_name:
            call_command(
                "provision_institution",
                code="PDUAM-AMJONGA",
                name="   ",
                contact_email="admin@example.edu",
            )
        self.assertIn("Institution name cannot be empty", str(ctx_name.exception))

        # Invalid email
        with self.assertRaises(CommandError) as ctx_email:
            call_command(
                "provision_institution",
                code="PDUAM-AMJONGA",
                name="PDUAM Amjonga",
                contact_email="not-an-email",
            )
        self.assertIn("Invalid contact email", str(ctx_email.exception))

    def test_29_provisioning_rejects_name_mismatch_on_existing_institution(self):
        """
        Identity verification requirement: If an active institution already exists with the configured
        code, verify that its stored name agrees with the trusted name supplied for provisioning.
        Prevents silently accepting or overwriting unexpected identity mismatches.
        """
        College.objects.create(
            name="Pandit Deendayal Upadhyaya Adarsha Mahavidyalaya",
            code="PDUAM-AMJONGA",
            contact_email="admin@example.edu",
            is_active=True,
        )

        with self.assertRaises(CommandError) as ctx:
            call_command(
                "provision_institution",
                code="PDUAM-AMJONGA",
                name="Fraudulent College Name",
                contact_email="admin@example.edu",
            )
        self.assertIn("Institutional identity mismatch", str(ctx.exception))
        self.assertIn("Stored name 'Pandit Deendayal Upadhyaya Adarsha Mahavidyalaya'", str(ctx.exception))
        self.assertIn("Fraudulent College Name", str(ctx.exception))
        self.assertIn("Manual reconciliation is required", str(ctx.exception))

        # Confirm the existing record was NOT altered or overwritten
        stored = College.objects.get(code="PDUAM-AMJONGA")
        self.assertEqual(stored.name, "Pandit Deendayal Upadhyaya Adarsha Mahavidyalaya")

    def test_30_provisioning_rejects_code_exceeding_max_length_or_invalid_format(self):
        """Verifies that provisioning rejects institution codes exceeding 20 chars or containing invalid characters."""
        with self.assertRaises(CommandError) as ctx_len:
            call_command(
                "provision_institution",
                code="A" * 21,
                name="PDUAM Amjonga",
                contact_email="admin@example.edu",
            )
        self.assertIn("does not match configured INSTITUTION_CODE", str(ctx_len.exception))

        with override_settings(INSTITUTION_CODE="invalid-code"):
            with self.assertRaises(CommandError) as ctx_fmt:
                call_command(
                    "provision_institution",
                    code="invalid-code",
                    name="PDUAM Amjonga",
                    contact_email="admin@example.edu",
                )
            self.assertIn("contains invalid characters", str(ctx_fmt.exception))

    def test_31_provisioning_concurrency_rejects_name_mismatch_on_recovery(self):
        """Verifies that concurrent recovery path also validates identity against name mismatch."""
        College.objects.create(
            code="PDUAM-AMJONGA",
            name="Original Stored Name",
            contact_email="admin@example.edu",
            is_active=True,
        )

        filter_call_count = 0
        original_filter = College.objects.filter

        def mock_filter(*args, **kwargs):
            nonlocal filter_call_count
            filter_call_count += 1
            if filter_call_count == 1:
                return original_filter(pk=-1)
            return original_filter(*args, **kwargs)

        with patch.object(College.objects, "filter", side_effect=mock_filter):
            with patch.object(College.objects, "create", side_effect=IntegrityError("Duplicate entry")):
                with self.assertRaises(CommandError) as ctx:
                    call_command(
                        "provision_institution",
                        code="PDUAM-AMJONGA",
                        name="Attempted Different Name",
                        contact_email="admin@example.edu",
                    )
                self.assertIn("Institutional identity mismatch", str(ctx.exception))
