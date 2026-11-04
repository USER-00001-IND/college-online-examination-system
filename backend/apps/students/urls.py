"""
URL Configuration for Students Domain.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.students.views import RegistrationApprovalViewSet, StudentProfileViewSet

app_name = 'students'

router = DefaultRouter()
router.register(r'profiles', StudentProfileViewSet, basename='student-profile')
router.register(r'registrations', RegistrationApprovalViewSet, basename='student-registration')

urlpatterns = [
    path('', include(router.urls)),
]
