"""
Tests for sensitive data redaction, traceback suppression, and JSON structured logging.
"""

import json
import logging
import sys
from unittest import TestCase
from django.test import override_settings

from apps.core.logging import JSONLogFormatter, SensitiveDataFilter


class SensitiveDataLoggingTests(TestCase):
    """Verifies that SensitiveDataFilter redacts passwords, tokens, PINs, and auth headers,
    and ensures that JSONLogFormatter and filters suppress tracebacks in production."""

    def setUp(self):
        self.filter = SensitiveDataFilter()
        self.formatter = JSONLogFormatter()

    def _create_record(self, msg, args=None, exc_info=None):
        return logging.LogRecord(
            name='test.logger',
            level=logging.INFO,
            pathname='test.py',
            lineno=10,
            msg=msg,
            args=args,
            exc_info=exc_info,
        )

    def test_redact_string_patterns(self):
        """Verify regex redaction for Bearer tokens, passwords, and PINs in log strings."""
        record = self._create_record('User login attempt with Bearer eyJhbGciOiJIUzI1Ni.secret_token_12345')
        self.filter.filter(record)
        self.assertNotIn('secret_token_12345', record.msg)
        self.assertIn('Bearer [REDACTED]', record.msg)

        record2 = self._create_record('Authentication failed for password=SuperSecretPassword123!')
        self.filter.filter(record2)
        self.assertNotIn('SuperSecretPassword123!', record2.msg)
        self.assertIn('password=[REDACTED]', record2.msg)

        record3 = self._create_record('Candidate entered exam_pin=982145 for session 42')
        self.filter.filter(record3)
        self.assertNotIn('982145', record3.msg)
        self.assertIn('exam_pin=[REDACTED]', record3.msg)

    def test_redact_dictionary_keys(self):
        """Verify dictionary args with sensitive keys have their values replaced by [REDACTED]."""
        payload = {
            'username': 'student01',
            'password': 'RawPassword!234',
            'pin': '654321',
            'exam_pin': '654321',
            'token': 'jwt.token.here',
            'dek': 'encryption-dek-value',
            'sessionid': 'sess_abc123',
            'metadata': {
                'browser': 'Firefox',
                'secret_key': 'internal-secret',
            },
        }
        # In Python logging, single dictionary args are mapped directly to record.args
        record = self._create_record('User payload: %(username)s', (payload,))
        self.filter.filter(record)

        cleaned_payload = record.args if isinstance(record.args, dict) else record.args[0]
        self.assertEqual(cleaned_payload['username'], 'student01')
        self.assertEqual(cleaned_payload['password'], '[REDACTED]')
        self.assertEqual(cleaned_payload['pin'], '[REDACTED]')
        self.assertEqual(cleaned_payload['exam_pin'], '[REDACTED]')
        self.assertEqual(cleaned_payload['token'], '[REDACTED]')
        self.assertEqual(cleaned_payload['dek'], '[REDACTED]')
        self.assertEqual(cleaned_payload['sessionid'], '[REDACTED]')
        self.assertEqual(cleaned_payload['metadata']['browser'], 'Firefox')
        self.assertEqual(cleaned_payload['metadata']['secret_key'], '[REDACTED]')

    def test_redact_sequence_args(self):
        """Verify sequence args containing dictionaries with sensitive keys are redacted."""
        payload = {'password': 'MySecretPassword', 'user_id': 101}
        record = self._create_record('Action %s with payload %s', ('login', payload))
        self.filter.filter(record)

        self.assertEqual(record.args[0], 'login')
        self.assertEqual(record.args[1]['user_id'], 101)
        self.assertEqual(record.args[1]['password'], '[REDACTED]')

    def test_redact_custom_record_attributes(self):
        """Verify custom attributes attached to log records are sanitized."""
        record = self._create_record('User event')
        record.auth_token = 'secret_token_value'
        record.user_context = {'role': 'student', 'pin': '123456'}
        self.filter.filter(record)

        self.assertEqual(record.auth_token, '[REDACTED]')
        self.assertEqual(record.user_context['pin'], '[REDACTED]')
        self.assertEqual(record.user_context['role'], 'student')

    @override_settings(DEBUG=False)
    def test_redact_exception_in_args_production(self):
        """Verify exception objects in positional args are replaced by safe class names in production."""
        exc = ValueError("Failed connection with password=TopSecretDbPassword!")
        record = self._create_record('Error occurred: %s', (exc,))
        self.filter.filter(record)

        self.assertEqual(record.args[0], '[ValueError]')
        self.assertNotIn('TopSecretDbPassword', str(record.args))

    @override_settings(DEBUG=False)
    def test_exc_info_suppression_in_production(self):
        """Verify exc_info and exc_text are suppressed when DEBUG=False."""
        try:
            raise RuntimeError("Database credentials leaked in traceback: password=SuperSecret999")
        except RuntimeError:
            exc_info = sys.exc_info()

        record = self._create_record('Unhandled exception occurred', exc_info=exc_info)
        record.exc_text = 'Traceback text containing password=SuperSecret999'
        self.filter.filter(record)

        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.exc_text)

    def test_safe_diagnostic_messages_preserved(self):
        """Verify ordinary diagnostic messages and metadata are preserved without alteration."""
        record = self._create_record('Examination attempt 402 admitted successfully for paper 88')
        self.filter.filter(record)
        self.assertEqual(record.msg, 'Examination attempt 402 admitted successfully for paper 88')

    @override_settings(DEBUG=False)
    def test_json_formatter_production_excludes_tracebacks(self):
        """Verify JSONLogFormatter in production excludes traceback text and emits structured fields."""
        try:
            raise KeyError("private_encryption_dek")
        except KeyError:
            exc_info = sys.exc_info()

        record = self._create_record('Failure processing request', exc_info=exc_info)
        record.error_category = 'UnhandledException'
        record.exception_type = 'KeyError'
        record.request_id = 'req-abc-123'

        self.filter.filter(record)
        formatted = self.formatter.format(record)
        parsed = json.loads(formatted)

        self.assertNotIn('exception', parsed)
        self.assertNotIn('private_encryption_dek', formatted)
        self.assertEqual(parsed['error_category'], 'UnhandledException')
        self.assertEqual(parsed['exception_type'], 'KeyError')
        self.assertEqual(parsed['request_id'], 'req-abc-123')
        self.assertEqual(parsed['level'], 'INFO')

    def test_nested_structures_cannot_bypass_redaction(self):
        """Verify deep nested structures with sensitive keys cannot bypass redaction."""
        nested = {
            'level1': [
                {'level2': {'secret_key': 'deep_secret_123', 'safe': 'visible'}},
                {'level2_b': {'pin': '888888', 'status': 'ok'}},
            ]
        }
        redacted = self.filter.redact_data(nested)
        self.assertEqual(redacted['level1'][0]['level2']['secret_key'], '[REDACTED]')
        self.assertEqual(redacted['level1'][0]['level2']['safe'], 'visible')
        self.assertEqual(redacted['level1'][1]['level2_b']['pin'], '[REDACTED]')
        self.assertEqual(redacted['level1'][1]['level2_b']['status'], 'ok')
