"""
Tests for centralized DRF exception handling, error envelope consistency,
production log sanitization, and strict request-ID normalization.
"""

import re
import uuid
from django.test import RequestFactory, TestCase, override_settings
from rest_framework import exceptions, status
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.exceptions import custom_exception_handler, normalize_request_id

UUID4_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


class CustomExceptionHandlerTests(TestCase):
    """Verifies that custom_exception_handler generates standardized envelopes, suppresses stack traces,
    normalizes request identifiers, and prevents sensitive data leakage in production logs and API responses."""

    def setUp(self):
        self.rf = RequestFactory()

    def _assert_valid_uuid(self, val: str):
        """Asserts that a string is a structurally valid UUIDv4 without depending on exact random value."""
        self.assertIsInstance(val, str)
        try:
            parsed = uuid.UUID(val, version=4)
            self.assertEqual(str(parsed), val.lower())
        except (ValueError, AttributeError):
            self.fail(f"Value '{val}' is not a structurally valid UUIDv4.")

    # --------------------------------------------------------------------------
    # DRF Standard Error Response Envelope Tests
    # --------------------------------------------------------------------------

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

    # --------------------------------------------------------------------------
    # Request-ID Normalization Unit Tests
    # --------------------------------------------------------------------------

    def test_normalize_request_id_missing_generates_uuid(self):
        """Verify None or omitted request ID results in a generated server-side UUID."""
        val = normalize_request_id(None)
        self._assert_valid_uuid(val)

    def test_normalize_request_id_empty_generates_uuid(self):
        """Verify empty string results in a generated server-side UUID."""
        val = normalize_request_id('')
        self._assert_valid_uuid(val)

    def test_normalize_request_id_valid_uuid_accepted(self):
        """Verify valid UUID-style request ID is accepted as syntactically valid."""
        raw = 'c6b9071b-26b2-4d22-9218-c21535496464'
        self.assertEqual(normalize_request_id(raw), raw)

    def test_normalize_request_id_valid_alphanumeric_accepted(self):
        """Verify valid alphanumeric identifier up to 64 chars is accepted."""
        raw = 'req_GU_FYUGP_2026-Exam_Session_10928'
        self.assertEqual(normalize_request_id(raw), raw)

        raw_64 = 'a' * 64
        self.assertEqual(normalize_request_id(raw_64), raw_64)

    def test_normalize_request_id_spaces_rejected(self):
        """Verify identifiers containing spaces are rejected."""
        val = normalize_request_id('req 12345')
        self._assert_valid_uuid(val)
        self.assertNotIn('req 12345', val)

    def test_normalize_request_id_newline_rejected(self):
        """Verify identifiers containing newlines (log injection vector) are rejected."""
        val = normalize_request_id('req-01\nINJECTED_LOG_ENTRY')
        self._assert_valid_uuid(val)
        self.assertNotIn('INJECTED', val)

    def test_normalize_request_id_carriage_return_rejected(self):
        """Verify identifiers containing carriage returns are rejected."""
        val = normalize_request_id('req-01\rINJECTED_LOG_ENTRY')
        self._assert_valid_uuid(val)
        self.assertNotIn('INJECTED', val)

    def test_normalize_request_id_tab_rejected(self):
        """Verify identifiers containing tab characters are rejected."""
        val = normalize_request_id('req\t01')
        self._assert_valid_uuid(val)

    def test_normalize_request_id_unicode_rejected(self):
        """Verify identifiers containing Unicode characters are rejected."""
        val = normalize_request_id('req_id_ü_123')
        self._assert_valid_uuid(val)
        self.assertNotIn('ü', val)

    def test_normalize_request_id_punctuation_outside_allowlist_rejected(self):
        """Verify identifiers containing punctuation outside hyphen and underscore are rejected."""
        for disallowed in ['req;drop', 'req/path', 'req:80', 'req.ext', 'req?query', 'req*wild']:
            val = normalize_request_id(disallowed)
            self._assert_valid_uuid(val)
            self.assertNotIn(disallowed, val)

    def test_normalize_request_id_longer_than_64_chars_rejected(self):
        """Verify identifiers exceeding conservative 64-character ceiling are rejected without truncation."""
        long_id = 'a' * 65
        val = normalize_request_id(long_id)
        self._assert_valid_uuid(val)
        self.assertNotEqual(val, long_id[:64])  # Must not truncate and accept

    def test_normalize_request_id_password_content_rejected(self):
        """Verify identifiers containing password text patterns are rejected."""
        val = normalize_request_id('password=SuperSecret123')
        self._assert_valid_uuid(val)
        self.assertNotIn('SuperSecret123', val)

    def test_normalize_request_id_bearer_token_rejected(self):
        """Verify identifiers containing bearer tokens are rejected."""
        val = normalize_request_id('Bearer eyJhbGciOiJIUzI1Ni.token')
        self._assert_valid_uuid(val)
        self.assertNotIn('Bearer', val)

    def test_normalize_request_id_json_content_rejected(self):
        """Verify identifiers containing JSON-like syntax are rejected."""
        val = normalize_request_id('{"request_id": "test_id"}')
        self._assert_valid_uuid(val)
        self.assertNotIn('{"', val)

    def test_normalize_request_id_control_characters_rejected(self):
        """Verify identifiers containing terminal control characters are rejected."""
        val = normalize_request_id('req\x00\x1b[31mRedText')
        self._assert_valid_uuid(val)
        self.assertNotIn('RedText', val)

    def test_normalize_request_id_non_string_types_rejected(self):
        """Verify non-string header values (integers, lists, dictionaries) are rejected safely."""
        for non_str in [12345, ['req-1'], {'id': 'val'}, 45.67]:
            val = normalize_request_id(non_str)
            self._assert_valid_uuid(val)

    # --------------------------------------------------------------------------
    # Production Logging & Exception Handler Integration Tests
    # --------------------------------------------------------------------------

    @override_settings(DEBUG=False)
    def test_unhandled_exception_with_valid_request_id(self):
        """Verify custom_exception_handler logs valid request ID in structured fields."""
        exc = ValueError("Database connection timeout")
        valid_id = 'req-valid-id-001'
        request = self.rf.get('/api/v1/test/', HTTP_X_REQUEST_ID=valid_id)
        context = {'view': 'ExaminationSubmissionView', 'request': request}

        with self.assertLogs('college.exceptions', level='ERROR') as captured_logs:
            response = custom_exception_handler(exc, context)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        log_output = '\n'.join(captured_logs.output)
        self.assertIn(f'request_id={valid_id}', log_output)

    @override_settings(DEBUG=False)
    def test_unhandled_exception_with_malicious_request_id_normalization(self):
        """Verify malicious or sensitive request ID is discarded and replaced with UUID in production logs."""
        exc = RuntimeError("Storage engine transient error")
        malicious_id = 'malicious_id\npassword=SecretP@ssword123\rBearer eyJ...{"admin":true}'
        request = self.rf.post('/api/v1/test/', HTTP_X_REQUEST_ID=malicious_id)
        context = {'view': 'CandidateAccessView', 'request': request}

        with self.assertLogs('college.exceptions', level='ERROR') as captured_logs:
            response = custom_exception_handler(exc, context)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data['error']['code'], 'INTERNAL_SERVER_ERROR')
        self.assertEqual(response.data['error']['message'], 'An unexpected server error occurred.')

        log_output = '\n'.join(captured_logs.output)
        # Verify raw malicious content was NEVER written to production logs
        self.assertNotIn('SecretP@ssword123', log_output)
        self.assertNotIn('Bearer', log_output)
        self.assertNotIn('admin', log_output)
        self.assertNotIn('\npassword=', log_output)

        # Verify a valid UUIDv4 replaced the malicious input in structured logs
        match = re.search(r'request_id=([0-9a-fA-F-]+)', log_output)
        self.assertIsNotNone(match, "Expected normalized request_id UUID in log output")
        normalized_id = match.group(1)
        self._assert_valid_uuid(normalized_id)

    @override_settings(DEBUG=False)
    def test_unhandled_exception_without_request_object_generates_uuid(self):
        """Verify unhandled exception without request object in context generates a UUID request ID."""
        exc = ZeroDivisionError("division by zero")
        context = {'view': 'InternalCalculationView'}

        with self.assertLogs('college.exceptions', level='ERROR') as captured_logs:
            response = custom_exception_handler(exc, context)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        log_output = '\n'.join(captured_logs.output)
        match = re.search(r'request_id=([0-9a-fA-F-]+)', log_output)
        self.assertIsNotNone(match)
        self._assert_valid_uuid(match.group(1))

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
