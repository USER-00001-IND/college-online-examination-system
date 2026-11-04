"""
Serializers for Students Domain.
Handles student registration, profile representation, self-updates,
and administrative registration approval reviews.
"""

from rest_framework import serializers
from apps.academics.models import College, Programme
from apps.accounts.models import RegistrationApproval, RegistrationApprovalStatus, User
from apps.accounts.serializers import UserSerializer
from apps.students.models import StudentProfile
from apps.students.services import (
    register_student,
    review_student_registration,
    update_student_profile,
    verify_email_token,
)


class StudentProfileSerializer(serializers.ModelSerializer):
    """
    Complete academic profile representation for students and administrators.
    """
    user_details = UserSerializer(source='user', read_only=True)
    college_code = serializers.CharField(source='college.code', read_only=True)
    college_name = serializers.CharField(source='college.name', read_only=True)
    programme_code = serializers.CharField(source='programme.code', read_only=True)
    programme_name = serializers.CharField(source='programme.name', read_only=True)

    class Meta:
        model = StudentProfile
        fields = [
            'id',
            'user',
            'user_details',
            'college',
            'college_code',
            'college_name',
            'programme',
            'programme_code',
            'programme_name',
            'enrollment_number',
            'registration_year',
            'current_semester',
            'phone_number',
            'date_of_birth',
            'gender',
            'guardian_name',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'user', 'college', 'programme', 'enrollment_number', 'registration_year', 'created_at', 'updated_at']

    def update(self, instance, validated_data):
        request = self.context.get('request')
        acting_user = request.user if request else instance.user
        return update_student_profile(
            profile_id=instance.pk,
            acting_user=acting_user,
            validated_data=validated_data,
        )


class StudentSelfUpdateSerializer(serializers.ModelSerializer):
    """
    Restricted profile serializer for student self-service updates.
    Institutional fields are strictly read-only.
    """
    class Meta:
        model = StudentProfile
        fields = [
            'phone_number',
            'guardian_name',
        ]


class StudentRegistrationSerializer(serializers.Serializer):
    """
    Public student self-registration payload serializer.
    Validates identity, institutional relationships, and enrollment credentials.
    Privileged fields (is_staff, is_superuser, role) are strictly forbidden.
    """
    username = serializers.CharField(max_length=150, required=True)
    email = serializers.EmailField(max_length=254, required=True)
    password = serializers.CharField(max_length=128, write_only=True, required=True)
    first_name = serializers.CharField(max_length=150, required=True)
    last_name = serializers.CharField(max_length=150, required=True)
    college = serializers.PrimaryKeyRelatedField(queryset=College.objects.filter(is_active=True))
    programme = serializers.PrimaryKeyRelatedField(queryset=Programme.objects.filter(is_active=True))
    enrollment_number = serializers.CharField(max_length=50, required=True)
    registration_year = serializers.IntegerField(min_value=2000, max_value=2100, required=True)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True, default=None)
    date_of_birth = serializers.DateField(required=False, allow_null=True, default=None)
    gender = serializers.CharField(max_length=20, required=False, allow_blank=True, default=None)
    guardian_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default=None)

    def validate(self, attrs):
        college = attrs['college']
        programme = attrs['programme']
        if programme.college_id != college.pk:
            raise serializers.ValidationError({
                "programme": f"Programme '{programme.code}' does not belong to college '{college.code}'."
            })
        return attrs

    def create(self, validated_data):
        user, profile, raw_token = register_student(**validated_data)
        # Store raw token in context for test verification / email dispatch
        self.context['raw_token'] = raw_token
        return user


class EmailVerificationSerializer(serializers.Serializer):
    """Payload serializer for email token verification."""
    token = serializers.CharField(required=True, trim_whitespace=True)

    def save(self):
        token = self.validated_data['token']
        return verify_email_token(token)


class RegistrationApprovalSerializer(serializers.ModelSerializer):
    """
    Serializes administrative registration approval requests.
    """
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    full_name = serializers.CharField(source='user.get_full_name', read_only=True)
    reviewed_by_username = serializers.CharField(source='reviewed_by.username', read_only=True)
    student_profile = serializers.SerializerMethodField()
    is_email_verified = serializers.SerializerMethodField()

    class Meta:
        model = RegistrationApproval
        fields = [
            'id',
            'user',
            'username',
            'email',
            'full_name',
            'status',
            'submitted_at',
            'reviewed_by',
            'reviewed_by_username',
            'reviewed_at',
            'rejection_reason',
            'student_profile',
            'is_email_verified',
        ]
        read_only_fields = fields

    def get_student_profile(self, obj):
        profile = getattr(obj.user, 'student_profile', None)
        if profile:
            return {
                "id": profile.id,
                "enrollment_number": profile.enrollment_number,
                "college_code": profile.college.code,
                "programme_code": profile.programme.code,
                "current_semester": profile.current_semester,
            }
        return None

    def get_is_email_verified(self, obj):
        return obj.user.email_verifications.filter(is_used=True).exists()


class RegistrationReviewActionSerializer(serializers.Serializer):
    """Payload serializer for approving or rejecting a student registration."""
    action = serializers.ChoiceField(choices=['APPROVE', 'REJECT'])
    rejection_reason = serializers.CharField(required=False, allow_blank=True, default='')

    def save(self, approval_instance, reviewer):
        action = self.validated_data['action']
        rejection_reason = self.validated_data.get('rejection_reason')
        return review_student_registration(
            approval_id=approval_instance.pk,
            action=action,
            reviewer=reviewer,
            rejection_reason=rejection_reason,
        )
