"""
Authentication and Role-Based Access Views for College Online Examination System.
Enforces session authentication, CSRF validation, enumeration resistance,
and audit logging to accounts_auth_event.
"""

import logging
from django.conf import settings
from django.contrib.auth import login as django_login, logout as django_logout
from django.db.models import Q
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from apps.accounts.authentication import ExamSessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import AuthEvent, AuthEventType, User
from apps.accounts.permissions import (
    IsAdminUserRole,
    IsCollegeSuperAdmin,
    IsFacultyUserRole,
    IsStudentUserRole,
)
from apps.accounts.serializers import LoginSerializer, UserSerializer

logger = logging.getLogger('college.accounts')


def _get_client_ip(request) -> str:
    """Extracts client IP address respecting configured proxy trust boundaries."""
    if getattr(settings, 'TRUST_PROXY_SSL_HEADER', False):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()[:45]
    remote_addr = request.META.get('REMOTE_ADDR', '127.0.0.1')
    return (remote_addr or '127.0.0.1')[:45]


def _get_user_agent(request) -> str:
    """Extracts client user agent, truncated to column limit."""
    ua = request.META.get('HTTP_USER_AGENT', '')
    return ua[:255] if ua else ''


def _log_auth_event(
    user: User | None,
    identifier: str,
    event_type: str,
    request,
) -> None:
    """
    Persists an authentication audit event to accounts_auth_event.
    Never persists passwords, raw secrets, or sensitive tokens.
    """
    try:
        AuthEvent.objects.create(
            user=user,
            identifier_entered=identifier[:254],
            event_type=event_type,
            ip_address=_get_client_ip(request),
            user_agent=_get_user_agent(request),
            created_at=timezone.now(),
        )
    except Exception as exc:
        logger.warning("Failed to record AuthEvent: %s", exc.__class__.__name__)


@method_decorator(ensure_csrf_cookie, name='dispatch')
class LoginView(APIView):
    """
    Session-based login endpoint.
    Validates username or email, rotates session key, checks account status,
    and logs authentication outcome to accounts_auth_event.
    Returns identical generic error messages for non-existent users and wrong passwords.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Validation failed.",
                        "details": serializer.errors,
                        "timestamp": timezone.now().isoformat(),
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        identifier = serializer.validated_data['identifier'].strip()
        password = serializer.validated_data['password']

        user = User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)
        ).first()

        # Mitigate username enumeration timing attacks
        if user is None:
            User().set_password(password)
            _log_auth_event(None, identifier, AuthEventType.LOGIN_FAILED, request)
            return Response(
                {
                    "error": {
                        "code": "AUTHENTICATION_FAILED",
                        "message": "Invalid username/email or password.",
                        "details": {},
                        "timestamp": timezone.now().isoformat(),
                    }
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Check password against stored hash
        if not user.check_password(password):
            _log_auth_event(user, identifier, AuthEventType.LOGIN_FAILED, request)
            return Response(
                {
                    "error": {
                        "code": "AUTHENTICATION_FAILED",
                        "message": "Invalid username/email or password.",
                        "details": {},
                        "timestamp": timezone.now().isoformat(),
                    }
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Check account activation status
        if not user.is_active:
            _log_auth_event(user, identifier, AuthEventType.LOGIN_FAILED, request)
            return Response(
                {
                    "error": {
                        "code": "ACCOUNT_INACTIVE",
                        "message": "Account is inactive. Please verify your email or await administrator approval.",
                        "details": {},
                        "timestamp": timezone.now().isoformat(),
                    }
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Authentication successful: establish session and cycle session key
        django_login(request, user, backend='apps.accounts.backends.EmailOrUsernameModelBackend')
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])

        _log_auth_event(user, identifier, AuthEventType.LOGIN_SUCCESS, request)

        return Response(
            {
                "message": "Authentication successful.",
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    """
    Session-based logout endpoint.
    Flushes the active session, deletes session cookies, and records the logout event.
    """
    authentication_classes = [ExamSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        _log_auth_event(user, user.username, AuthEventType.LOGOUT, request)
        django_logout(request)

        return Response(
            {
                "message": "Logged out successfully.",
            },
            status=status.HTTP_200_OK,
        )


class CurrentUserView(APIView):
    """
    Retrieves profile and role details for the currently authenticated session user.
    """
    authentication_classes = [ExamSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(
            {
                "user": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class AdminTestView(APIView):
    """RBAC test verification endpoint for Administrator access."""
    authentication_classes = [ExamSessionAuthentication]
    permission_classes = [IsAdminUserRole]

    def get(self, request):
        return Response(
            {"message": "Admin access granted."},
            status=status.HTTP_200_OK,
        )


class FacultyTestView(APIView):
    """RBAC test verification endpoint for Faculty access."""
    authentication_classes = [ExamSessionAuthentication]
    permission_classes = [IsFacultyUserRole]

    def get(self, request):
        return Response(
            {"message": "Faculty access granted."},
            status=status.HTTP_200_OK,
        )


class StudentTestView(APIView):
    """RBAC test verification endpoint for Student access."""
    authentication_classes = [ExamSessionAuthentication]
    permission_classes = [IsStudentUserRole]

    def get(self, request):
        return Response(
            {"message": "Student access granted."},
            status=status.HTTP_200_OK,
        )
