"""
Views and ViewSets for Faculty Domain.
Handles FacultyProfile CRUD, administrative provisioning, self-updates,
and assigned paper offering inquiries.
"""

import logging
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied as DRFPermissionDenied, ValidationError as DRFValidationError
from rest_framework.response import Response

from apps.accounts.models import RoleChoices
from apps.faculty.models import FacultyProfile
from apps.faculty.permissions import IsFacultySelfOrAdmin
from apps.faculty.serializers import (
    FacultyProfileSerializer,
    FacultyProvisioningSerializer,
    FacultySelfUpdateSerializer,
)
from apps.faculty.services import update_faculty_profile

logger = logging.getLogger('college.faculty')


class FacultyProfileViewSet(viewsets.ModelViewSet):
    """
    CRUD and self-service management for FacultyProfile (Table 7).
    - Faculty are scoped to viewing and updating their own contact profile and assigned papers.
    - Administrators have full querying and provisioning access.
    """
    serializer_class = FacultyProfileSerializer
    permission_classes = [IsFacultySelfOrAdmin]

    def get_queryset(self):
        user = self.request.user
        qs = FacultyProfile.objects.select_related(
            'user', 'college', 'department'
        ).all().order_by('employee_code')

        if not user or not user.is_authenticated:
            return qs.none()

        if user.role == RoleChoices.FACULTY:
            return qs.filter(user=user)

        # Admin filtering options
        college_id = self.request.query_params.get('college')
        if college_id:
            qs = qs.filter(college_id=college_id)

        department_id = self.request.query_params.get('department')
        if department_id:
            qs = qs.filter(department_id=department_id)

        employee_code = self.request.query_params.get('employee_code')
        if employee_code:
            qs = qs.filter(employee_code__iexact=employee_code.strip())

        is_examiner = self.request.query_params.get('is_examiner')
        if is_examiner is not None:
            if is_examiner.lower() in ('true', '1'):
                qs = qs.filter(is_examiner=True)
            elif is_examiner.lower() in ('false', '0'):
                qs = qs.filter(is_examiner=False)

        return qs

    def create(self, request, *args, **kwargs):
        """Administrative provisioning of a new faculty member."""
        user = request.user
        is_admin = (
            user.role in (RoleChoices.ADMIN, RoleChoices.SUPERADMIN)
            or user.is_superuser
            or (hasattr(user, "has_role") and user.has_role("COLLEGE_SUPERADMIN", "EXAM_OFFICER"))
        )
        if not is_admin:
            raise DRFPermissionDenied("Only institutional administrators can provision faculty accounts.")

        serializer = FacultyProvisioningSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        try:
            profile = serializer.save()
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, 'message_dict') else str(exc)
            return Response({"error": detail}, status=status.HTTP_400_BAD_REQUEST)

        out_serializer = FacultyProfileSerializer(profile, context={'request': request})
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get', 'patch'], url_path='me')
    def me(self, request):
        """
        Dedicated endpoint for the currently authenticated faculty member to view
        or update their own contact details without needing to know their profile ID.
        """
        user = request.user
        try:
            profile = FacultyProfile.objects.select_related('user', 'college', 'department').get(user=user)
        except FacultyProfile.DoesNotExist:
            raise NotFound("Faculty profile not found for the current user.")

        if request.method == 'GET':
            serializer = FacultyProfileSerializer(profile, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)

        # PATCH self-service
        serializer = FacultySelfUpdateSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            updated_profile = update_faculty_profile(
                profile_id=profile.pk,
                acting_user=user,
                validated_data=serializer.validated_data,
            )
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, 'message_dict') else str(exc)
            return Response({"error": detail}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        out_serializer = FacultyProfileSerializer(updated_profile, context={'request': request})
        return Response(out_serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='me/assignments')
    def my_assignments(self, request):
        """
        Returns all paper offerings assigned to the currently authenticated faculty member.
        """
        user = request.user
        try:
            profile = FacultyProfile.objects.get(user=user)
        except FacultyProfile.DoesNotExist:
            raise NotFound("Faculty profile not found for the current user.")

        from apps.academics.models import FacultySubjectAssignment
        from apps.academics.serializers import FacultySubjectAssignmentSerializer

        assignments = (
            FacultySubjectAssignment.objects.filter(faculty=profile)
            .select_related('paper_offering', 'paper_offering__academic_session', 'paper_offering__subject')
            .order_by('-paper_offering__academic_session__start_date', 'paper_offering__paper_code')
        )
        serializer = FacultySubjectAssignmentSerializer(assignments, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
