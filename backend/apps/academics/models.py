"""
Domain B: Academic Structure & FYUGP Hierarchy Models.
College Online Examination System (Gauhati University FYUGP Context).

Strictly adheres to the approved Chunk 02 Database Architecture (Tables 9-17 and 21):
- Table 9:  academics_college (College)
- Table 10: academics_academic_session (AcademicSession)
- Table 11: academics_programme (Programme)
- Table 12: academics_department (Department)
- Table 13: academics_semester (Semester)
- Table 14: academics_subject_category (SubjectCategory)
- Table 15: academics_subject (Subject)
- Table 16: academics_paper_offering (PaperOffering)
- Table 17: academics_paper_programme_mapping (PaperProgrammeMapping)
- Table 21: academics_institutional_config (InstitutionalConfig)

Tables 18 (enrollments_student_academic_record), 19 (enrollments_student_subject_enrollment),
and 20 (academics_faculty_subject_assignment) are strictly deferred to future authorized chunks.
"""

import json
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class College(models.Model):
    """
    Top-level college institution entity (Table 9: academics_college).
    """
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255, help_text="Full college title")
    code = models.CharField(max_length=20, unique=True, help_text="College institutional code e.g. MC-GU")
    address = models.TextField(blank=True, null=True, default=None, help_text="Postal address")
    contact_email = models.EmailField(max_length=254, help_text="Official administration email")
    contact_phone = models.CharField(max_length=20, blank=True, null=True, default=None, help_text="Official phone")
    is_active = models.BooleanField(default=True, help_text="Active status")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Creation timestamp")

    class Meta:
        db_table = "academics_college"
        verbose_name = "College"
        verbose_name_plural = "Colleges"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class AcademicSession(models.Model):
    """
    Academic sessions e.g. 2026-2027 (Table 10: academics_academic_session).
    """
    id = models.BigAutoField(primary_key=True)
    college = models.ForeignKey(
        College,
        on_delete=models.RESTRICT,
        related_name="academic_sessions",
        help_text="Owning college institution",
    )
    name = models.CharField(max_length=50, help_text='Session title e.g. "2026-2027"')
    start_date = models.DateField(help_text="Academic session start")
    end_date = models.DateField(help_text="Academic session end")
    is_current = models.BooleanField(default=False, help_text="Indicates current active academic year")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Creation timestamp")

    class Meta:
        db_table = "academics_academic_session"
        verbose_name = "Academic Session"
        verbose_name_plural = "Academic Sessions"
        ordering = ["-start_date", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["college", "name"],
                name="uk_session_college_name",
            )
        ]

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValidationError({"end_date": "Academic session start_date must precede end_date."})
        if self.pk:
            orig = AcademicSession.objects.filter(pk=self.pk).values("college_id", "is_current").first()
            if orig and orig["college_id"] != self.college_id:
                if orig["is_current"] or self.is_current:
                    raise ValidationError({
                        "college": "A current academic session cannot be reassigned to another college."
                    })
                if self.paper_offerings.exists():
                    raise ValidationError({
                        "college": "Cannot change academic session college while dependent paper offerings exist."
                    })

    def __str__(self) -> str:
        return f"{self.name} - {self.college.code}"


class Programme(models.Model):
    """
    Academic degree programmes under FYUGP (Table 11: academics_programme).
    """
    id = models.BigAutoField(primary_key=True)
    college = models.ForeignKey(
        College,
        on_delete=models.RESTRICT,
        related_name="programmes",
        help_text="Owning college institution",
    )
    name = models.CharField(max_length=150, help_text='Programme title e.g. "Bachelor of Arts (FYUGP)"')
    code = models.CharField(max_length=20, help_text="Short code e.g. BA-FYUGP")
    duration_semesters = models.PositiveSmallIntegerField(
        default=8,
        help_text="Standard duration (default: 8 semesters)",
    )
    degree_type = models.CharField(
        max_length=50,
        default="UNDERGRADUATE",
        help_text="Degree level (UG, PG, DIPLOMA, UNDERGRADUATE)",
    )
    is_active = models.BooleanField(default=True, help_text="Active status")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Creation timestamp")

    class Meta:
        db_table = "academics_programme"
        verbose_name = "Programme"
        verbose_name_plural = "Programmes"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["college", "code"],
                name="uk_programme_college_code",
            )
        ]

    def clean(self):
        super().clean()
        if self.duration_semesters < 1:
            raise ValidationError({"duration_semesters": "Duration in semesters must be at least 1."})
        if self.pk:
            max_sem = self.semesters.aggregate(max_num=models.Max("semester_number"))["max_num"]
            if max_sem is not None and self.duration_semesters < max_sem:
                raise ValidationError({
                    "duration_semesters": (
                        f"Cannot reduce programme duration to {self.duration_semesters}: semester {max_sem} exists."
                    )
                })
            max_mapped = self.paper_mappings.aggregate(
                max_sem=models.Max("paper_offering__semester__semester_number")
            )["max_sem"]
            if max_mapped is not None and self.duration_semesters < max_mapped:
                raise ValidationError({
                    "duration_semesters": (
                        f"Cannot reduce programme duration to {self.duration_semesters}: mapped paper offering exists in semester {max_mapped}."
                    )
                })
            orig = Programme.objects.filter(pk=self.pk).values("college_id").first()
            if orig and orig["college_id"] != self.college_id:
                has_offerings = self.semesters.filter(paper_offerings__isnull=False).exists()
                has_mappings = self.paper_mappings.exists()
                if has_offerings or has_mappings:
                    raise ValidationError({
                        "college": "Cannot change programme college while dependent paper offerings or mappings exist."
                    })

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Department(models.Model):
    """
    Academic departments offering subjects (Table 12: academics_department).
    """
    id = models.BigAutoField(primary_key=True)
    college = models.ForeignKey(
        College,
        on_delete=models.RESTRICT,
        related_name="departments",
        help_text="Owning college institution",
    )
    name = models.CharField(max_length=150, help_text='e.g. "Department of Political Science"')
    code = models.CharField(max_length=20, help_text="e.g. POL")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Creation timestamp")

    class Meta:
        db_table = "academics_department"
        verbose_name = "Department"
        verbose_name_plural = "Departments"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["college", "code"],
                name="uk_department_college_code",
            )
        ]

    def clean(self):
        super().clean()
        if self.pk:
            orig = Department.objects.filter(pk=self.pk).values("college_id").first()
            if orig and orig["college_id"] != self.college_id:
                if self.subjects.filter(paper_offerings__isnull=False).exists():
                    raise ValidationError({
                        "college": "Cannot change department college while dependent paper offerings exist."
                    })

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Semester(models.Model):
    """
    Configurable semester terms linked to programmes (Table 13: academics_semester).
    """
    id = models.BigAutoField(primary_key=True)
    programme = models.ForeignKey(
        Programme,
        on_delete=models.RESTRICT,
        related_name="semesters",
        help_text="Parent degree programme",
    )
    semester_number = models.PositiveSmallIntegerField(help_text="Integer between 1 and programme duration")
    name = models.CharField(max_length=50, help_text='e.g. "Semester 1", "Semester 6"')
    is_active = models.BooleanField(default=True, help_text="Active status")

    class Meta:
        db_table = "academics_semester"
        verbose_name = "Semester"
        verbose_name_plural = "Semesters"
        ordering = ["programme", "semester_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["programme", "semester_number"],
                name="uk_semester_programme_number",
            )
        ]

    def clean(self):
        super().clean()
        if self.semester_number < 1:
            raise ValidationError({"semester_number": "Semester number must be at least 1."})
        if self.programme_id:
            max_dur = self.programme.duration_semesters
            if self.semester_number > max_dur:
                raise ValidationError({
                    "semester_number": f"Semester number ({self.semester_number}) exceeds programme duration ({max_dur})."
                })
        if self.pk:
            min_mapped = self.paper_offerings.aggregate(
                min_dur=models.Min("programme_mappings__programme__duration_semesters")
            )["min_dur"]
            if min_mapped is not None and self.semester_number > min_mapped:
                raise ValidationError({
                    "semester_number": (
                        f"Cannot change semester number to {self.semester_number}: mapped programme exists with duration {min_mapped}."
                    )
                })
            orig = Semester.objects.filter(pk=self.pk).values("programme__college_id").first()
            if orig and self.programme_id and orig["programme__college_id"] != self.programme.college_id:
                if self.paper_offerings.exists():
                    raise ValidationError({
                        "programme": "Cannot reassign semester to a programme in a different college while dependent paper offerings exist."
                    })

    def __str__(self) -> str:
        return f"{self.programme.code} - {self.name}"


class SubjectCategory(models.Model):
    """
    Dynamic database-driven FYUGP subject categorization (Table 14: academics_subject_category).
    Supports NEP 2020 categories such as MAJOR, MINOR, MDC, AEC, SEC, VAC.
    """
    id = models.BigAutoField(primary_key=True)
    college = models.ForeignKey(
        College,
        on_delete=models.RESTRICT,
        related_name="subject_categories",
        help_text="Owning college institution",
    )
    code = models.CharField(max_length=20, help_text="e.g. MAJOR, MINOR, MDC, AEC, SEC, VAC")
    name = models.CharField(max_length=100, help_text='e.g. "Multidisciplinary Course", "Value Addition Course"')
    description = models.TextField(blank=True, null=True, default=None, help_text="Category description and regulation rules")
    min_credits = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=Decimal("2.0"),
        help_text="Minimum credits for papers in this category",
    )
    max_credits = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=Decimal("4.0"),
        help_text="Maximum credits for papers in this category",
    )
    is_active = models.BooleanField(default=True, help_text="Active status")

    class Meta:
        db_table = "academics_subject_category"
        verbose_name = "Subject Category"
        verbose_name_plural = "Subject Categories"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["college", "code"],
                name="uk_subcategory_college_code",
            )
        ]

    def clean(self):
        super().clean()
        if self.min_credits < Decimal("0.0"):
            raise ValidationError({"min_credits": "Minimum credits cannot be negative."})
        if self.max_credits < self.min_credits:
            raise ValidationError({"max_credits": "Maximum credits cannot be less than minimum credits."})
        if self.pk:
            min_c = self.paper_offerings.aggregate(min_c=models.Min("credits"))["min_c"]
            if min_c is not None and self.min_credits > min_c:
                raise ValidationError({
                    "min_credits": f"Cannot increase min_credits to {self.min_credits}: existing paper offering exists with {min_c} credits."
                })
            max_c = self.paper_offerings.aggregate(max_c=models.Max("credits"))["max_c"]
            if max_c is not None and self.max_credits < max_c:
                raise ValidationError({
                    "max_credits": f"Cannot decrease max_credits to {self.max_credits}: existing paper offering exists with {max_c} credits."
                })
            orig = SubjectCategory.objects.filter(pk=self.pk).values("college_id").first()
            if orig and orig["college_id"] != self.college_id:
                if self.paper_offerings.exists():
                    raise ValidationError({
                        "college": "Cannot change subject category college while dependent paper offerings exist."
                    })

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Subject(models.Model):
    """
    Broad academic disciplines under a department (Table 15: academics_subject).
    """
    id = models.BigAutoField(primary_key=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.RESTRICT,
        related_name="subjects",
        help_text="Parent academic department",
    )
    name = models.CharField(max_length=150, help_text='e.g. "Political Science", "Mathematics"')
    code = models.CharField(max_length=20, help_text="e.g. POLSCI, MATH")
    description = models.TextField(blank=True, null=True, default=None, help_text="Subject overview")
    is_active = models.BooleanField(default=True, help_text="Active status")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Creation timestamp")

    class Meta:
        db_table = "academics_subject"
        verbose_name = "Subject"
        verbose_name_plural = "Subjects"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["department", "code"],
                name="uk_subject_department_code",
            )
        ]

    def clean(self):
        super().clean()
        if self.pk and self.department_id:
            orig = Subject.objects.filter(pk=self.pk).values("department__college_id").first()
            if orig and orig["department__college_id"] != self.department.college_id:
                if self.paper_offerings.exists():
                    raise ValidationError({
                        "department": "Cannot reassign subject to a department in a different college while dependent paper offerings exist."
                    })

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class PaperOffering(models.Model):
    """
    Concrete academic paper offered in a specific semester and academic session (Table 16: academics_paper_offering).
    """
    id = models.BigAutoField(primary_key=True)
    academic_session = models.ForeignKey(
        AcademicSession,
        on_delete=models.RESTRICT,
        related_name="paper_offerings",
        help_text="Session in which this paper is offered",
    )
    semester = models.ForeignKey(
        Semester,
        on_delete=models.RESTRICT,
        related_name="paper_offerings",
        help_text="Semester curriculum term",
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.RESTRICT,
        related_name="paper_offerings",
        help_text="Academic discipline",
    )
    subject_category = models.ForeignKey(
        SubjectCategory,
        on_delete=models.RESTRICT,
        related_name="paper_offerings",
        help_text="FYUGP subject category e.g. MAJOR, MINOR, VAC",
    )
    paper_code = models.CharField(max_length=30, help_text="e.g. POL1014, VAC1012")
    title = models.CharField(max_length=255, help_text='e.g. "Foundations of Political Theory"')
    credits = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=Decimal("4.0"),
        help_text="Paper academic credit weight",
    )
    is_common_paper = models.BooleanField(
        default=False,
        help_text="Flag allowing cross-programme enrollment via PaperProgrammeMapping",
    )
    max_marks_internal = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("20.00"),
        help_text="Internal continuous evaluation marks",
    )
    max_marks_external = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("80.00"),
        help_text="External examination marks",
    )
    pass_marks_external = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("28.00"),
        help_text="Minimum external marks required to pass",
    )
    is_active = models.BooleanField(default=True, help_text="Active offering flag")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Creation timestamp")

    class Meta:
        db_table = "academics_paper_offering"
        verbose_name = "Paper Offering"
        verbose_name_plural = "Paper Offerings"
        ordering = ["-academic_session__start_date", "paper_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_session", "paper_code"],
                name="uk_paper_session_code",
            )
        ]
        indexes = [
            models.Index(fields=["academic_session", "semester"], name="idx_paper_session_sem"),
            models.Index(fields=["subject_category"], name="idx_paper_category"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        # Numeric bounds validation
        if self.credits < Decimal("0.0"):
            errors["credits"] = "Credits cannot be negative."
        if self.max_marks_internal < Decimal("0.0"):
            errors["max_marks_internal"] = "Internal marks cannot be negative."
        if self.max_marks_external < Decimal("0.0"):
            errors["max_marks_external"] = "External marks cannot be negative."
        if self.pass_marks_external < Decimal("0.0"):
            errors["pass_marks_external"] = "Pass marks cannot be negative."
        elif self.max_marks_external >= Decimal("0.0") and self.pass_marks_external > self.max_marks_external:
            errors["pass_marks_external"] = "Pass marks cannot exceed maximum external marks."

        # Category credit range validation
        if self.subject_category_id:
            cat = self.subject_category
            if self.credits < cat.min_credits or self.credits > cat.max_credits:
                errors["credits"] = (
                    f"Credits ({self.credits}) must fall within category '{cat.code}' "
                    f"range [{cat.min_credits}, {cat.max_credits}]."
                )

        # Cross-College Relationship Integrity Validation
        if self.academic_session_id and self.semester_id and self.subject_id and self.subject_category_id:
            session_college_id = self.academic_session.college_id
            sem_college_id = self.semester.programme.college_id
            sub_college_id = self.subject.department.college_id
            cat_college_id = self.subject_category.college_id

            if sem_college_id != session_college_id:
                errors["semester"] = "Semester programme does not belong to the same college as the academic session."
            if sub_college_id != session_college_id:
                errors["subject"] = "Subject department does not belong to the same college as the academic session."
            if cat_college_id != session_college_id:
                errors["subject_category"] = "Subject category does not belong to the same college as the academic session."

            if hasattr(self.semester, "programme") and self.semester.programme:
                if self.semester.semester_number > self.semester.programme.duration_semesters:
                    errors["semester"] = (
                        f"Semester number ({self.semester.semester_number}) exceeds programme duration "
                        f"({self.semester.programme.duration_semesters})."
                    )

        # Common-paper invariant: cannot set is_common_paper=False while programme mappings exist
        if self.pk and not self.is_common_paper:
            if self.programme_mappings.exists():
                errors["is_common_paper"] = (
                    "Cannot set is_common_paper to False while programme mappings exist. "
                    "Remove all programme mappings first."
                )

        # Programme duration coverage invariant: existing programme mappings must cover proposed semester number
        if self.pk and self.semester_id:
            sem_num = self.semester.semester_number
            for mapping in self.programme_mappings.select_related("programme"):
                if mapping.programme.duration_semesters < sem_num:
                    errors["semester"] = (
                        f"Cannot move paper offering to semester {sem_num}: mapped programme "
                        f"'{mapping.programme.code}' duration ({mapping.programme.duration_semesters} sem) "
                        f"does not cover proposed semester ({sem_num}). "
                        "Remove or update incompatible programme mappings first."
                    )
                    break

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.paper_code}: {self.title} ({self.academic_session.name})"


class PaperProgrammeMapping(models.Model):
    """
    Maps common papers to multiple eligible programmes (Table 17: academics_paper_programme_mapping).
    """
    id = models.BigAutoField(primary_key=True)
    paper_offering = models.ForeignKey(
        PaperOffering,
        on_delete=models.CASCADE,
        related_name="programme_mappings",
        help_text="Target paper offering",
    )
    programme = models.ForeignKey(
        Programme,
        on_delete=models.RESTRICT,
        related_name="paper_mappings",
        help_text="Eligible degree programme",
    )

    class Meta:
        db_table = "academics_paper_programme_mapping"
        verbose_name = "Paper Programme Mapping"
        verbose_name_plural = "Paper Programme Mappings"
        constraints = [
            models.UniqueConstraint(
                fields=["paper_offering", "programme"],
                name="uk_paper_programme_mapping",
            )
        ]

    def clean(self):
        super().clean()
        if self.paper_offering_id and self.programme_id:
            paper_college_id = self.paper_offering.academic_session.college_id
            prog_college_id = self.programme.college_id
            if paper_college_id != prog_college_id:
                raise ValidationError({
                    "programme": "Programme and PaperOffering must belong to the same college institution."
                })
            sem_num = self.paper_offering.semester.semester_number
            if self.programme.duration_semesters < sem_num:
                raise ValidationError({
                    "programme": (
                        f"Programme '{self.programme.code}' duration ({self.programme.duration_semesters} sem) "
                        f"does not cover offering semester ({sem_num})."
                    )
                })

    def __str__(self) -> str:
        return f"{self.paper_offering.paper_code} -> {self.programme.code}"


class ConfigDataType(models.TextChoices):
    """Supported data types for institutional configuration."""
    STRING = "STRING", "String"
    INTEGER = "INTEGER", "Integer"
    BOOLEAN = "BOOLEAN", "Boolean"
    JSON = "JSON", "JSON"


class InstitutionalConfig(models.Model):
    """
    Key-value configuration store for institutional parameters and activation gates
    (Table 21: academics_institutional_config).
    """
    id = models.BigAutoField(primary_key=True)
    college = models.ForeignKey(
        College,
        on_delete=models.RESTRICT,
        related_name="institutional_configs",
        help_text="Owning college institution",
    )
    config_key = models.CharField(max_length=100, help_text="Unique key identifier within college")
    config_value = models.TextField(help_text="Serialized configuration value")
    data_type = models.CharField(
        max_length=20,
        choices=ConfigDataType.choices,
        default=ConfigDataType.STRING,
        help_text="Configuration value data type",
    )
    description = models.TextField(blank=True, null=True, default=None, help_text="Setting explanation")
    is_sensitive = models.BooleanField(default=False, help_text="Hide in public or general authenticated responses")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_institutional_configs",
        help_text="User who last updated this configuration",
    )
    updated_at = models.DateTimeField(auto_now=True, help_text="Last modified timestamp")

    class Meta:
        db_table = "academics_institutional_config"
        verbose_name = "Institutional Configuration"
        verbose_name_plural = "Institutional Configurations"
        ordering = ["college", "config_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["college", "config_key"],
                name="uk_college_config_key",
            )
        ]

    def clean(self):
        super().clean()
        if self.config_value is not None:
            if self.data_type == ConfigDataType.INTEGER:
                try:
                    int(self.config_value)
                except (ValueError, TypeError):
                    raise ValidationError({"config_value": "Value must be a valid integer."})
            elif self.data_type == ConfigDataType.BOOLEAN:
                if str(self.config_value).strip().lower() not in ("true", "false", "1", "0"):
                    raise ValidationError({"config_value": "Value must be a valid boolean ('true' or 'false')."})
            elif self.data_type == ConfigDataType.JSON:
                try:
                    json.loads(self.config_value)
                except (json.JSONDecodeError, ValueError):
                    raise ValidationError({"config_value": "Value must be valid JSON."})

    def get_parsed_value(self):
        """Returns the Python-typed representation of config_value."""
        if self.data_type == ConfigDataType.INTEGER:
            return int(self.config_value)
        elif self.data_type == ConfigDataType.BOOLEAN:
            return str(self.config_value).strip().lower() in ("true", "1")
        elif self.data_type == ConfigDataType.JSON:
            return json.loads(self.config_value)
        return self.config_value

    def __str__(self) -> str:
        return f"{self.college.code}: {self.config_key}"


class FacultyAssignmentRole(models.TextChoices):
    """Approved teaching and examination roles for faculty paper assignments."""
    TEACHER = 'TEACHER', 'Teacher'
    INTERNAL_EXAMINER = 'INTERNAL_EXAMINER', 'Internal Examiner'
    EXTERNAL_EXAMINER = 'EXTERNAL_EXAMINER', 'External Examiner'
    MODERATOR = 'MODERATOR', 'Moderator'


class FacultySubjectAssignment(models.Model):
    """
    Faculty teaching and examination assignments for paper offerings (Table 20: academics_faculty_subject_assignment).
    Enforces institutional same-college boundaries and examiner eligibility constraints.
    """
    id = models.BigAutoField(primary_key=True)
    faculty = models.ForeignKey(
        'faculty.FacultyProfile',
        on_delete=models.RESTRICT,
        related_name='paper_assignments',
        db_column='faculty_id',
    )
    paper_offering = models.ForeignKey(
        'academics.PaperOffering',
        on_delete=models.RESTRICT,
        related_name='faculty_assignments',
        db_column='paper_offering_id',
    )
    role = models.CharField(
        max_length=30,
        choices=FacultyAssignmentRole.choices,
        default=FacultyAssignmentRole.TEACHER,
        help_text="Assigned academic role for this paper offering.",
    )
    assigned_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'academics_faculty_subject_assignment'
        verbose_name = 'Faculty Subject Assignment'
        verbose_name_plural = 'Faculty Subject Assignments'
        constraints = [
            models.UniqueConstraint(
                fields=['faculty', 'paper_offering', 'role'],
                name='uk_faculty_paper_role',
            )
        ]

    def __str__(self) -> str:
        return f"{self.faculty.employee_code} -> {self.paper_offering.paper_code} [{self.role}]"

    def clean(self):
        super().clean()
        errors = {}

        if hasattr(self, 'faculty') and self.faculty and hasattr(self, 'paper_offering') and self.paper_offering:
            # 1. Cross-college boundary verification
            offering_college_id = self.paper_offering.academic_session.college_id
            if self.faculty.college_id != offering_college_id:
                errors['faculty'] = (
                    f"Faculty college ID {self.faculty.college_id} does not match paper offering's "
                    f"college ID {offering_college_id}."
                )

            # 2. Examiner eligibility constraint
            if self.role in (FacultyAssignmentRole.INTERNAL_EXAMINER, FacultyAssignmentRole.EXTERNAL_EXAMINER):
                if not getattr(self.faculty, 'is_examiner', False):
                    errors['faculty'] = (
                        f"Faculty member '{self.faculty.employee_code}' is not marked as eligible for examiner roles."
                    )

        if errors:
            raise ValidationError(errors)

