"""
Custom Authentication Backend for College Online Examination System.
Supports authentication using either username or normalized email address.
Includes constant-time password checking mitigation to prevent timing-based user enumeration.
"""

from typing import Any, Optional
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q
from django.http import HttpRequest


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Authenticates against either username or email address.
    Executes constant-time dummy password calculation when user is not found to prevent timing enumeration.
    """

    def authenticate(
        self,
        request: Optional[HttpRequest],
        username: Optional[str] = None,
        password: Optional[str] = None,
        **kwargs: Any
    ):
        UserModel = get_user_model()
        identifier = username or kwargs.get('identifier') or kwargs.get('email')
        if not identifier or not password:
            return None

        identifier = str(identifier).strip()

        try:
            user = UserModel.objects.filter(
                Q(username__iexact=identifier) | Q(email__iexact=identifier)
            ).first()
        except Exception:
            return None

        if user is None:
            # Mitigate timing side-channels by hashing dummy password
            UserModel().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None
