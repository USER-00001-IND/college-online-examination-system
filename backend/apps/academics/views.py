"""
Academic Management Views and ViewSets.
Provides RESTful CRUD operations and administrative actions for Domain B FYUGP entities.
"""

from django.db import models, transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.academics.models import (
    AcademicSession,
    College,
    Department,
    InstitutionalConfig,
    PaperOffering,
    PaperProgrammeMapping,
    Programme,
    Semester,
    Subject,
    SubjectCategory,
)
from apps.academics.permissions import (
    IsAcademicAdminOrReadOnly,
    IsInstitutionalConfigPermission,
)
from apps.academics.serializers import (
    AcademicSessionSerializer,
    CollegeSerializer,
    DepartmentSerializer,
    InstitutionalConfigSerializer,
    PaperOfferingSerializer,
    PaperProgrammeMappingSerializer,
    ProgrammeSerializer,
    SemesterSerializer,
    SubjectCategorySerializer,
    SubjectSerializer,
)
from apps.academics.services import (
    map_paper_to_programmes,
    set_current_academic_session,
)


class BaseAcademicViewSet(viewsets.ModelViewSet):
    """
    Base ViewSet enforcing reference protection on deletion.
    Returns HTTP 409 Conflict if restricted foreign keys prevent record deletion.
    """
    permission_classes = [IsAcademicAdminOrReadOnly]

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except (models.ProtectedError, models.RestrictedError) as exc:
            return Response(
                {
                    "error": {
                        "code": "RESOURCE_CONFLICT",
                        "message": "Cannot delete record because it is referenced by existing academic data.",
                        "details": str(exc),
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )


class CollegeViewSet(BaseAcademicViewSet):
    queryset = College.objects.all()
    serializer_class = CollegeSerializer
    filterset_fields = ["code", "is_active"]
    search_fields = ["name", "code"]


class AcademicSessionViewSet(BaseAcademicViewSet):
    queryset = AcademicSession.objects.select_related("college").all()
    serializer_class = AcademicSessionSerializer
    filterset_fields = ["college", "is_current"]
    search_fields = ["name"]

    @action(detail=True, methods=["post"], url_path="set-current")
    def set_current(self, request, pk=None):
        session = self.get_object()
        updated_session = set_current_academic_session(session.college, session)
        serializer = self.get_serializer(updated_session)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ProgrammeViewSet(BaseAcademicViewSet):
    queryset = Programme.objects.select_related("college").all()
    serializer_class = ProgrammeSerializer
    filterset_fields = ["college", "code", "degree_type", "is_active"]
    search_fields = ["name", "code"]


class DepartmentViewSet(BaseAcademicViewSet):
    queryset = Department.objects.select_related("college").all()
    serializer_class = DepartmentSerializer
    filterset_fields = ["college", "code"]
    search_fields = ["name", "code"]


class SemesterViewSet(BaseAcademicViewSet):
    queryset = Semester.objects.select_related("programme", "programme__college").all()
    serializer_class = SemesterSerializer
    filterset_fields = ["programme", "semester_number", "is_active"]


class SubjectCategoryViewSet(BaseAcademicViewSet):
    queryset = SubjectCategory.objects.select_related("college").all()
    serializer_class = SubjectCategorySerializer
    filterset_fields = ["college", "code", "is_active"]
    search_fields = ["name", "code"]


class SubjectViewSet(BaseAcademicViewSet):
    queryset = Subject.objects.select_related("department", "department__college").all()
    serializer_class = SubjectSerializer
    filterset_fields = ["department", "code", "is_active"]
    search_fields = ["name", "code"]


class PaperOfferingViewSet(BaseAcademicViewSet):
    queryset = PaperOffering.objects.select_related(
        "academic_session",
        "semester",
        "semester__programme",
        "subject",
        "subject__department",
        "subject_category",
        "academic_session__college",
    ).prefetch_related("programme_mappings", "programme_mappings__programme").all()
    serializer_class = PaperOfferingSerializer
    filterset_fields = [
        "academic_session",
        "semester",
        "subject",
        "subject_category",
        "is_common_paper",
        "is_active",
    ]
    search_fields = ["paper_code", "title"]

    @action(detail=True, methods=["post"], url_path="map-programmes")
    def map_programmes(self, request, pk=None):
        """
        Maps a common paper offering to multiple eligible degree programmes.
        Body format: { "programme_ids": [1, 2, 3], "replace": true/false }
        """
        offering = self.get_object()
        programme_ids = request.data.get("programme_ids")

        if not isinstance(programme_ids, list) or not programme_ids:
            return Response(
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "programme_ids must be a non-empty list of programme IDs.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        programmes = list(Programme.objects.filter(pk__in=programme_ids))
        if len(programmes) != len(programme_ids):
            return Response(
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "One or more programme IDs could not be found.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        replace = bool(request.data.get("replace", False))

        try:
            mappings = map_paper_to_programmes(offering, programmes, replace=replace)
        except Exception as exc:
            return Response(
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": str(exc),
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PaperProgrammeMappingSerializer(mappings, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PaperProgrammeMappingViewSet(BaseAcademicViewSet):
    queryset = PaperProgrammeMapping.objects.select_related(
        "paper_offering", "programme"
    ).all()
    serializer_class = PaperProgrammeMappingSerializer
    filterset_fields = ["paper_offering", "programme"]


class InstitutionalConfigViewSet(BaseAcademicViewSet):
    queryset = InstitutionalConfig.objects.select_related("college", "updated_by").all()
    serializer_class = InstitutionalConfigSerializer
    permission_classes = [IsInstitutionalConfigPermission]
    filterset_fields = ["college", "config_key", "is_sensitive"]
    search_fields = ["config_key", "description"]
