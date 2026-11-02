"""
Tests for centralized DRF exception handling and error envelope consistency.
"""

from django.test import TestCase, override_settings
from rest_framework import exceptions, status
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.exceptions import custom_exception_handler


class CustomExceptionHandlerTests(TestCase):
    """Verifies that custom_exception_handler generates standardized envelopes and suppresses stack traces."""

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
    def test_unhandled_exception_suppression_in_production(self):
        """Verify unhandled 500 exceptions suppress internal stack traces when DEBUG=False."""
        exc = ZeroDivisionError('division by zero in database calculation')
        context = {'view': 'TestView'}
        response = custom_exception_handler(exc, context)

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

        error_body = response.data['error']
        self.assertEqual(error_body['code'], 'INTERNAL_SERVER_ERROR')
        self.assertEqual(error_body['message'], 'An unexpected server error occurred.')
        # Verify stack trace or division by zero detail is NOT leaked to caller
        self.assertNotIn('ZeroDivisionError', str(response.data))
        self.assertNotIn('division by zero', str(response.data))
        self.assertEqual(error_body['details'], {})
