"""
Academic Management Views and ViewSets.
Provides RESTful CRUD operations and administrative actions for Domain B FYUGP entities.
"""

import logging
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
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
    FacultySubjectAssignment,
)
from apps.academics.permissions import (
    IsAcademicAdminOrReadOnly,
    IsFacultyOrAdminAssignmentPermission,
    IsInstitutionalConfigPermission,
)
from apps.accounts.models import RoleChoices
from apps.academics.serializers import (
    AcademicSessionSerializer,
    CollegeSerializer,
    DepartmentSerializer,
    FacultySubjectAssignmentSerializer,
    InstitutionalConfigSerializer,
    MapProgrammesPayloadSerializer,
    PaperOfferingSerializer,
    PaperProgrammeMappingSerializer,
    ProgrammeSerializer,
    SemesterSerializer,
    SubjectCategorySerializer,
    SubjectSerializer,
)
from apps.academics.services import (
    delete_faculty_assignment,
    delete_institutional_config,
    delete_paper_programme_mapping,
    map_paper_to_programmes,
    set_current_academic_session,
)

logger = logging.getLogger("college.academics")


class BaseAcademicViewSet(viewsets.ModelViewSet):
    """
    Base ViewSet enforcing reference protection on deletion.
    Returns HTTP 409 Conflict if restricted foreign keys prevent record deletion.
    """
    permission_classes = [IsAcademicAdminOrReadOnly]

    @transaction.atomic
    def perform_create(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise DRFValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else (exc.messages if hasattr(exc, "messages") else [str(exc)])
            )

    @transaction.atomic
    def perform_update(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise DRFValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else (exc.messages if hasattr(exc, "messages") else [str(exc)])
            )

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except (models.ProtectedError, models.RestrictedError) as exc:
            logger.warning(
                "Restricted deletion prevented for %s [error_type=%s]",
                self.queryset.model.__name__ if hasattr(self, "queryset") and self.queryset is not None else "Model",
                type(exc).__name__,
            )
            return Response(
                {
                    "error": {
                        "code": "RESOURCE_CONFLICT",
                        "message": "Cannot delete record because it is referenced by existing academic data.",
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
        try:
            updated_session = set_current_academic_session(session.college, session)
        except (DjangoValidationError, DRFValidationError) as exc:
            return Response(
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Failed to update current academic session.",
                        "details": exc.message_dict if hasattr(exc, "message_dict") else (exc.messages if hasattr(exc, "messages") else [str(exc)]),
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
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
        Payload format: { "programme_ids": [1, 2, 3], "replace": true/false }
        Strictly validates genuine JSON boolean for 'replace' and non-empty distinct list of IDs.
        """
        offering = self.get_object()

        payload_serializer = MapProgrammesPayloadSerializer(data=request.data)
        if not payload_serializer.is_valid():
            return Response(
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Invalid mapping payload.",
                        "details": payload_serializer.errors,
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        programme_ids = payload_serializer.validated_data["programme_ids"]
        replace = payload_serializer.validated_data.get("replace", False)

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

        try:
            mappings = map_paper_to_programmes(offering, programmes, replace=replace)
        except (DjangoValidationError, DRFValidationError) as exc:
            return Response(
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Academic validation error.",
                        "details": exc.message_dict if hasattr(exc, "message_dict") else (exc.messages if hasattr(exc, "messages") else [str(exc)]),
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            # Sanitized logging under Chunk 03/04 policy: raw internal exception is never exposed to client
            logger.error(
                "Unexpected error during paper-programme mapping [offering_id=%s, error_type=%s]",
                offering.pk,
                type(exc).__name__,
                exc_info=True,
            )
            return Response(
                {
                    "error": {
                        "code": "INTERNAL_SERVER_ERROR",
                        "message": "An error occurred while processing the mapping request.",
                    }
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        serializer = PaperProgrammeMappingSerializer(mappings, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PaperProgrammeMappingViewSet(BaseAcademicViewSet):
    queryset = PaperProgrammeMapping.objects.select_related(
        "paper_offering", "programme"
    ).all()
    serializer_class = PaperProgrammeMappingSerializer
    filterset_fields = ["paper_offering", "programme"]

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            delete_paper_programme_mapping(mapping_id=instance.pk)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except (models.ProtectedError, models.RestrictedError) as exc:
            logger.warning(
                "Restricted deletion prevented for PaperProgrammeMapping [error_type=%s]",
                type(exc).__name__,
            )
            return Response(
                {
                    "error": {
                        "code": "RESOURCE_CONFLICT",
                        "message": "Cannot delete record because it is referenced by existing academic data.",
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )


class InstitutionalConfigViewSet(BaseAcademicViewSet):
    queryset = InstitutionalConfig.objects.select_related("college", "updated_by").all()
    serializer_class = InstitutionalConfigSerializer
    permission_classes = [IsInstitutionalConfigPermission]
    filterset_fields = ["college", "config_key", "is_sensitive"]
    search_fields = ["config_key", "description"]

    @transaction.atomic
    def perform_create(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise DRFValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else (exc.messages if hasattr(exc, "messages") else [str(exc)])
            )

    @transaction.atomic
    def perform_update(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise DRFValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else (exc.messages if hasattr(exc, "messages") else [str(exc)])
            )

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            delete_institutional_config(
                config_id=instance.pk,
                user=request.user,
            )
            return Response(status=status.HTTP_204_NO_CONTENT)
        except (models.ProtectedError, models.RestrictedError) as exc:
            logger.warning(
                "Restricted deletion prevented for %s [error_type=%s]",
                self.queryset.model.__name__,
                type(exc).__name__,
            )
            return Response(
                {
                    "error": {
                        "code": "RESOURCE_CONFLICT",
                        "message": "Cannot delete record because it is referenced by existing academic data.",
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )


class FacultySubjectAssignmentViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for FacultySubjectAssignment (Table 20).
    - Faculty and administrators can query assignments. Students are denied.
    - Creation and deletion strictly restricted to administrators.
    """
    serializer_class = FacultySubjectAssignmentSerializer
    permission_classes = [IsFacultyOrAdminAssignmentPermission]

    def get_queryset(self):
        user = self.request.user
        qs = FacultySubjectAssignment.objects.select_related(
            "faculty",
            "faculty__user",
            "paper_offering",
            "paper_offering__subject",
            "paper_offering__academic_session",
        ).all().order_by("-paper_offering__academic_session__start_date", "paper_offering__paper_code")

        if not user or not user.is_authenticated:
            return qs.none()

        if user.role == RoleChoices.STUDENT:
            return qs.none()

        if user.role == RoleChoices.FACULTY:
            qs = qs.filter(faculty__user=user)

        faculty_id = self.request.query_params.get("faculty")
        if faculty_id:
            qs = qs.filter(faculty_id=faculty_id)

        paper_offering_id = self.request.query_params.get("paper_offering")
        if paper_offering_id:
            qs = qs.filter(paper_offering_id=paper_offering_id)

        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(role=role.upper().strip())

        session_id = self.request.query_params.get("academic_session")
        if session_id:
            qs = qs.filter(paper_offering__academic_session_id=session_id)

        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            assignment = serializer.save()
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else str(exc)
            return Response({"error": detail}, status=status.HTTP_400_BAD_REQUEST)
        except DRFValidationError as exc:
            return Response({"error": exc.detail}, status=status.HTTP_400_BAD_REQUEST)

        out_serializer = self.get_serializer(assignment)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            assignment = serializer.save()
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else str(exc)
            return Response({"error": detail}, status=status.HTTP_400_BAD_REQUEST)
        except DRFValidationError as exc:
            return Response({"error": exc.detail}, status=status.HTTP_400_BAD_REQUEST)

        out_serializer = self.get_serializer(assignment)
        return Response(out_serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        delete_faculty_assignment(
            acting_user=request.user,
            assignment_id=instance.pk,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

