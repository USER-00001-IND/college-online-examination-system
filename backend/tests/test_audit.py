"""
Tests for Authentication Audit Metadata Validation and Persistence Integrity.
College Online Examination System.
"""

from unittest.mock import patch
from django.core.cache import cache
from django.db import DatabaseError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.audit import (
    AuditPersistenceError,
    get_validated_client_ip,
    record_auth_event,
    sanitize_identifier,
    sanitize_user_agent,
)
from apps.accounts.models import AuthEvent, AuthEventType, RoleChoices, User


class AuditMetadataValidationTests(TestCase):
    """
    Verifies IP address validation, proxy boundary separation,
    CRLF injection sanitization, and audit persistence error handling.
    """

    def setUp(self):
        cache.clear()
        self.rf = RequestFactory()
        self.password = 'SecurePassword@2026'
        self.student = User.objects.create_user(
            username='audit_student',
            email='audit.student@gauhati.ac.in',
            password=self.password,
            role=RoleChoices.STUDENT,
            is_active=True,
        )

    def tearDown(self):
        cache.clear()

    # --------------------------------------------------------------------------
    # IP Address Validation & Proxy Trust Tests
    # --------------------------------------------------------------------------

    def test_direct_remote_addr_used_when_proxy_trust_disabled(self):
        """Verify REMOTE_ADDR is used and X-Forwarded-For is ignored when TRUST_PROXY_CLIENT_IP=False."""
        request = self.rf.get(
            '/api/v1/auth/user/',
            REMOTE_ADDR='198.51.100.42',
            HTTP_X_FORWARDED_FOR='203.0.113.195',
        )
        with override_settings(TRUST_PROXY_CLIENT_IP=False):
            ip = get_validated_client_ip(request)
            self.assertEqual(ip, '198.51.100.42')

    def test_forwarded_ip_accepted_when_proxy_trust_enabled(self):
        """Verify validated first-hop X-Forwarded-For is used when TRUST_PROXY_CLIENT_IP=True."""
        request = self.rf.get(
            '/api/v1/auth/user/',
            REMOTE_ADDR='127.0.0.1',
            HTTP_X_FORWARDED_FOR='203.0.113.195, 10.0.0.1',
        )
        with override_settings(TRUST_PROXY_CLIENT_IP=True):
            ip = get_validated_client_ip(request)
            self.assertEqual(ip, '203.0.113.195')

    def test_ipv6_address_validated_correctly(self):
        """Verify valid IPv6 addresses are accepted."""
        request = self.rf.get(
            '/api/v1/auth/user/',
            REMOTE_ADDR='2001:0db8:85a3:0000:0000:8a2e:0370:7334',
        )
        ip = get_validated_client_ip(request)
        self.assertEqual(ip, '2001:db8:85a3::8a2e:370:7334')

    def test_invalid_ip_header_rejected_and_falls_back(self):
        """Verify malformed/injected IP header falls back to REMOTE_ADDR safely without crashing."""
        request = self.rf.get(
            '/api/v1/auth/user/',
            REMOTE_ADDR='198.51.100.5',
            HTTP_X_FORWARDED_FOR="<script>alert('xss')</script>, 10.0.0.1",
        )
        with override_settings(TRUST_PROXY_CLIENT_IP=True):
            ip = get_validated_client_ip(request)
            # Malformed X-Forwarded-For must be rejected, falling back to REMOTE_ADDR
            self.assertEqual(ip, '198.51.100.5')

    def test_missing_client_metadata_returns_none(self):
        """Verify missing REMOTE_ADDR returns None instead of inventing a loopback address."""
        request = self.rf.get('/api/v1/auth/user/')
        if 'REMOTE_ADDR' in request.META:
            del request.META['REMOTE_ADDR']
        ip = get_validated_client_ip(request)
        self.assertIsNone(ip)

    def test_malformed_remote_addr_returns_none(self):
        """Verify syntactically invalid REMOTE_ADDR returns None."""
        request = self.rf.get('/api/v1/auth/user/', REMOTE_ADDR='malformed_address')
        ip = get_validated_client_ip(request)
        self.assertIsNone(ip)

    def test_login_rejects_missing_client_ip(self):
        """Verify login request fails closed when trustworthy client IP cannot be determined."""
        from apps.accounts.views import LoginView
        request = self.rf.post(
            '/api/v1/auth/login/',
            data={'identifier': 'audit_student', 'password': self.password},
            content_type='application/json',
        )
        if 'REMOTE_ADDR' in request.META:
            del request.META['REMOTE_ADDR']

        # Enforce view execution without REMOTE_ADDR
        view = LoginView()
        view.setup(request)
        view.request = request
        response = view.post(request)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error']['code'], 'VALIDATION_ERROR')
        self.assertIn('Unable to verify trustworthy client IP', response.data['error']['message'])

    # --------------------------------------------------------------------------
    # Metadata Sanitization & Injection Prevention Tests
    # --------------------------------------------------------------------------

    def test_crlf_and_control_characters_stripped_from_identifier(self):
        """Verify newline and CRLF injection sequences are stripped from identifiers."""
        injected = "admin\r\nINJECTED_HEADER: True\x00@gauhati.ac.in"
        clean = sanitize_identifier(injected)
        self.assertNotIn('\r', clean)
        self.assertNotIn('\n', clean)
        self.assertNotIn('\x00', clean)
        self.assertEqual(clean, "adminINJECTED_HEADER: True@gauhati.ac.in")

    def test_oversized_identifier_truncated_safely(self):
        """Verify identifier exceeding 254 chars is truncated to column limit."""
        oversized = "a" * 300
        clean = sanitize_identifier(oversized)
        self.assertEqual(len(clean), 254)

    def test_crlf_and_control_characters_stripped_from_user_agent(self):
        """Verify CRLF and null characters are stripped from User-Agent."""
        request = self.rf.get(
            '/api/v1/auth/user/',
            HTTP_USER_AGENT="Mozilla/5.0\r\nAttack: header\x00Injected",
        )
        ua = sanitize_user_agent(request)
        self.assertNotIn('\r', ua)
        self.assertNotIn('\n', ua)
        self.assertNotIn('\x00', ua)

    def test_oversized_user_agent_truncated_safely(self):
        """Verify User-Agent exceeding 255 chars is truncated cleanly."""
        request = self.rf.get(
            '/api/v1/auth/user/',
            HTTP_USER_AGENT="A" * 500,
        )
        ua = sanitize_user_agent(request)
        self.assertEqual(len(ua), 255)

    # --------------------------------------------------------------------------
    # Audit Persistence Failure Behavior
    # --------------------------------------------------------------------------

    def test_login_success_fails_closed_when_audit_persistence_fails(self):
        """Verify that LOGIN_SUCCESS fails closed (aborts session) if AuthEvent write fails."""
        request = self.rf.post(
            '/api/v1/auth/login/',
            data={'identifier': 'audit_student', 'password': self.password},
            content_type='application/json',
        )

        with patch('apps.accounts.models.AuthEvent.objects.create', side_effect=DatabaseError("Disk full")):
            with self.assertRaises(AuditPersistenceError):
                record_auth_event(
                    user=self.student,
                    raw_identifier='audit_student',
                    event_type=AuthEventType.LOGIN_SUCCESS,
                    request=request,
                    raise_on_failure=True,
                )

    def test_login_failed_logs_error_without_crashing_when_audit_persistence_fails(self):
        """Verify that LOGIN_FAILED handles AuthEvent write failure gracefully."""
        request = self.rf.post(
            '/api/v1/auth/login/',
            data={'identifier': 'audit_student', 'password': 'WrongPassword'},
            content_type='application/json',
        )

        with patch('apps.accounts.models.AuthEvent.objects.create', side_effect=DatabaseError("DB read-only")):
            result = record_auth_event(
                user=self.student,
                raw_identifier='audit_student',
                event_type=AuthEventType.LOGIN_FAILED,
                request=request,
                raise_on_failure=False,
            )
            self.assertIsNone(result)

    def test_audit_event_never_stores_credentials(self):
        """Verify passwords and credentials are never persisted in AuthEvent table."""
        event = AuthEvent.objects.create(
            user=self.student,
            identifier_entered='audit_student',
            event_type=AuthEventType.LOGIN_SUCCESS,
            ip_address='127.0.0.1',
            user_agent='TestAgent/1.0',
        )
        self.assertFalse(hasattr(event, 'password'))
        self.assertFalse(hasattr(event, 'password_hash'))
        self.assertNotIn(self.password, event.identifier_entered)
