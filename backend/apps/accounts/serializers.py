"""
Serializers for Domain A: Accounts & Authentication.
College Online Examination System.
"""

from rest_framework import serializers
from apps.accounts.models import Role, User, UserRole


class LoginSerializer(serializers.Serializer):
    """
    Validates user authentication credentials.
    Supports either username or email address as the primary identifier.
    """
    identifier = serializers.CharField(
        required=True,
        allow_blank=False,
        max_length=254,
        trim_whitespace=True,
        help_text="Username or registered email address.",
    )
    password = serializers.CharField(
        required=True,
        allow_blank=False,
        write_only=True,
        style={'input_type': 'password'},
        max_length=255,
        help_text="Account password.",
    )


class RoleSerializer(serializers.ModelSerializer):
    """Serializes granular role definitions."""
    class Meta:
        model = Role
        fields = ['id', 'code', 'name', 'description']
        read_only_fields = fields


class UserRoleAssignmentSerializer(serializers.ModelSerializer):
    """Serializes user role assignments."""
    role_code = serializers.CharField(source='role.code', read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)

    class Meta:
        model = UserRole
        fields = ['id', 'role_code', 'role_name', 'assigned_at']
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    """
    Serializes user identity and role assignment details.
    Omits password hashes and internal verification tokens.
    """
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    assigned_roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'first_name',
            'last_name',
            'full_name',
            'role',
            'is_active',
            'is_staff',
            'is_superuser',
            'assigned_roles',
            'date_joined',
            'last_login',
        ]
        read_only_fields = fields

    def get_assigned_roles(self, obj: User):
        """Returns list of assigned granular role codes."""
        return list(obj.user_roles.values_list('role__code', flat=True))
