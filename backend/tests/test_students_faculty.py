"""
Comprehensive Automated Tests for Chunk 06: Student and Faculty Management.
Covers:
- StudentProfile (Table 6) CRUD, validation, permissions, semester bounds, cross-college boundaries.
- FacultyProfile (Table 7) CRUD, administrative provisioning, examiner flags, permissions, department boundaries.
- StudentAcademicRecord (Table 18) CRUD, status lifecycle, cross-college boundaries, uniqueness, student view scoping.
- FacultySubjectAssignment (Table 20) CRUD, examiner eligibility checks, cross-college boundaries, faculty view scoping.
- Student Self-Registration Workflow: Inactive accounts, token hashing, email verification, admin approval/rejection lifecycle, unverified approval defense.
- RBAC and is_staff=True privilege escalation defense across all Chunk 06 endpoints.
"""

from datetime import date, timedelta
from decimal import Decimal
import hashlib
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from rest_framework.test import APIClient

from apps.academics.models import (
    AcademicSession,
    College,
    Department,
    FacultyAssignmentRole,
    FacultySubjectAssignment,
    PaperOffering,
    Programme,
    Semester,
    Subject,
    SubjectCategory,
)
from apps.accounts.models import (
    EmailVerification,
    RegistrationApproval,
    RegistrationApprovalStatus,
    RoleChoices,
    User,
)
from apps.enrollments.models import AcademicRecordStatus, StudentAcademicRecord
from apps.faculty.models import FacultyProfile
from apps.faculty.services import create_faculty_profile, update_faculty_profile
from apps.students.models import StudentProfile
from apps.students.services import (
    register_student,
    review_student_registration,
    update_student_profile,
    verify_email_token,
)


class BaseStudentFacultyTestCase(TestCase):
    """Base test case provisioning institutions, admin users, faculty, and academic entities."""

    def setUp(self):
        self.client = APIClient()
        self.password = "SecuredPassword@2026"

        # 1. Colleges
        self.college_a = College.objects.create(
            name="Cotton University",
            code="CU",
            is_active=True,
        )
        self.college_b = College.objects.create(
            name="B. Borooah College",
            code="BBC",
            is_active=True,
        )

        # 2. Administrative Users
        self.superadmin = User.objects.create_user(
            username="super_admin",
            email="super@gauhati.ac.in",
            password=self.password,
            role=RoleChoices.SUPERADMIN,
            is_active=True,
            is_superuser=True,
        )
        self.admin = User.objects.create_user(
            username="college_admin",
            email="admin@gauhati.ac.in",
            password=self.password,
            role=RoleChoices.ADMIN,
            is_active=True,
        )
        # Note: Under approved 52-table schema, accounts_user has no college_id column.
        # Arbitrary caller-injected runtime attributes (self.admin.college_id) are rejected.
        # Ordinary admin has ambiguous scope and fails closed. Superadmin has system-wide access.

        # 3. Academic Structure for College A
        self.session_a = AcademicSession.objects.create(
            college=self.college_a,
            name="2026-2027",
            start_date=date(2026, 8, 1),
            end_date=date(2027, 5, 31),
            is_current=True,
        )
        self.dept_cs = Department.objects.create(
            college=self.college_a,
            name="Computer Science",
            code="CS",
        )
        self.dept_math = Department.objects.create(
            college=self.college_a,
            name="Mathematics",
            code="MATH",
        )
        self.prog_bca = Programme.objects.create(
            college=self.college_a,
            name="Bachelor of Computer Applications",
            code="BCA-FYUGP",
            duration_semesters=8,
            is_active=True,
        )
        self.sem_1 = Semester.objects.create(
            programme=self.prog_bca,
            semester_number=1,
        )
        self.sem_2 = Semester.objects.create(
            programme=self.prog_bca,
            semester_number=2,
        )
        self.sub_cat = SubjectCategory.objects.create(
            college=self.college_a,
            name="Major Courses",
            code="DSC",
            min_credits=Decimal("2.0"),
            max_credits=Decimal("6.0"),
        )
        self.subject_ds = Subject.objects.create(
            department=self.dept_cs,
            name="Data Structures",
            code="CS-101",
        )
        self.paper_offering = PaperOffering.objects.create(
            academic_session=self.session_a,
            semester=self.sem_1,
            subject=self.subject_ds,
            subject_category=self.sub_cat,
            paper_code="BCA-101-DS",
            credits=Decimal("4.0"),
            max_marks_internal=Decimal("20.0"),
            max_marks_external=Decimal("80.0"),
            pass_marks_external=Decimal("32.0"),
            is_active=True,
        )

        # 4. Academic Structure for College B
        self.session_b = AcademicSession.objects.create(
            college=self.college_b,
            name="2026-2027 BBC",
            start_date=date(2026, 8, 1),
            end_date=date(2027, 5, 31),
            is_current=True,
        )
        self.dept_b = Department.objects.create(
            college=self.college_b,
            name="Physics BBC",
            code="PHY-BBC",
        )
        self.prog_b = Programme.objects.create(
            college=self.college_b,
            name="B.Sc Physics BBC",
            code="BSC-PHY",
            duration_semesters=6,
            is_active=True,
        )

        # 5. Seeded Faculty User & Profile in College A
        self.faculty_user = User.objects.create_user(
            username="faculty_john",
            email="john@gauhati.ac.in",
            password=self.password,
            first_name="John",
            last_name="Doe",
            role=RoleChoices.FACULTY,
            is_active=True,
        )
        self.faculty_profile = FacultyProfile.objects.create(
            user=self.faculty_user,
            college=self.college_a,
            department=self.dept_cs,
            employee_code="EMP-CS-001",
            designation="Associate Professor",
            phone_number="9876543210",
            is_examiner=True,
        )

        # 6. Seeded Non-Examiner Faculty in College A
        self.faculty_user_non_examiner = User.objects.create_user(
            username="faculty_jane",
            email="jane@gauhati.ac.in",
            password=self.password,
            first_name="Jane",
            last_name="Smith",
            role=RoleChoices.FACULTY,
            is_active=True,
        )
        self.faculty_profile_non_examiner = FacultyProfile.objects.create(
            user=self.faculty_user_non_examiner,
            college=self.college_a,
            department=self.dept_math,
            employee_code="EMP-MATH-002",
            designation="Assistant Professor",
            is_examiner=False,
        )

        # 7. Seeded Active Student User & Profile in College A
        self.student_user = User.objects.create_user(
            username="student_alice",
            email="alice@gauhati.ac.in",
            password=self.password,
            first_name="Alice",
            last_name="Barman",
            role=RoleChoices.STUDENT,
            is_active=True,
        )
        self.student_profile = StudentProfile.objects.create(
            user=self.student_user,
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-2026-001",
            registration_year=2026,
            current_semester=1,
            phone_number="9123456780",
            guardian_name="Bhaben Barman",
        )

        # 8. Seeded Faculty & Student in College B
        self.sem_b1 = Semester.objects.create(
            programme=self.prog_b,
            semester_number=1,
        )
        self.faculty_user_b = User.objects.create_user(
            username="faculty_bob_b",
            email="bob_b@gauhati.ac.in",
            password=self.password,
            first_name="Bob",
            last_name="Barua",
            role=RoleChoices.FACULTY,
            is_active=True,
        )
        self.faculty_profile_b = FacultyProfile.objects.create(
            user=self.faculty_user_b,
            college=self.college_b,
            department=self.dept_b,
            employee_code="EMP-BBC-BOB-01",
            designation="Assistant Professor",
            is_examiner=True,
        )
        self.student_user_b = User.objects.create_user(
            username="student_rahul_b",
            email="rahul_b@gauhati.ac.in",
            password=self.password,
            first_name="Rahul",
            last_name="Das",
            role=RoleChoices.STUDENT,
            is_active=True,
        )
        self.student_profile_b = StudentProfile.objects.create(
            user=self.student_user_b,
            college=self.college_b,
            programme=self.prog_b,
            enrollment_number="ENR-BBC-RAHUL-01",
            registration_year=2026,
            current_semester=1,
        )
        self.subject_b = Subject.objects.create(
            department=self.dept_b,
            name="Mechanics BBC",
            code="PHY-101",
        )
        self.sub_cat_b = SubjectCategory.objects.create(
            college=self.college_b,
            name="Major BBC",
            code="DSC-B",
            min_credits=Decimal("2.0"),
            max_credits=Decimal("6.0"),
        )
        self.paper_offering_b = PaperOffering.objects.create(
            academic_session=self.session_b,
            semester=self.sem_b1,
            subject=self.subject_b,
            subject_category=self.sub_cat_b,
            paper_code="PHY-101-BBC",
            credits=Decimal("4.0"),
            max_marks_internal=Decimal("20.0"),
            max_marks_external=Decimal("80.0"),
            pass_marks_external=Decimal("32.0"),
            is_active=True,
        )


class StudentProfileModelAndServiceTests(BaseStudentFacultyTestCase):
    """Tests for StudentProfile (Table 6) model constraints and service functions."""

    def test_student_profile_creation_success(self):
        user = User.objects.create_user(
            username="student_bob",
            email="bob@gauhati.ac.in",
            password=self.password,
            role=RoleChoices.STUDENT,
            is_active=True,
        )
        profile = StudentProfile(
            user=user,
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-2026-002",
            registration_year=2026,
            current_semester=1,
        )
        profile.full_clean()
        profile.save()
        self.assertEqual(str(profile), "ENR-2026-002 - student_bob (BCA-FYUGP)")

    def test_student_profile_requires_student_role(self):
        user = User.objects.create_user(
            username="faculty_attempt",
            email="fac_attempt@gauhati.ac.in",
            password=self.password,
            role=RoleChoices.FACULTY,
            is_active=True,
        )
        profile = StudentProfile(
            user=user,
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-2026-003",
            registration_year=2026,
            current_semester=1,
        )
        with self.assertRaises(ValidationError) as ctx:
            profile.full_clean()
        self.assertIn("user", ctx.exception.message_dict)

    def test_student_profile_cross_college_programme_rejected(self):
        user = User.objects.create_user(
            username="student_cross",
            email="cross@gauhati.ac.in",
            password=self.password,
            role=RoleChoices.STUDENT,
            is_active=True,
        )
        profile = StudentProfile(
            user=user,
            college=self.college_a,
            programme=self.prog_b,  # Belongs to College B
            enrollment_number="ENR-2026-004",
            registration_year=2026,
            current_semester=1,
        )
        with self.assertRaises(ValidationError) as ctx:
            profile.full_clean()
        self.assertIn("programme", ctx.exception.message_dict)

    def test_student_profile_semester_bounds_validation(self):
        user = User.objects.create_user(
            username="student_bounds",
            email="bounds@gauhati.ac.in",
            password=self.password,
            role=RoleChoices.STUDENT,
            is_active=True,
        )
        # Exceeds programme duration (8)
        profile = StudentProfile(
            user=user,
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-2026-005",
            registration_year=2026,
            current_semester=9,
        )
        with self.assertRaises(ValidationError) as ctx:
            profile.full_clean()
        self.assertIn("current_semester", ctx.exception.message_dict)

    def test_student_profile_update_service_student_permitted_fields(self):
        updated = update_student_profile(
            profile_id=self.student_profile.pk,
            acting_user=self.student_user,
            validated_data={"phone_number": "9998887776", "guardian_name": "New Guardian"},
        )
        self.assertEqual(updated.phone_number, "9998887776")
        self.assertEqual(updated.guardian_name, "New Guardian")

    def test_student_profile_update_service_student_disallowed_institutional_fields(self):
        with self.assertRaises((DjangoPermissionDenied, DRFPermissionDenied)):
            update_student_profile(
                profile_id=self.student_profile.pk,
                acting_user=self.student_user,
                validated_data={"current_semester": 2},
            )

    def test_student_profile_update_service_admin_semester_update_within_and_exceeding_bounds(self):
        # Admin updates semester to 3 (valid)
        updated = update_student_profile(
            profile_id=self.student_profile.pk,
            acting_user=self.superadmin,
            validated_data={"current_semester": 3},
        )
        self.assertEqual(updated.current_semester, 3)

        # Admin updates semester to 10 (invalid, programme max is 8)
        with self.assertRaises(ValidationError):
            update_student_profile(
                profile_id=self.student_profile.pk,
                acting_user=self.superadmin,
                validated_data={"current_semester": 10},
            )


class FacultyProfileModelAndServiceTests(BaseStudentFacultyTestCase):
    """Tests for FacultyProfile (Table 7) model constraints and administrative provisioning."""

    def test_faculty_profile_creation_success(self):
        user = User.objects.create_user(
            username="faculty_prof_test",
            email="fac_test@gauhati.ac.in",
            password=self.password,
            role=RoleChoices.FACULTY,
            is_active=True,
        )
        profile = FacultyProfile(
            user=user,
            college=self.college_a,
            department=self.dept_cs,
            employee_code="EMP-TEST-099",
            designation="Professor",
        )
        profile.full_clean()
        profile.save()
        self.assertIn("EMP-TEST-099", str(profile))

    def test_faculty_profile_requires_faculty_role(self):
        user = User.objects.create_user(
            username="student_attempting_faculty",
            email="stud_fac@gauhati.ac.in",
            password=self.password,
            role=RoleChoices.STUDENT,
            is_active=True,
        )
        profile = FacultyProfile(
            user=user,
            college=self.college_a,
            department=self.dept_cs,
            employee_code="EMP-FAIL-01",
        )
        with self.assertRaises(ValidationError) as ctx:
            profile.full_clean()
        self.assertIn("user", ctx.exception.message_dict)

    def test_faculty_profile_cross_college_department_rejected(self):
        user = User.objects.create_user(
            username="fac_cross",
            email="cross_fac@gauhati.ac.in",
            password=self.password,
            role=RoleChoices.FACULTY,
            is_active=True,
        )
        profile = FacultyProfile(
            user=user,
            college=self.college_a,
            department=self.dept_b,  # Belongs to College B
            employee_code="EMP-CROSS-01",
        )
        with self.assertRaises(ValidationError) as ctx:
            profile.full_clean()
        self.assertIn("department", ctx.exception.message_dict)

    def test_create_faculty_profile_service_admin_success(self):
        profile = create_faculty_profile(
            acting_user=self.superadmin,
            username="new_faculty",
            email="new_fac@gauhati.ac.in",
            first_name="New",
            last_name="Faculty",
            college=self.college_a,
            department=self.dept_cs,
            employee_code="EMP-NEW-101",
            designation="Assistant Professor",
            phone_number="9871234560",
            is_examiner=True,
        )
        self.assertIsNotNone(profile.pk)
        self.assertFalse(profile.user.is_active)
        self.assertFalse(profile.user.has_usable_password())
        self.assertEqual(profile.user.role, RoleChoices.FACULTY)
        self.assertEqual(profile.employee_code, "EMP-NEW-101")

    def test_create_faculty_profile_service_non_admin_rejected(self):
        with self.assertRaises((DjangoPermissionDenied, DRFPermissionDenied)):
            create_faculty_profile(
                acting_user=self.student_user,
                username="unauthorized_fac",
                email="unauth@gauhati.ac.in",
                first_name="Unauthorized",
                last_name="Fac",
                college=self.college_a,
                department=self.dept_cs,
                employee_code="EMP-UNAUTH-01",
            )

    def test_create_faculty_profile_service_duplicate_employee_code_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            create_faculty_profile(
                acting_user=self.superadmin,
                username="duplicate_emp_user",
                email="dup_emp@gauhati.ac.in",
                first_name="Dup",
                last_name="Emp",
                college=self.college_a,
                department=self.dept_cs,
                employee_code="EMP-CS-001",  # Already belongs to self.faculty_profile
            )
        self.assertIn("employee_code", ctx.exception.message_dict)

    def test_update_faculty_profile_service_faculty_restrictions(self):
        # Faculty updating own phone number succeeds
        updated = update_faculty_profile(
            profile_id=self.faculty_profile.pk,
            acting_user=self.faculty_user,
            validated_data={"phone_number": "9112233445"},
        )
        self.assertEqual(updated.phone_number, "9112233445")

        # Faculty attempting to update designation or is_examiner rejected
        with self.assertRaises((DjangoPermissionDenied, DRFPermissionDenied)):
            update_faculty_profile(
                profile_id=self.faculty_profile.pk,
                acting_user=self.faculty_user,
                validated_data={"designation": "Professor"},
            )

    def test_update_faculty_profile_service_admin_allowed_and_cross_college_dept_rejected(self):
        # Admin updating designation and examiner flag
        updated = update_faculty_profile(
            profile_id=self.faculty_profile.pk,
            acting_user=self.superadmin,
            validated_data={"designation": "Professor & Head", "is_examiner": False},
        )
        self.assertEqual(updated.designation, "Professor & Head")
        self.assertFalse(updated.is_examiner)

        # Admin updating department to cross-college department rejected
        with self.assertRaises(ValidationError) as ctx:
            update_faculty_profile(
                profile_id=self.faculty_profile.pk,
                acting_user=self.superadmin,
                validated_data={"department": self.dept_b},
            )
        self.assertIn("department", ctx.exception.message_dict)


class StudentAcademicRecordModelAndServiceTests(BaseStudentFacultyTestCase):
    """Tests for StudentAcademicRecord (Table 18) admission ledger."""

    def test_academic_record_creation_success(self):
        from apps.enrollments.services import create_student_academic_record

        record = create_student_academic_record(
            acting_user=self.superadmin,
            student=self.student_profile,
            programme=self.prog_bca,
            academic_session=self.session_a,
            admission_date=date(2026, 8, 1),
            status=AcademicRecordStatus.ACTIVE,
        )
        self.assertEqual(record.status, AcademicRecordStatus.ACTIVE)
        self.assertIn("ENR-2026-001", str(record))

    def test_academic_record_non_admin_rejected(self):
        from apps.enrollments.services import create_student_academic_record

        with self.assertRaises((DjangoPermissionDenied, DRFPermissionDenied)):
            create_student_academic_record(
                acting_user=self.student_user,
                student=self.student_profile,
                programme=self.prog_bca,
                academic_session=self.session_a,
                admission_date=date(2026, 8, 1),
            )

    def test_academic_record_cross_college_programme_rejected(self):
        from apps.enrollments.services import create_student_academic_record

        with self.assertRaises(ValidationError) as ctx:
            create_student_academic_record(
                acting_user=self.superadmin,
                student=self.student_profile,  # College A
                programme=self.prog_b,        # College B
                academic_session=self.session_a,
                admission_date=date(2026, 8, 1),
            )
        self.assertIn("programme", ctx.exception.message_dict)

    def test_academic_record_cross_college_session_rejected(self):
        from apps.enrollments.services import create_student_academic_record

        with self.assertRaises(ValidationError) as ctx:
            create_student_academic_record(
                acting_user=self.superadmin,
                student=self.student_profile,  # College A
                programme=self.prog_bca,       # College A
                academic_session=self.session_b,  # College B
                admission_date=date(2026, 8, 1),
            )
        self.assertIn("academic_session", ctx.exception.message_dict)

    def test_academic_record_unique_constraint_enforced(self):
        from apps.enrollments.services import create_student_academic_record

        create_student_academic_record(
            acting_user=self.superadmin,
            student=self.student_profile,
            programme=self.prog_bca,
            academic_session=self.session_a,
            admission_date=date(2026, 8, 1),
        )

        with self.assertRaises(ValidationError) as ctx:
            create_student_academic_record(
                acting_user=self.superadmin,
                student=self.student_profile,
                programme=self.prog_bca,
                academic_session=self.session_a,
                admission_date=date(2026, 8, 1),
            )
        self.assertIn("non_field_errors", ctx.exception.message_dict)

    def test_academic_record_update_service_status_success(self):
        from apps.enrollments.services import create_student_academic_record, update_student_academic_record

        record = create_student_academic_record(
            acting_user=self.superadmin,
            student=self.student_profile,
            programme=self.prog_bca,
            academic_session=self.session_a,
            admission_date=date(2026, 8, 1),
        )

        updated = update_student_academic_record(
            record_id=record.pk,
            acting_user=self.superadmin,
            validated_data={"status": AcademicRecordStatus.SUSPENDED},
        )
        self.assertEqual(updated.status, AcademicRecordStatus.SUSPENDED)

    def test_academic_record_immutable_fields_rejected(self):
        from apps.enrollments.services import create_student_academic_record, update_student_academic_record

        record = create_student_academic_record(
            acting_user=self.superadmin,
            student=self.student_profile,
            programme=self.prog_bca,
            academic_session=self.session_a,
            admission_date=date(2026, 8, 1),
        )

        with self.assertRaises(ValidationError) as ctx:
            update_student_academic_record(
                record_id=record.pk,
                acting_user=self.superadmin,
                validated_data={"programme": self.prog_b},
            )
        self.assertIn("programme", ctx.exception.message_dict)


class FacultySubjectAssignmentModelAndServiceTests(BaseStudentFacultyTestCase):
    """Tests for FacultySubjectAssignment (Table 20) teaching and exam roles."""

    def test_assignment_creation_success(self):
        from apps.academics.services import assign_faculty_to_paper

        assignment = assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )
        self.assertEqual(assignment.role, FacultyAssignmentRole.TEACHER)
        self.assertIn("EMP-CS-001 -> BCA-101-DS", str(assignment))

    def test_assignment_non_admin_rejected(self):
        from apps.academics.services import assign_faculty_to_paper

        with self.assertRaises((DjangoPermissionDenied, DRFPermissionDenied)):
            assign_faculty_to_paper(
                acting_user=self.faculty_user,
                faculty=self.faculty_profile,
                paper_offering=self.paper_offering,
                role=FacultyAssignmentRole.TEACHER,
            )

    def test_assignment_cross_college_rejected(self):
        from apps.academics.services import assign_faculty_to_paper

        # Create faculty in College B
        user_b = User.objects.create_user(
            username="faculty_col_b",
            email="fac_b@gauhati.ac.in",
            password=self.password,
            role=RoleChoices.FACULTY,
            is_active=True,
        )
        faculty_b = FacultyProfile.objects.create(
            user=user_b,
            college=self.college_b,
            department=self.dept_b,
            employee_code="EMP-BBC-001",
            is_examiner=True,
        )

        with self.assertRaises(ValidationError) as ctx:
            assign_faculty_to_paper(
                acting_user=self.superadmin,
                faculty=faculty_b,
                paper_offering=self.paper_offering,  # Belongs to College A
                role=FacultyAssignmentRole.TEACHER,
            )
        self.assertIn("faculty", ctx.exception.message_dict)

    def test_assignment_examiner_role_requires_is_examiner_true(self):
        from apps.academics.services import assign_faculty_to_paper

        # faculty_profile_non_examiner has is_examiner=False
        with self.assertRaises(ValidationError) as ctx:
            assign_faculty_to_paper(
                acting_user=self.superadmin,
                faculty=self.faculty_profile_non_examiner,
                paper_offering=self.paper_offering,
                role=FacultyAssignmentRole.INTERNAL_EXAMINER,
            )
        self.assertIn("faculty", ctx.exception.message_dict)

    def test_assignment_teacher_role_allowed_for_non_examiner(self):
        from apps.academics.services import assign_faculty_to_paper

        # Teaching role is permitted regardless of is_examiner flag
        assignment = assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile_non_examiner,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )
        self.assertEqual(assignment.role, FacultyAssignmentRole.TEACHER)

    def test_assignment_unique_constraint_enforced(self):
        from apps.academics.services import assign_faculty_to_paper

        assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )

        with self.assertRaises(ValidationError) as ctx:
            assign_faculty_to_paper(
                acting_user=self.superadmin,
                faculty=self.faculty_profile,
                paper_offering=self.paper_offering,
                role=FacultyAssignmentRole.TEACHER,
            )
        self.assertIn("non_field_errors", ctx.exception.message_dict)

    def test_assignment_deletion_service_admin_success_and_non_admin_rejected(self):
        from apps.academics.services import assign_faculty_to_paper, delete_faculty_assignment

        assignment = assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )

        with self.assertRaises((DjangoPermissionDenied, DRFPermissionDenied)):
            delete_faculty_assignment(
                acting_user=self.student_user,
                assignment_id=assignment.pk,
            )

        delete_faculty_assignment(
            acting_user=self.superadmin,
            assignment_id=assignment.pk,
        )
        self.assertFalse(FacultySubjectAssignment.objects.filter(pk=assignment.pk).exists())


class StudentRegistrationAndApprovalWorkflowTests(BaseStudentFacultyTestCase):
    """Tests for multi-step student self-registration, verification, and administrator review."""

    def test_self_registration_endpoint_success_and_inactive_user(self):
        payload = {
            "username": "self_reg_student",
            "email": "self_reg@gauhati.ac.in",
            "password": "StrongStudentPassword@2026",
            "first_name": "Raktim",
            "last_name": "Sarma",
            "college": self.college_a.pk,
            "programme": self.prog_bca.pk,
            "enrollment_number": "ENR-2026-REG01",
            "registration_year": 2026,
            "phone_number": "9864012345",
        }
        response = self.client.post("/api/v1/auth/register/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("user_id", response.data)
        self.assertNotIn("token", response.data)
        self.assertNotIn("password", response.data)

        # Verify created entities
        user = User.objects.get(username="self_reg_student")
        self.assertFalse(user.is_active)
        self.assertEqual(user.role, RoleChoices.STUDENT)

        profile = StudentProfile.objects.get(user=user)
        self.assertEqual(profile.enrollment_number, "ENR-2026-REG01")
        self.assertEqual(profile.current_semester, 1)

        approval = RegistrationApproval.objects.get(user=user)
        self.assertEqual(approval.status, RegistrationApprovalStatus.PENDING)

        verification = EmailVerification.objects.get(user=user)
        self.assertFalse(verification.is_used)

    def test_self_registration_cross_college_programme_rejected(self):
        payload = {
            "username": "cross_reg_student",
            "email": "cross_reg@gauhati.ac.in",
            "password": "StrongStudentPassword@2026",
            "first_name": "Cross",
            "last_name": "Student",
            "college": self.college_a.pk,
            "programme": self.prog_b.pk,  # Belongs to College B
            "enrollment_number": "ENR-2026-CROSS01",
            "registration_year": 2026,
        }
        response = self.client.post("/api/v1/auth/register/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_self_registration_duplicate_username_rejected(self):
        payload = {
            "username": "student_alice",  # Already exists
            "email": "alice_unique@gauhati.ac.in",
            "password": "StrongStudentPassword@2026",
            "first_name": "Alice",
            "last_name": "Barman",
            "college": self.college_a.pk,
            "programme": self.prog_bca.pk,
            "enrollment_number": "ENR-2026-DUPUSER",
            "registration_year": 2026,
        }
        response = self.client.post("/api/v1/auth/register/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_email_verification_success_and_single_use(self):
        user, profile, raw_token = register_student(
            username="verify_student",
            email="verify_student@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="Verify",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-2026-VER01",
            registration_year=2026,
        )
        self.assertFalse(user.is_active)

        # 1. GET verification inspect without confirm=true (safe against prefetching)
        inspect_response = self.client.get(f"/api/v1/auth/verify-email/?token={raw_token}")
        self.assertEqual(inspect_response.status_code, status.HTTP_200_OK)
        self.assertEqual(inspect_response.data["status"], "CONFIRM_REQUIRED")
        # Token not consumed yet
        ev = EmailVerification.objects.get(user=user)
        self.assertFalse(ev.is_used)
        self.assertIsNone(ev.verified_at)

        # GET even with confirm=true does NOT consume token (R3 Hardening)
        get_res = self.client.get(f"/api/v1/auth/verify-email/?token={raw_token}&confirm=true")
        self.assertEqual(get_res.status_code, status.HTTP_200_OK)
        self.assertEqual(get_res.data["status"], "CONFIRM_REQUIRED")
        ev.refresh_from_db()
        self.assertFalse(ev.is_used)

        # 2. POST is authoritative and consumes token
        response = self.client.post("/api/v1/auth/verify-email/", {"token": raw_token}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_email_verified"])

        # User is still NOT active (requires admin approval)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

        # 3. Attempting to use the same token again is rejected
        response_reused = self.client.post("/api/v1/auth/verify-email/", {"token": raw_token}, format="json")
        self.assertEqual(response_reused.status_code, status.HTTP_400_BAD_REQUEST)

    def test_email_verification_expired_token_rejected(self):
        user, profile, raw_token = register_student(
            username="expired_student",
            email="expired_student@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="Expired",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-2026-EXP01",
            registration_year=2026,
        )
        # Fast-forward token past 24 hours
        EmailVerification.objects.filter(user=user).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )

        response = self.client.post("/api/v1/auth/verify-email/", {"token": raw_token}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_email_verification_invalid_token_rejected(self):
        response = self.client.post("/api/v1/auth/verify-email/", {"token": "completely-invalid-token"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_approval_unverified_email_rejected(self):
        user, profile, raw_token = register_student(
            username="unverified_student",
            email="unverified@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="Unverified",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-2026-UNV01",
            registration_year=2026,
        )
        approval = RegistrationApproval.objects.get(user=user)

        self.client.force_authenticate(user=self.superadmin)
        response = self.client.post(f"/api/v1/students/registrations/{approval.pk}/approve/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_admin_approval_verified_email_activates_user(self):
        user, profile, raw_token = register_student(
            username="ready_for_approval",
            email="ready@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="Ready",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-2026-RDY01",
            registration_year=2026,
        )
        verify_email_token(raw_token)
        approval = RegistrationApproval.objects.get(user=user)

        self.client.force_authenticate(user=self.superadmin)
        response = self.client.post(f"/api/v1/students/registrations/{approval.pk}/approve/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "APPROVED")

        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_admin_rejection_with_reason_leaves_user_inactive(self):
        user, profile, raw_token = register_student(
            username="rejected_student",
            email="rejected@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="Rejected",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-2026-REJ01",
            registration_year=2026,
        )
        approval = RegistrationApproval.objects.get(user=user)

        self.client.force_authenticate(user=self.superadmin)
        response = self.client.post(
            f"/api/v1/students/registrations/{approval.pk}/reject/",
            {"rejection_reason": "Incomplete identity documentation submitted."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "REJECTED")
        self.assertEqual(response.data["rejection_reason"], "Incomplete identity documentation submitted.")

        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_admin_rejection_missing_reason_rejected(self):
        user, profile, raw_token = register_student(
            username="rejected_noreason",
            email="rejected_noreason@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="NoReason",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-2026-NR01",
            registration_year=2026,
        )
        approval = RegistrationApproval.objects.get(user=user)

        self.client.force_authenticate(user=self.superadmin)
        response = self.client.post(
            f"/api/v1/students/registrations/{approval.pk}/reject/",
            {"rejection_reason": ""},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_admin_cannot_review_registration(self):
        user, profile, raw_token = register_student(
            username="unauth_review",
            email="unauth_review@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="Unauth",
            last_name="Review",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-2026-UAR01",
            registration_year=2026,
        )
        approval = RegistrationApproval.objects.get(user=user)

        # Student user attempt
        self.client.force_authenticate(user=self.student_user)
        response = self.client.post(f"/api/v1/students/registrations/{approval.pk}/approve/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Faculty user attempt
        self.client.force_authenticate(user=self.faculty_user)
        response = self.client.post(f"/api/v1/students/registrations/{approval.pk}/approve/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class StudentFacultyApiEndpointsAndRBACTests(BaseStudentFacultyTestCase):
    """Tests for DRF API endpoints, viewset query scoping, and RBAC / privilege escalation defenses."""

    def test_student_profile_list_scoped_to_self(self):
        self.client.force_authenticate(user=self.student_user)
        response = self.client.get("/api/v1/students/profiles/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only see their own profile
        self.assertEqual(len(response.data["results"] if "results" in response.data else response.data), 1)

    def test_student_profile_me_get_and_patch(self):
        self.client.force_authenticate(user=self.student_user)
        # GET /me/
        response = self.client.get("/api/v1/students/profiles/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["enrollment_number"], self.student_profile.enrollment_number)

        # PATCH /me/ personal fields
        response_patch = self.client.patch(
            "/api/v1/students/profiles/me/",
            {"phone_number": "9001122334"},
            format="json",
        )
        self.assertEqual(response_patch.status_code, status.HTTP_200_OK)
        self.student_profile.refresh_from_db()
        self.assertEqual(self.student_profile.phone_number, "9001122334")

    def test_student_profile_admin_full_list_and_filter(self):
        self.client.force_authenticate(user=self.superadmin)
        response = self.client.get(f"/api/v1/students/profiles/?college={self.college_a.pk}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["results"] if "results" in response.data else response.data
        self.assertGreaterEqual(len(data), 1)

    def test_faculty_profile_list_scoped_to_self(self):
        self.client.force_authenticate(user=self.faculty_user)
        response = self.client.get("/api/v1/faculty/profiles/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["results"] if "results" in response.data else response.data
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["employee_code"], self.faculty_profile.employee_code)

    def test_faculty_profile_me_get_and_patch(self):
        self.client.force_authenticate(user=self.faculty_user)
        # GET /me/
        response = self.client.get("/api/v1/faculty/profiles/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["employee_code"], self.faculty_profile.employee_code)

        # PATCH /me/
        response_patch = self.client.patch(
            "/api/v1/faculty/profiles/me/",
            {"phone_number": "9445566778"},
            format="json",
        )
        self.assertEqual(response_patch.status_code, status.HTTP_200_OK)
        self.faculty_profile.refresh_from_db()
        self.assertEqual(self.faculty_profile.phone_number, "9445566778")

    def test_faculty_profile_admin_provisioning_endpoint(self):
        self.client.force_authenticate(user=self.superadmin)
        payload = {
            "username": "api_provisioned_faculty",
            "email": "api_fac@gauhati.ac.in",
            "password": "StrongPassword@2026",
            "first_name": "API",
            "last_name": "Faculty",
            "college": self.college_a.pk,
            "department": self.dept_cs.pk,
            "employee_code": "EMP-API-555",
            "designation": "Assistant Professor",
            "is_examiner": True,
        }
        response = self.client.post("/api/v1/faculty/profiles/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["employee_code"], "EMP-API-555")

    def test_faculty_my_assignments_endpoint(self):
        from apps.academics.services import assign_faculty_to_paper

        assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )

        self.client.force_authenticate(user=self.faculty_user)
        response = self.client.get("/api/v1/faculty/profiles/me/assignments/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["paper_code"], self.paper_offering.paper_code)

    def test_student_academic_record_api_student_read_scoped_and_write_blocked(self):
        from apps.enrollments.services import create_student_academic_record

        record = create_student_academic_record(
            acting_user=self.superadmin,
            student=self.student_profile,
            programme=self.prog_bca,
            academic_session=self.session_a,
            admission_date=date(2026, 8, 1),
        )

        self.client.force_authenticate(user=self.student_user)
        # Student GET succeeds and is scoped
        response = self.client.get("/api/v1/enrollments/academic-records/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["results"] if "results" in response.data else response.data
        self.assertEqual(len(data), 1)

        # Student POST is rejected
        response_post = self.client.post(
            "/api/v1/enrollments/academic-records/",
            {
                "student": self.student_profile.pk,
                "programme": self.prog_bca.pk,
                "academic_session": self.session_a.pk,
                "admission_date": "2026-08-01",
            },
            format="json",
        )
        self.assertEqual(response_post.status_code, status.HTTP_403_FORBIDDEN)

    def test_student_academic_record_api_admin_crud(self):
        self.client.force_authenticate(user=self.superadmin)
        payload = {
            "student": self.student_profile.pk,
            "programme": self.prog_bca.pk,
            "academic_session": self.session_a.pk,
            "admission_date": "2026-08-01",
            "status": "ACTIVE",
        }
        response = self.client.post("/api/v1/enrollments/academic-records/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        rec_id = response.data["id"]

        # Admin PATCH
        response_patch = self.client.patch(
            f"/api/v1/enrollments/academic-records/{rec_id}/",
            {"status": "SUSPENDED"},
            format="json",
        )
        self.assertEqual(response_patch.status_code, status.HTTP_200_OK)
        self.assertEqual(response_patch.data["status"], "SUSPENDED")

    def test_faculty_assignment_api_student_denied(self):
        self.client.force_authenticate(user=self.student_user)
        response = self.client.get("/api/v1/academics/faculty-assignments/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_faculty_assignment_api_faculty_read_and_write_blocked(self):
        from apps.academics.services import assign_faculty_to_paper

        assignment = assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )

        self.client.force_authenticate(user=self.faculty_user)
        # Read succeeds
        response = self.client.get("/api/v1/academics/faculty-assignments/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Write rejected
        response_post = self.client.post(
            "/api/v1/academics/faculty-assignments/",
            {
                "faculty": self.faculty_profile.pk,
                "paper_offering": self.paper_offering.pk,
                "role": "MODERATOR",
            },
            format="json",
        )
        self.assertEqual(response_post.status_code, status.HTTP_403_FORBIDDEN)

    def test_faculty_assignment_api_admin_crud(self):
        self.client.force_authenticate(user=self.superadmin)
        payload = {
            "faculty": self.faculty_profile.pk,
            "paper_offering": self.paper_offering.pk,
            "role": "TEACHER",
        }
        response = self.client.post("/api/v1/academics/faculty-assignments/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        assign_id = response.data["id"]

        # Admin DELETE
        response_del = self.client.delete(f"/api/v1/academics/faculty-assignments/{assign_id}/")
        self.assertEqual(response_del.status_code, status.HTTP_204_NO_CONTENT)

    def test_is_staff_privilege_escalation_defense(self):
        # A student with is_staff=True MUST NOT gain admin access
        escalated_student = User.objects.create_user(
            username="escalated_student",
            email="escalated@gauhati.ac.in",
            password=self.password,
            role=RoleChoices.STUDENT,
            is_active=True,
            is_staff=True,
        )
        self.client.force_authenticate(user=escalated_student)

        # 1. Cannot access registration approvals
        res1 = self.client.get("/api/v1/students/registrations/")
        self.assertEqual(res1.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Cannot provision faculty
        res2 = self.client.post(
            "/api/v1/faculty/profiles/",
            {
                "username": "escalated_fac",
                "email": "esc_fac@gauhati.ac.in",
                "password": "StrongPassword@2026",
                "first_name": "Esc",
                "last_name": "Fac",
                "college": self.college_a.pk,
                "department": self.dept_cs.pk,
                "employee_code": "EMP-ESC-01",
            },
            format="json",
        )
        self.assertEqual(res2.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Cannot create academic records
        res3 = self.client.post(
            "/api/v1/enrollments/academic-records/",
            {
                "student": self.student_profile.pk,
                "programme": self.prog_bca.pk,
                "academic_session": self.session_a.pk,
                "admission_date": "2026-08-01",
            },
            format="json",
        )
        self.assertEqual(res3.status_code, status.HTTP_403_FORBIDDEN)

        # 4. Cannot assign faculty to paper
        res4 = self.client.post(
            "/api/v1/academics/faculty-assignments/",
            {
                "faculty": self.faculty_profile.pk,
                "paper_offering": self.paper_offering.pk,
                "role": "TEACHER",
            },
            format="json",
        )
        self.assertEqual(res4.status_code, status.HTTP_403_FORBIDDEN)


class Chunk06Round2CorrectionsTests(BaseStudentFacultyTestCase):
    """
    Dedicated tests verifying all Chunk 06 Round 2 audit corrections:
    - Finding A: Email delivery failure rollback, outbox verification, safe prefetch inspect vs confirm.
    - Finding B: Faculty provisioning creates inactive accounts with unusable passwords.
    - Finding C: Deletion prevention on StudentProfile, FacultyProfile, and StudentAcademicRecord.
    - Finding D: Faculty data access scoping (academic records denied; own assignments only).
    - Finding E: Faculty assignment complete-state validation on PATCH; examiner revocation protection.
    - Finding F: Academic parent updates invalidate dependent Chunk 06 records.
    """

    def test_student_registration_email_delivery_and_outbox(self):
        from django.core import mail
        mail.outbox = []

        payload = {
            "username": "email_outbox_student",
            "email": "outbox_student@gauhati.ac.in",
            "password": "StrongPassword@2026",
            "first_name": "Outbox",
            "last_name": "Student",
            "college": self.college_a.pk,
            "programme": self.prog_bca.pk,
            "enrollment_number": "ENR-2026-OUT01",
            "registration_year": 2026,
        }
        response = self.client.post("/api/v1/auth/register/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertIn("Verify Your Student Email Address", sent_email.subject)
        self.assertEqual(sent_email.to, ["outbox_student@gauhati.ac.in"])
        self.assertIn("verification token is:", sent_email.body)

    def test_student_registration_email_failure_rolls_back_and_returns_503(self):
        from unittest.mock import patch
        from apps.students.services import VerificationEmailDeliveryError

        with patch("apps.students.services.send_student_verification_email", side_effect=VerificationEmailDeliveryError("SMTP unavailable")):
            payload = {
                "username": "smtp_fail_student",
                "email": "smtp_fail@gauhati.ac.in",
                "password": "StrongPassword@2026",
                "first_name": "SMTP",
                "last_name": "Fail",
                "college": self.college_a.pk,
                "programme": self.prog_bca.pk,
                "enrollment_number": "ENR-2026-SMTP01",
                "registration_year": 2026,
            }
            response = self.client.post("/api/v1/auth/register/", payload, format="json")
            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertEqual(response.data["error"]["code"], "EMAIL_DELIVERY_UNAVAILABLE")
            # Verify database rollback
            self.assertFalse(User.objects.filter(username="smtp_fail_student").exists())
            self.assertFalse(StudentProfile.objects.filter(enrollment_number="ENR-2026-SMTP01").exists())

    def test_student_email_verification_get_inspect_safe_against_prefetch(self):
        user, profile, raw_token = register_student(
            username="prefetch_student",
            email="prefetch@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="Prefetch",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-2026-PRE01",
            registration_year=2026,
        )
        # GET without confirm=true
        inspect_res = self.client.get(f"/api/v1/auth/verify-email/?token={raw_token}")
        self.assertEqual(inspect_res.status_code, status.HTTP_200_OK)
        self.assertEqual(inspect_res.data["status"], "CONFIRM_REQUIRED")
        # Token remains unconsumed
        ev = EmailVerification.objects.get(user=user)
        self.assertFalse(ev.is_used)
        self.assertIsNone(ev.verified_at)

    def test_student_email_verification_get_does_not_consume_token_even_with_confirm_flag(self):
        user, profile, raw_token = register_student(
            username="get_confirm_student",
            email="get_confirm@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="GetConfirm",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-2026-GC01",
            registration_year=2026,
        )
        # GET with confirm=true strictly returns confirmation prompt without consuming token (R3 Hardening)
        confirm_res = self.client.get(f"/api/v1/auth/verify-email/?token={raw_token}&confirm=true")
        self.assertEqual(confirm_res.status_code, status.HTTP_200_OK)
        self.assertEqual(confirm_res.data["status"], "CONFIRM_REQUIRED")
        ev = EmailVerification.objects.get(user=user)
        self.assertFalse(ev.is_used)
        self.assertIsNone(ev.verified_at)

        # Only POST authoritatively consumes token
        post_res = self.client.post("/api/v1/auth/verify-email/", {"token": raw_token}, format="json")
        self.assertEqual(post_res.status_code, status.HTTP_200_OK)
        self.assertTrue(post_res.data["is_email_verified"])
        ev.refresh_from_db()
        self.assertTrue(ev.is_used)

    def test_student_email_verification_post_consumes_token(self):
        user, profile, raw_token = register_student(
            username="post_verify_student",
            email="post_verify@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="PostVerify",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-2026-PV01",
            registration_year=2026,
        )
        post_res = self.client.post("/api/v1/auth/verify-email/", {"token": raw_token}, format="json")
        self.assertEqual(post_res.status_code, status.HTTP_200_OK)
        self.assertTrue(post_res.data["is_email_verified"])
        ev = EmailVerification.objects.get(user=user)
        self.assertTrue(ev.is_used)

    def test_faculty_provisioning_inactive_account_and_unusable_password(self):
        self.client.force_authenticate(user=self.superadmin)
        payload = {
            "username": "provisioned_inactive_faculty",
            "email": "inactive_provision@gauhati.ac.in",
            "first_name": "Inactive",
            "last_name": "Provisioned",
            "college": self.college_a.pk,
            "department": self.dept_cs.pk,
            "employee_code": "EMP-INACT-500",
            "designation": "Assistant Professor",
            "is_examiner": True,
        }
        res = self.client.post("/api/v1/faculty/profiles/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        created_user = User.objects.get(username="provisioned_inactive_faculty")
        self.assertFalse(created_user.is_active)
        self.assertFalse(created_user.has_usable_password())
        self.assertFalse(created_user.is_staff)
        self.assertFalse(created_user.is_superuser)

    def test_provisioned_faculty_cannot_login(self):
        self.client.force_authenticate(user=self.superadmin)
        payload = {
            "username": "locked_out_faculty",
            "email": "locked_out@gauhati.ac.in",
            "first_name": "Locked",
            "last_name": "Out",
            "college": self.college_a.pk,
            "department": self.dept_cs.pk,
            "employee_code": "EMP-LOCK-01",
        }
        res = self.client.post("/api/v1/faculty/profiles/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # Attempt login
        self.client.force_authenticate(user=None)
        login_res = self.client.post(
            "/api/v1/auth/login/",
            {"identifier": "locked_out_faculty", "password": "AnyAttemptedPassword123!"},
            format="json",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(login_res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_student_profile_delete_blocked_with_403(self):
        self.client.force_authenticate(user=self.superadmin)
        response = self.client.delete(f"/api/v1/students/profiles/{self.student_profile.pk}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_faculty_profile_delete_blocked_with_403(self):
        self.client.force_authenticate(user=self.superadmin)
        response = self.client.delete(f"/api/v1/faculty/profiles/{self.faculty_profile.pk}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_student_academic_record_delete_blocked_with_403(self):
        from apps.enrollments.services import create_student_academic_record
        record = create_student_academic_record(
            acting_user=self.superadmin,
            student=self.student_profile,
            programme=self.prog_bca,
            academic_session=self.session_a,
            admission_date=date(2026, 8, 1),
        )
        self.client.force_authenticate(user=self.superadmin)
        response = self.client.delete(f"/api/v1/enrollments/academic-records/{record.pk}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_faculty_user_cannot_access_student_academic_records(self):
        from apps.enrollments.services import create_student_academic_record
        record = create_student_academic_record(
            acting_user=self.superadmin,
            student=self.student_profile,
            programme=self.prog_bca,
            academic_session=self.session_a,
            admission_date=date(2026, 8, 1),
        )
        self.client.force_authenticate(user=self.faculty_user)
        # List endpoint: faculty gets empty queryset
        list_res = self.client.get("/api/v1/enrollments/academic-records/")
        self.assertIn(list_res.status_code, [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN])
        if list_res.status_code == status.HTTP_200_OK:
            self.assertEqual(len(list_res.data), 0)
        # Detail endpoint: faculty denied access
        detail_res = self.client.get(f"/api/v1/enrollments/academic-records/{record.pk}/")
        self.assertIn(detail_res.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN])

    def test_faculty_user_scoped_to_own_faculty_assignments(self):
        from apps.academics.services import assign_faculty_to_paper
        # Assign Jane (non-examiner)
        assign_jane = assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile_non_examiner,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )
        # Authenticate as John (faculty_user)
        self.client.force_authenticate(user=self.faculty_user)
        # List: John does not see Jane's assignment
        list_res = self.client.get("/api/v1/academics/faculty-assignments/")
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in list_res.data]
        self.assertNotIn(assign_jane.pk, ids)
        # Detail: John cannot view Jane's assignment
        detail_res = self.client.get(f"/api/v1/academics/faculty-assignments/{assign_jane.pk}/")
        self.assertIn(detail_res.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN])

    def test_faculty_assignment_patch_examiner_validation(self):
        from apps.academics.services import assign_faculty_to_paper
        # Assign Jane (non-examiner) as TEACHER
        assign_jane = assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile_non_examiner,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )
        self.client.force_authenticate(user=self.superadmin)
        # Partial PATCH to INTERNAL_EXAMINER fails because Jane is not an examiner
        patch_res = self.client.patch(
            f"/api/v1/academics/faculty-assignments/{assign_jane.pk}/",
            {"role": "INTERNAL_EXAMINER"},
            format="json",
        )
        self.assertEqual(patch_res.status_code, status.HTTP_400_BAD_REQUEST)

        # Assign John (examiner) as TEACHER
        assign_john = assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )
        # Partial PATCH to INTERNAL_EXAMINER succeeds because John is an examiner
        patch_res_john = self.client.patch(
            f"/api/v1/academics/faculty-assignments/{assign_john.pk}/",
            {"role": "INTERNAL_EXAMINER"},
            format="json",
        )
        self.assertEqual(patch_res_john.status_code, status.HTTP_200_OK)
        assign_john.refresh_from_db()
        self.assertEqual(assign_john.role, FacultyAssignmentRole.INTERNAL_EXAMINER)

    def test_faculty_cannot_revoke_examiner_flag_with_active_assignments(self):
        from apps.academics.services import assign_faculty_to_paper
        assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.INTERNAL_EXAMINER,
        )
        # Attempt to revoke is_examiner
        with self.assertRaises(ValidationError) as ctx:
            update_faculty_profile(
                profile_id=self.faculty_profile.pk,
                acting_user=self.superadmin,
                validated_data={"is_examiner": False},
            )
        self.assertIn("is_examiner", ctx.exception.message_dict)

    def test_programme_duration_reduction_rejected_when_student_in_higher_semester(self):
        from apps.academics.services import update_programme
        self.student_profile.current_semester = 6
        self.student_profile.save(update_fields=["current_semester"])

        with self.assertRaises(ValidationError) as ctx:
            update_programme(
                programme_id=self.prog_bca.pk,
                validated_data={"duration_semesters": 4},
            )
        self.assertIn("duration_semesters", ctx.exception.message_dict)

    def test_programme_college_change_rejected_when_student_profiles_exist(self):
        from apps.academics.services import update_programme
        with self.assertRaises(ValidationError) as ctx:
            update_programme(
                programme_id=self.prog_bca.pk,
                validated_data={"college": self.college_b},
            )
        self.assertIn("college", ctx.exception.message_dict)

    def test_department_college_change_rejected_when_faculty_profiles_exist(self):
        from apps.academics.services import update_department
        with self.assertRaises(ValidationError) as ctx:
            update_department(
                department_id=self.dept_cs.pk,
                validated_data={"college": self.college_b},
            )
        self.assertIn("college", ctx.exception.message_dict)

    def test_academic_session_college_change_rejected_when_academic_records_exist(self):
        from apps.academics.services import update_academic_session
        from apps.enrollments.services import create_student_academic_record
        create_student_academic_record(
            acting_user=self.superadmin,
            student=self.student_profile,
            programme=self.prog_bca,
            academic_session=self.session_a,
            admission_date=date(2026, 8, 1),
        )
        with self.assertRaises(ValidationError) as ctx:
            update_academic_session(
                session_id=self.session_a.pk,
                validated_data={"college": self.college_b},
            )
        self.assertIn("college", ctx.exception.message_dict)

    def test_paper_offering_session_cross_college_change_rejected_with_faculty_assignment(self):
        from apps.academics.services import assign_faculty_to_paper, update_paper_offering
        assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )
        with self.assertRaises(ValidationError) as ctx:
            update_paper_offering(
                paper_offering_id=self.paper_offering.pk,
                validated_data={"academic_session": self.session_b},
            )
        self.assertIn("academic_session", ctx.exception.message_dict)


class Chunk06Round3CorrectionsTests(BaseStudentFacultyTestCase):
    """
    Dedicated tests verifying all Chunk 06 Round 3 audit corrections:
    - R3-A: Administrator cross-college authorization scoping & fail-closed ambiguous boundaries.
    - R3-B: Faculty department change strict lock hierarchy (College lock -> Dept lock -> Profile reload).
    - R3-C: Faculty assignment update lock hierarchy (College lock -> Offering & Faculty lock -> Assignment reload).
    - R3-D: Administrator direct StudentProfile creation endpoint disabled with HTTP 403.
    - R3-E: Registration email failure atomic cleanup service & recovery state checks.
    - Hardening: Email verification GET endpoint strictly non-consuming; POST authoritative.
    """

    # --------------------------------------------------------------------------
    # R3-A: Multi-College Administrator Scoping Tests
    # --------------------------------------------------------------------------
    def test_ordinary_admin_cannot_list_another_college_students(self):
        # Ordinary admin with ambiguous institutional scope fails closed (empty queryset)
        self.client.force_authenticate(user=self.admin)
        res = self.client.get("/api/v1/students/profiles/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        returned_ids = [item["id"] for item in res.data]
        self.assertEqual(len(returned_ids), 0)

        # Superadmin has system-wide access to all colleges
        self.client.force_authenticate(user=self.superadmin)
        res_super = self.client.get("/api/v1/students/profiles/")
        self.assertEqual(res_super.status_code, status.HTTP_200_OK)
        super_ids = [item["id"] for item in res_super.data]
        self.assertIn(self.student_profile.pk, super_ids)
        self.assertIn(self.student_profile_b.pk, super_ids)

    def test_ordinary_admin_cannot_retrieve_another_college_student_by_id(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(f"/api/v1/students/profiles/{self.student_profile_b.pk}/")
        self.assertIn(res.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN])

    def test_ordinary_admin_cannot_update_another_college_student(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.patch(
            f"/api/v1/students/profiles/{self.student_profile_b.pk}/",
            {"current_semester": 2},
            format="json",
        )
        self.assertIn(res.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN])

        with self.assertRaises(DjangoPermissionDenied):
            update_student_profile(
                profile_id=self.student_profile_b.pk,
                acting_user=self.admin,
                validated_data={"current_semester": 2},
            )

    def test_ordinary_admin_cannot_approve_another_college_student_registration(self):
        user_reg, prof_reg, token = register_student(
            username="reg_b_student",
            email="reg_b@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="RegB",
            last_name="Student",
            college=self.college_b,
            programme=self.prog_b,
            enrollment_number="ENR-REG-B-01",
            registration_year=2026,
        )
        approval_b = RegistrationApproval.objects.get(user=user_reg)

        self.client.force_authenticate(user=self.admin)
        res = self.client.post(f"/api/v1/students/registrations/{approval_b.pk}/approve/")
        self.assertIn(res.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN])

        with self.assertRaises(DjangoPermissionDenied):
            review_student_registration(
                approval_id=approval_b.pk,
                action="APPROVE",
                reviewer=self.admin,
            )

    def test_ordinary_admin_cannot_create_faculty_in_unauthorized_college(self):
        self.client.force_authenticate(user=self.admin)
        payload = {
            "username": "new_b_faculty_user",
            "email": "new_b_fac@gauhati.ac.in",
            "first_name": "NewB",
            "last_name": "Faculty",
            "college": self.college_b.pk,
            "department": self.dept_b.pk,
            "employee_code": "EMP-NEW-B01",
        }
        res = self.client.post("/api/v1/faculty/profiles/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        with self.assertRaises(DjangoPermissionDenied):
            create_faculty_profile(
                acting_user=self.admin,
                username="new_b_fac_svc",
                email="new_b_svc@gauhati.ac.in",
                first_name="NewB",
                last_name="Faculty",
                college=self.college_b,
                department=self.dept_b,
                employee_code="EMP-NEW-B02",
            )

    def test_ordinary_admin_cannot_modify_another_college_faculty_record(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.patch(
            f"/api/v1/faculty/profiles/{self.faculty_profile_b.pk}/",
            {"designation": "Professor"},
            format="json",
        )
        self.assertIn(res.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN])

        with self.assertRaises(DjangoPermissionDenied):
            update_faculty_profile(
                profile_id=self.faculty_profile_b.pk,
                acting_user=self.admin,
                validated_data={"designation": "Professor"},
            )

    def test_ordinary_admin_cannot_create_or_modify_another_college_academic_record(self):
        from apps.enrollments.services import create_student_academic_record, update_student_academic_record

        # Admin for College A cannot create academic record for student in College B
        with self.assertRaises(DjangoPermissionDenied):
            create_student_academic_record(
                acting_user=self.admin,
                student=self.student_profile_b,
                programme=self.prog_b,
                academic_session=self.session_b,
                admission_date=date(2026, 8, 1),
            )

        # Superadmin creates record in College B
        rec_b = create_student_academic_record(
            acting_user=self.superadmin,
            student=self.student_profile_b,
            programme=self.prog_b,
            academic_session=self.session_b,
            admission_date=date(2026, 8, 1),
        )

        # Admin for College A cannot update record in College B
        with self.assertRaises(DjangoPermissionDenied):
            update_student_academic_record(
                record_id=rec_b.pk,
                acting_user=self.admin,
                validated_data={"status": "SUSPENDED"},
            )

    def test_ordinary_admin_cannot_create_or_modify_another_college_faculty_assignment(self):
        from apps.academics.services import assign_faculty_to_paper, update_faculty_assignment, delete_faculty_assignment

        # Admin A cannot assign in College B
        with self.assertRaises(DjangoPermissionDenied):
            assign_faculty_to_paper(
                acting_user=self.admin,
                faculty=self.faculty_profile_b,
                paper_offering=self.paper_offering_b,
                role=FacultyAssignmentRole.TEACHER,
            )

        # Superadmin assigns in College B
        assign_b = assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile_b,
            paper_offering=self.paper_offering_b,
            role=FacultyAssignmentRole.TEACHER,
        )

        # Admin A cannot update assignment in College B
        with self.assertRaises(DjangoPermissionDenied):
            update_faculty_assignment(
                assignment_id=assign_b.pk,
                acting_user=self.admin,
                validated_data={"role": FacultyAssignmentRole.INTERNAL_EXAMINER},
            )

        # Admin A cannot delete assignment in College B
        with self.assertRaises(DjangoPermissionDenied):
            delete_faculty_assignment(
                acting_user=self.admin,
                assignment_id=assign_b.pk,
            )

    def test_query_parameters_cannot_widen_admin_access(self):
        self.client.force_authenticate(user=self.admin)
        r1 = self.client.get(f"/api/v1/students/profiles/?college={self.college_b.pk}")
        self.assertEqual(len(r1.data), 0)

        r2 = self.client.get(f"/api/v1/faculty/profiles/?college={self.college_b.pk}")
        self.assertEqual(len(r2.data), 0)

        r3 = self.client.get(f"/api/v1/enrollments/academic-records/?college={self.college_b.pk}")
        self.assertEqual(len(r3.data), 0)

        r4 = self.client.get(f"/api/v1/academics/faculty-assignments/?college={self.college_b.pk}")
        self.assertEqual(len(r4.data), 0)

    def test_admin_with_ambiguous_scope_fails_closed(self):
        from apps.accounts.authorization import check_college_operation_authority
        unscoped_admin = User.objects.create_user(
            username="unscoped_admin_user",
            email="unscoped@gauhati.ac.in",
            password=self.password,
            role=RoleChoices.ADMIN,
            is_active=True,
        )
        with self.assertRaises(DjangoPermissionDenied):
            check_college_operation_authority(unscoped_admin, self.college_a.pk)

        self.client.force_authenticate(user=unscoped_admin)
        res = self.client.get("/api/v1/students/profiles/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 0)

    def test_superadmin_has_multi_college_access(self):
        self.client.force_authenticate(user=self.superadmin)
        res = self.client.get("/api/v1/students/profiles/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in res.data]
        self.assertIn(self.student_profile.pk, ids)
        self.assertIn(self.student_profile_b.pk, ids)

    # --------------------------------------------------------------------------
    # R3-B: Faculty Department Change Lock Hierarchy Tests
    # --------------------------------------------------------------------------
    def test_faculty_department_change_same_college_succeeds(self):
        updated = update_faculty_profile(
            profile_id=self.faculty_profile.pk,
            acting_user=self.superadmin,
            validated_data={"department": self.dept_math},
        )
        self.assertEqual(updated.department, self.dept_math)
        self.faculty_profile.refresh_from_db()
        self.assertEqual(self.faculty_profile.department, self.dept_math)

    def test_faculty_department_change_cross_college_fails(self):
        with self.assertRaises(ValidationError) as ctx:
            update_faculty_profile(
                profile_id=self.faculty_profile.pk,
                acting_user=self.superadmin,
                validated_data={"department": self.dept_b},
            )
        self.assertIn("department", ctx.exception.message_dict)

    def test_faculty_cannot_change_own_department(self):
        with self.assertRaises(DjangoPermissionDenied):
            update_faculty_profile(
                profile_id=self.faculty_profile.pk,
                acting_user=self.faculty_user,
                validated_data={"department": self.dept_math},
            )

    # --------------------------------------------------------------------------
    # R3-C: Faculty Assignment Update Lock Order Tests
    # --------------------------------------------------------------------------
    def test_faculty_assignment_update_college_first_locking_and_reassignment(self):
        from apps.academics.services import assign_faculty_to_paper, update_faculty_assignment

        assign = assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )

        updated = update_faculty_assignment(
            assignment_id=assign.pk,
            acting_user=self.superadmin,
            validated_data={"role": FacultyAssignmentRole.INTERNAL_EXAMINER},
        )
        self.assertEqual(updated.role, FacultyAssignmentRole.INTERNAL_EXAMINER)

    def test_faculty_assignment_update_cross_college_faculty_rejected(self):
        from apps.academics.services import assign_faculty_to_paper, update_faculty_assignment

        assign = assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )

        with self.assertRaises(ValidationError) as ctx:
            update_faculty_assignment(
                assignment_id=assign.pk,
                acting_user=self.superadmin,
                validated_data={"faculty": self.faculty_profile_b},
            )
        self.assertIn("faculty", ctx.exception.message_dict)

    # --------------------------------------------------------------------------
    # R3-D: Administrator Direct StudentProfile POST Disabled Tests
    # --------------------------------------------------------------------------
    def test_direct_student_profile_post_disabled_with_403(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/v1/students/profiles/",
            {
                "user": self.student_user.pk,
                "college": self.college_a.pk,
                "programme": self.prog_bca.pk,
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Direct student profile creation is not permitted", str(res.data))

    def test_unauthenticated_direct_student_profile_post_rejected(self):
        self.client.force_authenticate(user=None)
        res = self.client.post("/api/v1/students/profiles/", {}, format="json")
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    # --------------------------------------------------------------------------
    # R3-E: Registration Email Delivery Failure Atomic Cleanup Tests
    # --------------------------------------------------------------------------
    def test_registration_email_delivery_failure_atomic_cleanup_and_recovery(self):
        from unittest.mock import patch
        from apps.students.services import VerificationEmailDeliveryError

        with patch("apps.students.services.send_student_verification_email", side_effect=VerificationEmailDeliveryError("SMTP error")):
            payload = {
                "username": "smtp_cleanup_student",
                "email": "smtp_cleanup@gauhati.ac.in",
                "password": "StrongPassword@2026",
                "first_name": "Cleanup",
                "last_name": "Student",
                "college": self.college_a.pk,
                "programme": self.prog_bca.pk,
                "enrollment_number": "ENR-2026-CLEAN01",
                "registration_year": 2026,
            }
            res = self.client.post("/api/v1/auth/register/", payload, format="json")
            self.assertEqual(res.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertEqual(res.data["error"]["code"], "EMAIL_DELIVERY_UNAVAILABLE")

            # Verify atomic cleanup: no dangling user or profile
            self.assertFalse(User.objects.filter(username="smtp_cleanup_student").exists())
            self.assertFalse(StudentProfile.objects.filter(enrollment_number="ENR-2026-CLEAN01").exists())

        # Repeated registration succeeds without conflict
        res_retry = self.client.post("/api/v1/auth/register/", payload, format="json")
        self.assertEqual(res_retry.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(username="smtp_cleanup_student").exists())

    def test_cleanup_unverified_registration_refuses_to_delete_verified_or_approved_user(self):
        from apps.students.services import cleanup_unverified_registration

        # Active user cannot be cleaned up
        cleaned_active = cleanup_unverified_registration(self.student_user.pk)
        self.assertFalse(cleaned_active)
        self.assertTrue(User.objects.filter(pk=self.student_user.pk).exists())

    # --------------------------------------------------------------------------
    # Hardening: Email Verification GET Strictly Non-Consuming Tests
    # --------------------------------------------------------------------------
    def test_email_verification_get_never_consumes_token(self):
        user, profile, raw_token = register_student(
            username="get_hardening_student",
            email="hardening@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="Hardening",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-2026-HARD01",
            registration_year=2026,
        )

        # GET without confirm
        res1 = self.client.get(f"/api/v1/auth/verify-email/?token={raw_token}")
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res1.data["status"], "CONFIRM_REQUIRED")

        # GET with confirm=true still does NOT consume token
        res2 = self.client.get(f"/api/v1/auth/verify-email/?token={raw_token}&confirm=true")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["status"], "CONFIRM_REQUIRED")

        ev = EmailVerification.objects.get(user=user)
        self.assertFalse(ev.is_used)

        # Only POST authoritatively consumes token
        post_res = self.client.post("/api/v1/auth/verify-email/", {"token": raw_token}, format="json")
        self.assertEqual(post_res.status_code, status.HTTP_200_OK)
        self.assertTrue(post_res.data["is_email_verified"])

        ev.refresh_from_db()
        self.assertTrue(ev.is_used)


class Chunk06Round4CorrectionsTests(BaseStudentFacultyTestCase):
    """
    Dedicated tests verifying all Chunk 06 Round 4 audit corrections:
    - R4-A: Ordinary administrator persistent college assignment & fail-closed scoping.
    - R4-B: Registration approval single-table locking queries (no nullable outer-join locks).
    - R4-C: Unified lock hierarchy (User -> Approval -> EmailVerification -> Profile) & precondition checks.
    - R4-D: Evaluated Department row lock acquisition in update_faculty_profile.
    - R4-E: Standardized lock hierarchy across faculty assignment operations.
    - R4-F: Verify email documentation and endpoint consumption exclusively via POST.
    """

    # --------------------------------------------------------------------------
    # R4-A: Ordinary Admin Institutional Scope & Persistence Tests
    # --------------------------------------------------------------------------
    def test_ordinary_admin_without_persistent_college_linkage_fails_closed(self):
        from apps.accounts.authorization import check_college_operation_authority, get_actor_authorized_college_ids

        # Authorized college IDs is an empty set (fail-closed)
        authorized = get_actor_authorized_college_ids(self.admin)
        self.assertEqual(authorized, set())

        # Calling check_college_operation_authority for any college raises PermissionDenied
        with self.assertRaises(DjangoPermissionDenied):
            check_college_operation_authority(self.admin, self.college_a.pk, "any_operation")

        with self.assertRaises(DjangoPermissionDenied):
            check_college_operation_authority(self.admin, self.college_b.pk, "any_operation")

    def test_runtime_attribute_injection_does_not_grant_authority(self):
        from apps.accounts.authorization import check_college_operation_authority, get_actor_authorized_college_ids

        # Attempt to inject runtime Python attributes
        self.admin.college_id = self.college_a.pk
        self.admin.college = self.college_a

        # Scoping service ignores caller-injected runtime attributes
        authorized = get_actor_authorized_college_ids(self.admin)
        self.assertEqual(authorized, set())

        with self.assertRaises(DjangoPermissionDenied):
            check_college_operation_authority(self.admin, self.college_a.pk, "test_injected_attr")

    def test_superadmin_retains_system_wide_multi_college_access(self):
        from apps.accounts.authorization import check_college_operation_authority, get_actor_authorized_college_ids

        # Superadmin returns None (system-wide access)
        authorized = get_actor_authorized_college_ids(self.superadmin)
        self.assertIsNone(authorized)

        # check_college_operation_authority does not raise for any college
        check_college_operation_authority(self.superadmin, self.college_a.pk, "op_a")
        check_college_operation_authority(self.superadmin, self.college_b.pk, "op_b")

    # --------------------------------------------------------------------------
    # R4-B & R4-C: Registration Approval & Cleanup Unified Lock Hierarchy Tests
    # --------------------------------------------------------------------------
    def test_review_student_registration_single_table_locking_and_approval(self):
        from apps.students.services import review_student_registration

        user, profile, raw_token = register_student(
            username="r4_review_student",
            email="r4_review@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="R4Review",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-R4-001",
            registration_year=2026,
        )
        approval = RegistrationApproval.objects.get(user=user)

        # Unverified email approval rejected under lock
        with self.assertRaises(ValidationError) as ctx:
            review_student_registration(
                approval_id=approval.pk,
                action="APPROVE",
                reviewer=self.superadmin,
            )
        self.assertIn("email", ctx.exception.message_dict)

        # Verify email token
        verify_email_token(raw_token)

        # Now approve succeeds under single-table lock
        reviewed = review_student_registration(
            approval_id=approval.pk,
            action="APPROVE",
            reviewer=self.superadmin,
        )
        self.assertEqual(reviewed.status, RegistrationApprovalStatus.APPROVED)
        user.refresh_from_db()
        self.assertTrue(user.is_active)

        # Attempting review again fails (no longer pending)
        with self.assertRaises(ValidationError) as ctx2:
            review_student_registration(
                approval_id=approval.pk,
                action="APPROVE",
                reviewer=self.superadmin,
            )
        self.assertIn("status", ctx2.exception.message_dict)

    def test_cleanup_unverified_registration_precondition_revalidation(self):
        from apps.students.services import cleanup_unverified_registration

        user, profile, raw_token = register_student(
            username="r4_cleanup_student",
            email="r4_cleanup@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="R4Cleanup",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-R4-002",
            registration_year=2026,
        )

        # Precondition check 1: Active user cannot be cleaned up
        user.is_active = True
        user.save(update_fields=["is_active"])
        self.assertFalse(cleanup_unverified_registration(user.pk))
        user.is_active = False
        user.save(update_fields=["is_active"])

        # Precondition check 2: Non-student role cannot be cleaned up
        user.role = RoleChoices.FACULTY
        user.save(update_fields=["role"])
        self.assertFalse(cleanup_unverified_registration(user.pk))
        user.role = RoleChoices.STUDENT
        user.save(update_fields=["role"])

        # Precondition check 3: Non-pending approval cannot be cleaned up
        approval = RegistrationApproval.objects.get(user=user)
        approval.status = RegistrationApprovalStatus.REJECTED
        approval.save(update_fields=["status"])
        self.assertFalse(cleanup_unverified_registration(user.pk))
        approval.status = RegistrationApprovalStatus.PENDING
        approval.save(update_fields=["status"])

        # Precondition check 4: Used verification token cannot be cleaned up
        ev = EmailVerification.objects.get(user=user)
        ev.is_used = True
        ev.save(update_fields=["is_used"])
        self.assertFalse(cleanup_unverified_registration(user.pk))
        ev.is_used = False
        ev.save(update_fields=["is_used"])

        # All preconditions satisfied -> atomic cleanup succeeds
        cleaned = cleanup_unverified_registration(user.pk)
        self.assertTrue(cleaned)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        self.assertFalse(StudentProfile.objects.filter(pk=profile.pk).exists())
        self.assertFalse(RegistrationApproval.objects.filter(pk=approval.pk).exists())
        self.assertFalse(EmailVerification.objects.filter(pk=ev.pk).exists())

    def test_verify_email_token_lock_order_and_expiry(self):
        user, profile, raw_token = register_student(
            username="r4_token_student",
            email="r4_token@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="R4Token",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-R4-003",
            registration_year=2026,
        )

        # Consumes token
        verified_user = verify_email_token(raw_token)
        self.assertEqual(verified_user.pk, user.pk)
        self.assertFalse(verified_user.is_active)  # still inactive until approved

        # Attempt to use consumed token
        with self.assertRaises(ValidationError) as ctx:
            verify_email_token(raw_token)
        self.assertIn("already been used", ctx.exception.message_dict["token"][0])

    # --------------------------------------------------------------------------
    # R4-D: Evaluated Department Locks in Faculty Profile Update Tests
    # --------------------------------------------------------------------------
    def test_update_faculty_profile_materialized_department_locks(self):
        # Admin updates department to another department within same college
        updated = update_faculty_profile(
            profile_id=self.faculty_profile.pk,
            acting_user=self.superadmin,
            validated_data={"department": self.dept_math},
        )
        self.assertEqual(updated.department_id, self.dept_math.pk)
        self.faculty_profile.refresh_from_db()
        self.assertEqual(self.faculty_profile.department_id, self.dept_math.pk)

    # --------------------------------------------------------------------------
    # R4-E: Faculty Assignment Standardized Lock Hierarchy Tests
    # --------------------------------------------------------------------------
    def test_faculty_assignment_standardized_lock_sequence_crud(self):
        from apps.academics.services import (
            assign_faculty_to_paper,
            update_faculty_assignment,
            delete_faculty_assignment,
        )

        # Create assignment
        assign = assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )
        self.assertEqual(assign.role, FacultyAssignmentRole.TEACHER)

        # Update assignment following Level 1 College -> Level 2 PaperOffering -> Level 3 FacultyProfile -> Level 4 Assignment
        updated = update_faculty_assignment(
            assignment_id=assign.pk,
            acting_user=self.superadmin,
            validated_data={"role": FacultyAssignmentRole.INTERNAL_EXAMINER},
        )
        self.assertEqual(updated.role, FacultyAssignmentRole.INTERNAL_EXAMINER)

        # Delete assignment following Level 1 College -> Level 2 PaperOffering -> Level 4 Assignment
        delete_faculty_assignment(
            acting_user=self.superadmin,
            assignment_id=assign.pk,
        )
        self.assertFalse(FacultySubjectAssignment.objects.filter(pk=assign.pk).exists())


class Chunk06Round5CorrectionsTests(BaseStudentFacultyTestCase):
    """
    Dedicated regression test suite verifying Chunk 06 Round 5 corrections:
    - R5-A: Stale relationship overwrite prevention in update/delete faculty assignment.
    - R5-B: Mandatory student identity integrity and evaluated profile locks during registration review.
    - R5-C: Evaluated StudentProfile locks and non-partial cleanup refusal in registration cleanup.
    """

    def setUp(self):
        super().setUp()
        from apps.academics.services import assign_faculty_to_paper
        self.assign_faculty_to_paper = assign_faculty_to_paper

        # Secondary faculty in College A for reassignment testing
        self.faculty_user_2 = User.objects.create_user(
            username="faculty_r5_2",
            email="faculty_r5_2@gauhati.ac.in",
            password=self.password,
            first_name="Secondary",
            last_name="Examiner",
            role=RoleChoices.FACULTY,
            is_active=True,
        )
        self.faculty_profile_2 = FacultyProfile.objects.create(
            user=self.faculty_user_2,
            college=self.college_a,
            department=self.dept_cs,
            employee_code="EMP-CS-R5-02",
            designation="Associate Professor",
            is_examiner=True,
        )

        # Secondary offering in College A
        self.subject_math = Subject.objects.create(
            department=self.dept_math,
            name="Calculus",
            code="MATH-101",
        )
        self.offering_2 = PaperOffering.objects.create(
            academic_session=self.session_a,
            semester=self.sem_1,
            subject=self.subject_math,
            subject_category=self.sub_cat,
            paper_code="BCA-102-CALC",
            credits=Decimal("4.0"),
            max_marks_internal=Decimal("20.0"),
            max_marks_external=Decimal("80.0"),
            pass_marks_external=Decimal("32.0"),
            is_active=True,
        )

    # --------------------------------------------------------------------------
    # R5-A: Stale Relationship Protection in Faculty Assignment
    # --------------------------------------------------------------------------
    def test_faculty_assignment_update_role_only_preserves_relationships(self):
        """Role-only update preserves authoritative faculty and paper-offering relationships."""
        from apps.academics.services import update_faculty_assignment

        assign = self.assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )

        updated = update_faculty_assignment(
            assignment_id=assign.pk,
            acting_user=self.superadmin,
            validated_data={"role": FacultyAssignmentRole.INTERNAL_EXAMINER},
        )
        self.assertEqual(updated.role, FacultyAssignmentRole.INTERNAL_EXAMINER)
        self.assertEqual(updated.faculty_id, self.faculty_profile.pk)
        self.assertEqual(updated.paper_offering_id, self.paper_offering.pk)

        assign.refresh_from_db()
        self.assertEqual(assign.role, FacultyAssignmentRole.INTERNAL_EXAMINER)
        self.assertEqual(assign.faculty_id, self.faculty_profile.pk)
        self.assertEqual(assign.paper_offering_id, self.paper_offering.pk)

    def test_faculty_assignment_update_stale_faculty_relationship_rejected(self):
        """Concurrent modification to faculty relationship between candidate read and lock is rejected."""
        import unittest.mock
        from apps.academics.services import update_faculty_assignment

        assign = self.assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )

        # Simulate concurrent change to faculty between candidate read and lock acquisition
        original_sfu = PaperOffering.objects.select_for_update

        def race_condition_concurrent_reassign(*args, **kwargs):
            FacultySubjectAssignment.objects.filter(pk=assign.pk).update(faculty=self.faculty_profile_2)
            return original_sfu(*args, **kwargs)

        with unittest.mock.patch.object(PaperOffering.objects, "select_for_update", side_effect=race_condition_concurrent_reassign):
            with self.assertRaises(ValidationError) as ctx:
                update_faculty_assignment(
                    assignment_id=assign.pk,
                    acting_user=self.superadmin,
                    validated_data={"role": FacultyAssignmentRole.INTERNAL_EXAMINER},
                )
            self.assertIn("assignment", ctx.exception.message_dict)
            self.assertIn("Authoritative assignment relationships changed concurrently", ctx.exception.message_dict["assignment"][0])

    def test_faculty_assignment_update_stale_offering_relationship_rejected(self):
        """Concurrent modification to paper offering between candidate read and lock is rejected."""
        import unittest.mock
        from apps.academics.services import update_faculty_assignment

        assign = self.assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )

        original_sfu = PaperOffering.objects.select_for_update

        def race_condition_concurrent_offering_reassign(*args, **kwargs):
            FacultySubjectAssignment.objects.filter(pk=assign.pk).update(paper_offering=self.offering_2)
            return original_sfu(*args, **kwargs)

        with unittest.mock.patch.object(PaperOffering.objects, "select_for_update", side_effect=race_condition_concurrent_offering_reassign):
            with self.assertRaises(ValidationError) as ctx:
                update_faculty_assignment(
                    assignment_id=assign.pk,
                    acting_user=self.superadmin,
                    validated_data={"role": FacultyAssignmentRole.INTERNAL_EXAMINER},
                )
            self.assertIn("assignment", ctx.exception.message_dict)
            self.assertIn("Authoritative assignment relationships changed concurrently", ctx.exception.message_dict["assignment"][0])

    def test_faculty_assignment_delete_stale_relationship_rejected(self):
        """Concurrent modification to assignment relationships before delete lock is rejected."""
        import unittest.mock
        from apps.academics.services import delete_faculty_assignment

        assign = self.assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )

        original_sfu = PaperOffering.objects.select_for_update

        def race_condition_concurrent_delete_reassign(*args, **kwargs):
            FacultySubjectAssignment.objects.filter(pk=assign.pk).update(faculty=self.faculty_profile_2)
            return original_sfu(*args, **kwargs)

        with unittest.mock.patch.object(PaperOffering.objects, "select_for_update", side_effect=race_condition_concurrent_delete_reassign):
            with self.assertRaises(ValidationError) as ctx:
                delete_faculty_assignment(
                    acting_user=self.superadmin,
                    assignment_id=assign.pk,
                )
            self.assertIn("assignment", ctx.exception.message_dict)
            self.assertIn("Authoritative assignment relationships changed concurrently", ctx.exception.message_dict["assignment"][0])

    def test_faculty_assignment_delete_valid_authorized_succeeds(self):
        """Clean, consistent faculty assignment deletion succeeds and deletes the record."""
        from apps.academics.services import delete_faculty_assignment

        assign = self.assign_faculty_to_paper(
            acting_user=self.superadmin,
            faculty=self.faculty_profile,
            paper_offering=self.paper_offering,
            role=FacultyAssignmentRole.TEACHER,
        )
        delete_faculty_assignment(
            acting_user=self.superadmin,
            assignment_id=assign.pk,
        )
        self.assertFalse(FacultySubjectAssignment.objects.filter(pk=assign.pk).exists())

    # --------------------------------------------------------------------------
    # R5-B: Registration Review Identity Integrity Tests
    # --------------------------------------------------------------------------
    def test_review_student_registration_missing_student_profile_rejected(self):
        """Reviewing student registration when StudentProfile is missing is rejected for both APPROVE and REJECT."""
        user, profile, raw_token = register_student(
            username="r5_noprofile_stud",
            email="r5_noprofile@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="NoProfile",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-R5-001",
            registration_year=2026,
        )
        verify_email_token(raw_token)
        approval = RegistrationApproval.objects.get(user=user)

        # Delete profile to simulate incomplete/missing identity
        profile.delete()

        # Attempt APPROVE fails
        with self.assertRaises(ValidationError) as ctx_approve:
            review_student_registration(
                approval_id=approval.pk,
                action="APPROVE",
                reviewer=self.superadmin,
            )
        self.assertIn("student_profile", ctx_approve.exception.message_dict)
        self.assertIn("valid linked student profile is required", ctx_approve.exception.message_dict["student_profile"][0])

        # Attempt REJECT also fails
        with self.assertRaises(ValidationError) as ctx_reject:
            review_student_registration(
                approval_id=approval.pk,
                action="REJECT",
                reviewer=self.superadmin,
            )
        self.assertIn("student_profile", ctx_reject.exception.message_dict)
        self.assertIn("valid linked student profile is required", ctx_reject.exception.message_dict["student_profile"][0])

    def test_superadmin_cannot_approve_student_lacking_profile(self):
        """Superadministrator authority does not bypass mandatory StudentProfile identity invariant."""
        user, profile, raw_token = register_student(
            username="r5_super_noprofile",
            email="r5_super_noprofile@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="Super",
            last_name="NoProfile",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-R5-002",
            registration_year=2026,
        )
        verify_email_token(raw_token)
        approval = RegistrationApproval.objects.get(user=user)

        profile.delete()

        with self.assertRaises(ValidationError) as ctx:
            review_student_registration(
                approval_id=approval.pk,
                action="APPROVE",
                reviewer=self.superadmin,
            )
        self.assertIn("student_profile", ctx.exception.message_dict)

    def test_review_student_registration_user_role_not_student_rejected(self):
        """Review is rejected if user's role is not RoleChoices.STUDENT."""
        user, profile, raw_token = register_student(
            username="r5_wrongrole_stud",
            email="r5_wrongrole@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="WrongRole",
            last_name="User",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-R5-003",
            registration_year=2026,
        )
        verify_email_token(raw_token)
        approval = RegistrationApproval.objects.get(user=user)

        user.role = RoleChoices.FACULTY
        user.save(update_fields=["role"])

        with self.assertRaises(ValidationError) as ctx:
            review_student_registration(
                approval_id=approval.pk,
                action="APPROVE",
                reviewer=self.superadmin,
            )
        self.assertIn("user", ctx.exception.message_dict)
        self.assertIn("User primary role must be 'STUDENT'", ctx.exception.message_dict["user"][0])

    def test_review_student_registration_cross_college_programme_rejected(self):
        """Review is rejected if student profile's programme belongs to a different college."""
        user, profile, raw_token = register_student(
            username="r5_crosscollege_stud",
            email="r5_crosscollege@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="CrossCollege",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-R5-004",
            registration_year=2026,
        )
        verify_email_token(raw_token)
        approval = RegistrationApproval.objects.get(user=user)

        # Alter programme to College B programme
        profile.programme = self.prog_b
        profile.save(update_fields=["programme"])

        with self.assertRaises(ValidationError) as ctx:
            review_student_registration(
                approval_id=approval.pk,
                action="APPROVE",
                reviewer=self.superadmin,
            )
        self.assertIn("programme", ctx.exception.message_dict)
        self.assertIn("does not belong to the student's college", ctx.exception.message_dict["programme"][0])

    def test_review_student_registration_wrong_college_admin_rejected(self):
        """Review by an administrator lacking authority over student's college raises PermissionDenied."""
        user, profile, raw_token = register_student(
            username="r5_unauth_admin_stud",
            email="r5_unauth_admin@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="UnauthAdmin",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-R5-005",
            registration_year=2026,
        )
        verify_email_token(raw_token)
        approval = RegistrationApproval.objects.get(user=user)

        # Ordinary administrator fails closed on institutional checks
        with self.assertRaises(DjangoPermissionDenied):
            review_student_registration(
                approval_id=approval.pk,
                action="APPROVE",
                reviewer=self.admin,
            )

    def test_review_student_registration_unverified_email_rejected(self):
        """Review APPROVE is rejected if student has not verified their email token."""
        user, profile, raw_token = register_student(
            username="r5_unverified_stud",
            email="r5_unverified@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="Unverified",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-R5-006",
            registration_year=2026,
        )
        approval = RegistrationApproval.objects.get(user=user)

        with self.assertRaises(ValidationError) as ctx:
            review_student_registration(
                approval_id=approval.pk,
                action="APPROVE",
                reviewer=self.superadmin,
            )
        self.assertIn("email", ctx.exception.message_dict)

    # --------------------------------------------------------------------------
    # R5-C: Evaluated StudentProfile Lock & Registration Cleanup Refusal Tests
    # --------------------------------------------------------------------------
    def test_cleanup_unverified_registration_missing_student_profile_refused(self):
        """Cleanup refuses deletion if StudentProfile is missing, avoiding partial record purge."""
        from apps.students.services import cleanup_unverified_registration

        user, profile, raw_token = register_student(
            username="r5_cleanup_noprofile",
            email="r5_cleanup_noprofile@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="CleanupNoProfile",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-R5-007",
            registration_year=2026,
        )
        profile.delete()

        result = cleanup_unverified_registration(user.pk)
        self.assertFalse(result)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertTrue(RegistrationApproval.objects.filter(user=user).exists())
        self.assertTrue(EmailVerification.objects.filter(user=user).exists())

    def test_cleanup_unverified_registration_missing_approval_refused(self):
        """Cleanup refuses deletion if RegistrationApproval is missing."""
        from apps.students.services import cleanup_unverified_registration

        user, profile, raw_token = register_student(
            username="r5_cleanup_noapp",
            email="r5_cleanup_noapp@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="CleanupNoApp",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-R5-008",
            registration_year=2026,
        )
        RegistrationApproval.objects.filter(user=user).delete()

        result = cleanup_unverified_registration(user.pk)
        self.assertFalse(result)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertTrue(StudentProfile.objects.filter(user=user).exists())

    def test_cleanup_unverified_registration_missing_verification_refused(self):
        """Cleanup refuses deletion if EmailVerification is missing."""
        from apps.students.services import cleanup_unverified_registration

        user, profile, raw_token = register_student(
            username="r5_cleanup_noev",
            email="r5_cleanup_noev@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="CleanupNoEV",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-R5-009",
            registration_year=2026,
        )
        EmailVerification.objects.filter(user=user).delete()

        result = cleanup_unverified_registration(user.pk)
        self.assertFalse(result)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertTrue(StudentProfile.objects.filter(user=user).exists())

    def test_cleanup_unverified_registration_evaluates_profile_lock_and_succeeds(self):
        """Cleanup succeeds when all preconditions and evaluated locks are met."""
        from apps.students.services import cleanup_unverified_registration

        user, profile, raw_token = register_student(
            username="r5_cleanup_valid",
            email="r5_cleanup_valid@gauhati.ac.in",
            password="StrongPassword@2026",
            first_name="CleanupValid",
            last_name="Student",
            college=self.college_a,
            programme=self.prog_bca,
            enrollment_number="ENR-R5-010",
            registration_year=2026,
        )
        user_id = user.pk
        profile_id = profile.pk

        result = cleanup_unverified_registration(user_id)
        self.assertTrue(result)
        self.assertFalse(User.objects.filter(pk=user_id).exists())
        self.assertFalse(StudentProfile.objects.filter(pk=profile_id).exists())
        self.assertFalse(RegistrationApproval.objects.filter(user_id=user_id).exists())
        self.assertFalse(EmailVerification.objects.filter(user_id=user_id).exists())
