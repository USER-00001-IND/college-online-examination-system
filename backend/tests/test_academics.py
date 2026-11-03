"""
Comprehensive Test Suite for Chunk 05: FYUGP Academic Management Backend.
Covers:
- Academic Models & Schema Integrity (Tables 9-17, 21)
- Validation, Constraints & Referential Integrity (RESTRICT vs CASCADE)
- Service Layer Operations & Transactions
- Institutional RBAC & Privilege Escalation Defenses (is_staff=True defense)
- REST API Operations, Standardized Error Envelopes & Sensitive Config Masking
"""

import json
from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import patch
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.academics.models import (
    AcademicSession,
    College,
    ConfigDataType,
    Department,
    InstitutionalConfig,
    PaperOffering,
    PaperProgrammeMapping,
    Programme,
    Semester,
    Subject,
    SubjectCategory,
)
from apps.academics.services import (
    create_paper_offering,
    map_paper_to_programmes,
    set_current_academic_session,
    set_institutional_config,
    validate_academic_session_dates,
)
from apps.accounts.models import Role, RoleChoices, User, UserRole


class AcademicModelUnitTests(TestCase):
    """Tests model definitions, field validations, and clean() methods."""

    def setUp(self):
        self.college = College.objects.create(
            name="Model College (Gauhati University)",
            code="MC-GU",
            contact_email="admin@modelcollege.edu.in",
        )

    def test_college_creation(self):
        self.assertEqual(str(self.college), "Model College (Gauhati University) (MC-GU)")
        self.assertTrue(self.college.is_active)

    def test_academic_session_clean_valid(self):
        session = AcademicSession(
            college=self.college,
            name="2026-2027",
            start_date=date(2026, 7, 1),
            end_date=date(2027, 6, 30),
        )
        session.full_clean()
        session.save()
        self.assertEqual(session.name, "2026-2027")
        self.assertFalse(session.is_current)

    def test_academic_session_clean_invalid_dates_rejected(self):
        session = AcademicSession(
            college=self.college,
            name="2026-2027",
            start_date=date(2027, 7, 1),
            end_date=date(2026, 6, 30),
        )
        with self.assertRaises(ValidationError) as cm:
            session.full_clean()
        self.assertIn("end_date", cm.exception.message_dict)

    def test_programme_clean_valid(self):
        prog = Programme(
            college=self.college,
            name="Bachelor of Arts (FYUGP)",
            code="BA-FYUGP",
            duration_semesters=8,
            degree_type="UNDERGRADUATE",
        )
        prog.full_clean()
        prog.save()
        self.assertEqual(prog.duration_semesters, 8)

    def test_programme_clean_invalid_duration_rejected(self):
        prog = Programme(
            college=self.college,
            name="Zero Semester Programme",
            code="ZERO",
            duration_semesters=0,
        )
        with self.assertRaises(ValidationError) as cm:
            prog.full_clean()
        self.assertIn("duration_semesters", cm.exception.message_dict)

    def test_department_and_subject_creation(self):
        dept = Department.objects.create(
            college=self.college,
            name="Department of Political Science",
            code="POL",
        )
        subject = Subject(
            department=dept,
            name="Political Science",
            code="POLSCI",
        )
        subject.full_clean()
        subject.save()
        self.assertEqual(str(subject), "Political Science (POLSCI)")

    def test_semester_validation_bounds(self):
        prog = Programme.objects.create(
            college=self.college,
            name="Bachelor of Science",
            code="BSC",
            duration_semesters=6,
        )
        # Valid semester
        sem1 = Semester(programme=prog, semester_number=1, name="Semester 1")
        sem1.full_clean()
        sem1.save()

        # Invalid: 0
        sem_zero = Semester(programme=prog, semester_number=0, name="Semester 0")
        with self.assertRaises(ValidationError):
            sem_zero.full_clean()

        # Invalid: 7 (exceeds duration 6)
        sem_seven = Semester(programme=prog, semester_number=7, name="Semester 7")
        with self.assertRaises(ValidationError) as cm:
            sem_seven.full_clean()
        self.assertIn("semester_number", cm.exception.message_dict)

    def test_subject_category_credit_validation(self):
        # Valid category
        cat = SubjectCategory(
            college=self.college,
            code="MAJOR",
            name="Major Course",
            min_credits=Decimal("4.0"),
            max_credits=Decimal("4.0"),
        )
        cat.full_clean()
        cat.save()

        # Invalid: min_credits < 0
        cat_neg = SubjectCategory(
            college=self.college,
            code="NEG",
            name="Negative Credits",
            min_credits=Decimal("-1.0"),
            max_credits=Decimal("4.0"),
        )
        with self.assertRaises(ValidationError):
            cat_neg.full_clean()

        # Invalid: max_credits < min_credits
        cat_inv = SubjectCategory(
            college=self.college,
            code="INV",
            name="Inverted Credits",
            min_credits=Decimal("4.0"),
            max_credits=Decimal("2.0"),
        )
        with self.assertRaises(ValidationError):
            cat_inv.full_clean()

    def test_paper_offering_numeric_and_marks_validation(self):
        session = AcademicSession.objects.create(
            college=self.college,
            name="2026-2027",
            start_date=date(2026, 7, 1),
            end_date=date(2027, 6, 30),
        )
        prog = Programme.objects.create(
            college=self.college, name="BA", code="BA", duration_semesters=8
        )
        sem = Semester.objects.create(programme=prog, semester_number=1, name="Sem 1")
        dept = Department.objects.create(college=self.college, name="Pol Sci", code="POL")
        sub = Subject.objects.create(department=dept, name="Pol Sci", code="POLSCI")
        cat = SubjectCategory.objects.create(
            college=self.college, code="MAJOR", name="Major", min_credits=Decimal("2.0"), max_credits=Decimal("4.0")
        )

        # Valid offering
        offering = PaperOffering(
            academic_session=session,
            semester=sem,
            subject=sub,
            subject_category=cat,
            paper_code="POL1014",
            title="Political Theory",
            credits=Decimal("4.0"),
            max_marks_internal=Decimal("20.00"),
            max_marks_external=Decimal("80.00"),
            pass_marks_external=Decimal("28.00"),
        )
        offering.full_clean()
        offering.save()
        self.assertEqual(offering.paper_code, "POL1014")

        # Invalid: Credits outside category range
        offering_bad_cred = PaperOffering(
            academic_session=session,
            semester=sem,
            subject=sub,
            subject_category=cat,
            paper_code="POL1016",
            title="Extra Heavy Paper",
            credits=Decimal("6.0"),  # Exceeds max 4.0
        )
        with self.assertRaises(ValidationError) as cm:
            offering_bad_cred.full_clean()
        self.assertIn("credits", cm.exception.message_dict)

        # Invalid: Pass marks > Max external marks
        offering_bad_marks = PaperOffering(
            academic_session=session,
            semester=sem,
            subject=sub,
            subject_category=cat,
            paper_code="POL1012",
            title="Paper",
            credits=Decimal("4.0"),
            max_marks_external=Decimal("50.00"),
            pass_marks_external=Decimal("60.00"),
        )
        with self.assertRaises(ValidationError) as cm:
            offering_bad_marks.full_clean()
        self.assertIn("pass_marks_external", cm.exception.message_dict)

    def test_cross_college_paper_offering_rejected(self):
        other_college = College.objects.create(
            name="Other College",
            code="OC-GU",
            contact_email="admin@other.edu.in",
        )
        session = AcademicSession.objects.create(
            college=self.college,
            name="2026-2027",
            start_date=date(2026, 7, 1),
            end_date=date(2027, 6, 30),
        )
        # Programme belongs to other college
        prog_other = Programme.objects.create(
            college=other_college, name="Other Prog", code="OP", duration_semesters=8
        )
        sem_other = Semester.objects.create(programme=prog_other, semester_number=1, name="Sem 1")
        dept = Department.objects.create(college=self.college, name="Pol Sci", code="POL")
        sub = Subject.objects.create(department=dept, name="Pol Sci", code="POLSCI")
        cat = SubjectCategory.objects.create(
            college=self.college, code="MAJOR", name="Major", min_credits=Decimal("2.0"), max_credits=Decimal("4.0")
        )

        offering = PaperOffering(
            academic_session=session,
            semester=sem_other,
            subject=sub,
            subject_category=cat,
            paper_code="CROSS101",
            title="Cross College Offering",
            credits=Decimal("4.0"),
        )
        with self.assertRaises(ValidationError) as cm:
            offering.full_clean()
        self.assertIn("semester", cm.exception.message_dict)

    def test_institutional_config_data_type_validation(self):
        # STRING
        c1 = InstitutionalConfig(
            college=self.college,
            config_key="PORTAL_TITLE",
            config_value="Model College Online Portal",
            data_type=ConfigDataType.STRING,
        )
        c1.full_clean()
        self.assertEqual(c1.get_parsed_value(), "Model College Online Portal")

        # INTEGER valid
        c2 = InstitutionalConfig(
            college=self.college,
            config_key="MAX_ATTEMPTS",
            config_value="5",
            data_type=ConfigDataType.INTEGER,
        )
        c2.full_clean()
        self.assertEqual(c2.get_parsed_value(), 5)

        # INTEGER invalid
        c2_bad = InstitutionalConfig(
            college=self.college,
            config_key="BAD_INT",
            config_value="five",
            data_type=ConfigDataType.INTEGER,
        )
        with self.assertRaises(ValidationError):
            c2_bad.full_clean()

        # BOOLEAN valid
        c3 = InstitutionalConfig(
            college=self.college,
            config_key="ALLOW_CALCULATOR",
            config_value="true",
            data_type=ConfigDataType.BOOLEAN,
        )
        c3.full_clean()
        self.assertTrue(c3.get_parsed_value())

        # BOOLEAN invalid
        c3_bad = InstitutionalConfig(
            college=self.college,
            config_key="BAD_BOOL",
            config_value="maybe",
            data_type=ConfigDataType.BOOLEAN,
        )
        with self.assertRaises(ValidationError):
            c3_bad.full_clean()

        # JSON valid
        c4 = InstitutionalConfig(
            college=self.college,
            config_key="GRADING_POLICY",
            config_value=json.dumps({"A": 90, "B": 80}),
            data_type=ConfigDataType.JSON,
        )
        c4.full_clean()
        self.assertEqual(c4.get_parsed_value()["A"], 90)

        # JSON invalid
        c4_bad = InstitutionalConfig(
            college=self.college,
            config_key="BAD_JSON",
            config_value="{not valid json",
            data_type=ConfigDataType.JSON,
        )
        with self.assertRaises(ValidationError):
            c4_bad.full_clean()


class AcademicConstraintIntegrityTests(TestCase):
    """Tests database unique constraints and referential RESTRICT protections."""

    def setUp(self):
        self.college = College.objects.create(
            name="Model College",
            code="MC-GU",
            contact_email="admin@modelcollege.edu.in",
        )

    def test_duplicate_college_code_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                College.objects.create(
                    name="Duplicate Code College",
                    code="MC-GU",  # Duplicate
                    contact_email="other@college.edu.in",
                )

    def test_duplicate_session_name_within_college_rejected(self):
        AcademicSession.objects.create(
            college=self.college,
            name="2026-2027",
            start_date=date(2026, 7, 1),
            end_date=date(2027, 6, 30),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AcademicSession.objects.create(
                    college=self.college,
                    name="2026-2027",  # Duplicate in same college
                    start_date=date(2026, 7, 1),
                    end_date=date(2027, 6, 30),
                )

        # Allowed in a different college
        other_college = College.objects.create(
            name="Other College", code="OC-GU", contact_email="admin@oc.edu"
        )
        other_session = AcademicSession.objects.create(
            college=other_college,
            name="2026-2027",
            start_date=date(2026, 7, 1),
            end_date=date(2027, 6, 30),
        )
        self.assertIsNotNone(other_session.pk)

    def test_duplicate_programme_code_within_college_rejected(self):
        Programme.objects.create(college=self.college, name="BA", code="BA-FYUGP")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Programme.objects.create(college=self.college, name="BA 2", code="BA-FYUGP")

    def test_duplicate_department_code_within_college_rejected(self):
        Department.objects.create(college=self.college, name="Pol Sci", code="POL")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Department.objects.create(college=self.college, name="Political", code="POL")

    def test_duplicate_semester_number_within_programme_rejected(self):
        prog = Programme.objects.create(college=self.college, name="BA", code="BA")
        Semester.objects.create(programme=prog, semester_number=1, name="Sem 1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Semester.objects.create(programme=prog, semester_number=1, name="Sem 1 Duplicate")

    def test_duplicate_subject_category_code_within_college_rejected(self):
        SubjectCategory.objects.create(college=self.college, code="MAJOR", name="Major")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SubjectCategory.objects.create(college=self.college, code="MAJOR", name="Major Duplicate")

    def test_duplicate_subject_code_within_department_rejected(self):
        dept = Department.objects.create(college=self.college, name="Math", code="MATH")
        Subject.objects.create(department=dept, name="Calculus", code="CALC")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Subject.objects.create(department=dept, name="Advanced Calc", code="CALC")

    def test_duplicate_paper_code_within_session_rejected(self):
        session = AcademicSession.objects.create(
            college=self.college, name="2026-2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30)
        )
        prog = Programme.objects.create(college=self.college, name="BA", code="BA")
        sem = Semester.objects.create(programme=prog, semester_number=1, name="Sem 1")
        dept = Department.objects.create(college=self.college, name="Pol Sci", code="POL")
        sub = Subject.objects.create(department=dept, name="Pol Sci", code="POLSCI")
        cat = SubjectCategory.objects.create(college=self.college, code="MAJOR", name="Major")

        PaperOffering.objects.create(
            academic_session=session,
            semester=sem,
            subject=sub,
            subject_category=cat,
            paper_code="POL1014",
            title="Paper 1",
            credits=Decimal("4.0"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaperOffering.objects.create(
                    academic_session=session,
                    semester=sem,
                    subject=sub,
                    subject_category=cat,
                    paper_code="POL1014",  # Duplicate paper code in same session
                    title="Paper 2",
                    credits=Decimal("4.0"),
                )

    def test_referential_integrity_restrict_deletions(self):
        dept = Department.objects.create(college=self.college, name="Pol Sci", code="POL")
        sub = Subject.objects.create(department=dept, name="Pol Sci", code="POLSCI")

        # Deleting department when subject references it must raise ProtectedError / RestrictedError
        with self.assertRaises((models.ProtectedError, models.RestrictedError)):
            dept.delete()

        # Deleting college when department references it must raise ProtectedError / RestrictedError
        with self.assertRaises((models.ProtectedError, models.RestrictedError)):
            self.college.delete()

    def test_cascade_paper_programme_mapping_deletion(self):
        session = AcademicSession.objects.create(
            college=self.college, name="2026-2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30)
        )
        prog = Programme.objects.create(college=self.college, name="BA", code="BA")
        sem = Semester.objects.create(programme=prog, semester_number=1, name="Sem 1")
        dept = Department.objects.create(college=self.college, name="Pol Sci", code="POL")
        sub = Subject.objects.create(department=dept, name="Pol Sci", code="POLSCI")
        cat = SubjectCategory.objects.create(college=self.college, code="VAC", name="VAC")

        offering = PaperOffering.objects.create(
            academic_session=session,
            semester=sem,
            subject=sub,
            subject_category=cat,
            paper_code="VAC101",
            title="Environmental Studies",
            credits=Decimal("2.0"),
            is_common_paper=True,
        )
        mapping = PaperProgrammeMapping.objects.create(paper_offering=offering, programme=prog)
        mapping_id = mapping.id

        # Deleting paper offering should CASCADE and delete the mapping
        offering.delete()
        self.assertFalse(PaperProgrammeMapping.objects.filter(id=mapping_id).exists())


class AcademicServicesTests(TestCase):
    """Tests service functions and transactional operations."""

    def setUp(self):
        self.college = College.objects.create(
            name="Model College", code="MC-GU", contact_email="admin@mc.edu"
        )
        self.superadmin = User.objects.create_superuser(
            username="super_service",
            email="super_service@mc.edu",
            password="StrongPassword123!",
            role=RoleChoices.SUPERADMIN,
        )
        self.session1 = AcademicSession.objects.create(
            college=self.college, name="2025-2026", start_date=date(2025, 7, 1), end_date=date(2026, 6, 30), is_current=True
        )
        self.session2 = AcademicSession.objects.create(
            college=self.college, name="2026-2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30), is_current=False
        )

    def test_set_current_academic_session_atomic(self):
        set_current_academic_session(self.college, self.session2)
        self.session1.refresh_from_db()
        self.session2.refresh_from_db()
        self.assertFalse(self.session1.is_current)
        self.assertTrue(self.session2.is_current)

    def test_set_current_academic_session_cross_college_rejected(self):
        other_college = College.objects.create(
            name="Other College", code="OC-GU", contact_email="admin@oc.edu"
        )
        with self.assertRaises(ValidationError):
            set_current_academic_session(other_college, self.session2)

    def test_map_paper_to_programmes_service(self):
        prog_ba = Programme.objects.create(college=self.college, name="BA", code="BA", duration_semesters=8)
        prog_bsc = Programme.objects.create(college=self.college, name="BSc", code="BSC", duration_semesters=6)
        sem = Semester.objects.create(programme=prog_ba, semester_number=2, name="Sem 2")
        dept = Department.objects.create(college=self.college, name="Env", code="ENV")
        sub = Subject.objects.create(department=dept, name="Env Studies", code="ENVS")
        cat = SubjectCategory.objects.create(college=self.college, code="VAC", name="VAC", min_credits=Decimal("2.0"), max_credits=Decimal("2.0"))

        offering = create_paper_offering(
            academic_session=self.session2,
            semester=sem,
            subject=sub,
            subject_category=cat,
            paper_code="ENV1022",
            title="Environmental Studies",
            credits=Decimal("2.0"),
            is_common_paper=False,
        )
        self.assertFalse(offering.is_common_paper)

        mappings = map_paper_to_programmes(offering, [prog_ba, prog_bsc])
        self.assertEqual(len(mappings), 2)
        offering.refresh_from_db()
        self.assertTrue(offering.is_common_paper)

    def test_map_paper_cross_college_rejected(self):
        other_college = College.objects.create(name="Other College", code="OC-GU", contact_email="admin@oc.edu")
        prog_other = Programme.objects.create(college=other_college, name="BCom", code="BCOM", duration_semesters=6)
        prog_ba = Programme.objects.create(college=self.college, name="BA", code="BA", duration_semesters=8)
        sem = Semester.objects.create(programme=prog_ba, semester_number=1, name="Sem 1")
        dept = Department.objects.create(college=self.college, name="Env", code="ENV")
        sub = Subject.objects.create(department=dept, name="Env Studies", code="ENVS")
        cat = SubjectCategory.objects.create(college=self.college, code="VAC", name="VAC")

        offering = create_paper_offering(
            academic_session=self.session2,
            semester=sem,
            subject=sub,
            subject_category=cat,
            paper_code="VAC101",
            title="Env",
            credits=Decimal("2.0"),
        )
        with self.assertRaises(ValidationError) as cm:
            map_paper_to_programmes(offering, [prog_other])
        self.assertTrue("programme" in cm.exception.message_dict or "programmes" in cm.exception.message_dict)

    def test_set_institutional_config_service(self):
        cfg = set_institutional_config(
            college=self.college,
            config_key="OFFICIAL_GRADING_SCALE",
            config_value=json.dumps({"O": 10, "A+": 9}),
            data_type=ConfigDataType.JSON,
            is_sensitive=True,
            description="Official GU 10-point scale",
            user=self.superadmin,
        )
        self.assertEqual(cfg.config_key, "OFFICIAL_GRADING_SCALE")
        self.assertTrue(cfg.is_sensitive)
        self.assertEqual(cfg.updated_by, self.superadmin)


class AcademicAuthorizationTests(TestCase):
    """
    Tests institutional RBAC enforcement across API endpoints.
    Verifies that:
    - Administrators have full mutation authority.
    - Faculty and Students have read-only access to the academic catalogue.
    - Anonymous users receive 401 Unauthorized.
    - is_staff=True alone NEVER grants administrative access (Finding B defense).
    - Students and Faculty are strictly barred from InstitutionalConfig endpoints.
    """

    def setUp(self):
        self.client = APIClient()
        self.college = College.objects.create(
            name="Model College", code="MC-GU", contact_email="admin@mc.edu"
        )
        self.session = AcademicSession.objects.create(
            college=self.college, name="2026-2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30)
        )

        # Users
        self.admin_user = User.objects.create_user(
            username="admin_user",
            email="admin@mc.edu",
            password="StrongAdminPassword123!",
            role=RoleChoices.ADMIN,
            is_active=True,
        )
        self.superadmin_user = User.objects.create_superuser(
            username="superadmin_user",
            email="superadmin@mc.edu",
            password="StrongSuperAdminPassword123!",
        )
        self.faculty_user = User.objects.create_user(
            username="faculty_user",
            email="faculty@mc.edu",
            password="StrongFacultyPassword123!",
            role=RoleChoices.FACULTY,
            is_active=True,
        )
        self.student_user = User.objects.create_user(
            username="student_user",
            email="student@mc.edu",
            password="StrongStudentPassword123!",
            role=RoleChoices.STUDENT,
            is_active=True,
        )
        # Escalation attacker: Student with is_staff=True
        self.staff_student_user = User.objects.create_user(
            username="staff_student",
            email="staff_student@mc.edu",
            password="StrongPassword123!",
            role=RoleChoices.STUDENT,
            is_active=True,
        )
        self.staff_student_user.is_staff = True
        self.staff_student_user.save()

    def test_anonymous_access_denied_401(self):
        url = reverse("academics:college-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_catalogue_read_access(self):
        url = reverse("academics:college-list")

        # Admin can read
        self.client.force_authenticate(user=self.admin_user)
        res_admin = self.client.get(url)
        self.assertEqual(res_admin.status_code, status.HTTP_200_OK)

        # Faculty can read
        self.client.force_authenticate(user=self.faculty_user)
        res_fac = self.client.get(url)
        self.assertEqual(res_fac.status_code, status.HTTP_200_OK)

        # Student can read
        self.client.force_authenticate(user=self.student_user)
        res_stu = self.client.get(url)
        self.assertEqual(res_stu.status_code, status.HTTP_200_OK)

    def test_faculty_cannot_mutate_academic_records_403(self):
        self.client.force_authenticate(user=self.faculty_user)
        url = reverse("academics:programme-list")
        data = {
            "college": self.college.id,
            "name": "Unauthorized Programme",
            "code": "UNAUTH",
            "duration_semesters": 8,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_student_cannot_mutate_academic_records_403(self):
        self.client.force_authenticate(user=self.student_user)
        url = reverse("academics:programme-list")
        data = {
            "college": self.college.id,
            "name": "Student Hack Programme",
            "code": "HACK",
            "duration_semesters": 8,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_is_staff_alone_does_not_grant_admin_access_403(self):
        """Verifies that is_staff=True on a student account cannot create academic records."""
        self.client.force_authenticate(user=self.staff_student_user)
        url = reverse("academics:programme-list")
        data = {
            "college": self.college.id,
            "name": "Escalated Programme",
            "code": "ESCAL",
            "duration_semesters": 8,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_mutate_academic_records_201(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("academics:programme-list")
        data = {
            "college": self.college.id,
            "name": "Bachelor of Commerce (FYUGP)",
            "code": "BCOM-FYUGP",
            "duration_semesters": 8,
            "degree_type": "UNDERGRADUATE",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["code"], "BCOM-FYUGP")

    def test_institutional_config_access_isolation(self):
        config = InstitutionalConfig.objects.create(
            college=self.college,
            config_key="EVIDENCE_KEY_RETENTION",
            config_value="90",
            data_type=ConfigDataType.INTEGER,
            is_sensitive=True,
        )
        url = reverse("academics:institutional-config-detail", kwargs={"pk": config.id})

        # Student denied 403
        self.client.force_authenticate(user=self.student_user)
        res_stu = self.client.get(url)
        self.assertEqual(res_stu.status_code, status.HTTP_403_FORBIDDEN)

        # Faculty denied 403
        self.client.force_authenticate(user=self.faculty_user)
        res_fac = self.client.get(url)
        self.assertEqual(res_fac.status_code, status.HTTP_403_FORBIDDEN)

        # Admin gets 200, but sensitive value is masked
        self.client.force_authenticate(user=self.admin_user)
        res_adm = self.client.get(url)
        self.assertEqual(res_adm.status_code, status.HTTP_200_OK)
        self.assertEqual(res_adm.data["config_value"], "********")

        # SuperAdmin gets 200 with raw value
        self.client.force_authenticate(user=self.superadmin_user)
        res_super = self.client.get(url)
        self.assertEqual(res_super.status_code, status.HTTP_200_OK)
        self.assertEqual(res_super.data["config_value"], "90")

        # Admin cannot mutate sensitive config (403)
        self.client.force_authenticate(user=self.admin_user)
        res_adm_mutate = self.client.patch(url, {"config_value": "120"})
        self.assertEqual(res_adm_mutate.status_code, status.HTTP_403_FORBIDDEN)

        # Superadmin can mutate sensitive config (200)
        self.client.force_authenticate(user=self.superadmin_user)
        res_super_mutate = self.client.patch(url, {"config_value": "120"})
        self.assertEqual(res_super_mutate.status_code, status.HTTP_200_OK)
        config.refresh_from_db()
        self.assertEqual(config.config_value, "120")


class AcademicAPIOperationsTests(TestCase):
    """Tests end-to-end REST API workflows, actions, and conflict errors."""

    def setUp(self):
        self.client = APIClient()
        self.college = College.objects.create(
            name="Model College", code="MC-GU", contact_email="admin@mc.edu"
        )
        self.session = AcademicSession.objects.create(
            college=self.college, name="2026-2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30)
        )
        self.admin = User.objects.create_user(
            username="admin", email="admin@mc.edu", password="StrongPassword123!", role=RoleChoices.ADMIN, is_active=True
        )
        self.client.force_authenticate(user=self.admin)

    def test_academic_session_set_current_action(self):
        session2 = AcademicSession.objects.create(
            college=self.college, name="2027-2028", start_date=date(2027, 7, 1), end_date=date(2028, 6, 30), is_current=False
        )
        url = reverse("academics:session-set-current", kwargs={"pk": session2.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        session2.refresh_from_db()
        self.assertTrue(session2.is_current)

    def test_paper_offering_map_programmes_action(self):
        prog1 = Programme.objects.create(college=self.college, name="BA", code="BA", duration_semesters=8)
        prog2 = Programme.objects.create(college=self.college, name="BSc", code="BSC", duration_semesters=6)
        sem = Semester.objects.create(programme=prog1, semester_number=1, name="Sem 1")
        dept = Department.objects.create(college=self.college, name="Env", code="ENV")
        sub = Subject.objects.create(department=dept, name="Env Studies", code="ENVS")
        cat = SubjectCategory.objects.create(college=self.college, code="VAC", name="VAC")

        offering = PaperOffering.objects.create(
            academic_session=self.session,
            semester=sem,
            subject=sub,
            subject_category=cat,
            paper_code="VAC101",
            title="Environmental Studies",
            credits=Decimal("2.0"),
        )
        url = reverse("academics:paper-offering-map-programmes", kwargs={"pk": offering.id})
        data = {"programme_ids": [prog1.id, prog2.id], "replace": True}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        offering.refresh_from_db()
        self.assertTrue(offering.is_common_paper)

    def test_delete_referenced_entity_returns_409_conflict(self):
        prog = Programme.objects.create(college=self.college, name="BA", code="BA")
        Semester.objects.create(programme=prog, semester_number=1, name="Sem 1")

        url = reverse("academics:programme-detail", kwargs={"pk": prog.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"]["code"], "RESOURCE_CONFLICT")
        self.assertIn("referenced by existing academic data", response.data["error"]["message"])



class ZeroValuedPatchValidationRegressionTests(TestCase):
    """
    HIGH Finding A Regression Tests:
    Verifies that explicit field-presence checks prevent invalid zero-valued PATCH updates
    from bypassing validation, and that model-level complete-state validation is enforced.
    """

    def setUp(self):
        self.client = APIClient()
        self.college = College.objects.create(
            name="Model College", code="MC-GU", contact_email="admin@mc.edu"
        )
        self.session = AcademicSession.objects.create(
            college=self.college,
            name="2026-2027",
            start_date=date(2026, 7, 1),
            end_date=date(2027, 6, 30),
        )
        self.prog = Programme.objects.create(
            college=self.college, name="BA", code="BA", duration_semesters=8
        )
        self.sem = Semester.objects.create(programme=self.prog, semester_number=1, name="Sem 1")
        self.dept = Department.objects.create(college=self.college, name="Pol Sci", code="POL")
        self.sub = Subject.objects.create(department=self.dept, name="Pol Sci", code="POLSCI")
        self.cat = SubjectCategory.objects.create(
            college=self.college,
            code="MAJOR",
            name="Major",
            min_credits=Decimal("2.0"),
            max_credits=Decimal("4.0"),
        )
        self.offering = PaperOffering.objects.create(
            academic_session=self.session,
            semester=self.sem,
            subject=self.sub,
            subject_category=self.cat,
            paper_code="POL1014",
            title="Political Theory",
            credits=Decimal("4.0"),
            max_marks_internal=Decimal("20.00"),
            max_marks_external=Decimal("80.00"),
            pass_marks_external=Decimal("28.00"),
        )
        self.admin = User.objects.create_user(
            username="admin", email="admin@mc.edu", password="Password123!", role=RoleChoices.ADMIN, is_active=True
        )
        self.client.force_authenticate(user=self.admin)
        self.url = reverse("academics:paper-offering-detail", kwargs={"pk": self.offering.id})

    def test_patch_max_marks_external_zero_with_positive_pass_marks_rejected(self):
        """PATCH max_marks_external=0 while pass_marks_external is 28 must be rejected with 400."""
        response = self.client.patch(self.url, {"max_marks_external": "0.00"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.offering.refresh_from_db()
        self.assertEqual(self.offering.max_marks_external, Decimal("80.00"))

    def test_patch_max_marks_external_zero_and_pass_marks_zero_accepted(self):
        """PATCH max_marks_external=0 and pass_marks_external=0 simultaneously is valid (e.g. non-credit/internal only)."""
        response = self.client.patch(self.url, {"max_marks_external": "0.00", "pass_marks_external": "0.00"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.offering.refresh_from_db()
        self.assertEqual(self.offering.max_marks_external, Decimal("0.00"))
        self.assertEqual(self.offering.pass_marks_external, Decimal("0.00"))

    def test_patch_max_marks_internal_zero_accepted(self):
        """PATCH max_marks_internal=0 is valid."""
        response = self.client.patch(self.url, {"max_marks_internal": "0.00"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.offering.refresh_from_db()
        self.assertEqual(self.offering.max_marks_internal, Decimal("0.00"))

    def test_patch_pass_marks_external_zero_accepted(self):
        """PATCH pass_marks_external=0 with positive max_marks_external is valid."""
        response = self.client.patch(self.url, {"pass_marks_external": "0.00"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.offering.refresh_from_db()
        self.assertEqual(self.offering.pass_marks_external, Decimal("0.00"))

    def test_patch_credits_zero_outside_category_bounds_rejected(self):
        """PATCH credits=0 when category min_credits=2.0 must be rejected with 400."""
        response = self.client.patch(self.url, {"credits": "0.0"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.offering.refresh_from_db()
        self.assertEqual(self.offering.credits, Decimal("4.0"))

    def test_patch_credits_zero_inside_category_bounds_accepted(self):
        """PATCH credits=0 when category min_credits=0.0 must be accepted."""
        zero_cat = SubjectCategory.objects.create(
            college=self.college, code="NONCREDIT", name="Non Credit", min_credits=Decimal("0.0"), max_credits=Decimal("2.0")
        )
        self.offering.subject_category = zero_cat
        self.offering.save()

        response = self.client.patch(self.url, {"credits": "0.0"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.offering.refresh_from_db()
        self.assertEqual(self.offering.credits, Decimal("0.0"))

    def test_patch_category_min_credits_zero_accepted(self):
        """PATCH min_credits=0 on SubjectCategory must be accepted."""
        cat_url = reverse("academics:subject-category-detail", kwargs={"pk": self.cat.id})
        response = self.client.patch(cat_url, {"min_credits": "0.0"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.cat.refresh_from_db()
        self.assertEqual(self.cat.min_credits, Decimal("0.0"))

    def test_patch_category_max_credits_zero_with_positive_min_credits_rejected(self):
        """PATCH max_credits=0 on SubjectCategory when min_credits=2.0 must be rejected."""
        cat_url = reverse("academics:subject-category-detail", kwargs={"pk": self.cat.id})
        response = self.client.patch(cat_url, {"max_credits": "0.0"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.cat.refresh_from_db()
        self.assertEqual(self.cat.max_credits, Decimal("4.0"))

    def test_patch_semester_number_outside_programme_duration_rejected(self):
        """PATCH semester_number exceeding programme duration must be rejected."""
        sem_url = reverse("academics:semester-detail", kwargs={"pk": self.sem.id})
        response = self.client.patch(sem_url, {"semester_number": 9})  # Duration is 8
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.sem.refresh_from_db()
        self.assertEqual(self.sem.semester_number, 1)

    def test_patch_paper_cross_college_semester_rejected(self):
        """PATCH offering semester to a semester from another college must be rejected."""
        other_college = College.objects.create(name="Other College", code="OC-GU", contact_email="admin@oc.edu")
        other_prog = Programme.objects.create(college=other_college, name="Other BA", code="OBA", duration_semesters=8)
        other_sem = Semester.objects.create(programme=other_prog, semester_number=1, name="Other Sem 1")

        response = self.client.patch(self.url, {"semester": other_sem.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.offering.refresh_from_db()
        self.assertEqual(self.offering.semester.id, self.sem.id)

    def test_patch_omitted_fields_preserve_existing_values(self):
        """PATCH title only must preserve all numeric and relational attributes."""
        response = self.client.patch(self.url, {"title": "Updated Title"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.offering.refresh_from_db()
        self.assertEqual(self.offering.title, "Updated Title")
        self.assertEqual(self.offering.max_marks_external, Decimal("80.00"))
        self.assertEqual(self.offering.pass_marks_external, Decimal("28.00"))
        self.assertEqual(self.offering.credits, Decimal("4.0"))


class SensitiveInstitutionalConfigAuthorizationRegressionTests(TestCase):
    """
    HIGH Finding B Regression Tests:
    Verifies that ordinary administrators cannot create, modify, or downgrade sensitive
    institutional configurations, while superadministrators retain full authority.
    """

    def setUp(self):
        self.client = APIClient()
        self.college = College.objects.create(
            name="Model College", code="MC-GU", contact_email="admin@mc.edu"
        )
        self.admin = User.objects.create_user(
            username="admin", email="admin@mc.edu", password="Password123!", role=RoleChoices.ADMIN, is_active=True
        )
        self.superadmin = User.objects.create_superuser(
            username="superadmin", email="superadmin@mc.edu", password="Password123!"
        )
        self.staff_student = User.objects.create_user(
            username="staff_student", email="staff_student@mc.edu", password="Password123!", role=RoleChoices.STUDENT, is_active=True
        )
        self.staff_student.is_staff = True
        self.staff_student.save()

        self.list_url = reverse("academics:institutional-config-list")

    def test_admin_creates_nonsensitive_config_permitted(self):
        self.client.force_authenticate(user=self.admin)
        data = {
            "college": self.college.id,
            "config_key": "PORTAL_NAME",
            "config_value": "MC Exam Portal",
            "data_type": "STRING",
            "is_sensitive": False,
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_admin_creates_sensitive_config_rejected_403(self):
        self.client.force_authenticate(user=self.admin)
        data = {
            "college": self.college.id,
            "config_key": "MASTER_SECRET",
            "config_value": "super_secret_value",
            "data_type": "STRING",
            "is_sensitive": True,
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(InstitutionalConfig.objects.filter(config_key="MASTER_SECRET").exists())

    def test_superadmin_creates_sensitive_config_permitted_201(self):
        self.client.force_authenticate(user=self.superadmin)
        data = {
            "college": self.college.id,
            "config_key": "MASTER_SECRET",
            "config_value": "super_secret_value",
            "data_type": "STRING",
            "is_sensitive": True,
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(InstitutionalConfig.objects.filter(config_key="MASTER_SECRET", is_sensitive=True).exists())

    def test_admin_changes_nonsensitive_to_sensitive_rejected_403(self):
        cfg = InstitutionalConfig.objects.create(
            college=self.college, config_key="SETTING_A", config_value="val", is_sensitive=False
        )
        url = reverse("academics:institutional-config-detail", kwargs={"pk": cfg.id})
        self.client.force_authenticate(user=self.admin)

        response = self.client.patch(url, {"is_sensitive": True})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        cfg.refresh_from_db()
        self.assertFalse(cfg.is_sensitive)

    def test_admin_changes_sensitive_to_nonsensitive_rejected_403(self):
        cfg = InstitutionalConfig.objects.create(
            college=self.college, config_key="SETTING_B", config_value="secret", is_sensitive=True
        )
        url = reverse("academics:institutional-config-detail", kwargs={"pk": cfg.id})
        self.client.force_authenticate(user=self.admin)

        response = self.client.patch(url, {"is_sensitive": False})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        cfg.refresh_from_db()
        self.assertTrue(cfg.is_sensitive)

    def test_admin_updates_sensitive_config_value_rejected_403(self):
        cfg = InstitutionalConfig.objects.create(
            college=self.college, config_key="SETTING_C", config_value="secret", is_sensitive=True
        )
        url = reverse("academics:institutional-config-detail", kwargs={"pk": cfg.id})
        self.client.force_authenticate(user=self.admin)

        response = self.client.patch(url, {"config_value": "tampered"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        cfg.refresh_from_db()
        self.assertEqual(cfg.config_value, "secret")

    def test_admin_deletes_sensitive_config_rejected_403(self):
        cfg = InstitutionalConfig.objects.create(
            college=self.college, config_key="SETTING_D", config_value="secret", is_sensitive=True
        )
        url = reverse("academics:institutional-config-detail", kwargs={"pk": cfg.id})
        self.client.force_authenticate(user=self.admin)

        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(InstitutionalConfig.objects.filter(pk=cfg.id).exists())

    def test_superadmin_updates_sensitive_config_permitted_200(self):
        cfg = InstitutionalConfig.objects.create(
            college=self.college, config_key="SETTING_E", config_value="secret", is_sensitive=True
        )
        url = reverse("academics:institutional-config-detail", kwargs={"pk": cfg.id})
        self.client.force_authenticate(user=self.superadmin)

        response = self.client.patch(url, {"config_value": "new_secret"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        cfg.refresh_from_db()
        self.assertEqual(cfg.config_value, "new_secret")

    def test_student_with_is_staff_denied_403(self):
        self.client.force_authenticate(user=self.staff_student)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_attempted_sensitivity_downgrade_does_not_expose_original_value(self):
        cfg = InstitutionalConfig.objects.create(
            college=self.college, config_key="SECRET_KEY", config_value="actual_secret", is_sensitive=True
        )
        url = reverse("academics:institutional-config-detail", kwargs={"pk": cfg.id})
        self.client.force_authenticate(user=self.admin)

        response = self.client.patch(url, {"is_sensitive": False})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn("actual_secret", str(response.content))

    def test_direct_service_sensitive_config_checks_authorization(self):
        from rest_framework.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            set_institutional_config(
                college=self.college,
                config_key="SERVICE_SECRET",
                config_value="secret",
                is_sensitive=True,
                user=self.admin,
            )


class AcademicSessionCurrentStateIntegrityRegressionTests(TestCase):
    """
    MEDIUM Finding C Regression Tests:
    Verifies that is_current is read-only in ordinary CRUD endpoints, that the dedicated
    set-current action exclusively switches sessions, and that row-locking coordinates concurrent changes.
    """

    def setUp(self):
        self.client = APIClient()
        self.college = College.objects.create(
            name="Model College", code="MC-GU", contact_email="admin@mc.edu"
        )
        self.session1 = AcademicSession.objects.create(
            college=self.college, name="2025-2026", start_date=date(2025, 7, 1), end_date=date(2026, 6, 30), is_current=True
        )
        self.session2 = AcademicSession.objects.create(
            college=self.college, name="2026-2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30), is_current=False
        )
        self.admin = User.objects.create_user(
            username="admin", email="admin@mc.edu", password="Password123!", role=RoleChoices.ADMIN, is_active=True
        )
        self.client.force_authenticate(user=self.admin)
        self.list_url = reverse("academics:session-list")
        self.detail_url2 = reverse("academics:session-detail", kwargs={"pk": self.session2.id})

    def test_ordinary_post_with_is_current_true_rejected_400(self):
        data = {
            "college": self.college.id,
            "name": "2027-2028",
            "start_date": "2027-07-01",
            "end_date": "2028-06-30",
            "is_current": True,
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("is_current", str(response.data))

    def test_ordinary_patch_with_is_current_true_rejected_400(self):
        response = self.client.patch(self.detail_url2, {"is_current": True})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.session2.refresh_from_db()
        self.assertFalse(self.session2.is_current)

    def test_ordinary_patch_with_is_current_false_rejected_400(self):
        detail_url1 = reverse("academics:session-detail", kwargs={"pk": self.session1.id})
        response = self.client.patch(detail_url1, {"is_current": False})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.session1.refresh_from_db()
        self.assertTrue(self.session1.is_current)

    def test_newly_created_session_defaults_to_noncurrent(self):
        data = {
            "college": self.college.id,
            "name": "2028-2029",
            "start_date": "2028-07-01",
            "end_date": "2029-06-30",
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        new_session = AcademicSession.objects.get(name="2028-2029")
        self.assertFalse(new_session.is_current)

    def test_dedicated_set_current_action_activates_session(self):
        url = reverse("academics:session-set-current", kwargs={"pk": self.session2.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.session1.refresh_from_db()
        self.session2.refresh_from_db()
        self.assertFalse(self.session1.is_current)
        self.assertTrue(self.session2.is_current)

    def test_exactly_one_session_is_current_after_sequential_switches(self):
        session3 = AcademicSession.objects.create(
            college=self.college, name="2027-2028", start_date=date(2027, 7, 1), end_date=date(2028, 6, 30), is_current=False
        )
        url2 = reverse("academics:session-set-current", kwargs={"pk": self.session2.id})
        url3 = reverse("academics:session-set-current", kwargs={"pk": session3.id})

        self.client.post(url2)
        self.client.post(url3)

        current_count = AcademicSession.objects.filter(college=self.college, is_current=True).count()
        self.assertEqual(current_count, 1)
        session3.refresh_from_db()
        self.assertTrue(session3.is_current)

    def test_other_college_current_session_is_unaffected(self):
        other_college = College.objects.create(name="Other College", code="OC-GU", contact_email="admin@oc.edu")
        other_session = AcademicSession.objects.create(
            college=other_college, name="2026-2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30), is_current=True
        )

        url = reverse("academics:session-set-current", kwargs={"pk": self.session2.id})
        self.client.post(url)

        other_session.refresh_from_db()
        self.assertTrue(other_session.is_current)

    def test_cross_college_session_selection_rejected_400(self):
        other_college = College.objects.create(name="Other College", code="OC-GU", contact_email="admin@oc.edu")
        other_session = AcademicSession.objects.create(
            college=other_college, name="2026-2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30), is_current=False
        )
        with self.assertRaises(ValidationError):
            set_current_academic_session(self.college, other_session)


class PaperProgrammeMappingIntegrityRegressionTests(TestCase):
    """
    MEDIUM Finding D Regression Tests:
    Verifies that direct CRUD operations on PaperProgrammeMapping enforce same-college
    and duration-coverage rules, matching the service layer invariants.
    """

    def setUp(self):
        self.client = APIClient()
        self.college = College.objects.create(
            name="Model College", code="MC-GU", contact_email="admin@mc.edu"
        )
        self.session = AcademicSession.objects.create(
            college=self.college, name="2026-2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30)
        )
        self.prog_8sem = Programme.objects.create(
            college=self.college, name="BA (Honours)", code="BA-HON", duration_semesters=8
        )
        self.prog_2sem = Programme.objects.create(
            college=self.college, name="Diploma (1 Year)", code="DIP-1YR", duration_semesters=2
        )
        self.sem_4 = Semester.objects.create(programme=self.prog_8sem, semester_number=4, name="Sem 4")
        self.dept = Department.objects.create(college=self.college, name="Env", code="ENV")
        self.sub = Subject.objects.create(department=self.dept, name="Env Studies", code="ENVS")
        self.cat = SubjectCategory.objects.create(college=self.college, code="VAC", name="VAC")

        self.offering = PaperOffering.objects.create(
            academic_session=self.session,
            semester=self.sem_4,
            subject=self.sub,
            subject_category=self.cat,
            paper_code="VAC204",
            title="Advanced Environmental Studies",
            credits=Decimal("2.0"),
            is_common_paper=False,
        )
        self.admin = User.objects.create_user(
            username="admin", email="admin@mc.edu", password="Password123!", role=RoleChoices.ADMIN, is_active=True
        )
        self.client.force_authenticate(user=self.admin)
        self.list_url = reverse("academics:paper-mapping-list")

    def test_valid_same_college_direct_post_succeeds_201(self):
        prog_6sem = Programme.objects.create(
            college=self.college, name="BSc Regular", code="BSC-REG", duration_semesters=6
        )
        data = {
            "paper_offering": self.offering.id,
            "programme": prog_6sem.id,
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.offering.refresh_from_db()
        self.assertTrue(self.offering.is_common_paper)

    def test_cross_college_direct_post_rejected_400(self):
        other_college = College.objects.create(name="Other College", code="OC-GU", contact_email="admin@oc.edu")
        prog_other = Programme.objects.create(
            college=other_college, name="Other Prog", code="OP", duration_semesters=8
        )
        data = {
            "paper_offering": self.offering.id,
            "programme": prog_other.id,
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(PaperProgrammeMapping.objects.filter(programme=prog_other).exists())

    def test_duration_shorter_than_offering_semester_direct_post_rejected_400(self):
        """Offering is for semester 4; mapping to a 2-semester programme must be rejected."""
        data = {
            "paper_offering": self.offering.id,
            "programme": self.prog_2sem.id,
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(PaperProgrammeMapping.objects.filter(programme=self.prog_2sem).exists())

    def test_direct_patch_enforces_same_rules(self):
        prog_6sem = Programme.objects.create(
            college=self.college, name="BSc", code="BSC", duration_semesters=6
        )
        mapping = PaperProgrammeMapping.objects.create(paper_offering=self.offering, programme=prog_6sem)
        detail_url = reverse("academics:paper-mapping-detail", kwargs={"pk": mapping.id})

        # Attempt to patch programme to short 2-semester programme
        response = self.client.patch(detail_url, {"programme": self.prog_2sem.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mapping.refresh_from_db()
        self.assertEqual(mapping.programme.id, prog_6sem.id)


class MapProgrammesReplaceBooleanAndExceptionSafetyRegressionTests(TestCase):
    """
    MEDIUM Finding E Regression Tests:
    Verifies that 'replace' strictly requires a genuine JSON boolean, that ambiguous strings
    and integers are rejected, that validation happens before any deletion, and that exception
    details are never leaked to clients.
    """

    def setUp(self):
        self.client = APIClient()
        self.college = College.objects.create(
            name="Model College", code="MC-GU", contact_email="admin@mc.edu"
        )
        self.session = AcademicSession.objects.create(
            college=self.college, name="2026-2027", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30)
        )
        self.prog1 = Programme.objects.create(college=self.college, name="BA", code="BA", duration_semesters=8)
        self.prog2 = Programme.objects.create(college=self.college, name="BSc", code="BSC", duration_semesters=6)
        self.prog3 = Programme.objects.create(college=self.college, name="BCom", code="BCOM", duration_semesters=6)
        self.sem = Semester.objects.create(programme=self.prog1, semester_number=1, name="Sem 1")
        self.dept = Department.objects.create(college=self.college, name="Env", code="ENV")
        self.sub = Subject.objects.create(department=self.dept, name="Env Studies", code="ENVS")
        self.cat = SubjectCategory.objects.create(college=self.college, code="VAC", name="VAC")

        self.offering = PaperOffering.objects.create(
            academic_session=self.session,
            semester=self.sem,
            subject=self.sub,
            subject_category=self.cat,
            paper_code="VAC101",
            title="Environmental Studies",
            credits=Decimal("2.0"),
        )
        # Pre-existing mapping
        self.mapping1 = PaperProgrammeMapping.objects.create(paper_offering=self.offering, programme=self.prog1)

        self.admin = User.objects.create_user(
            username="admin", email="admin@mc.edu", password="Password123!", role=RoleChoices.ADMIN, is_active=True
        )
        self.client.force_authenticate(user=self.admin)
        self.url = reverse("academics:paper-offering-map-programmes", kwargs={"pk": self.offering.id})

    def test_replace_false_retains_existing_mappings(self):
        data = {"programme_ids": [self.prog2.id], "replace": False}
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(PaperProgrammeMapping.objects.filter(paper_offering=self.offering).count(), 2)

    def test_replace_true_performs_authorized_replacement(self):
        data = {"programme_ids": [self.prog2.id, self.prog3.id], "replace": True}
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        current_progs = set(PaperProgrammeMapping.objects.filter(paper_offering=self.offering).values_list("programme_id", flat=True))
        self.assertEqual(current_progs, {self.prog2.id, self.prog3.id})
        self.assertNotIn(self.prog1.id, current_progs)

    def test_replace_string_false_rejected_no_deletion(self):
        """String 'false' must be rejected with 400 and existing mappings must NOT be deleted."""
        data = {"programme_ids": [self.prog2.id], "replace": "false"}
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Verify original mapping was preserved
        self.assertTrue(PaperProgrammeMapping.objects.filter(pk=self.mapping1.id).exists())

    def test_replace_string_true_rejected_no_deletion(self):
        data = {"programme_ids": [self.prog2.id], "replace": "true"}
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(PaperProgrammeMapping.objects.filter(pk=self.mapping1.id).exists())

    def test_replace_number_zero_rejected_no_deletion(self):
        data = {"programme_ids": [self.prog2.id], "replace": 0}
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(PaperProgrammeMapping.objects.filter(pk=self.mapping1.id).exists())

    def test_replace_number_one_rejected_no_deletion(self):
        data = {"programme_ids": [self.prog2.id], "replace": 1}
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(PaperProgrammeMapping.objects.filter(pk=self.mapping1.id).exists())

    def test_replace_omitted_defaults_to_false(self):
        data = {"programme_ids": [self.prog2.id]}
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # prog1 retained, prog2 added
        self.assertEqual(PaperProgrammeMapping.objects.filter(paper_offering=self.offering).count(), 2)

    def test_empty_programme_ids_rejected_400(self):
        data = {"programme_ids": []}
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_programme_ids_rejected_400(self):
        data = {"programme_ids": [self.prog2.id, self.prog2.id]}
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_programme_ids_rejected_400(self):
        data = {"programme_ids": [99999]}
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cross_college_programme_ids_rejected_400(self):
        other_college = College.objects.create(name="Other College", code="OC-GU", contact_email="admin@oc.edu")
        other_prog = Programme.objects.create(college=other_college, name="Other", code="OTH", duration_semesters=8)
        data = {"programme_ids": [other_prog.id], "replace": True}
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Original mapping preserved despite replace=True
        self.assertTrue(PaperProgrammeMapping.objects.filter(pk=self.mapping1.id).exists())

    def test_transaction_failure_preserves_original_mappings(self):
        other_college = College.objects.create(name="Other College", code="OC-GU", contact_email="admin@oc.edu")
        other_prog = Programme.objects.create(college=other_college, name="Other", code="OTH", duration_semesters=8)
        # Payload contains one valid and one cross-college programme with replace=True
        data = {"programme_ids": [self.prog2.id, other_prog.id], "replace": True}
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Original mapping MUST still exist
        self.assertTrue(PaperProgrammeMapping.objects.filter(pk=self.mapping1.id).exists())


class MandatoryInstitutionalConfigServiceAuthorizationRegressionTests(TestCase):
    """
    Round 3 Regression Tests for Finding A:
    Enforces mandatory user argument and RBAC authorization in set_institutional_config().
    """

    def setUp(self):
        self.college = College.objects.create(
            name="Model College", code="MC-GU", contact_email="admin@mc.edu"
        )
        self.superadmin = User.objects.create_superuser(
            username="super_user",
            email="super@mc.edu",
            password="StrongPassword123!",
            role=RoleChoices.SUPERADMIN,
        )
        self.admin = User.objects.create_user(
            username="admin_user",
            email="admin@mc.edu",
            password="StrongPassword123!",
            role=RoleChoices.ADMIN,
        )
        self.faculty = User.objects.create_user(
            username="faculty_user",
            email="faculty@mc.edu",
            password="StrongPassword123!",
            role=RoleChoices.FACULTY,
        )
        self.student = User.objects.create_user(
            username="student_user",
            email="student@mc.edu",
            password="StrongPassword123!",
            role=RoleChoices.STUDENT,
        )

    def test_admin_creates_nonsensitive_config_allowed(self):
        cfg = set_institutional_config(
            college=self.college,
            config_key="PORTAL_NAME",
            config_value="GU Portal",
            is_sensitive=False,
            user=self.admin,
        )
        self.assertEqual(cfg.config_key, "PORTAL_NAME")
        self.assertFalse(cfg.is_sensitive)
        self.assertEqual(cfg.updated_by, self.admin)

    def test_admin_creates_sensitive_config_denied(self):
        from rest_framework.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            set_institutional_config(
                college=self.college,
                config_key="API_SECRET",
                config_value="secret123",
                is_sensitive=True,
                user=self.admin,
            )

    def test_superadmin_creates_sensitive_config_allowed(self):
        cfg = set_institutional_config(
            college=self.college,
            config_key="API_SECRET",
            config_value="secret123",
            is_sensitive=True,
            user=self.superadmin,
        )
        self.assertEqual(cfg.config_key, "API_SECRET")
        self.assertTrue(cfg.is_sensitive)
        self.assertEqual(cfg.updated_by, self.superadmin)

    def test_admin_updates_nonsensitive_config_allowed(self):
        cfg = set_institutional_config(
            college=self.college,
            config_key="MAX_STUDENTS",
            config_value="100",
            data_type=ConfigDataType.INTEGER,
            is_sensitive=False,
            user=self.admin,
        )
        updated = set_institutional_config(
            college=self.college,
            config_key="MAX_STUDENTS",
            config_value="200",
            data_type=ConfigDataType.INTEGER,
            is_sensitive=False,
            user=self.admin,
        )
        self.assertEqual(updated.config_value, "200")
        self.assertEqual(updated.updated_by, self.admin)

    def test_admin_updates_sensitive_config_denied(self):
        from rest_framework.exceptions import PermissionDenied
        set_institutional_config(
            college=self.college,
            config_key="PAYMENT_GATEWAY_KEY",
            config_value="pg_secret",
            is_sensitive=True,
            user=self.superadmin,
        )
        with self.assertRaises(PermissionDenied):
            set_institutional_config(
                college=self.college,
                config_key="PAYMENT_GATEWAY_KEY",
                config_value="new_secret",
                is_sensitive=True,
                user=self.admin,
            )

    def test_admin_cannot_promote_nonsensitive_to_sensitive(self):
        from rest_framework.exceptions import PermissionDenied
        set_institutional_config(
            college=self.college,
            config_key="NOTICE_BOARD",
            config_value="Open to all",
            is_sensitive=False,
            user=self.admin,
        )
        with self.assertRaises(PermissionDenied):
            set_institutional_config(
                college=self.college,
                config_key="NOTICE_BOARD",
                config_value="Now confidential",
                is_sensitive=True,
                user=self.admin,
            )

    def test_admin_cannot_demote_sensitive_to_nonsensitive(self):
        from rest_framework.exceptions import PermissionDenied
        set_institutional_config(
            college=self.college,
            config_key="VAULT_PASSCODE",
            config_value="vault999",
            is_sensitive=True,
            user=self.superadmin,
        )
        with self.assertRaises(PermissionDenied):
            set_institutional_config(
                college=self.college,
                config_key="VAULT_PASSCODE",
                config_value="plaintext",
                is_sensitive=False,
                user=self.admin,
            )

    def test_student_invoking_service_denied(self):
        from rest_framework.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            set_institutional_config(
                college=self.college,
                config_key="STUDENT_KEY",
                config_value="val",
                user=self.student,
            )

    def test_faculty_invoking_service_denied(self):
        from rest_framework.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            set_institutional_config(
                college=self.college,
                config_key="FACULTY_KEY",
                config_value="val",
                user=self.faculty,
            )

    def test_student_with_is_staff_true_denied(self):
        from rest_framework.exceptions import PermissionDenied
        self.student.is_staff = True
        self.student.save()
        with self.assertRaises(PermissionDenied):
            set_institutional_config(
                college=self.college,
                config_key="ATTEMPT_BYPASS",
                config_value="val",
                user=self.student,
            )

    def test_faculty_with_is_staff_true_denied(self):
        from rest_framework.exceptions import PermissionDenied
        self.faculty.is_staff = True
        self.faculty.save()
        with self.assertRaises(PermissionDenied):
            set_institutional_config(
                college=self.college,
                config_key="ATTEMPT_BYPASS",
                config_value="val",
                user=self.faculty,
            )

    def test_anonymous_or_none_user_denied(self):
        from rest_framework.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            set_institutional_config(
                college=self.college,
                config_key="ANON_KEY",
                config_value="val",
                user=None,
            )
        anon = AnonymousUser()
        with self.assertRaises(PermissionDenied):
            set_institutional_config(
                college=self.college,
                config_key="ANON_KEY",
                config_value="val",
                user=anon,
            )

    def test_inactive_user_denied(self):
        from rest_framework.exceptions import PermissionDenied
        self.admin.is_active = False
        self.admin.save()
        with self.assertRaises(PermissionDenied):
            set_institutional_config(
                college=self.college,
                config_key="INACTIVE_KEY",
                config_value="val",
                user=self.admin,
            )

    def test_missing_user_kwarg_raises_typeerror(self):
        with self.assertRaises(TypeError):
            # user argument omitted
            set_institutional_config(
                self.college,
                "OMITTED_USER_KEY",
                "val",
            )

    def test_enforce_authorization_param_rejected(self):
        with self.assertRaises(TypeError):
            # enforce_authorization was removed from service signature
            set_institutional_config(
                college=self.college,
                config_key="PARAM_KEY",
                config_value="val",
                user=self.admin,
                enforce_authorization=False,
            )


class CommonPaperInvariantAndRowLockingRegressionTests(TestCase):
    """
    Round 3 Regression Tests for Finding B:
    Ensures that if paper offering has one or more programme mappings, is_common_paper MUST be True.
    Setting is_common_paper to False while mappings exist is rejected across API and model layers.
    Also verifies row-locking and atomic operations.
    """

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            username="admin_common",
            email="admin_common@mc.edu",
            password="StrongPassword123!",
            role=RoleChoices.SUPERADMIN,
        )
        self.client.force_authenticate(user=self.admin)

        self.college = College.objects.create(name="Model College", code="MC-GU", contact_email="admin@mc.edu")
        self.session = AcademicSession.objects.create(
            college=self.college, name="2025-2026", start_date=date(2025, 7, 1), end_date=date(2026, 6, 30), is_current=True
        )
        self.prog1 = Programme.objects.create(college=self.college, name="BA", code="BA", duration_semesters=8)
        self.prog2 = Programme.objects.create(college=self.college, name="BSc", code="BSC", duration_semesters=8)
        self.sem1 = Semester.objects.create(programme=self.prog1, semester_number=1, name="Sem 1")
        self.dept = Department.objects.create(college=self.college, name="Philosophy", code="PHIL")
        self.subject = Subject.objects.create(department=self.dept, name="Ethics", code="ETH101")
        self.category = SubjectCategory.objects.create(college=self.college, code="VAC", name="Value Added Course")

        self.offering = PaperOffering.objects.create(
            academic_session=self.session,
            semester=self.sem1,
            subject=self.subject,
            subject_category=self.category,
            paper_code="VAC101",
            title="Ethics in Public Life",
            credits=Decimal("2.0"),
            is_common_paper=False,
        )

    def test_unmapped_paper_can_have_is_common_paper_false(self):
        self.assertFalse(self.offering.is_common_paper)
        self.offering.full_clean()  # Should not raise

        url = reverse("academics:paper-offering-detail", kwargs={"pk": self.offering.id})
        res = self.client.patch(url, {"title": "Updated Title", "is_common_paper": False})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.offering.refresh_from_db()
        self.assertFalse(self.offering.is_common_paper)

    def test_service_mapping_sets_is_common_paper_true(self):
        self.assertFalse(self.offering.is_common_paper)
        map_paper_to_programmes(self.offering, [self.prog1, self.prog2])
        self.offering.refresh_from_db()
        self.assertTrue(self.offering.is_common_paper)
        self.assertEqual(self.offering.programme_mappings.count(), 2)

    def test_direct_mapping_post_sets_is_common_paper_true(self):
        self.assertFalse(self.offering.is_common_paper)
        url = reverse("academics:paper-mapping-list")
        res = self.client.post(url, {
            "paper_offering": self.offering.id,
            "programme": self.prog1.id,
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.offering.refresh_from_db()
        self.assertTrue(self.offering.is_common_paper)

    def test_direct_mapping_patch_maintains_is_common_paper_true(self):
        mapping = PaperProgrammeMapping.objects.create(paper_offering=self.offering, programme=self.prog1)
        self.offering.is_common_paper = True
        self.offering.save()

        url = reverse("academics:paper-mapping-detail", kwargs={"pk": mapping.id})
        res = self.client.patch(url, {"programme": self.prog2.id})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.offering.refresh_from_db()
        self.assertTrue(self.offering.is_common_paper)

    def test_mapped_paper_cannot_be_set_to_non_common_via_api(self):
        PaperProgrammeMapping.objects.create(paper_offering=self.offering, programme=self.prog1)
        self.offering.is_common_paper = True
        self.offering.save()

        url = reverse("academics:paper-offering-detail", kwargs={"pk": self.offering.id})
        res = self.client.patch(url, {"is_common_paper": False})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("is_common_paper", str(res.content))

        # Ensure database state remains unchanged
        self.offering.refresh_from_db()
        self.assertTrue(self.offering.is_common_paper)
        self.assertTrue(self.offering.programme_mappings.exists())

    def test_mapped_paper_cannot_be_set_to_non_common_via_model_clean(self):
        PaperProgrammeMapping.objects.create(paper_offering=self.offering, programme=self.prog1)
        self.offering.is_common_paper = False
        with self.assertRaises(ValidationError) as cm:
            self.offering.clean()
        self.assertIn("is_common_paper", cm.exception.message_dict)

    def test_unmapping_all_allows_setting_is_common_paper_false(self):
        mapping = PaperProgrammeMapping.objects.create(paper_offering=self.offering, programme=self.prog1)
        self.offering.is_common_paper = True
        self.offering.save()

        # Delete the mapping
        mapping.delete()

        # Now setting is_common_paper to False should succeed
        url = reverse("academics:paper-offering-detail", kwargs={"pk": self.offering.id})
        res = self.client.patch(url, {"is_common_paper": False})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.offering.refresh_from_db()
        self.assertFalse(self.offering.is_common_paper)

    def test_bulk_mapping_atomic_rollback_preserves_state(self):
        other_college = College.objects.create(name="Cross College", code="CC-GU", contact_email="cc@gu.edu")
        other_prog = Programme.objects.create(college=other_college, name="Other", code="OTH", duration_semesters=8)
        # Offering currently has no mappings and is_common_paper=False
        self.assertFalse(self.offering.is_common_paper)

        with self.assertRaises(ValidationError):
            map_paper_to_programmes(self.offering, [self.prog1, other_prog])

        self.offering.refresh_from_db()
        self.assertFalse(self.offering.is_common_paper)
        self.assertEqual(self.offering.programme_mappings.count(), 0)


class SanitizedExceptionHandlingRegressionTests(TestCase):
    """
    Round 3 Regression Tests for Finding C:
    Guarantees internal exception details (SQL syntax, table names, tracebacks) are never leaked to clients.
    """

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            username="admin_sec",
            email="admin_sec@mc.edu",
            password="StrongPassword123!",
            role=RoleChoices.SUPERADMIN,
        )
        self.client.force_authenticate(user=self.admin)
        self.college = College.objects.create(name="Model College", code="MC-GU", contact_email="admin@mc.edu")
        self.session = AcademicSession.objects.create(
            college=self.college, name="2025-2026", start_date=date(2025, 7, 1), end_date=date(2026, 6, 30), is_current=True
        )

    def test_restricted_deletion_returns_409_without_internal_details(self):
        # AcademicSession references College with on_delete=RESTRICT
        url = reverse("academics:college-detail", kwargs={"pk": self.college.id})
        res = self.client.delete(url)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        data = res.json()
        self.assertIn("error", data)
        self.assertEqual(data["error"]["code"], "RESOURCE_CONFLICT")
        self.assertEqual(data["error"]["message"], "Cannot delete record because it is referenced by existing academic data.")
        # Ensure no internal SQL, table names, or details field leaked
        self.assertNotIn("details", data["error"])
        content_str = str(res.content)
        self.assertNotIn("academics_academicsession", content_str)
        self.assertNotIn("RESTRICT", content_str)
        self.assertNotIn("foreign key", content_str.lower())

    def test_unexpected_mapping_error_returns_500_without_internal_disclosure(self):
        prog = Programme.objects.create(college=self.college, name="BA", code="BA", duration_semesters=8)
        sem = Semester.objects.create(programme=prog, semester_number=1, name="Sem 1")
        dept = Department.objects.create(college=self.college, name="Philosophy", code="PHIL")
        sub = Subject.objects.create(department=dept, name="Ethics", code="ETH101")
        cat = SubjectCategory.objects.create(college=self.college, code="VAC", name="VAC")
        offering = PaperOffering.objects.create(
            academic_session=self.session,
            semester=sem,
            subject=sub,
            subject_category=cat,
            paper_code="VAC101",
            title="Ethics",
            credits=Decimal("2.0"),
        )
        url = reverse("academics:paper-offering-map-programmes", kwargs={"pk": offering.id})

        with patch("apps.academics.views.map_paper_to_programmes", side_effect=RuntimeError("SecretDatabaseConnectionFailed")):
            res = self.client.post(url, {"programme_ids": [prog.id]}, format="json")
            self.assertEqual(res.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
            content_str = str(res.content)
            self.assertNotIn("SecretDatabaseConnectionFailed", content_str)
            self.assertNotIn("RuntimeError", content_str)
            data = res.json()
            self.assertEqual(data["error"]["code"], "INTERNAL_SERVER_ERROR")

    def test_json_decode_error_returns_sanitized_message(self):
        url = reverse("academics:institutional-config-list")
        res = self.client.post(url, {
            "college": self.college.id,
            "config_key": "BAD_JSON_KEY",
            "config_value": "{malformed_json: true,",
            "data_type": "JSON",
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        content_str = str(res.content)
        # Should return clean validation message without raw Python JSONDecodeError internals
        self.assertIn("Value must be valid JSON.", content_str)
        self.assertNotIn("Expecting property name enclosed in double quotes", content_str)
        self.assertNotIn("line 1 column", content_str)
