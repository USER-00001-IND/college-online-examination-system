"""
Academic Management Serializers.
Provides serialization, validation, and relational integrity checking for Domain B FYUGP entities.
"""

from decimal import Decimal
import json
from rest_framework import serializers

from apps.academics.models import (
    AcademicSession,
    College,
    ConfigDataType,
    Department,
    InstitutionalConfig,
    PaperOffering,
    PaperProgrammeMapping,
    Programme,
    Semester,
    Subject,
    SubjectCategory,
)
from apps.accounts.models import RoleChoices


class CollegeSerializer(serializers.ModelSerializer):
    class Meta:
        model = College
        fields = [
            "id",
            "name",
            "code",
            "address",
            "contact_email",
            "contact_phone",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class AcademicSessionSerializer(serializers.ModelSerializer):
    college_code = serializers.CharField(source="college.code", read_only=True)

    class Meta:
        model = AcademicSession
        fields = [
            "id",
            "college",
            "college_code",
            "name",
            "start_date",
            "end_date",
            "is_current",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        start_date = attrs.get("start_date") or getattr(self.instance, "start_date", None)
        end_date = attrs.get("end_date") or getattr(self.instance, "end_date", None)
        if start_date and end_date and start_date >= end_date:
            raise serializers.ValidationError({"end_date": "Academic session start_date must precede end_date."})
        return attrs


class ProgrammeSerializer(serializers.ModelSerializer):
    college_code = serializers.CharField(source="college.code", read_only=True)

    class Meta:
        model = Programme
        fields = [
            "id",
            "college",
            "college_code",
            "name",
            "code",
            "duration_semesters",
            "degree_type",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_duration_semesters(self, value):
        if value < 1:
            raise serializers.ValidationError("Duration in semesters must be at least 1.")
        return value


class DepartmentSerializer(serializers.ModelSerializer):
    college_code = serializers.CharField(source="college.code", read_only=True)

    class Meta:
        model = Department
        fields = [
            "id",
            "college",
            "college_code",
            "name",
            "code",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class SemesterSerializer(serializers.ModelSerializer):
    programme_code = serializers.CharField(source="programme.code", read_only=True)

    class Meta:
        model = Semester
        fields = [
            "id",
            "programme",
            "programme_code",
            "semester_number",
            "name",
            "is_active",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        prog = attrs.get("programme") or getattr(self.instance, "programme", None)
        sem_num = attrs.get("semester_number") or getattr(self.instance, "semester_number", None)

        if sem_num is not None and sem_num < 1:
            raise serializers.ValidationError({"semester_number": "Semester number must be at least 1."})

        if prog and sem_num:
            if sem_num > prog.duration_semesters:
                raise serializers.ValidationError({
                    "semester_number": f"Semester number ({sem_num}) exceeds programme duration ({prog.duration_semesters})."
                })
        return attrs


class SubjectCategorySerializer(serializers.ModelSerializer):
    college_code = serializers.CharField(source="college.code", read_only=True)

    class Meta:
        model = SubjectCategory
        fields = [
            "id",
            "college",
            "college_code",
            "code",
            "name",
            "description",
            "min_credits",
            "max_credits",
            "is_active",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        min_c = attrs.get("min_credits") or getattr(self.instance, "min_credits", Decimal("2.0"))
        max_c = attrs.get("max_credits") or getattr(self.instance, "max_credits", Decimal("4.0"))

        if min_c < Decimal("0.0"):
            raise serializers.ValidationError({"min_credits": "Minimum credits cannot be negative."})
        if max_c < min_c:
            raise serializers.ValidationError({"max_credits": "Maximum credits cannot be less than minimum credits."})
        return attrs


class SubjectSerializer(serializers.ModelSerializer):
    department_code = serializers.CharField(source="department.code", read_only=True)

    class Meta:
        model = Subject
        fields = [
            "id",
            "department",
            "department_code",
            "name",
            "code",
            "description",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class PaperOfferingSerializer(serializers.ModelSerializer):
    academic_session_name = serializers.CharField(source="academic_session.name", read_only=True)
    semester_name = serializers.CharField(source="semester.name", read_only=True)
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    subject_category_code = serializers.CharField(source="subject_category.code", read_only=True)

    class Meta:
        model = PaperOffering
        fields = [
            "id",
            "academic_session",
            "academic_session_name",
            "semester",
            "semester_name",
            "subject",
            "subject_code",
            "subject_category",
            "subject_category_code",
            "paper_code",
            "title",
            "credits",
            "is_common_paper",
            "max_marks_internal",
            "max_marks_external",
            "pass_marks_external",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        session = attrs.get("academic_session") or getattr(self.instance, "academic_session", None)
        sem = attrs.get("semester") or getattr(self.instance, "semester", None)
        sub = attrs.get("subject") or getattr(self.instance, "subject", None)
        cat = attrs.get("subject_category") or getattr(self.instance, "subject_category", None)
        creds = attrs.get("credits") or getattr(self.instance, "credits", Decimal("4.0"))
        int_marks = attrs.get("max_marks_internal") or getattr(self.instance, "max_marks_internal", Decimal("20.00"))
        ext_marks = attrs.get("max_marks_external") or getattr(self.instance, "max_marks_external", Decimal("80.00"))
        pass_marks = attrs.get("pass_marks_external") or getattr(self.instance, "pass_marks_external", Decimal("28.00"))

        errors = {}

        # Numeric bounds
        if creds < Decimal("0.0"):
            errors["credits"] = "Credits cannot be negative."
        elif cat:
            if creds < cat.min_credits or creds > cat.max_credits:
                errors["credits"] = (
                    f"Credits ({creds}) must fall within category '{cat.code}' "
                    f"range [{cat.min_credits}, {cat.max_credits}]."
                )

        if int_marks < Decimal("0.0"):
            errors["max_marks_internal"] = "Internal marks cannot be negative."
        if ext_marks < Decimal("0.0"):
            errors["max_marks_external"] = "External marks cannot be negative."
        if pass_marks < Decimal("0.0"):
            errors["pass_marks_external"] = "Pass marks cannot be negative."
        elif ext_marks >= Decimal("0.0") and pass_marks > ext_marks:
            errors["pass_marks_external"] = "Pass marks cannot exceed maximum external marks."

        # Cross-college validation
        if session and sem and sub and cat:
            college_id = session.college_id
            if sem.programme.college_id != college_id:
                errors["semester"] = "Semester programme does not belong to the same college as the academic session."
            if sub.department.college_id != college_id:
                errors["subject"] = "Subject department does not belong to the same college as the academic session."
            if cat.college_id != college_id:
                errors["subject_category"] = "Subject category does not belong to the same college as the academic session."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class PaperProgrammeMappingSerializer(serializers.ModelSerializer):
    paper_code = serializers.CharField(source="paper_offering.paper_code", read_only=True)
    programme_code = serializers.CharField(source="programme.code", read_only=True)

    class Meta:
        model = PaperProgrammeMapping
        fields = [
            "id",
            "paper_offering",
            "paper_code",
            "programme",
            "programme_code",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        paper = attrs.get("paper_offering") or getattr(self.instance, "paper_offering", None)
        prog = attrs.get("programme") or getattr(self.instance, "programme", None)

        if paper and prog:
            if paper.academic_session.college_id != prog.college_id:
                raise serializers.ValidationError({
                    "programme": "Programme and PaperOffering must belong to the same college institution."
                })
        return attrs


class InstitutionalConfigSerializer(serializers.ModelSerializer):
    college_code = serializers.CharField(source="college.code", read_only=True)
    updated_by_username = serializers.CharField(source="updated_by.username", read_only=True)

    class Meta:
        model = InstitutionalConfig
        fields = [
            "id",
            "college",
            "college_code",
            "config_key",
            "config_value",
            "data_type",
            "description",
            "is_sensitive",
            "updated_by",
            "updated_by_username",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_by", "updated_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None)

        # Sensitive value masking: only superadmins or users with COLLEGE_SUPERADMIN can view raw sensitive values
        if instance.is_sensitive:
            is_superadmin = (
                user
                and user.is_authenticated
                and (user.role == RoleChoices.SUPERADMIN or user.is_superuser or user.has_role("COLLEGE_SUPERADMIN"))
            )
            if not is_superadmin:
                data["config_value"] = "********"
        return data

    def validate(self, attrs):
        val = attrs.get("config_value")
        d_type = attrs.get("data_type") or getattr(self.instance, "data_type", ConfigDataType.STRING)

        if val is not None:
            if d_type == ConfigDataType.INTEGER:
                try:
                    int(val)
                except (ValueError, TypeError):
                    raise serializers.ValidationError({"config_value": "Value must be a valid integer."})
            elif d_type == ConfigDataType.BOOLEAN:
                if str(val).strip().lower() not in ("true", "false", "1", "0"):
                    raise serializers.ValidationError({"config_value": "Value must be a valid boolean ('true' or 'false')."})
            elif d_type == ConfigDataType.JSON:
                try:
                    json.loads(val)
                except Exception as e:
                    raise serializers.ValidationError({"config_value": f"Value must be valid JSON: {e}"})

        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["updated_by"] = request.user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["updated_by"] = request.user
        return super().update(instance, validated_data)
