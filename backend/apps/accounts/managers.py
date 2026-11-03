"""
Custom User Model Manager for College Online Examination System.
Enforces email normalization, role validation, and institutional security defaults.
"""

from typing import Any, Optional
from django.contrib.auth.base_user import BaseUserManager
from django.core.exceptions import ValidationError


class UserManager(BaseUserManager):
    """
    Custom user manager supporting username/email authentication,
    strict role enforcement, and institutional onboarding defaults.
    """

    def create_user(
        self,
        username: str,
        email: str,
        password: Optional[str] = None,
        role: str = 'STUDENT',
        **extra_fields: Any
    ):
        """
        Creates and saves a standard User with the given username, email, password, and role.
        For students, is_active defaults to False until email verification and admin approval.
        """
        if not username or not username.strip():
            raise ValueError('A unique username must be provided.')
        if not email or not email.strip():
            raise ValueError('A valid email address must be provided.')

        username = username.strip()
        email = self.normalize_email(email).lower()

        # Import locally to avoid circular dependencies
        from apps.accounts.models import RoleChoices

        valid_roles = [choice[0] for choice in RoleChoices.choices]
        if role not in valid_roles:
            raise ValidationError(f"Invalid role '{role}'. Must be one of: {valid_roles}")

        # Students require email verification and administrative approval before activation
        if 'is_active' not in extra_fields:
            extra_fields['is_active'] = False if role == RoleChoices.STUDENT else True

        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)

        user = self.model(
            username=username,
            email=email,
            role=role,
            **extra_fields
        )
        if password:
            from django.contrib.auth.password_validation import validate_password
            validate_password(password, user=user)
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        username: str,
        email: str,
        password: Optional[str] = None,
        **extra_fields: Any
    ):
        """
        Creates and saves an administrative Superuser.
        Enforces is_staff=True, is_superuser=True, is_active=True, and role='SUPERADMIN'.
        """
        from apps.accounts.models import RoleChoices

        extra_fields['is_staff'] = True
        extra_fields['is_superuser'] = True
        extra_fields['is_active'] = True
        extra_fields['role'] = RoleChoices.SUPERADMIN

        if not password:
            raise ValueError('Superusers must be created with a password.')

        return self.create_user(
            username=username,
            email=email,
            password=password,
            **extra_fields
        )
