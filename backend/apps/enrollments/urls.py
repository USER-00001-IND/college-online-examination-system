"""
URL Configuration for Enrollments Domain.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.enrollments.views import StudentAcademicRecordViewSet

app_name = 'enrollments'

router = DefaultRouter()
router.register(r'academic-records', StudentAcademicRecordViewSet, basename='student-academic-record')

urlpatterns = [
    path('', include(router.urls)),
]
