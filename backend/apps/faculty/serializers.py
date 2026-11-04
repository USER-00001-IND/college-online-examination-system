"""
Serializers for Faculty Domain.
Handles faculty profile representation, self-updates, and administrative provisioning.
"""

from rest_framework import serializers
from apps.academics.models import College, Department
from apps.accounts.serializers import UserSerializer
from apps.faculty.models import FacultyProfile
from apps.faculty.services import create_faculty_profile, update_faculty_profile


class FacultyProfileSerializer(serializers.ModelSerializer):
    """Complete profile representation for faculty and administrators."""
    user_details = UserSerializer(source='user', read_only=True)
    college_code = serializers.CharField(source='college.code', read_only=True)
    college_name = serializers.CharField(source='college.name', read_only=True)
    department_code = serializers.CharField(source='department.code', read_only=True)
    department_name = serializers.CharField(source='department.name', read_only=True)

    class Meta:
        model = FacultyProfile
        fields = [
            'id',
            'user',
            'user_details',
            'college',
            'college_code',
            'college_name',
            'department',
            'department_code',
            'department_name',
            'employee_code',
            'designation',
            'phone_number',
            'is_examiner',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'user', 'college', 'employee_code', 'created_at', 'updated_at']

    def update(self, instance, validated_data):
        request = self.context.get('request')
        acting_user = request.user if request else instance.user
        return update_faculty_profile(
            profile_id=instance.pk,
            acting_user=acting_user,
            validated_data=validated_data,
        )


class FacultySelfUpdateSerializer(serializers.ModelSerializer):
    """Restricted profile serializer for faculty self-service updates."""
    class Meta:
        model = FacultyProfile
        fields = ['phone_number']


class FacultyProvisioningSerializer(serializers.Serializer):
    """
    Administrative provisioning serializer for creating faculty user and profile atomically.
    Strictly restricted to institutional administrators.
    Accounts are created in an inactive state with unusable passwords.
    """
    username = serializers.CharField(max_length=150, required=True)
    email = serializers.EmailField(max_length=254, required=True)
    first_name = serializers.CharField(max_length=150, required=True)
    last_name = serializers.CharField(max_length=150, required=True)
    college = serializers.PrimaryKeyRelatedField(queryset=College.objects.filter(is_active=True))
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all())
    employee_code = serializers.CharField(max_length=50, required=True)
    designation = serializers.CharField(max_length=100, required=False, default='Assistant Professor')
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True, default=None)
    is_examiner = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        college = attrs['college']
        department = attrs['department']
        if department.college_id != college.pk:
            raise serializers.ValidationError({
                "department": f"Department '{department.code}' does not belong to college '{college.code}'."
            })
        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        acting_user = request.user if request else None
        return create_faculty_profile(acting_user=acting_user, **validated_data)
