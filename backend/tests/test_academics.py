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
        self.assertIn("programmes", cm.exception.message_dict)

    def test_set_institutional_config_service(self):
        cfg = set_institutional_config(
            college=self.college,
            config_key="OFFICIAL_GRADING_SCALE",
            config_value=json.dumps({"O": 10, "A+": 9}),
            data_type=ConfigDataType.JSON,
            is_sensitive=True,
            description="Official GU 10-point scale",
        )
        self.assertEqual(cfg.config_key, "OFFICIAL_GRADING_SCALE")
        self.assertTrue(cfg.is_sensitive)


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
