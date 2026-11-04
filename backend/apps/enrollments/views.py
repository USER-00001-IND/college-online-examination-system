"""
Views and ViewSets for Enrollments Domain.
Manages StudentAcademicRecord ledger entries (Table 18).
"""

import logging
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from apps.accounts.authorization import get_actor_authorized_college_ids
from apps.accounts.models import RoleChoices
from apps.enrollments.models import StudentAcademicRecord
from apps.enrollments.permissions import IsStudentAcademicRecordPermission
from apps.enrollments.serializers import StudentAcademicRecordSerializer

logger = logging.getLogger('college.enrollments')


class StudentAcademicRecordViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for StudentAcademicRecord (Table 18).
    - Students can view only their own admission records.
    - Faculty and administrators can query records across programmes and sessions.
    - Mutations are strictly restricted to administrators.
    """
    serializer_class = StudentAcademicRecordSerializer
    permission_classes = [IsStudentAcademicRecordPermission]

    def get_queryset(self):
        user = self.request.user
        qs = StudentAcademicRecord.objects.select_related(
            'student',
            'student__user',
            'programme',
            'academic_session',
        ).all().order_by('-admission_date', 'student__enrollment_number')

        if not user or not user.is_authenticated:
            return qs.none()

        # Faculty accounts have no access to student academic records
        if user.role == RoleChoices.FACULTY:
            return qs.none()

        if user.role == RoleChoices.STUDENT:
            return qs.filter(student__user=user)

        authorized = get_actor_authorized_college_ids(user)
        if authorized is not None:
            if not authorized:
                return qs.none()
            qs = qs.filter(student__college_id__in=authorized)

        # Admin filtering options - query params cannot widen access
        college_id = self.request.query_params.get('college')
        if college_id:
            try:
                cid = int(college_id)
                if authorized is not None and cid not in authorized:
                    return qs.none()
                qs = qs.filter(student__college_id=cid)
            except (ValueError, TypeError):
                return qs.none()

        student_id = self.request.query_params.get('student')
        if student_id:
            qs = qs.filter(student_id=student_id)

        programme_id = self.request.query_params.get('programme')
        if programme_id:
            qs = qs.filter(programme_id=programme_id)

        session_id = self.request.query_params.get('academic_session')
        if session_id:
            qs = qs.filter(academic_session_id=session_id)

        record_status = self.request.query_params.get('status')
        if record_status:
            qs = qs.filter(status=record_status.upper().strip())

        return qs

    def destroy(self, request, *args, **kwargs):
        """Prohibits deletion of student academic records to preserve historical admission ledger."""
        from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
        raise DRFPermissionDenied(
            "Historical academic admission records cannot be deleted. "
            "Use status updates (SUSPENDED, ALUMNI, DROPOUT) to manage student enrollment lifecycle."
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            record = serializer.save()
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, 'message_dict') else str(exc)
            return Response({"error": detail}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        out_serializer = self.get_serializer(record)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            record = serializer.save()
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, 'message_dict') else str(exc)
            return Response({"error": detail}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        out_serializer = self.get_serializer(record)
        return Response(out_serializer.data, status=status.HTTP_200_OK)
