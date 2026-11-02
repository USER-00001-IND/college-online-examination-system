"""
Core utility views for College Online Examination System.
Includes minimal, credential-safe health check endpoint.
"""

from datetime import datetime, timezone

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    """
    Public health check endpoint.
    Reports service liveness without leaking sensitive system details,
    internal credentials, or host infrastructure configurations.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        env_name = getattr(settings, 'ENVIRONMENT_NAME', 'development')
        app_version = getattr(settings, 'APP_VERSION', '1.0.0')

        payload = {
            'status': 'healthy',
            'version': app_version,
            'environment': env_name,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
        return Response(payload, status=status.HTTP_200_OK)
