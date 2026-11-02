"""
URL Configuration for College Online Examination System.
"""

from django.urls import path
from apps.core.views import HealthCheckView

urlpatterns = [
    # Health check endpoint
    path('api/v1/health/', HealthCheckView.as_view(), name='api-health'),
]
