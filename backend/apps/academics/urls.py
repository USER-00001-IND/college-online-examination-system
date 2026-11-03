"""
URL configuration for Academics Domain.
Registers REST endpoints for FYUGP academic management.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.academics.views import (
    AcademicSessionViewSet,
    CollegeViewSet,
    DepartmentViewSet,
    InstitutionalConfigViewSet,
    PaperOfferingViewSet,
    PaperProgrammeMappingViewSet,
    ProgrammeViewSet,
    SemesterViewSet,
    SubjectCategoryViewSet,
    SubjectViewSet,
)

app_name = "academics"

router = DefaultRouter()
router.register(r"colleges", CollegeViewSet, basename="college")
router.register(r"sessions", AcademicSessionViewSet, basename="session")
router.register(r"programmes", ProgrammeViewSet, basename="programme")
router.register(r"departments", DepartmentViewSet, basename="department")
router.register(r"semesters", SemesterViewSet, basename="semester")
router.register(r"subject-categories", SubjectCategoryViewSet, basename="subject-category")
router.register(r"subjects", SubjectViewSet, basename="subject")
router.register(r"paper-offerings", PaperOfferingViewSet, basename="paper-offering")
router.register(r"paper-mappings", PaperProgrammeMappingViewSet, basename="paper-mapping")
router.register(r"institutional-configs", InstitutionalConfigViewSet, basename="institutional-config")

urlpatterns = [
    path("", include(router.urls)),
]
