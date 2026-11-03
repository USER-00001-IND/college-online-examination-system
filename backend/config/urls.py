"""
URL Configuration for College Online Examination System.
"""

from django.urls import include, path
from apps.core.views import HealthCheckView

urlpatterns = [
    # Health check endpoint
    path('api/v1/health/', HealthCheckView.as_view(), name='api-health'),

    # Authentication & Accounts (Chunk 04)
    path('api/v1/auth/', include('apps.accounts.urls', namespace='accounts')),

    # Academic Structure & FYUGP Management (Chunk 05)
    path('api/v1/academics/', include('apps.academics.urls', namespace='academics')),
]
