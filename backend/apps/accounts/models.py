"""
Domain A: Identity, Authentication & Role-Based Access Control Models.
College Online Examination System (Gauhati University FYUGP Context).

Strictly adheres to the approved Chunk 02 Database Architecture (Tables 1, 2, 3, 4, 5, and 8).
Tables 6 (StudentProfile) and 7 (FacultyProfile) have ForeignKeys to Domain B (Academics)
and are strictly deferred to Chunk 06 (Student and Faculty Management).
"""

from typing import Iterable, Optional
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models
from django.utils import timezone

from apps.accounts.managers import UserManager


class RoleChoices(models.TextChoices):
    """Primary user role classifications."""
    STUDENT = 'STUDENT', 'Student'
    FACULTY = 'FACULTY', 'Faculty'
    ADMIN = 'ADMIN', 'Admin'
    SUPERADMIN = 'SUPERADMIN', 'Superadmin'


class RegistrationApprovalStatus(models.TextChoices):
    """Onboarding administrative review status."""
    PENDING = 'PENDING', 'Pending'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'


class AuthEventType(models.TextChoices):
    """Audit log authentication event types."""
    LOGIN_SUCCESS = 'LOGIN_SUCCESS', 'Login Success'
    LOGIN_FAILED = 'LOGIN_FAILED', 'Login Failed'
    LOGOUT = 'LOGOUT', 'Logout'
    PASSWORD_RESET = 'PASSWORD_RESET', 'Password Reset'
    LOCKOUT = 'LOCKOUT', 'Lockout'
    PIN_VERIFY_SUCCESS = 'PIN_VERIFY_SUCCESS', 'PIN Verify Success'
    PIN_VERIFY_FAILED = 'PIN_VERIFY_FAILED', 'PIN Verify Failed'


class User(AbstractBaseUser):
    """
    Central user authentication account (Table 1: accounts_user).
    Extends Django AbstractBaseUser with signed BigAutoField primary key,
    explicit database table mapping, and institutional role tracking.
    """
    id = models.BigAutoField(primary_key=True)
    username = models.CharField(max_length=150, unique=True, db_index=True)
    email = models.EmailField(max_length=254, unique=True, db_index=True)
    password = models.CharField(max_length=255, db_column='password_hash')
    first_name = models.CharField(max_length=150, blank=True, default='')
    last_name = models.CharField(max_length=150, blank=True, default='')
    role = models.CharField(
        max_length=20,
        choices=RoleChoices.choices,
        default=RoleChoices.STUDENT,
    )
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = 'username'
    EMAIL_FIELD = 'email'
    REQUIRED_FIELDS = ['email']

    class Meta:
        db_table = 'accounts_user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        indexes = [
            models.Index(fields=['role', 'is_active'], name='idx_user_role_active'),
        ]

    def __str__(self) -> str:
        return f"{self.username} ({self.role})"

    def get_full_name(self) -> str:
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or self.username

    def get_short_name(self) -> str:
        return self.first_name or self.username

    def has_perm(self, perm: str, obj: Optional[models.Model] = None) -> bool:
        """Django permission hook: Superusers possess all permissions."""
        return self.is_superuser

    def has_module_perms(self, app_label: str) -> bool:
        """Django module permission hook: Staff and Superusers have access."""
        return self.is_staff or self.is_superuser

    def has_role(self, *role_codes: str) -> bool:
        """
        Evaluates whether the user holds any of the given primary or granular roles.
        Checks primary role match first, then queries accounts_user_role.
        """
        if self.role in role_codes:
            return True
        return self.user_roles.filter(role__code__in=role_codes).exists()


class Role(models.Model):
    """
    Granular role definitions supporting institutional RBAC (Table 2: accounts_role).
    e.g. COLLEGE_SUPERADMIN, EXAM_OFFICER, HEAD_EXAMINER, INVIGILATOR.
    """
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'accounts_role'
        verbose_name = 'Role'
        verbose_name_plural = 'Roles'

    def __str__(self) -> str:
        return f"{self.name} [{self.code}]"


class UserRole(models.Model):
    """
    Many-to-many relationship assigning granular roles to users (Table 3: accounts_user_role).
    Tracks assigning administrator and timestamp.
    """
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='user_roles',
        db_column='user_id',
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.RESTRICT,
        related_name='role_users',
        db_column='role_id',
    )
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_roles',
        db_column='assigned_by_id',
    )
    assigned_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'accounts_user_role'
        verbose_name = 'User Role Assignment'
        verbose_name_plural = 'User Role Assignments'
        constraints = [
            models.UniqueConstraint(fields=['user', 'role'], name='uk_user_role'),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} -> {self.role.code}"


class EmailVerification(models.Model):
    """
    Cryptographic verification token storage for email validation (Table 4: accounts_email_verification).
    Stores SHA-256 hash of random 32-byte token to prevent database token theft.
    """
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='email_verifications',
        db_column='user_id',
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    is_used = models.BooleanField(default=False)

    class Meta:
        db_table = 'accounts_email_verification'
        verbose_name = 'Email Verification'
        verbose_name_plural = 'Email Verifications'
        indexes = [
            models.Index(fields=['token_hash'], name='idx_email_token_hash'),
            models.Index(fields=['user', 'is_used'], name='idx_email_user_lookup'),
        ]

    def __str__(self) -> str:
        return f"EmailVerification(user={self.user.username}, used={self.is_used})"


class RegistrationApproval(models.Model):
    """
    Administrative approval tracking for self-registered accounts (Table 5: accounts_registration_approval).
    """
    id = models.BigAutoField(primary_key=True)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='registration_approval',
        db_column='user_id',
    )
    status = models.CharField(
        max_length=20,
        choices=RegistrationApprovalStatus.choices,
        default=RegistrationApprovalStatus.PENDING,
    )
    submitted_at = models.DateTimeField(default=timezone.now)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_registrations',
        db_column='reviewed_by_id',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'accounts_registration_approval'
        verbose_name = 'Registration Approval'
        verbose_name_plural = 'Registration Approvals'
        indexes = [
            models.Index(fields=['status', 'submitted_at'], name='idx_reg_approval_status'),
        ]

    def __str__(self) -> str:
        return f"RegistrationApproval(user={self.user.username}, status={self.status})"


class AuthEvent(models.Model):
    """
    Comprehensive audit log of authentication and security events (Table 8: accounts_auth_event).
    NEVER logs raw passwords, plaintext tokens, or cryptographic secrets.
    """
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='auth_events',
        db_column='user_id',
    )
    identifier_entered = models.CharField(max_length=254, default='', blank=True)
    event_type = models.CharField(max_length=30, choices=AuthEventType.choices)
    ip_address = models.CharField(max_length=45)
    user_agent = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'accounts_auth_event'
        verbose_name = 'Authentication Event'
        verbose_name_plural = 'Authentication Events'
        indexes = [
            models.Index(fields=['user', 'event_type', 'created_at'], name='idx_auth_event_lookup'),
            models.Index(fields=['ip_address', 'event_type', 'created_at'], name='idx_auth_ip_event'),
        ]

    def __str__(self) -> str:
        return f"AuthEvent({self.event_type}, user={self.user_id}, ip={self.ip_address})"
