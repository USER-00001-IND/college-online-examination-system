"""
Authentication and Role-Based Access Views for College Online Examination System.
Enforces session authentication, CSRF validation, brute-force rate limiting,
enumeration resistance, and secure audit logging to accounts_auth_event.
"""

import logging
from django.conf import settings
from django.contrib.auth import login as django_login, logout as django_logout
from django.db.models import Q
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import exceptions, status
from rest_framework.authentication import CSRFCheck
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.audit import (
    AuditPersistenceError,
    get_validated_client_ip,
    record_auth_event,
)
from apps.accounts.authentication import ExamSessionAuthentication
from apps.accounts.models import AuthEventType, User
from apps.accounts.permissions import (
    IsAdminUserRole,
    IsCollegeSuperAdmin,
    IsFacultyUserRole,
    IsStudentUserRole,
)
from apps.accounts.serializers import LoginSerializer, UserSerializer
from apps.accounts.throttling import AuthenticationThrottle, ThrottleBackendError

logger = logging.getLogger('college.accounts')


@method_decorator(ensure_csrf_cookie, name='dispatch')
class CsrfBootstrapView(APIView):
    """
    Explicit GET bootstrap endpoint to deliver an initial CSRF token and cookie.
    Allows single-page applications and API clients to obtain a valid CSRF token
    before submitting state-changing authentication requests.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        csrf_token = get_token(request)
        return Response(
            {
                "message": "CSRF cookie set.",
                "csrf_token": csrf_token,
            },
            status=status.HTTP_200_OK,
        )


@method_decorator(ensure_csrf_cookie, name='dispatch')
class LoginView(APIView):
    """
    Session-based login endpoint.
    Enforces explicit CSRF validation, dual-dimension brute-force throttling,
    enumeration resistance (timing mitigation + identical error messages),
    fail-closed audit logging, and session-key rotation.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    @classmethod
    def as_view(cls, **initkwargs):
        """
        Overrides DRF's default csrf_exempt=True wrapping on APIView.
        Ensures Django's CsrfViewMiddleware actively validates incoming POST requests.
        """
        view = super().as_view(**initkwargs)
        view.csrf_exempt = False
        return view

    def initial(self, request, *args, **kwargs):
        """
        Enforces DRF-level CSRFCheck defense-in-depth on the unauthenticated login POST.
        """
        super().initial(request, *args, **kwargs)
        self.enforce_csrf(request)

    def enforce_csrf(self, request):
        """
        Validates the incoming CSRF token using Django's CSRFCheck.
        Rejects missing, mismatched, or invalid tokens with standardized 403 response.
        """
        def dummy_get_response(req):
            return None

        check = CSRFCheck(dummy_get_response)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise exceptions.PermissionDenied(
                "CSRF validation failed. Token missing or invalid."
            )

    def post(self, request):
        ip_address = get_validated_client_ip(request)
        if not ip_address:
            return Response(
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Unable to verify trustworthy client IP address for authentication.",
                        "details": {},
                        "timestamp": timezone.now().isoformat(),
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_identifier = request.data.get('identifier', '') if isinstance(request.data, dict) else ''

        # ----------------------------------------------------------------------
        # Round 3/4: Atomic Pre-Auth Admission & Throttling (Fails Closed on Failure)
        # ----------------------------------------------------------------------
        throttle = AuthenticationThrottle()
        try:
            admission = throttle.acquire_admission(ip_address, str(raw_identifier))
            admitted, retry_after, reason = admission
        except ThrottleBackendError:
            logger.critical(
                "Authentication request rejected: Throttle infrastructure failure [category=%s]",
                "THROTTLE_BACKEND_UNAVAILABLE",
                exc_info=False,
            )
            return Response(
                {
                    "error": {
                        "code": "SERVICE_UNAVAILABLE",
                        "message": "Authentication service temporarily unavailable. Rate-limiting infrastructure error.",
                        "details": {},
                        "timestamp": timezone.now().isoformat(),
                    }
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not admitted:
            resp = Response(
                {
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": f"Too many failed login attempts. Please wait {retry_after} seconds before trying again.",
                        "details": {
                            "retry_after_seconds": retry_after,
                        },
                        "timestamp": timezone.now().isoformat(),
                    }
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            resp["Retry-After"] = str(retry_after)
            return resp

        # ----------------------------------------------------------------------
        # Input Validation
        # ----------------------------------------------------------------------
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
            record_auth_event(None, identifier, AuthEventType.LOGIN_FAILED, request, raise_on_failure=False)
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
            record_auth_event(user, identifier, AuthEventType.LOGIN_FAILED, request, raise_on_failure=False)
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
            record_auth_event(user, identifier, AuthEventType.LOGIN_FAILED, request, raise_on_failure=False)
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

        # ----------------------------------------------------------------------
        # Authentication Successful: Fail-Closed Audit Logging & Session Creation
        # ----------------------------------------------------------------------
        try:
            record_auth_event(user, identifier, AuthEventType.LOGIN_SUCCESS, request, raise_on_failure=True)
        except AuditPersistenceError:
            logger.error("Login aborted: Unable to persist mandatory LOGIN_SUCCESS audit event.")
            return Response(
                {
                    "error": {
                        "code": "INTERNAL_SERVER_ERROR",
                        "message": "Authentication service temporarily unavailable. Please retry.",
                        "details": {},
                        "timestamp": timezone.now().isoformat(),
                    }
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Establish Django session and cycle session key to prevent session fixation
        django_login(request, user, backend='apps.accounts.backends.EmailOrUsernameModelBackend')
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])

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
        record_auth_event(user, user.username, AuthEventType.LOGOUT, request, raise_on_failure=False)
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


class StudentRegisterView(APIView):
    """
    Public student self-registration endpoint.
    Creates an inactive student user, StudentProfile, RegistrationApproval (PENDING),
    and cryptographic EmailVerification token.
    Dispatches a verification email using the configured email backend.
    Never exposes plaintext password or raw verification token in the response.
    If email delivery fails, fails closed and cleans up the unverified account.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        from apps.students.serializers import StudentRegistrationSerializer
        from apps.students.services import VerificationEmailDeliveryError, send_student_verification_email
        from django.core.exceptions import ValidationError as DjangoValidationError

        serializer = StudentRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = serializer.save()
            raw_token = serializer.context.get('raw_token')
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else str(exc)
            return Response({"error": detail}, status=status.HTTP_400_BAD_REQUEST)

        # Attempt verification email delivery outside database transaction lock
        try:
            send_student_verification_email(user=user, raw_token=raw_token)
        except VerificationEmailDeliveryError:
            # Atomically clean up the unverified account so duplicate username/email/enrollment do not block future retries
            from apps.students.services import cleanup_unverified_registration
            cleanup_unverified_registration(user.pk)

            return Response(
                {
                    "error": {
                        "code": "EMAIL_DELIVERY_UNAVAILABLE",
                        "message": "Email delivery service is currently unavailable. Registration could not be completed. Please try again later.",
                    }
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "message": "Student registration submitted successfully. A verification email has been dispatched to your email address. Please verify your email before administrative approval.",
                "user_id": user.pk,
                "username": user.username,
                "email": user.email,
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyEmailView(APIView):
    """
    Public cryptographic email verification endpoint.
    - POST {"token": "..."}: Authoritatively validates and atomically consumes verification token.
    - GET ?token=...: Non-consuming token validity inspection (safe against email scanners and link prefetchers).
    Validates token expiration (24h) and single-use constraint.
    Does NOT activate account; account remains inactive pending administrator approval.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        token_str = request.data.get("token") if isinstance(request.data, dict) else None
        return self._consume_token(token_str)

    def get(self, request):
        token_str = request.query_params.get("token")
        return self._inspect_token(token_str)

    def _inspect_token(self, token_str):
        if not token_str or not str(token_str).strip():
            return Response(
                {"error": {"token": "Verification token is required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        import hashlib
        from django.utils import timezone
        from apps.accounts.models import EmailVerification

        token_hash = hashlib.sha256(str(token_str).strip().encode('utf-8')).hexdigest()
        verification = EmailVerification.objects.filter(token_hash=token_hash).first()
        if not verification:
            return Response({"error": {"token": "Invalid verification token."}}, status=status.HTTP_400_BAD_REQUEST)
        if verification.is_used:
            return Response({"error": {"token": "Verification token has already been used."}}, status=status.HTTP_400_BAD_REQUEST)
        if timezone.now() > verification.expires_at:
            return Response({"error": {"token": "Verification token has expired (validity is 24 hours)."}}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "status": "CONFIRM_REQUIRED",
                "action_required": "CONFIRM_REQUIRED",
                "token_valid": True,
                "message": "Verification token validated. Submit a POST request with this token to complete email verification.",
            },
            status=status.HTTP_200_OK,
        )

    def _consume_token(self, token_str):
        from apps.students.serializers import EmailVerificationSerializer
        from django.core.exceptions import ValidationError as DjangoValidationError

        if not token_str or not str(token_str).strip():
            return Response(
                {"error": {"token": "Verification token is required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = EmailVerificationSerializer(data={"token": str(token_str).strip()})
        serializer.is_valid(raise_exception=True)
        try:
            user = serializer.save()
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else str(exc)
            return Response({"error": detail}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "message": "Email address verified successfully. Your account is pending administrative approval.",
                "username": user.username,
                "is_email_verified": True,
            },
            status=status.HTTP_200_OK,
        )


