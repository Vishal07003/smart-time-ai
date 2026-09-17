from rest_framework import serializers

from .models import (
    Classroom,
    Department,
    Division,
    Laboratory,
    PracticalBatch,
    Program,
    Semester,
    Subject,
    TeacherAvailability,
    TeacherLeave,
    TeacherSubject,
    Timetable,
    TimetableSlot,
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


class TeacherSubjectSerializer(serializers.ModelSerializer):
    """
    Serializer for TeacherSubject assignment mapping model.
    """

    teacher_employee_code = serializers.CharField(
        source="teacher.employee_code", read_only=True
    )
    teacher_name = serializers.CharField(
        source="teacher.user.get_full_name", read_only=True
    )
    subject_name = serializers.CharField(
        source="subject.name", read_only=True
    )
    subject_code = serializers.CharField(
        source="subject.code", read_only=True
    )

    class Meta:
        model = TeacherSubject
        fields = [
            "id",
            "teacher",
            "teacher_employee_code",
            "teacher_name",
            "subject",
            "subject_name",
            "subject_code",
            "priority",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "teacher_employee_code",
            "teacher_name",
            "subject_name",
            "subject_code",
            "created_at",
            "updated_at",
        ]

    def validate_priority(self, value):
        if value < 1:
            raise serializers.ValidationError("Priority must be a positive integer greater than 0.")
        return value

    def validate(self, attrs):
        teacher = attrs.get("teacher") or (self.instance.teacher if self.instance else None)
        subject = attrs.get("subject") or (self.instance.subject if self.instance else None)

        if teacher and subject:
            qs = TeacherSubject.objects.filter(teacher=teacher, subject=subject)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    "This teacher is already assigned to this subject."
                )

        return attrs


class TeacherAvailabilitySerializer(serializers.ModelSerializer):
    """
    Serializer for TeacherAvailability model.
    """

    teacher_employee_code = serializers.CharField(
        source="teacher.employee_code", read_only=True
    )
    teacher_name = serializers.CharField(
        source="teacher.user.get_full_name", read_only=True
    )

    class Meta:
        model = TeacherAvailability
        fields = [
            "id",
            "teacher",
            "teacher_employee_code",
            "teacher_name",
            "day",
            "start_time",
            "end_time",
            "is_available",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "teacher_employee_code",
            "teacher_name",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "teacher": {"required": False},
        }

    def validate_day(self, value):
        cleaned = value.strip().upper() if isinstance(value, str) else value
        if cleaned not in TeacherAvailability.Day.values:
            raise serializers.ValidationError(f"Invalid day '{value}'.")
        return cleaned

    def validate(self, attrs):
        request = self.context.get("request")
        teacher = attrs.get("teacher") or (self.instance.teacher if self.instance else None)

        if not teacher and request and hasattr(request.user, "teacher_profile"):
            teacher = request.user.teacher_profile
            attrs["teacher"] = teacher

        if not teacher:
            raise serializers.ValidationError({"teacher": "Teacher profile is required."})

        # If teacher user, ensure they can only assign themselves
        if (
            request
            and request.user.is_authenticated
            and hasattr(request.user, "role")
            and request.user.role == "TEACHER"
        ):
            if hasattr(request.user, "teacher_profile") and teacher != request.user.teacher_profile:
                raise serializers.ValidationError(
                    {"teacher": "Teachers can only manage their own availability."}
                )

        day = attrs.get("day") or (self.instance.day if self.instance else None)
        start_time = attrs.get("start_time") or (self.instance.start_time if self.instance else None)
        end_time = attrs.get("end_time") or (self.instance.end_time if self.instance else None)

        if start_time and end_time:
            if start_time >= end_time:
                raise serializers.ValidationError(
                    {"end_time": "End time must be strictly after start time."}
                )

            if teacher and day:
                overlapping_qs = TeacherAvailability.objects.filter(
                    teacher=teacher,
                    day=day,
                    start_time__lt=end_time,
                    end_time__gt=start_time,
                )
                if self.instance:
                    overlapping_qs = overlapping_qs.exclude(pk=self.instance.pk)
                if overlapping_qs.exists():
                    raise serializers.ValidationError(
                        "Availability time slot overlaps with an existing slot for this teacher on this day."
                    )

        return attrs


class TeacherLeaveSerializer(serializers.ModelSerializer):
    """
    Serializer for TeacherLeave model.
    - Teachers can only submit leaves for themselves, with status=PENDING.
    - Staff can create/update leaves for any teacher, including approving/rejecting.
    """

    teacher_employee_code = serializers.CharField(
        source="teacher.employee_code", read_only=True
    )
    teacher_name = serializers.CharField(
        source="teacher.user.get_full_name", read_only=True
    )

    class Meta:
        model = TeacherLeave
        fields = [
            "id",
            "teacher",
            "teacher_employee_code",
            "teacher_name",
            "start_date",
            "end_date",
            "reason",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "teacher_employee_code",
            "teacher_name",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "teacher": {"required": False},
        }

    def validate_reason(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Reason for leave cannot be blank.")
        return value.strip()

    def validate(self, attrs):
        request = self.context.get("request")
        teacher = attrs.get("teacher") or (self.instance.teacher if self.instance else None)

        # Auto-bind teacher profile for teacher role user
        if not teacher and request and hasattr(request.user, "teacher_profile"):
            teacher = request.user.teacher_profile
            attrs["teacher"] = teacher

        if not teacher:
            raise serializers.ValidationError({"teacher": "Teacher profile is required."})

        # Permissions and status restrictions for teachers
        if (
            request
            and request.user.is_authenticated
            and hasattr(request.user, "role")
            and request.user.role == "TEACHER"
        ):
            if hasattr(request.user, "teacher_profile") and teacher != request.user.teacher_profile:
                raise serializers.ValidationError(
                    {"teacher": "Teachers can only manage their own leaves."}
                )

            # Prevent teacher from setting or changing status to APPROVED or REJECTED
            if "status" in attrs and attrs["status"] != TeacherLeave.Status.PENDING:
                raise serializers.ValidationError(
                    {"status": "Only staff members can approve or reject leaves."}
                )
            if not self.instance:
                attrs["status"] = TeacherLeave.Status.PENDING

        start_date = attrs.get("start_date") or (self.instance.start_date if self.instance else None)
        end_date = attrs.get("end_date") or (self.instance.end_date if self.instance else None)

        if start_date and end_date:
            if start_date > end_date:
                raise serializers.ValidationError(
                    {"end_date": "End date must be greater than or equal to start date."}
                )

            # Check overlap if status is not REJECTED
            target_status = attrs.get("status") or (self.instance.status if self.instance else TeacherLeave.Status.PENDING)
            if target_status != TeacherLeave.Status.REJECTED and teacher:
                overlapping_qs = TeacherLeave.objects.filter(
                    teacher=teacher,
                    start_date__lte=end_date,
                    end_date__gte=start_date,
                ).exclude(status=TeacherLeave.Status.REJECTED)

                if self.instance:
                    overlapping_qs = overlapping_qs.exclude(pk=self.instance.pk)

                if overlapping_qs.exists():
                    raise serializers.ValidationError(
                        "A leave request for this teacher already overlaps with the selected date range."
                    )

        return attrs


class ClassroomSerializer(serializers.ModelSerializer):
    """
    Serializer for Classroom model.
    """

    class Meta:
        model = Classroom
        fields = [
            "id",
            "building",
            "room_number",
            "floor",
            "capacity",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_building(self, value):
        return validate_non_empty_name(value, "Building")

    def validate_room_number(self, value):
        return validate_non_empty_name(value, "Room number")

    def validate_capacity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Capacity must be a positive integer greater than 0.")
        return value

    def validate_status(self, value):
        cleaned = value.strip().upper() if isinstance(value, str) else value
        if cleaned not in Classroom.Status.values:
            raise serializers.ValidationError(f"Invalid status '{value}'.")
        return cleaned

    def validate(self, attrs):
        building = attrs.get("building") or (self.instance.building if self.instance else None)
        room_number = attrs.get("room_number") or (self.instance.room_number if self.instance else None)

        if building and room_number:
            b_clean = normalize_string(building)
            r_clean = normalize_string(room_number)
            qs = Classroom.objects.filter(building__iexact=b_clean, room_number__iexact=r_clean)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    "A classroom with this room number already exists in this building."
                )

        return attrs


class LaboratorySerializer(serializers.ModelSerializer):
    """
    Serializer for Laboratory model.
    """

    class Meta:
        model = Laboratory
        fields = [
            "id",
            "building",
            "lab_number",
            "name",
            "floor",
            "capacity",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_building(self, value):
        return validate_non_empty_name(value, "Building")

    def validate_lab_number(self, value):
        return validate_non_empty_name(value, "Lab number")

    def validate_name(self, value):
        return validate_non_empty_name(value, "Laboratory name")

    def validate_capacity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Capacity must be a positive integer greater than 0.")
        return value

    def validate_status(self, value):
        cleaned = value.strip().upper() if isinstance(value, str) else value
        if cleaned not in Laboratory.Status.values:
            raise serializers.ValidationError(f"Invalid status '{value}'.")
        return cleaned

    def validate(self, attrs):
        building = attrs.get("building") or (self.instance.building if self.instance else None)
        lab_number = attrs.get("lab_number") or (self.instance.lab_number if self.instance else None)

        if building and lab_number:
            b_clean = normalize_string(building)
            l_clean = normalize_string(lab_number)
            qs = Laboratory.objects.filter(building__iexact=b_clean, lab_number__iexact=l_clean)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    "A laboratory with this lab number already exists in this building."
                )

        return attrs


class TimetableSerializer(serializers.ModelSerializer):
    """
    Serializer for Timetable model.
    Workflow: DRAFT -> GENERATED -> REVIEW -> PUBLISHED -> ARCHIVED
    """

    semester_number = serializers.IntegerField(
        source="semester.number", read_only=True
    )
    program_code = serializers.CharField(
        source="semester.program.code", read_only=True
    )
    program_name = serializers.CharField(
        source="semester.program.name", read_only=True
    )
    created_by_username = serializers.CharField(
        source="created_by.username", read_only=True
    )

    class Meta:
        model = Timetable
        fields = [
            "id",
            "semester",
            "semester_number",
            "program_code",
            "program_name",
            "academic_year",
            "version",
            "status",
            "created_by",
            "created_by_username",
            "published_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "semester_number",
            "program_code",
            "program_name",
            "created_by",
            "created_by_username",
            "published_at",
            "created_at",
            "updated_at",
        ]

    def validate_academic_year(self, value):
        return validate_academic_year(value)

    def validate_version(self, value):
        if value < 1:
            raise serializers.ValidationError("Version must be a positive integer greater than 0.")
        return value

    def validate_status(self, value):
        cleaned = value.strip().upper() if isinstance(value, str) else value
        if cleaned not in Timetable.Status.values:
            raise serializers.ValidationError(f"Invalid status '{value}'.")
        return cleaned

    def validate(self, attrs):
        if self.instance and self.instance.status == Timetable.Status.ARCHIVED:
            raise serializers.ValidationError("Cannot edit an ARCHIVED timetable.")

        semester = attrs.get("semester") or (self.instance.semester if self.instance else None)
        academic_year = attrs.get("academic_year") or (self.instance.academic_year if self.instance else None)
        version = attrs.get("version") or (self.instance.version if self.instance else None)

        if semester and academic_year and version:
            qs = Timetable.objects.filter(
                semester=semester,
                academic_year=academic_year.strip(),
                version=version,
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    "A timetable with this semester, academic year, and version already exists."
                )

        return attrs


class TimetableSlotSerializer(serializers.ModelSerializer):
    """
    Serializer for TimetableSlot model.
    """

    division_name = serializers.CharField(
        source="division.name", read_only=True
    )
    batch_name = serializers.CharField(
        source="batch.name", read_only=True
    )
    subject_code = serializers.CharField(
        source="subject.code", read_only=True
    )
    subject_name = serializers.CharField(
        source="subject.name", read_only=True
    )
    teacher_employee_code = serializers.CharField(
        source="teacher.employee_code", read_only=True
    )
    teacher_name = serializers.CharField(
        source="teacher.user.get_full_name", read_only=True
    )
    classroom_name = serializers.SerializerMethodField()
    laboratory_name = serializers.SerializerMethodField()

    class Meta:
        model = TimetableSlot
        fields = [
            "id",
            "timetable",
            "division",
            "division_name",
            "batch",
            "batch_name",
            "subject",
            "subject_code",
            "subject_name",
            "teacher",
            "teacher_employee_code",
            "teacher_name",
            "classroom",
            "classroom_name",
            "laboratory",
            "laboratory_name",
            "day",
            "start_time",
            "end_time",
            "session_type",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "division_name",
            "batch_name",
            "subject_code",
            "subject_name",
            "teacher_employee_code",
            "teacher_name",
            "classroom_name",
            "laboratory_name",
            "created_at",
            "updated_at",
        ]

    def get_classroom_name(self, obj):
        if obj.classroom:
            return f"{obj.classroom.building} - {obj.classroom.room_number}"
        return None

    def get_laboratory_name(self, obj):
        if obj.laboratory:
            return f"{obj.laboratory.building} - {obj.laboratory.lab_number} ({obj.laboratory.name})"
        return None

    def validate_day(self, value):
        cleaned = value.strip().upper() if isinstance(value, str) else value
        if cleaned not in TimetableSlot.Day.values:
            raise serializers.ValidationError(f"Invalid day '{value}'.")
        return cleaned

    def validate_session_type(self, value):
        cleaned = value.strip().upper() if isinstance(value, str) else value
        if cleaned not in TimetableSlot.SessionType.values:
            raise serializers.ValidationError(f"Invalid session type '{value}'.")
        return cleaned

    def validate_status(self, value):
        cleaned = value.strip().upper() if isinstance(value, str) else value
        if cleaned not in TimetableSlot.Status.values:
            raise serializers.ValidationError(f"Invalid status '{value}'.")
        return cleaned

    def validate(self, attrs):
        timetable = attrs.get("timetable") or (self.instance.timetable if self.instance else None)
        division = attrs.get("division") or (self.instance.division if self.instance else None)
        batch = attrs.get("batch") if "batch" in attrs else (self.instance.batch if self.instance else None)
        subject = attrs.get("subject") or (self.instance.subject if self.instance else None)
        teacher = attrs.get("teacher") or (self.instance.teacher if self.instance else None)
        classroom = attrs.get("classroom") if "classroom" in attrs else (self.instance.classroom if self.instance else None)
        laboratory = attrs.get("laboratory") if "laboratory" in attrs else (self.instance.laboratory if self.instance else None)
        session_type = attrs.get("session_type") or (self.instance.session_type if self.instance else TimetableSlot.SessionType.LECTURE)
        start_time = attrs.get("start_time") or (self.instance.start_time if self.instance else None)
        end_time = attrs.get("end_time") or (self.instance.end_time if self.instance else None)

        if timetable and timetable.status == Timetable.Status.ARCHIVED:
            raise serializers.ValidationError({"timetable": "Cannot create or modify slots for an ARCHIVED timetable."})

        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError({"end_time": "End time must be strictly after start time."})

        if division and timetable and division.semester_id != timetable.semester_id:
            raise serializers.ValidationError(
                {"division": "Selected division does not belong to the timetable's semester."}
            )

        if batch and division and batch.division_id != division.id:
            raise serializers.ValidationError(
                {"batch": "Selected batch does not belong to the specified division."}
            )

        if session_type == TimetableSlot.SessionType.PRACTICAL:
            if not laboratory and not classroom:
                raise serializers.ValidationError({"laboratory": "Practical sessions should have an assigned laboratory."})
        elif session_type in (TimetableSlot.SessionType.LECTURE, TimetableSlot.SessionType.TUTORIAL):
            if not classroom and not laboratory:
                raise serializers.ValidationError({"classroom": "Lecture and tutorial sessions should have an assigned classroom."})

        return attrs


