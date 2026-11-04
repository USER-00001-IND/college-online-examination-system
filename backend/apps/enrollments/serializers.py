"""
Serializers for Enrollments Domain.
Handles StudentAcademicRecord representation, validation, and persistence.
"""

from rest_framework import serializers
from apps.academics.models import AcademicSession, Programme
from apps.enrollments.models import AcademicRecordStatus, StudentAcademicRecord
from apps.enrollments.services import (
    create_student_academic_record,
    update_student_academic_record,
)
from apps.students.models import StudentProfile


class StudentAcademicRecordSerializer(serializers.ModelSerializer):
    """
    Serializer for student programme admission ledger (Table 18: enrollments_student_academic_record).
    """
    student_enrollment_number = serializers.CharField(source='student.enrollment_number', read_only=True)
    student_name = serializers.CharField(source='student.user.get_full_name', read_only=True)
    programme_code = serializers.CharField(source='programme.code', read_only=True)
    programme_name = serializers.CharField(source='programme.name', read_only=True)
    academic_session_name = serializers.CharField(source='academic_session.name', read_only=True)

    class Meta:
        model = StudentAcademicRecord
        fields = [
            'id',
            'student',
            'student_enrollment_number',
            'student_name',
            'programme',
            'programme_code',
            'programme_name',
            'academic_session',
            'academic_session_name',
            'admission_date',
            'status',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def validate(self, attrs):
        student = attrs.get('student') or getattr(self.instance, 'student', None)
        programme = attrs.get('programme') or getattr(self.instance, 'programme', None)
        session = attrs.get('academic_session') or getattr(self.instance, 'academic_session', None)

        if student and programme and session:
            college_id = student.college_id
            if programme.college_id != college_id:
                raise serializers.ValidationError({
                    "programme": f"Programme '{programme.code}' does not belong to student's college."
                })
            if session.college_id != college_id:
                raise serializers.ValidationError({
                    "academic_session": f"Session '{session.name}' does not belong to student's college."
                })
        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        acting_user = request.user if request else None
        return create_student_academic_record(acting_user=acting_user, **validated_data)

    def update(self, instance, validated_data):
        request = self.context.get('request')
        acting_user = request.user if request else None
        return update_student_academic_record(
            record_id=instance.pk,
            acting_user=acting_user,
            validated_data=validated_data,
        )
