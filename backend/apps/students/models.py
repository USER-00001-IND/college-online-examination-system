"""
Student Profile Models (Table 6: students_student_profile).
College Online Examination System (Gauhati University FYUGP Context).
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from apps.accounts.models import RoleChoices, User


class StudentProfile(models.Model):
    """
    Academic student profile linked to accounts_user (Table 6: students_student_profile).
    Strictly restricted to users with primary role STUDENT.
    """
    id = models.BigAutoField(primary_key=True)
    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.RESTRICT,
        related_name='student_profile',
        db_column='user_id',
    )
    college = models.ForeignKey(
        'academics.College',
        on_delete=models.RESTRICT,
        related_name='student_profiles',
        db_column='college_id',
    )
    enrollment_number = models.CharField(
        max_length=50,
        unique=True,
        help_text="Globally unique institutional student enrollment number.",
    )
    registration_year = models.PositiveSmallIntegerField(
        help_text="Year of admission to the institution.",
    )
    programme = models.ForeignKey(
        'academics.Programme',
        on_delete=models.RESTRICT,
        related_name='student_profiles',
        db_column='programme_id',
    )
    current_semester = models.PositiveSmallIntegerField(
        default=1,
        help_text="Current academic semester (1 up to programme duration).",
    )
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, null=True, blank=True)
    guardian_name = models.CharField(max_length=150, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'students_student_profile'
        verbose_name = 'Student Profile'
        verbose_name_plural = 'Student Profiles'
        indexes = [
            models.Index(fields=['programme', 'current_semester'], name='idx_student_programme'),
        ]

    def __str__(self) -> str:
        return f"{self.enrollment_number} - {self.user.get_full_name()} ({self.programme.code})"

    def clean(self):
        super().clean()
        errors = {}

        # 1. Primary role enforcement
        if hasattr(self, 'user') and self.user:
            if self.user.role != RoleChoices.STUDENT:
                errors['user'] = f"User must hold the primary role '{RoleChoices.STUDENT}'. Found: '{self.user.role}'."

        # 2. Institutional relationship boundary: Programme must belong to the Student's College
        if hasattr(self, 'programme') and self.programme and hasattr(self, 'college') and self.college:
            if self.programme.college_id != self.college_id:
                errors['programme'] = (
                    f"Programme '{self.programme.code}' belongs to college ID {self.programme.college_id}, "
                    f"which does not match student college ID {self.college_id}."
                )

        # 3. Semester bounds validation
        if self.current_semester < 1:
            errors['current_semester'] = "Current semester must be greater than or equal to 1."
        elif hasattr(self, 'programme') and self.programme:
            if self.current_semester > self.programme.duration_semesters:
                errors['current_semester'] = (
                    f"Current semester ({self.current_semester}) exceeds programme duration "
                    f"({self.programme.duration_semesters}) for programme '{self.programme.code}'."
                )

        if errors:
            raise ValidationError(errors)
