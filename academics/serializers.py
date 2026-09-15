from rest_framework import serializers

from .models import (
    Department,
    Division,
    PracticalBatch,
    Program,
    Semester,
    Subject,
)
from .validators import (
    normalize_code,
    normalize_string,
    validate_academic_year,
    validate_code_format,
    validate_non_empty_name,
)


class DepartmentSerializer(serializers.ModelSerializer):
    """
    Serializer for Department model with case-insensitive unique code validation.
    """

    class Meta:
        model = Department
        fields = [
            "id",
            "name",
            "code",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_name(self, value):
        return validate_non_empty_name(value, "Department name")

    def validate_code(self, value):
        cleaned = validate_code_format(value)
        qs = Department.objects.filter(code__iexact=cleaned)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A department with this code already exists."
            )
        return cleaned


class ProgramSerializer(serializers.ModelSerializer):
    """
    Serializer for Program model with department nested read details.
    """

    department_name = serializers.CharField(
        source="department.name", read_only=True
    )
    department_code = serializers.CharField(
        source="department.code", read_only=True
    )

    class Meta:
        model = Program
        fields = [
            "id",
            "department",
            "department_name",
            "department_code",
            "name",
            "code",
            "duration_years",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "department_name",
            "department_code",
            "created_at",
            "updated_at",
        ]

    def validate_name(self, value):
        return validate_non_empty_name(value, "Program name")

    def validate_code(self, value):
        cleaned = validate_code_format(value)
        qs = Program.objects.filter(code__iexact=cleaned)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A program with this code already exists."
            )
        return cleaned

    def validate_duration_years(self, value):
        if value < 1 or value > 10:
            raise serializers.ValidationError(
                "Duration in years must be between 1 and 10."
            )
        return value


class SemesterSerializer(serializers.ModelSerializer):
    """
    Serializer for Semester model with program and department read-only attributes.
    """

    program_name = serializers.CharField(source="program.name", read_only=True)
    program_code = serializers.CharField(source="program.code", read_only=True)
    department_name = serializers.CharField(
        source="program.department.name", read_only=True
    )

    class Meta:
        model = Semester
        fields = [
            "id",
            "program",
            "program_name",
            "program_code",
            "department_name",
            "number",
            "academic_year",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "program_name",
            "program_code",
            "department_name",
            "created_at",
            "updated_at",
        ]

    def validate_academic_year(self, value):
        return validate_academic_year(value)

    def validate_number(self, value):
        if value < 1 or value > 20:
            raise serializers.ValidationError(
                "Semester number must be between 1 and 20."
            )
        return value

    def validate(self, attrs):
        program = attrs.get("program") or (self.instance.program if self.instance else None)
        number = attrs.get("number") or (self.instance.number if self.instance else None)
        academic_year = attrs.get("academic_year") or (
            self.instance.academic_year if self.instance else None
        )

        if program and number and academic_year:
            qs = Semester.objects.filter(
                program=program,
                number=number,
                academic_year__iexact=academic_year.strip(),
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    "A semester with this program, number, and academic year already exists."
                )

            max_semesters = program.duration_years * 2
            if number > max_semesters:
                raise serializers.ValidationError(
                    {
                        "number": f"Semester number ({number}) cannot exceed maximum program semesters ({max_semesters})."
                    }
                )

        return attrs


class DivisionSerializer(serializers.ModelSerializer):
    """
    Serializer for Division model.
    """

    semester_number = serializers.IntegerField(
        source="semester.number", read_only=True
    )
    academic_year = serializers.CharField(
        source="semester.academic_year", read_only=True
    )
    program_code = serializers.CharField(
        source="semester.program.code", read_only=True
    )

    class Meta:
        model = Division
        fields = [
            "id",
            "semester",
            "semester_number",
            "academic_year",
            "program_code",
            "name",
            "capacity",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "semester_number",
            "academic_year",
            "program_code",
            "created_at",
            "updated_at",
        ]

    def validate_name(self, value):
        return validate_non_empty_name(value, "Division name")

    def validate_capacity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Capacity must be a positive integer greater than 0.")
        return value

    def validate(self, attrs):
        semester = attrs.get("semester") or (self.instance.semester if self.instance else None)
        name = attrs.get("name") or (self.instance.name if self.instance else None)

        if semester and name:
            cleaned_name = normalize_string(name)
            qs = Division.objects.filter(semester=semester, name__iexact=cleaned_name)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    "A division with this name already exists in this semester."
                )

        return attrs


class PracticalBatchSerializer(serializers.ModelSerializer):
    """
    Serializer for PracticalBatch model.
    """

    division_name = serializers.CharField(
        source="division.name", read_only=True
    )
    semester_number = serializers.IntegerField(
        source="division.semester.number", read_only=True
    )

    class Meta:
        model = PracticalBatch
        fields = [
            "id",
            "division",
            "division_name",
            "semester_number",
            "name",
            "capacity",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "division_name",
            "semester_number",
            "created_at",
            "updated_at",
        ]

    def validate_name(self, value):
        return validate_non_empty_name(value, "Batch name")

    def validate_capacity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Capacity must be a positive integer greater than 0.")
        return value

    def validate(self, attrs):
        division = attrs.get("division") or (self.instance.division if self.instance else None)
        name = attrs.get("name") or (self.instance.name if self.instance else None)

        if division and name:
            cleaned_name = normalize_string(name)
            qs = PracticalBatch.objects.filter(division=division, name__iexact=cleaned_name)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    "A practical batch with this name already exists in this division."
                )

        return attrs


class SubjectSerializer(serializers.ModelSerializer):
    """
    Serializer for Subject model.
    """

    program_name = serializers.CharField(source="program.name", read_only=True)
    program_code = serializers.CharField(source="program.code", read_only=True)

    class Meta:
        model = Subject
        fields = [
            "id",
            "program",
            "program_name",
            "program_code",
            "name",
            "code",
            "type",
            "credits",
            "weekly_lectures",
            "weekly_practicals",
            "duration_minutes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "program_name",
            "program_code",
            "created_at",
            "updated_at",
        ]

    def validate_name(self, value):
        return validate_non_empty_name(value, "Subject name")

    def validate_code(self, value):
        cleaned = validate_code_format(value)
        qs = Subject.objects.filter(code__iexact=cleaned)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A subject with this code already exists.")
        return cleaned

    def validate_credits(self, value):
        if value < 0:
            raise serializers.ValidationError("Credits cannot be negative.")
        return value

    def validate_weekly_lectures(self, value):
        if value < 0:
            raise serializers.ValidationError("Weekly lectures cannot be negative.")
        return value

    def validate_weekly_practicals(self, value):
        if value < 0:
            raise serializers.ValidationError("Weekly practicals cannot be negative.")
        return value

    def validate_duration_minutes(self, value):
        if value <= 0:
            raise serializers.ValidationError("Duration in minutes must be greater than 0.")
        return value
