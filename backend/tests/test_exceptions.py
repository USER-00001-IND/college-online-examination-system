"""
Tests for centralized DRF exception handling, error envelope consistency, and production log sanitization.
"""

from django.test import RequestFactory, TestCase, override_settings
from rest_framework import exceptions, status
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.exceptions import custom_exception_handler


class CustomExceptionHandlerTests(TestCase):
    """Verifies that custom_exception_handler generates standardized envelopes, suppresses stack traces,
    and prevents sensitive data leakage in production logs and API responses."""

    def setUp(self):
        self.rf = RequestFactory()

    def test_validation_error_envelope(self):
        """Verify ValidationError generates structured 400 envelope."""
        exc = ValidationError({'roll_number': ['This field is required.']})
        context = {'view': 'TestView'}
        response = custom_exception_handler(exc, context)

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

        error_body = response.data['error']
        self.assertEqual(error_body['code'], 'VALIDATION_ERROR')
        self.assertEqual(error_body['message'], 'Validation failed.')
        self.assertIn('roll_number', error_body['details'])
        self.assertIn('timestamp', error_body)

    def test_permission_denied_envelope(self):
        """Verify PermissionDenied generates structured 403 envelope."""
        exc = PermissionDenied('Administrator role required.')
        context = {'view': 'TestView'}
        response = custom_exception_handler(exc, context)

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error']['code'], 'PERMISSION_DENIED')
        self.assertEqual(response.data['error']['message'], 'Administrator role required.')
        self.assertIn('timestamp', response.data['error'])

    def test_not_found_envelope(self):
        """Verify NotFound generates structured 404 envelope."""
        exc = exceptions.NotFound('Examination session not found.')
        context = {'view': 'TestView'}
        response = custom_exception_handler(exc, context)

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['error']['code'], 'RESOURCE_NOT_FOUND')
        self.assertEqual(response.data['error']['message'], 'Examination session not found.')

    @override_settings(DEBUG=False)
    def test_unhandled_exception_password_leak_prevention(self):
        """Verify an unhandled exception containing password=SuperSecret123 does not leak into logs or HTTP response."""
        exc = ValueError("Database connection failed for password=SuperSecret123 at host 127.0.0.1")
        request = self.rf.get('/api/v1/test/', HTTP_X_REQUEST_ID='req-test-uuid-001')
        context = {'view': 'ExaminationSubmissionView', 'request': request}

        with self.assertLogs('college.exceptions', level='ERROR') as captured_logs:
            response = custom_exception_handler(exc, context)

        # 1. Verify HTTP response
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data['error']['code'], 'INTERNAL_SERVER_ERROR')
        self.assertEqual(response.data['error']['message'], 'An unexpected server error occurred.')
        self.assertEqual(response.data['error']['details'], {})
        self.assertNotIn('SuperSecret123', str(response.data))
        self.assertNotIn('password', str(response.data))

        # 2. Verify server log output
        log_output = '\n'.join(captured_logs.output)
        self.assertNotIn('SuperSecret123', log_output)
        self.assertNotIn('password=', log_output)
        # Verify safe diagnostic metadata was recorded
        self.assertIn('UnhandledServerException', log_output)
        self.assertIn('ValueError', log_output)
        self.assertIn('req-test-uuid-001', log_output)

    @override_settings(DEBUG=False)
    def test_unhandled_exception_exam_pin_leak_prevention(self):
        """Verify an unhandled exception containing exam_pin=982145 does not leak into logs or HTTP response."""
        exc = RuntimeError("Authentication failed unexpectedly: exam_pin=982145")
        request = self.rf.post('/api/v1/test/')
        context = {'view': 'CandidateAccessView', 'request': request}

        with self.assertLogs('college.exceptions', level='ERROR') as captured_logs:
            response = custom_exception_handler(exc, context)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertNotIn('982145', str(response.data))

        log_output = '\n'.join(captured_logs.output)
        self.assertNotIn('982145', log_output)
        self.assertIn('RuntimeError', log_output)

    @override_settings(DEBUG=False)
    def test_unhandled_exception_bearer_token_leak_prevention(self):
        """Verify an unhandled exception containing a bearer token does not leak into logs or HTTP response."""
        exc = Exception("Upstream service rejected Bearer eyJhbGciOiJIUzI1Ni.secret_token_value_99999")
        context = {'view': 'UpstreamBridgeView'}

        with self.assertLogs('college.exceptions', level='ERROR') as captured_logs:
            response = custom_exception_handler(exc, context)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertNotIn('secret_token_value_99999', str(response.data))

        log_output = '\n'.join(captured_logs.output)
        self.assertNotIn('secret_token_value_99999', log_output)

    @override_settings(DEBUG=False)
    def test_unhandled_exception_traceback_suppression_in_production(self):
        """Verify unhandled exceptions do not log tracebacks or file paths in production."""
        try:
            # Generate a real exception with a traceback
            raise KeyError("encryption_key_dek_secret")
        except KeyError as exc:
            context = {'view': 'EvidenceDecryptionView'}
            with self.assertLogs('college.exceptions', level='ERROR') as captured_logs:
                response = custom_exception_handler(exc, context)

        log_output = '\n'.join(captured_logs.output)
        self.assertNotIn('Traceback (most recent call last)', log_output)
        self.assertNotIn('encryption_key_dek_secret', log_output)
        self.assertIn('KeyError', log_output)
