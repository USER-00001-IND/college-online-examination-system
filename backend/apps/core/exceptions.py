"""
Centralized error handling conventions for College Online Examination System.
Standardizes all DRF error responses into a consistent JSON envelope and suppresses
internal stack traces and sensitive error data from API responses and production logs.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger('college.exceptions')

# Status code to machine-readable error code mapping
STATUS_CODE_MAP = {
    status.HTTP_400_BAD_REQUEST: 'VALIDATION_ERROR',
    status.HTTP_401_UNAUTHORIZED: 'AUTHENTICATION_REQUIRED',
    status.HTTP_403_FORBIDDEN: 'PERMISSION_DENIED',
    status.HTTP_404_NOT_FOUND: 'RESOURCE_NOT_FOUND',
    status.HTTP_405_METHOD_NOT_ALLOWED: 'METHOD_NOT_ALLOWED',
    status.HTTP_408_REQUEST_TIMEOUT: 'REQUEST_TIMEOUT',
    status.HTTP_409_CONFLICT: 'RESOURCE_CONFLICT',
    status.HTTP_410_GONE: 'RESOURCE_GONE',
    status.HTTP_429_TOO_MANY_REQUESTS: 'RATE_LIMIT_EXCEEDED',
    status.HTTP_500_INTERNAL_SERVER_ERROR: 'INTERNAL_SERVER_ERROR',
    status.HTTP_502_BAD_GATEWAY: 'BAD_GATEWAY',
    status.HTTP_503_SERVICE_UNAVAILABLE: 'SERVICE_UNAVAILABLE',
}


def _format_error_details(data: Any) -> Any:
    """Recursively formats DRF error detail structures into clean dictionaries/lists."""
    if isinstance(data, dict):
        return {k: _format_error_details(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_format_error_details(item) for item in data]
    return str(data)


def custom_exception_handler(exc: Exception, context: Dict[str, Any]) -> Optional[Response]:
    """
    Centralized DRF exception handler.
    Guarantees that every error response conforms to the standardized envelope:
    {
        "error": {
            "code": "ERROR_CODE",
            "message": "Human readable summary",
            "details": {...},
            "timestamp": "2026-11-03T03:30:00Z"
        }
    }
    Enforces strict production log sanitization: raw exception messages and stack traces
    are never emitted into production logs or returned in production HTTP responses.
    """
    response = drf_exception_handler(exc, context)
    now_iso = datetime.now(timezone.utc).isoformat()
    is_debug = getattr(settings, 'DEBUG', False)

    if response is not None:
        status_code = response.status_code
        error_code = STATUS_CODE_MAP.get(status_code, 'APPLICATION_ERROR')

        raw_data = response.data
        details = {}
        message = 'An error occurred processing the request.'

        if isinstance(raw_data, dict):
            if 'detail' in raw_data:
                message = str(raw_data['detail'])
                details = {k: _format_error_details(v) for k, v in raw_data.items() if k != 'detail'}
            elif 'non_field_errors' in raw_data:
                message = 'Validation error.'
                details = _format_error_details(raw_data)
            else:
                message = 'Validation failed.'
                details = _format_error_details(raw_data)
        elif isinstance(raw_data, list):
            message = 'Validation failed.'
            details = {'errors': _format_error_details(raw_data)}
        elif isinstance(raw_data, str):
            message = raw_data

        response.data = {
            'error': {
                'code': error_code,
                'message': message,
                'details': details,
                'timestamp': now_iso,
            }
        }
        return response

    # --------------------------------------------------------------------------
    # Unhandled 500 error handling & secure production logging
    # --------------------------------------------------------------------------
    view = context.get('view', None)
    sanitized_view = view.__class__.__name__ if hasattr(view, '__class__') else str(view or 'UnknownView')

    request = context.get('request', None)
    request_id = 'N/A'
    if request and hasattr(request, 'META') and isinstance(request.META, dict):
        request_id = str(request.META.get('HTTP_X_REQUEST_ID', 'N/A'))

    exc_class = exc.__class__.__name__
    error_category = 'UnhandledServerException'

    if not is_debug:
        # PRODUCTION: Log structured diagnostic event without raw exception message or traceback
        # Never log str(exc), exception args, request bodies, cookies, or auth headers
        logger.error(
            "Unhandled server exception in view '%s' [category=%s, type=%s, request_id=%s]",
            sanitized_view,
            error_category,
            exc_class,
            request_id,
            extra={
                'error_category': error_category,
                'exception_type': exc_class,
                'view': sanitized_view,
                'request_id': request_id,
            },
            exc_info=False,
        )

        error_payload = {
            'error': {
                'code': 'INTERNAL_SERVER_ERROR',
                'message': 'An unexpected server error occurred.',
                'details': {},
                'timestamp': now_iso,
            }
        }
    else:
        # DEVELOPMENT: Allow traceback in development logs and include debug type in response
        logger.error(
            "Unhandled server exception in view '%s' [%s]: %s",
            sanitized_view,
            exc_class,
            str(exc),
            exc_info=True,
            extra={
                'error_category': error_category,
                'exception_type': exc_class,
                'view': sanitized_view,
                'request_id': request_id,
            },
        )

        error_payload = {
            'error': {
                'code': 'INTERNAL_SERVER_ERROR',
                'message': str(exc),
                'details': {'type': exc_class},
                'timestamp': now_iso,
            }
        }

    return Response(error_payload, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
