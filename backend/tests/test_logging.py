"""
Tests for sensitive data redaction in logging.
"""

import logging
from unittest import TestCase
from apps.core.logging import JSONLogFormatter, SensitiveDataFilter


class SensitiveDataLoggingTests(TestCase):
    """Verifies that SensitiveDataFilter redacts passwords, tokens, PINs, and auth headers."""

    def setUp(self):
        self.filter = SensitiveDataFilter()
        self.formatter = JSONLogFormatter()

    def _create_record(self, msg, args=None):
        return logging.LogRecord(
            name='test.logger',
            level=logging.INFO,
            pathname='test.py',
            lineno=10,
            msg=msg,
            args=args,
            exc_info=None,
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

    def test_json_formatter_produces_valid_json(self):
        """Verify JSONLogFormatter formats records as valid JSON."""
        record = self._create_record('System initialized successfully')
        formatted = self.formatter.format(record)
        self.assertIn('"message": "System initialized successfully"', formatted)
        self.assertIn('"level": "INFO"', formatted)
        self.assertIn('"logger": "test.logger"', formatted)
