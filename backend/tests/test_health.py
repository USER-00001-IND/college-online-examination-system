"""
Tests for health check endpoint (/api/v1/health/).
"""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class HealthCheckEndpointTests(APITestCase):
    """Verifies health check endpoint functionality, schema, and security."""

    def test_health_check_success(self):
        """Verify GET /api/v1/health/ returns 200 OK with expected structure."""
        url = reverse('api-health')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get('status'), 'healthy')
        self.assertIn('version', response.data)
        self.assertIn('environment', response.data)
        self.assertIn('timestamp', response.data)

    def test_health_check_leakage_prevention(self):
        """Verify health check response does not expose credentials or internal configuration."""
        url = reverse('api-health')
        response = self.client.get(url)

        forbidden_keys = [
            'database', 'db_password', 'db_user', 'password',
            'secret', 'secret_key', 'host', 'port', 'token',
        ]
        response_text = str(response.content).lower()
        for forbidden in forbidden_keys:
            self.assertNotIn(forbidden, response.data)
            self.assertNotIn(f'"{forbidden}"', response_text)

    def test_health_check_unauthenticated_access(self):
        """Verify health check endpoint is publicly accessible without credentials."""
        self.client.credentials()  # Clear any credentials
        url = reverse('api-health')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_health_check_disallowed_methods(self):
        """Verify non-GET methods are rejected with standard error envelope."""
        url = reverse('api-health')
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertIn('error', response.data)
        self.assertEqual(response.data['error']['code'], 'METHOD_NOT_ALLOWED')
