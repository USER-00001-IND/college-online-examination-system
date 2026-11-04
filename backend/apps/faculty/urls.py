"""
URL Configuration for Faculty Domain.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.faculty.views import FacultyProfileViewSet

app_name = 'faculty'

router = DefaultRouter()
router.register(r'profiles', FacultyProfileViewSet, basename='faculty-profile')

urlpatterns = [
    path('', include(router.urls)),
]
