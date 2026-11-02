"""
Structured logging filters and formatters for College Online Examination System.
Enforces sensitive data redaction across all log records.
"""

import json
import logging
import re
from typing import Any


class SensitiveDataFilter(logging.Filter):
    """
    Log filter that redacts sensitive values (passwords, PINs, tokens, keys,
    authorization headers, cookies) from log messages, args, and attributes.
    """

    SENSITIVE_KEYS = {
        'password',
        'pin',
        'exam_pin',
        'pin_hash',
        'pin_salt',
        'secret',
        'secret_key',
        'token',
        'access_token',
        'refresh_token',
        'authorization',
        'auth_token',
        'sessionid',
        'cookie',
        'dek',
        'kek',
        'master_kek',
        'private_key',
        'api_key',
        'credit_card',
    }

    # Regex patterns for sensitive values in string messages
    PATTERNS = [
        (re.compile(r'(Bearer\s+)[A-Za-z0-9_\-\.]+', re.IGNORECASE), r'\1[REDACTED]'),
        (re.compile(r'(Basic\s+)[A-Za-z0-9+/=]+', re.IGNORECASE), r'\1[REDACTED]'),
        (
            re.compile(
                r'("?(?:password|pin|token|secret|authorization|exam_pin)"?\s*[:=]\s*"?)[^"\'\s,]+("?)',
                re.IGNORECASE,
            ),
            r'\1[REDACTED]\2',
        ),
    ]

    def redact_data(self, data: Any) -> Any:
        """Recursively redact dictionary or sequence data."""
        if isinstance(data, dict):
            redacted = {}
            for k, v in data.items():
                if isinstance(k, str) and any(
                    sensitive in k.lower() for sensitive in self.SENSITIVE_KEYS
                ):
                    redacted[k] = '[REDACTED]'
                else:
                    redacted[k] = self.redact_data(v)
            return redacted
        elif isinstance(data, (list, tuple)):
            res = [self.redact_data(item) for item in data]
            return tuple(res) if isinstance(data, tuple) else res
        elif isinstance(data, str):
            res = data
            for pattern, replacement in self.PATTERNS:
                res = pattern.sub(replacement, res)
            return res
        return data

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter and redact the log record in place."""
        if isinstance(record.msg, str):
            for pattern, replacement in self.PATTERNS:
                record.msg = pattern.sub(replacement, record.msg)
        elif isinstance(record.msg, dict):
            record.msg = self.redact_data(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = self.redact_data(record.args)
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(self.redact_data(item) for item in record.args)

        return True


class JSONLogFormatter(logging.Formatter):
    """
    Format log records as single-line JSON objects for production ingestion.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            'timestamp': self.formatTime(record, self.datefmt),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'line': record.lineno,
        }
        if record.exc_info and record.exc_text:
            log_entry['exception'] = record.exc_text
        elif record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)
