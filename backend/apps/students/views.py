"""
Views and ViewSets for Students Domain.
Handles StudentProfile management and administrative RegistrationApproval reviews.
"""

import logging
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied as DRFPermissionDenied, ValidationError as DRFValidationError
from rest_framework.response import Response

from apps.accounts.authorization import get_actor_authorized_college_ids
from apps.accounts.models import RegistrationApproval, RoleChoices
from apps.accounts.permissions import IsAdminUserRole
from apps.students.models import StudentProfile
from apps.students.permissions import IsStudentSelfOrAdmin
from apps.students.serializers import (
    RegistrationApprovalSerializer,
    RegistrationReviewActionSerializer,
    StudentProfileSerializer,
    StudentSelfUpdateSerializer,
)
from apps.students.services import (
    review_student_registration,
    update_student_profile,
)

logger = logging.getLogger('college.students')


class StudentProfileViewSet(viewsets.ModelViewSet):
    """
    CRUD and self-service management for StudentProfile (Table 6).
    - Students are scoped to viewing and updating their own contact profile.
    - Administrators have full querying and semester management access.
    """
    serializer_class = StudentProfileSerializer
    permission_classes = [IsStudentSelfOrAdmin]

    def get_queryset(self):
        user = self.request.user
        qs = StudentProfile.objects.select_related(
            'user', 'college', 'programme'
        ).all().order_by('enrollment_number')

        if not user or not user.is_authenticated:
            return qs.none()

        if user.role == RoleChoices.STUDENT:
            return qs.filter(user=user)

        authorized = get_actor_authorized_college_ids(user)
        if authorized is not None:
            if not authorized:
                return qs.none()
            qs = qs.filter(college_id__in=authorized)

        # Admin filtering options - query params cannot widen access
        college_id = self.request.query_params.get('college')
        if college_id:
            try:
                cid = int(college_id)
                if authorized is not None and cid not in authorized:
                    return qs.none()
                qs = qs.filter(college_id=cid)
            except (ValueError, TypeError):
                return qs.none()

        programme_id = self.request.query_params.get('programme')
        if programme_id:
            qs = qs.filter(programme_id=programme_id)

        semester = self.request.query_params.get('current_semester')
        if semester:
            qs = qs.filter(current_semester=semester)

        enrollment_num = self.request.query_params.get('enrollment_number')
        if enrollment_num:
            qs = qs.filter(enrollment_number__iexact=enrollment_num.strip())

        return qs

    def create(self, request, *args, **kwargs):
        """
        Direct creation of StudentProfile via POST is strictly disabled (Finding R3-D).
        Students must be onboarded through the student self-registration workflow
        (POST /api/v1/auth/register/) and administrative review/approval.
        """
        raise DRFPermissionDenied(
            "Direct student profile creation is not permitted. Students must be onboarded "
            "through the student self-registration workflow and administrative approval."
        )

    def perform_create(self, serializer):
        raise DRFPermissionDenied("Direct student profile creation is not permitted.")

    def destroy(self, request, *args, **kwargs):
        """Prohibits deletion of student profiles to preserve academic history."""
        raise DRFPermissionDenied("Student profiles cannot be deleted. Institutional records must be preserved.")

    @action(detail=False, methods=['get', 'patch'], url_path='me')
    def me(self, request):
        """
        Dedicated endpoint for the currently authenticated student to view or update
        their own profile without needing to know their profile ID.
        """
        user = request.user
        try:
            profile = StudentProfile.objects.select_related('user', 'college', 'programme').get(user=user)
        except StudentProfile.DoesNotExist:
            raise NotFound("Student profile not found for the current user.")

        if request.method == 'GET':
            serializer = StudentProfileSerializer(profile, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)

        # PATCH self-service
        serializer = StudentSelfUpdateSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            updated_profile = update_student_profile(
                profile_id=profile.pk,
                acting_user=user,
                validated_data=serializer.validated_data,
            )
        except (DjangoValidationError, DRFValidationError) as exc:
            detail = exc.message_dict if hasattr(exc, 'message_dict') else exc.detail if hasattr(exc, 'detail') else str(exc)
            return Response({"error": detail}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        out_serializer = StudentProfileSerializer(updated_profile, context={'request': request})
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class RegistrationApprovalViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Administrative management of student self-registration approvals.
    Restricted strictly to institutional administrators.
    """
    serializer_class = RegistrationApprovalSerializer
    permission_classes = [IsAdminUserRole]

    def get_queryset(self):
        user = self.request.user
        qs = RegistrationApproval.objects.select_related(
            'user',
            'reviewed_by',
            'user__student_profile',
            'user__student_profile__college',
            'user__student_profile__programme',
        ).all().order_by('-submitted_at')

        authorized = get_actor_authorized_college_ids(user)
        if authorized is not None:
            if not authorized:
                return qs.none()
            qs = qs.filter(user__student_profile__college_id__in=authorized)

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param.upper().strip())

        return qs

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        """Atomically approves a pending registration and activates the user account."""
        approval = self.get_object()
        try:
            updated = review_student_registration(
                approval_id=approval.pk,
                action='APPROVE',
                reviewer=request.user,
            )
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, 'message_dict') else str(exc)
            return Response({"error": detail}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(updated)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        """Atomically rejects a pending registration with a mandatory reason."""
        approval = self.get_object()
        reason = request.data.get('rejection_reason', '')
        try:
            updated = review_student_registration(
                approval_id=approval.pk,
                action='REJECT',
                reviewer=request.user,
                rejection_reason=reason,
            )
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, 'message_dict') else str(exc)
            return Response({"error": detail}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(updated)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='review')
    def review(self, request, pk=None):
        """Action endpoint supporting either APPROVE or REJECT action."""
        approval = self.get_object()
        serializer = RegistrationReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = serializer.save(approval_instance=approval, reviewer=request.user)
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, 'message_dict') else str(exc)
            return Response({"error": detail}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        out_serializer = self.get_serializer(updated)
        return Response(out_serializer.data, status=status.HTTP_200_OK)
