"""
Student Academic Record Ledger Models (Table 18: enrollments_student_academic_record).
College Online Examination System (Gauhati University FYUGP Context).
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class AcademicRecordStatus(models.TextChoices):
    """Institutional enrolment lifecycle status."""
    ACTIVE = 'ACTIVE', 'Active'
    SUSPENDED = 'SUSPENDED', 'Suspended'
    ALUMNI = 'ALUMNI', 'Alumni'
    DROPOUT = 'DROPOUT', 'Dropout'


class StudentAcademicRecord(models.Model):
    """
    High-level student programme enrollment ledger preserving admission status (Table 18).
    Maintains historical enrollment continuity independent of individual paper registrations.
    """
    id = models.BigAutoField(primary_key=True)
    student = models.ForeignKey(
        'students.StudentProfile',
        on_delete=models.RESTRICT,
        related_name='academic_records',
        db_column='student_id',
    )
    programme = models.ForeignKey(
        'academics.Programme',
        on_delete=models.RESTRICT,
        related_name='student_academic_records',
        db_column='programme_id',
    )
    academic_session = models.ForeignKey(
        'academics.AcademicSession',
        on_delete=models.RESTRICT,
        related_name='student_academic_records',
        db_column='academic_session_id',
    )
    admission_date = models.DateField(
        help_text="Official date of admission to the programme.",
    )
    status = models.CharField(
        max_length=20,
        choices=AcademicRecordStatus.choices,
        default=AcademicRecordStatus.ACTIVE,
        help_text="Current academic status in this programme session.",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'enrollments_student_academic_record'
        verbose_name = 'Student Academic Record'
        verbose_name_plural = 'Student Academic Records'
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'programme', 'academic_session'],
                name='uk_student_prog_session',
            ),
        ]

    def __str__(self) -> str:
        return f"{self.student.enrollment_number} - {self.programme.code} ({self.academic_session.name}) [{self.status}]"

    def clean(self):
        super().clean()
        errors = {}

        # Cross-college relationship consistency
        if hasattr(self, 'student') and self.student:
            student_college_id = self.student.college_id

            if hasattr(self, 'programme') and self.programme:
                if self.programme.college_id != student_college_id:
                    errors['programme'] = (
                        f"Programme '{self.programme.code}' belongs to college ID {self.programme.college_id}, "
                        f"which does not match student's college ID {student_college_id}."
                    )

            if hasattr(self, 'academic_session') and self.academic_session:
                if self.academic_session.college_id != student_college_id:
                    errors['academic_session'] = (
                        f"Academic session '{self.academic_session.name}' belongs to college ID {self.academic_session.college_id}, "
                        f"which does not match student's college ID {student_college_id}."
                    )

        if errors:
            raise ValidationError(errors)
