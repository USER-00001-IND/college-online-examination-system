"""
Academic Management Serializers.
Provides serialization, complete-state validation, and relational integrity checking for Domain B FYUGP entities.
"""

from decimal import Decimal
import json
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import exceptions, serializers

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
from apps.academics.services import (
    create_institutional_config,
    update_institutional_config,
    update_paper_offering,
    validate_paper_offering_relationships,
    validate_paper_programme_mapping,
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
        read_only_fields = ["id", "is_current", "created_at"]

    def validate(self, attrs):
        # Reject attempts to modify is_current via ordinary CRUD
        request = self.context.get("request")
        if "is_current" in attrs or (request and "is_current" in getattr(request, "data", {})):
            raise serializers.ValidationError({
                "is_current": (
                    "is_current cannot be modified via ordinary CRUD endpoints. "
                    "Use the dedicated POST /api/v1/academics/sessions/{id}/set-current/ action."
                )
            })

        start_date = (
            attrs["start_date"]
            if "start_date" in attrs
            else getattr(self.instance, "start_date", None)
        )
        end_date = (
            attrs["end_date"]
            if "end_date" in attrs
            else getattr(self.instance, "end_date", None)
        )

        if start_date and end_date and start_date >= end_date:
            raise serializers.ValidationError({
                "end_date": "Academic session start_date must precede end_date."
            })
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
        prog = (
            attrs["programme"]
            if "programme" in attrs
            else getattr(self.instance, "programme", None)
        )
        sem_num = (
            attrs["semester_number"]
            if "semester_number" in attrs
            else getattr(self.instance, "semester_number", None)
        )

        errors = {}
        if sem_num is not None and sem_num < 1:
            errors["semester_number"] = "Semester number must be at least 1."

        if prog and sem_num is not None:
            if sem_num > prog.duration_semesters:
                errors["semester_number"] = (
                    f"Semester number ({sem_num}) exceeds programme duration ({prog.duration_semesters})."
                )

        if errors:
            raise serializers.ValidationError(errors)
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
        min_c = (
            attrs["min_credits"]
            if "min_credits" in attrs
            else getattr(self.instance, "min_credits", Decimal("2.0"))
        )
        max_c = (
            attrs["max_credits"]
            if "max_credits" in attrs
            else getattr(self.instance, "max_credits", Decimal("4.0"))
        )

        errors = {}
        if min_c < Decimal("0.0"):
            errors["min_credits"] = "Minimum credits cannot be negative."
        if max_c < min_c:
            errors["max_credits"] = "Maximum credits cannot be less than minimum credits."

        if errors:
            raise serializers.ValidationError(errors)
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
        # Explicit field-presence checks to ensure complete-state validation and avoid truthiness zero bypass
        session = (
            attrs["academic_session"]
            if "academic_session" in attrs
            else getattr(self.instance, "academic_session", None)
        )
        sem = (
            attrs["semester"]
            if "semester" in attrs
            else getattr(self.instance, "semester", None)
        )
        sub = (
            attrs["subject"]
            if "subject" in attrs
            else getattr(self.instance, "subject", None)
        )
        cat = (
            attrs["subject_category"]
            if "subject_category" in attrs
            else getattr(self.instance, "subject_category", None)
        )
        creds = (
            attrs["credits"]
            if "credits" in attrs
            else getattr(self.instance, "credits", Decimal("4.0"))
        )
        int_marks = (
            attrs["max_marks_internal"]
            if "max_marks_internal" in attrs
            else getattr(self.instance, "max_marks_internal", Decimal("20.00"))
        )
        ext_marks = (
            attrs["max_marks_external"]
            if "max_marks_external" in attrs
            else getattr(self.instance, "max_marks_external", Decimal("80.00"))
        )
        pass_marks = (
            attrs["pass_marks_external"]
            if "pass_marks_external" in attrs
            else getattr(self.instance, "pass_marks_external", Decimal("28.00"))
        )

        errors = {}
        if not session:
            errors["academic_session"] = "Academic session is required."
        if not sem:
            errors["semester"] = "Semester is required."
        if not sub:
            errors["subject"] = "Subject is required."
        if not cat:
            errors["subject_category"] = "Subject category is required."

        if errors:
            raise serializers.ValidationError(errors)

        # Common-paper invariant: cannot set is_common_paper to False while programme mappings exist
        if self.instance and self.instance.pk:
            new_is_common = attrs.get("is_common_paper", self.instance.is_common_paper)
            if not new_is_common and self.instance.programme_mappings.exists():
                raise serializers.ValidationError({
                    "is_common_paper": (
                        "Cannot set is_common_paper to False while programme mappings exist. "
                        "Remove all programme mappings first."
                    )
                })

        # Programme duration coverage invariant: existing programme mappings must cover proposed semester number
        if self.instance and self.instance.pk and sem:
            sem_num = sem.semester_number
            for mapping in self.instance.programme_mappings.select_related("programme"):
                if mapping.programme.duration_semesters < sem_num:
                    raise serializers.ValidationError({
                        "semester": (
                            f"Cannot move paper offering to semester {sem_num}: mapped programme "
                            f"'{mapping.programme.code}' duration ({mapping.programme.duration_semesters} sem) "
                            f"does not cover proposed semester ({sem_num}). "
                            "Remove or update incompatible programme mappings first."
                        )
                    })

        try:
            validate_paper_offering_relationships(
                academic_session=session,
                semester=sem,
                subject=sub,
                subject_category=cat,
                credits=creds,
                max_marks_internal=int_marks,
                max_marks_external=ext_marks,
                pass_marks_external=pass_marks,
            )
        except DjangoValidationError as exc:
            if hasattr(exc, "message_dict"):
                raise serializers.ValidationError(exc.message_dict)
            raise serializers.ValidationError(exc.messages if hasattr(exc, "messages") else [str(exc)])

        return attrs

    def update(self, instance, validated_data):
        try:
            return update_paper_offering(
                paper_offering_id=instance.pk,
                validated_data=validated_data,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else (exc.messages if hasattr(exc, "messages") else [str(exc)])
            )


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
        paper = (
            attrs["paper_offering"]
            if "paper_offering" in attrs
            else getattr(self.instance, "paper_offering", None)
        )
        prog = (
            attrs["programme"]
            if "programme" in attrs
            else getattr(self.instance, "programme", None)
        )

        if not paper or not prog:
            raise serializers.ValidationError("Both paper_offering and programme are required.")

        try:
            validate_paper_programme_mapping(paper, prog)
        except DjangoValidationError as exc:
            if hasattr(exc, "message_dict"):
                raise serializers.ValidationError(exc.message_dict)
            raise serializers.ValidationError(exc.messages if hasattr(exc, "messages") else [str(exc)])

        return attrs

    def create(self, validated_data):
        with transaction.atomic():
            paper = PaperOffering.objects.select_for_update().get(pk=validated_data["paper_offering"].pk)
            mapping = super().create(validated_data)
            if not paper.is_common_paper:
                paper.is_common_paper = True
                paper.save(update_fields=["is_common_paper"])
            return mapping

    def update(self, instance, validated_data):
        with transaction.atomic():
            target_paper_offering = validated_data.get("paper_offering", instance.paper_offering)
            pks = sorted({instance.paper_offering_id, target_paper_offering.pk})
            locked_offerings = {
                po.pk: po
                for po in PaperOffering.objects.select_for_update().filter(pk__in=pks).order_by("pk")
            }
            mapping = super().update(instance, validated_data)
            paper = locked_offerings[target_paper_offering.pk]
            if not paper.is_common_paper:
                paper.is_common_paper = True
                paper.save(update_fields=["is_common_paper"])
            return mapping


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
                and (
                    user.role == RoleChoices.SUPERADMIN
                    or user.is_superuser
                    or (hasattr(user, "has_role") and user.has_role("COLLEGE_SUPERADMIN"))
                )
                and user.role != RoleChoices.STUDENT
                and user.role != RoleChoices.FACULTY
            )
            if not is_superadmin:
                data["config_value"] = "********"
        return data

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        # Check sensitivity authorization:
        # If existing object is sensitive OR requested sensitivity is True, require Superadmin privileges
        existing_sensitive = getattr(self.instance, "is_sensitive", False) if self.instance else False
        new_sensitive = (
            attrs["is_sensitive"]
            if "is_sensitive" in attrs
            else existing_sensitive
        )

        if existing_sensitive or new_sensitive:
            is_superadmin = (
                user
                and user.is_authenticated
                and (
                    user.role == RoleChoices.SUPERADMIN
                    or user.is_superuser
                    or (hasattr(user, "has_role") and user.has_role("COLLEGE_SUPERADMIN"))
                )
                and user.role != RoleChoices.STUDENT
                and user.role != RoleChoices.FACULTY
            )
            if not is_superadmin:
                raise exceptions.PermissionDenied(
                    "Superadministrator privileges required for sensitive institutional configuration."
                )

        val = (
            attrs["config_value"]
            if "config_value" in attrs
            else getattr(self.instance, "config_value", None)
        )
        d_type = (
            attrs["data_type"]
            if "data_type" in attrs
            else getattr(self.instance, "data_type", ConfigDataType.STRING)
        )

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
                except (json.JSONDecodeError, ValueError):
                    raise serializers.ValidationError({"config_value": "Value must be valid JSON."})

        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        try:
            return create_institutional_config(
                college_id=validated_data["college"].pk,
                validated_data=validated_data,
                user=user,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else (exc.messages if hasattr(exc, "messages") else [str(exc)])
            )

    def update(self, instance, validated_data):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        try:
            return update_institutional_config(
                config_id=instance.pk,
                validated_data=validated_data,
                user=user,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else (exc.messages if hasattr(exc, "messages") else [str(exc)])
            )


class MapProgrammesPayloadSerializer(serializers.Serializer):
    """
    Dedicated explicit serializer for POST /paper-offerings/{id}/map-programmes/ action.
    Enforces strict boolean type validation on 'replace' and non-empty distinct integer list on 'programme_ids'.
    """
    programme_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )
    replace = serializers.BooleanField(
        required=False,
        default=False,
    )

    def validate_programme_ids(self, value):
        if not value:
            raise serializers.ValidationError("programme_ids list cannot be empty.")
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Duplicate programme IDs are not permitted in programme_ids.")
        return value

    def validate_replace(self, value):
        raw_replace = self.initial_data.get("replace")
        if raw_replace is not None:
            # Genuine JSON boolean check: type(True) is bool, type(False) is bool.
            # Reject strings like "false", "true", or numbers 0, 1.
            if type(raw_replace) is not bool:
                raise serializers.ValidationError(
                    "replace must be a genuine JSON boolean (true or false), not a string or number."
                )
        return value
