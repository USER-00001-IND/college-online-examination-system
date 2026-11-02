"""
Structured logging filters and formatters for College Online Examination System.
Enforces sensitive data redaction and production traceback suppression across all log records.
"""

import json
import logging
import re
from typing import Any

from django.conf import settings


class SensitiveDataFilter(logging.Filter):
    """
    Log filter that redacts sensitive values (passwords, PINs, tokens, keys,
    authorization headers, cookies) from log messages, args, tracebacks, and attributes.
    Suppresses unsanitized exception tracebacks in production environments.
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

    # Standard LogRecord attribute names to distinguish custom extra attributes
    STANDARD_ATTRS = {
        'args',
        'msg',
        'message',
        'name',
        'levelno',
        'levelname',
        'pathname',
        'filename',
        'module',
        'exc_info',
        'exc_text',
        'stack_info',
        'lineno',
        'funcName',
        'created',
        'msecs',
        'relativeCreated',
        'thread',
        'threadName',
        'processName',
        'process',
        'taskName',
    }

    # Regex patterns for sensitive values in string messages and logs
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
        (
            re.compile(r'([a-zA-Z0-9_.+-]+://[^:]+:)([^@]+)(@)', re.IGNORECASE),
            r'\1[REDACTED]\3',
        ),
    ]

    def redact_string(self, text: str) -> str:
        """Apply regex-based pattern redaction to a string."""
        for pattern, replacement in self.PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    def redact_data(self, data: Any) -> Any:
        """Recursively redact dictionary, sequence, exception, or string data."""
        if isinstance(data, Exception):
            # In production, replace raw exception instances with class name to prevent data leaks
            is_debug = getattr(settings, 'DEBUG', False)
            if not is_debug:
                return f"[{data.__class__.__name__}]"
            return self.redact_string(str(data))
        elif isinstance(data, dict):
            redacted = {}
            for k, v in data.items():
                if isinstance(k, str) and any(
                    sensitive in k.lower() for sensitive in self.SENSITIVE_KEYS
                ):
                    redacted[k] = '[REDACTED]'
                else:
                    redacted[k] = self.redact_data(v)
            return redacted
        elif isinstance(data, (list, tuple, set)):
            res = [self.redact_data(item) for item in data]
            if isinstance(data, tuple):
                return tuple(res)
            elif isinstance(data, set):
                return set(res)
            return res
        elif isinstance(data, str):
            return self.redact_string(data)
        return data

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter and redact the log record in place."""
        is_debug = getattr(settings, 'DEBUG', False)

        # 1. Sanitize message
        if isinstance(record.msg, str):
            record.msg = self.redact_string(record.msg)
        elif isinstance(record.msg, dict):
            record.msg = self.redact_data(record.msg)

        # 2. Sanitize positional arguments
        if record.args:
            if isinstance(record.args, dict):
                record.args = self.redact_data(record.args)
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(self.redact_data(item) for item in record.args)

        # 3. Sanitize custom record attributes
        for attr, value in list(record.__dict__.items()):
            if attr not in self.STANDARD_ATTRS:
                if any(sensitive in attr.lower() for sensitive in self.SENSITIVE_KEYS):
                    setattr(record, attr, '[REDACTED]')
                else:
                    setattr(record, attr, self.redact_data(value))

        # 4. Production Exception & Traceback Sanitization Policy
        # Traceback text and raw exception objects must never be emitted in production logs
        if not is_debug:
            if record.exc_info:
                record.exc_info = None
            if record.exc_text:
                record.exc_text = None
            if record.stack_info:
                record.stack_info = None
        else:
            # In development, sanitize traceback text if already formatted
            if record.exc_text:
                record.exc_text = self.redact_string(record.exc_text)

        return True


class JSONLogFormatter(logging.Formatter):
    """
    Format log records as single-line JSON objects for production ingestion.
    Strictly excludes raw exception messages and stack traces when DEBUG is False.
    """

    def format(self, record: logging.LogRecord) -> str:
        is_debug = getattr(settings, 'DEBUG', False)

        log_entry = {
            'timestamp': self.formatTime(record, self.datefmt),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'line': record.lineno,
        }

        # Include safe custom diagnostic attributes if present
        for attr in ['error_category', 'exception_type', 'view', 'request_id']:
            if hasattr(record, attr):
                log_entry[attr] = getattr(record, attr)

        # Exception formatting policy:
        # Development: serialize sanitized traceback for developer convenience
        # Production: suppress traceback completely; retain only safe exception_type metadata
        if is_debug:
            if record.exc_info and record.exc_text:
                log_entry['exception'] = record.exc_text
            elif record.exc_info:
                log_entry['exception'] = self.formatException(record.exc_info)
        else:
            if hasattr(record, 'exception_type'):
                log_entry['exception_type'] = getattr(record, 'exception_type')
            elif record.exc_info and record.exc_info[0]:
                log_entry['exception_type'] = record.exc_info[0].__name__

        # Apply final redaction defense-in-depth on the complete JSON dictionary
        sanitized_entry = SensitiveDataFilter().redact_data(log_entry)
        return json.dumps(sanitized_entry, default=str)
