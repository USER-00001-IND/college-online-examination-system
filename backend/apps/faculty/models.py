"""
Faculty Profile Models (Table 7: faculty_faculty_profile).
College Online Examination System (Gauhati University FYUGP Context).
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from apps.accounts.models import RoleChoices, User


class FacultyProfile(models.Model):
    """
    Academic faculty profile linked to accounts_user (Table 7: faculty_faculty_profile).
    Strictly restricted to users with primary role FACULTY.
    """
    id = models.BigAutoField(primary_key=True)
    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.RESTRICT,
        related_name='faculty_profile',
        db_column='user_id',
    )
    college = models.ForeignKey(
        'academics.College',
        on_delete=models.RESTRICT,
        related_name='faculty_profiles',
        db_column='college_id',
    )
    employee_code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Globally unique institutional faculty employee identifier.",
    )
    department = models.ForeignKey(
        'academics.Department',
        on_delete=models.RESTRICT,
        related_name='faculty_profiles',
        db_column='department_id',
    )
    designation = models.CharField(
        max_length=100,
        default='Assistant Professor',
        help_text="Academic staff designation.",
    )
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    is_examiner = models.BooleanField(
        default=True,
        help_text="Designates whether the faculty member is eligible for examination grading roles.",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'faculty_faculty_profile'
        verbose_name = 'Faculty Profile'
        verbose_name_plural = 'Faculty Profiles'
        indexes = [
            models.Index(fields=['department'], name='idx_faculty_dept'),
        ]

    def __str__(self) -> str:
        return f"{self.employee_code} - {self.user.get_full_name()} ({self.designation}, {self.department.code})"

    def clean(self):
        super().clean()
        errors = {}

        # 1. Primary role enforcement
        if hasattr(self, 'user') and self.user:
            if self.user.role != RoleChoices.FACULTY:
                errors['user'] = f"User must hold the primary role '{RoleChoices.FACULTY}'. Found: '{self.user.role}'."

        # 2. Institutional relationship boundary: Department must belong to the Faculty's College
        if hasattr(self, 'department') and self.department and hasattr(self, 'college') and self.college:
            if self.department.college_id != self.college_id:
                errors['department'] = (
                    f"Department '{self.department.code}' belongs to college ID {self.department.college_id}, "
                    f"which does not match faculty college ID {self.college_id}."
                )

        # 3. Cannot revoke examiner eligibility if active examiner assignments exist
        if self.pk and not self.is_examiner:
            from apps.academics.models import FacultyAssignmentRole, FacultySubjectAssignment
            if FacultySubjectAssignment.objects.filter(
                faculty_id=self.pk,
                role__in=[FacultyAssignmentRole.INTERNAL_EXAMINER, FacultyAssignmentRole.EXTERNAL_EXAMINER],
            ).exists():
                errors['is_examiner'] = (
                    f"Cannot revoke examiner eligibility for faculty member '{self.employee_code}' "
                    f"while active examiner assignments exist."
                )

        if errors:
            raise ValidationError(errors)
