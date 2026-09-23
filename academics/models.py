import uuid
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from .validators import (
    normalize_code,
    normalize_string,
    validate_academic_year,
    validate_code_format,
    validate_non_empty_name,
)
class Department(models.Model):
    """
    Academic Department (e.g. Computer Science, Mechanical Engineering).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=150,
        help_text="Full department name (e.g., Computer Engineering)",
    )
    code = models.CharField(
        max_length=20,
        unique=True,
        help_text="Unique department code (e.g., CS, MECH, IT)",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Department"
        verbose_name_plural = "Departments"
        constraints = [
            models.UniqueConstraint(
                Lower("code"),
                name="unique_lower_department_code",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def clean(self):
        super().clean()
        if self.name:
            self.name = validate_non_empty_name(self.name, "Department name")
        if self.code:
            self.code = validate_code_format(self.code)
            # Case-insensitive duplicate check
            qs = Department.objects.filter(code__iexact=self.code)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({"code": "A department with this code already exists."})

    def save(self, *args, **kwargs):
        if self.name:
            self.name = normalize_string(self.name)
        if self.code:
            self.code = normalize_code(self.code)
        super().save(*args, **kwargs)


class Program(models.Model):
    """
    Academic Degree/Diploma Program (e.g. B.Tech Computer Science).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="programs",
        help_text="Parent department offering this program",
    )
    name = models.CharField(
        max_length=150,
        help_text="Full program name (e.g., Bachelor of Technology in Computer Science)",
    )
    code = models.CharField(
        max_length=20,
        unique=True,
        help_text="Unique program code (e.g., BTECH-CS, BE-IT)",
    )
    duration_years = models.PositiveSmallIntegerField(
        default=4,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Program duration in years (e.g., 4 for B.Tech, 2 for M.Tech)",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Program"
        verbose_name_plural = "Programs"
        constraints = [
            models.UniqueConstraint(
                Lower("code"),
                name="unique_lower_program_code",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def clean(self):
        super().clean()
        if self.name:
            self.name = validate_non_empty_name(self.name, "Program name")
        if self.code:
            self.code = validate_code_format(self.code)
            qs = Program.objects.filter(code__iexact=self.code)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({"code": "A program with this code already exists."})

    def save(self, *args, **kwargs):
        if self.name:
            self.name = normalize_string(self.name)
        if self.code:
            self.code = normalize_code(self.code)
        super().save(*args, **kwargs)


class Semester(models.Model):
    """
    Academic Semester tied to a Program and Academic Year.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    program = models.ForeignKey(
        Program,
        on_delete=models.CASCADE,
        related_name="semesters",
        help_text="Parent program for this semester",
    )
    number = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(20)],
        help_text="Semester number (e.g., 1, 2, 3, ...)",
    )
    academic_year = models.CharField(
        max_length=9,
        validators=[validate_academic_year],
        help_text="Academic session in 'YYYY-YYYY' format (e.g., 2025-2026)",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["academic_year", "number"]
        verbose_name = "Semester"
        verbose_name_plural = "Semesters"
        constraints = [
            models.UniqueConstraint(
                fields=["program", "number", "academic_year"],
                name="unique_program_semester_academic_year",
            ),
        ]

    def __str__(self):
        return f"{self.program.code} - Sem {self.number} ({self.academic_year})"

    def clean(self):
        super().clean()
        if self.academic_year:
            self.academic_year = validate_academic_year(self.academic_year)
        if self.number is not None and self.program_id:
            max_semesters = self.program.duration_years * 2
            if self.number > max_semesters:
                raise ValidationError(
                    {
                        "number": f"Semester number ({self.number}) cannot exceed program capacity of {max_semesters} semesters."
                    }
                )

    def save(self, *args, **kwargs):
        if self.academic_year:
            self.academic_year = self.academic_year.strip()
        super().save(*args, **kwargs)


class Division(models.Model):
    """
    Class Division / Section within a Semester (e.g. Div A, Div B).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    semester = models.ForeignKey(
        Semester,
        on_delete=models.CASCADE,
        related_name="divisions",
        help_text="Parent semester for this division",
    )
    name = models.CharField(
        max_length=30,
        help_text="Division/Section name (e.g., A, B, Div-1)",
    )
    capacity = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(1)],
        help_text="Maximum student capacity for this division (must be > 0)",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Division"
        verbose_name_plural = "Divisions"
        constraints = [
            models.UniqueConstraint(
                fields=["semester", "name"],
                name="unique_semester_division_name",
            ),
        ]

    def __str__(self):
        return f"{self.semester} - Div {self.name}"

    def clean(self):
        super().clean()
        if self.name:
            self.name = validate_non_empty_name(self.name, "Division name")
        if self.capacity is not None and self.capacity <= 0:
            raise ValidationError({"capacity": "Capacity must be a positive integer."})

    def save(self, *args, **kwargs):
        if self.name:
            self.name = normalize_string(self.name)
        super().save(*args, **kwargs)


class PracticalBatch(models.Model):
    """
    Practical/Lab Batch within a Division (e.g. Batch B1, Batch B2).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    division = models.ForeignKey(
        Division,
        on_delete=models.CASCADE,
        related_name="batches",
        help_text="Parent division for this practical batch",
    )
    name = models.CharField(
        max_length=30,
        help_text="Batch name (e.g., B1, B2, Batch-A)",
    )
    capacity = models.PositiveIntegerField(
        default=20,
        validators=[MinValueValidator(1)],
        help_text="Maximum student capacity for this practical batch (must be > 0)",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Practical Batch"
        verbose_name_plural = "Practical Batches"
        constraints = [
            models.UniqueConstraint(
                fields=["division", "name"],
                name="unique_division_batch_name",
            ),
        ]

    def __str__(self):
        return f"{self.division} - {self.name}"

    def clean(self):
        super().clean()
        if self.name:
            self.name = validate_non_empty_name(self.name, "Batch name")
        if self.capacity is not None and self.capacity <= 0:
            raise ValidationError({"capacity": "Capacity must be a positive integer."})

    def save(self, *args, **kwargs):
        if self.name:
            self.name = normalize_string(self.name)
        super().save(*args, **kwargs)


class Subject(models.Model):
    """
    Curricular Subject / Course tied to a Program.
    """

    class Type(models.TextChoices):
        LECTURE = "LECTURE", "Lecture"
        PRACTICAL = "PRACTICAL", "Practical"
        TUTORIAL = "TUTORIAL", "Tutorial"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    program = models.ForeignKey(
        Program,
        on_delete=models.CASCADE,
        related_name="subjects",
        help_text="Parent program offering this subject",
    )
    name = models.CharField(
        max_length=150,
        help_text="Subject title (e.g., Data Structures and Algorithms)",
    )
    code = models.CharField(
        max_length=30,
        unique=True,
        help_text="Unique subject code (e.g., CS201, IT-302)",
    )
    type = models.CharField(
        max_length=20,
        choices=Type.choices,
        default=Type.LECTURE,
        help_text="Subject delivery type (LECTURE, PRACTICAL, or TUTORIAL)",
    )
    credits = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=Decimal("3.0"),
        validators=[MinValueValidator(Decimal("0.0"))],
        help_text="Credit points assigned to this subject (>= 0)",
    )
    weekly_lectures = models.PositiveSmallIntegerField(
        default=3,
        validators=[MinValueValidator(0)],
        help_text="Number of lecture sessions per week (>= 0)",
    )
    weekly_practicals = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of practical/lab sessions per week (>= 0)",
    )
    duration_minutes = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(1)],
        help_text="Standard duration of a single session in minutes (e.g., 60)",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Subject"
        verbose_name_plural = "Subjects"
        constraints = [
            models.UniqueConstraint(
                Lower("code"),
                name="unique_lower_subject_code",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.code}) - {self.get_type_display()}"

    def clean(self):
        super().clean()
        if self.name:
            self.name = validate_non_empty_name(self.name, "Subject name")
        if self.code:
            self.code = validate_code_format(self.code)
            qs = Subject.objects.filter(code__iexact=self.code)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({"code": "A subject with this code already exists."})

        if self.duration_minutes is not None and self.duration_minutes <= 0:
            raise ValidationError(
                {"duration_minutes": "Duration in minutes must be greater than 0."}
            )

    def save(self, *args, **kwargs):
        if self.name:
            self.name = normalize_string(self.name)
        if self.code:
            self.code = normalize_code(self.code)
        super().save(*args, **kwargs)


class TeacherSubject(models.Model):
    """
    Mapping model assigning Subjects to TeacherProfiles.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    teacher = models.ForeignKey(
        "accounts.TeacherProfile",
        on_delete=models.CASCADE,
        related_name="teacher_subjects",
        help_text="Assigned teacher profile",
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="teacher_subjects",
        help_text="Assigned subject",
    )
    priority = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Assignment priority/preference rank (e.g., 1 = primary)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["teacher", "priority", "created_at"]
        verbose_name = "Teacher Subject Assignment"
        verbose_name_plural = "Teacher Subject Assignments"
        constraints = [
            models.UniqueConstraint(
                fields=["teacher", "subject"],
                name="unique_teacher_subject_assignment",
            ),
        ]

    def __str__(self):
        return f"{self.teacher.employee_code} -> {self.subject.code} (Priority: {self.priority})"

    def clean(self):
        super().clean()
        if self.priority is not None and self.priority < 1:
            raise ValidationError(
                {"priority": "Priority must be a positive integer greater than 0."}
            )
        if self.teacher_id and self.subject_id:
            qs = TeacherSubject.objects.filter(
                teacher_id=self.teacher_id, subject_id=self.subject_id
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    {"non_field_errors": ["This teacher is already assigned to this subject."]}
                )


class TeacherAvailability(models.Model):
    """
    Weekly availability / schedule constraints for Teachers.
    """

    class Day(models.TextChoices):
        MONDAY = "MONDAY", "Monday"
        TUESDAY = "TUESDAY", "Tuesday"
        WEDNESDAY = "WEDNESDAY", "Wednesday"
        THURSDAY = "THURSDAY", "Thursday"
        FRIDAY = "FRIDAY", "Friday"
        SATURDAY = "SATURDAY", "Saturday"
        SUNDAY = "SUNDAY", "Sunday"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    teacher = models.ForeignKey(
        "accounts.TeacherProfile",
        on_delete=models.CASCADE,
        related_name="availabilities",
        help_text="Associated teacher profile",
    )
    day = models.CharField(
        max_length=15,
        choices=Day.choices,
        help_text="Day of the week (e.g. MONDAY)",
    )
    start_time = models.TimeField(
        help_text="Slot start time",
    )
    end_time = models.TimeField(
        help_text="Slot end time",
    )
    is_available = models.BooleanField(
        default=True,
        help_text="Designates whether the teacher is available or unavailable during this slot",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["day", "start_time"]
        verbose_name = "Teacher Availability"
        verbose_name_plural = "Teacher Availabilities"

    def __str__(self):
        status = "Available" if self.is_available else "Unavailable"
        return f"{self.teacher.employee_code} - {self.day} ({self.start_time} - {self.end_time}) [{status}]"

    def clean(self):
        super().clean()
        if self.day:
            self.day = self.day.strip().upper()
            if self.day not in self.Day.values:
                raise ValidationError({"day": f"Invalid day '{self.day}'."})

        if self.start_time and self.end_time:
            if self.start_time >= self.end_time:
                raise ValidationError(
                    {"end_time": "End time must be strictly after start time."}
                )

            if self.teacher_id and self.day:
                overlapping_qs = TeacherAvailability.objects.filter(
                    teacher_id=self.teacher_id,
                    day=self.day,
                    start_time__lt=self.end_time,
                    end_time__gt=self.start_time,
                )
                if self.pk:
                    overlapping_qs = overlapping_qs.exclude(pk=self.pk)
                if overlapping_qs.exists():
                    raise ValidationError(
                        "Availability time slot overlaps with an existing slot for this teacher on this day."
                    )

    def save(self, *args, **kwargs):
        if self.day:
            self.day = self.day.strip().upper()
        super().save(*args, **kwargs)


class TeacherLeave(models.Model):
    """
    Teacher leave request model.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    teacher = models.ForeignKey(
        "accounts.TeacherProfile",
        on_delete=models.CASCADE,
        related_name="leaves",
        help_text="Associated teacher profile",
    )
    start_date = models.DateField(
        help_text="Leave start date",
    )
    end_date = models.DateField(
        help_text="Leave end date",
    )
    reason = models.TextField(
        help_text="Reason for leave request",
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Leave request status (PENDING, APPROVED, REJECTED)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date", "-created_at"]
        verbose_name = "Teacher Leave"
        verbose_name_plural = "Teacher Leaves"

    def __str__(self):
        return f"{self.teacher.employee_code} Leave: {self.start_date} to {self.end_date} [{self.status}]"

    def clean(self):
        super().clean()
        if self.reason:
            self.reason = self.reason.strip()
        if not self.reason:
            raise ValidationError({"reason": "Reason for leave cannot be blank."})

        if self.start_date and self.end_date:
            if self.start_date > self.end_date:
                raise ValidationError(
                    {"end_date": "End date must be greater than or equal to start date."}
                )

            if self.teacher_id:
                overlapping_qs = TeacherLeave.objects.filter(
                    teacher_id=self.teacher_id,
                    start_date__lte=self.end_date,
                    end_date__gte=self.start_date,
                ).exclude(status=self.Status.REJECTED)
                if self.pk:
                    overlapping_qs = overlapping_qs.exclude(pk=self.pk)
                if overlapping_qs.exists():
                    raise ValidationError(
                        "A leave request for this teacher already overlaps with the selected date range."
                    )

    def save(self, *args, **kwargs):
        if self.reason:
            self.reason = self.reason.strip()
        super().save(*args, **kwargs)


class Classroom(models.Model):
    """
    Physical classroom / lecture hall resource.
    """

    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        UNAVAILABLE = "UNAVAILABLE", "Unavailable"
        MAINTENANCE = "MAINTENANCE", "Maintenance"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    building = models.CharField(
        max_length=50,
        help_text="Building name or code (e.g., Main Building, Block A)",
    )
    room_number = models.CharField(
        max_length=20,
        help_text="Room number/name (e.g., 101, LH-1)",
    )
    floor = models.IntegerField(
        default=0,
        help_text="Floor number (e.g., 0 for Ground, 1 for 1st Floor)",
    )
    capacity = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(1)],
        help_text="Seating capacity (must be > 0)",
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.AVAILABLE,
        help_text="Classroom availability status (AVAILABLE, UNAVAILABLE, MAINTENANCE)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["building", "room_number"]
        verbose_name = "Classroom"
        verbose_name_plural = "Classrooms"
        constraints = [
            models.UniqueConstraint(
                fields=["building", "room_number"],
                name="unique_classroom_building_room",
            ),
        ]

    def __str__(self):
        return f"{self.building} - Room {self.room_number} (Cap: {self.capacity}) [{self.status}]"

    def clean(self):
        super().clean()
        if self.building:
            self.building = validate_non_empty_name(self.building, "Building")
        if self.room_number:
            self.room_number = validate_non_empty_name(self.room_number, "Room number")
        if self.capacity is not None and self.capacity <= 0:
            raise ValidationError({"capacity": "Capacity must be a positive integer."})
        if self.status:
            self.status = self.status.strip().upper()
            if self.status not in self.Status.values:
                raise ValidationError({"status": f"Invalid status '{self.status}'."})

    def save(self, *args, **kwargs):
        if self.building:
            self.building = normalize_string(self.building)
        if self.room_number:
            self.room_number = normalize_string(self.room_number)
        if self.status:
            self.status = self.status.strip().upper()
        super().save(*args, **kwargs)


class Laboratory(models.Model):
    """
    Physical laboratory resource.
    """

    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        UNAVAILABLE = "UNAVAILABLE", "Unavailable"
        MAINTENANCE = "MAINTENANCE", "Maintenance"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    building = models.CharField(
        max_length=50,
        help_text="Building name or code (e.g., Tech Block, Block B)",
    )
    lab_number = models.CharField(
        max_length=20,
        help_text="Lab number/code (e.g., LAB-101, L1)",
    )
    name = models.CharField(
        max_length=100,
        help_text="Laboratory name (e.g., Computer Systems Lab, Physics Lab)",
    )
    floor = models.IntegerField(
        default=0,
        help_text="Floor number (e.g., 0 for Ground, 1 for 1st Floor)",
    )
    capacity = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(1)],
        help_text="Lab student capacity (must be > 0)",
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.AVAILABLE,
        help_text="Laboratory availability status (AVAILABLE, UNAVAILABLE, MAINTENANCE)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["building", "lab_number"]
        verbose_name = "Laboratory"
        verbose_name_plural = "Laboratories"
        constraints = [
            models.UniqueConstraint(
                fields=["building", "lab_number"],
                name="unique_laboratory_building_lab",
            ),
        ]

    def __str__(self):
        return f"{self.building} - {self.lab_number} ({self.name}) [{self.status}]"

    def clean(self):
        super().clean()
        if self.building:
            self.building = validate_non_empty_name(self.building, "Building")
        if self.lab_number:
            self.lab_number = validate_non_empty_name(self.lab_number, "Lab number")
        if self.name:
            self.name = validate_non_empty_name(self.name, "Laboratory name")
        if self.capacity is not None and self.capacity <= 0:
            raise ValidationError({"capacity": "Capacity must be a positive integer."})
        if self.status:
            self.status = self.status.strip().upper()
            if self.status not in self.Status.values:
                raise ValidationError({"status": f"Invalid status '{self.status}'."})

    def save(self, *args, **kwargs):
        if self.building:
            self.building = normalize_string(self.building)
        if self.lab_number:
            self.lab_number = normalize_string(self.lab_number)
        if self.name:
            self.name = normalize_string(self.name)
        if self.status:
            self.status = self.status.strip().upper()
        super().save(*args, **kwargs)


class Timetable(models.Model):
    """
    Timetable version for a Semester and Academic Year.
    Workflow: DRAFT -> GENERATED -> REVIEW -> PUBLISHED -> ARCHIVED
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        GENERATED = "GENERATED", "Generated"
        REVIEW = "REVIEW", "Review"
        PUBLISHED = "PUBLISHED", "Published"
        ARCHIVED = "ARCHIVED", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    semester = models.ForeignKey(
        "academics.Semester",
        on_delete=models.CASCADE,
        related_name="timetables",
        help_text="Semester for this timetable",
    )
    academic_year = models.CharField(
        max_length=9,
        help_text="Academic year in YYYY-YYYY format (e.g. 2025-2026)",
    )
    version = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Version number of this timetable configuration",
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.DRAFT,
        help_text="Current timetable lifecycle status",
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_timetables",
        help_text="Staff user who created this timetable",
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the timetable was published",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-academic_year", "semester", "-version"]
        verbose_name = "Timetable"
        verbose_name_plural = "Timetables"
        constraints = [
            models.UniqueConstraint(
                fields=["semester", "academic_year", "version"],
                name="unique_semester_year_version_timetable",
            ),
        ]

    def __str__(self):
        return f"{self.semester} ({self.academic_year}) v{self.version} [{self.status}]"

    def clean(self):
        super().clean()
        if self.academic_year:
            self.academic_year = validate_academic_year(self.academic_year)
        if self.status:
            self.status = self.status.strip().upper()
            if self.status not in self.Status.values:
                raise ValidationError({"status": f"Invalid status '{self.status}'."})

        if self.status == self.Status.PUBLISHED and not self.published_at:
            from django.utils import timezone
            self.published_at = timezone.now()

    def save(self, *args, **kwargs):
        if self.academic_year:
            self.academic_year = self.academic_year.strip()
        if self.status:
            self.status = self.status.strip().upper()
            if self.status == self.Status.PUBLISHED and not self.published_at:
                from django.utils import timezone
                self.published_at = timezone.now()
        super().save(*args, **kwargs)


class TimetableSlot(models.Model):
    """
    Individual scheduled slot within a Timetable.
    """

    class Day(models.TextChoices):
        MONDAY = "MONDAY", "Monday"
        TUESDAY = "TUESDAY", "Tuesday"
        WEDNESDAY = "WEDNESDAY", "Wednesday"
        THURSDAY = "THURSDAY", "Thursday"
        FRIDAY = "FRIDAY", "Friday"
        SATURDAY = "SATURDAY", "Saturday"
        SUNDAY = "SUNDAY", "Sunday"

    class SessionType(models.TextChoices):
        LECTURE = "LECTURE", "Lecture"
        PRACTICAL = "PRACTICAL", "Practical"
        TUTORIAL = "TUTORIAL", "Tutorial"

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"
        CANCELLED = "CANCELLED", "Cancelled"
        RESCHEDULED = "RESCHEDULED", "Rescheduled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timetable = models.ForeignKey(
        Timetable,
        on_delete=models.CASCADE,
        related_name="slots",
        help_text="Parent timetable",
    )
    division = models.ForeignKey(
        "academics.Division",
        on_delete=models.CASCADE,
        related_name="timetable_slots",
        help_text="Class division",
    )
    batch = models.ForeignKey(
        "academics.PracticalBatch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="timetable_slots",
        help_text="Practical/Lab batch (if practical or batch-specific)",
    )
    subject = models.ForeignKey(
        "academics.Subject",
        on_delete=models.CASCADE,
        related_name="timetable_slots",
        help_text="Subject/Course for this slot",
    )
    teacher = models.ForeignKey(
        "accounts.TeacherProfile",
        on_delete=models.CASCADE,
        related_name="timetable_slots",
        help_text="Assigned teacher",
    )
    classroom = models.ForeignKey(
        "academics.Classroom",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="timetable_slots",
        help_text="Classroom allocated for lecture/tutorial session",
    )
    laboratory = models.ForeignKey(
        "academics.Laboratory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="timetable_slots",
        help_text="Laboratory allocated for practical session",
    )
    day = models.CharField(
        max_length=15,
        choices=Day.choices,
        help_text="Day of the week",
    )
    start_time = models.TimeField(
        help_text="Slot start time",
    )
    end_time = models.TimeField(
        help_text="Slot end time",
    )
    session_type = models.CharField(
        max_length=15,
        choices=SessionType.choices,
        default=SessionType.LECTURE,
        help_text="Type of academic session (LECTURE, PRACTICAL, TUTORIAL)",
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.SCHEDULED,
        help_text="Slot status (SCHEDULED, CANCELLED, RESCHEDULED)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["timetable", "day", "start_time"]
        verbose_name = "Timetable Slot"
        verbose_name_plural = "Timetable Slots"

    def __str__(self):
        return f"{self.timetable} | {self.day} {self.start_time}-{self.end_time} | {self.subject.code} ({self.session_type})"

    def clean(self):
        super().clean()
        if self.day:
            self.day = self.day.strip().upper()
            if self.day not in self.Day.values:
                raise ValidationError({"day": f"Invalid day '{self.day}'."})

        if self.session_type:
            self.session_type = self.session_type.strip().upper()
            if self.session_type not in self.SessionType.values:
                raise ValidationError({"session_type": f"Invalid session type '{self.session_type}'."})

        if self.status:
            self.status = self.status.strip().upper()
            if self.status not in self.Status.values:
                raise ValidationError({"status": f"Invalid status '{self.status}'."})

        if self.start_time and self.end_time:
            if self.start_time >= self.end_time:
                raise ValidationError({"end_time": "End time must be strictly after start time."})

        # Validate timetable status: cannot add/modify slots for ARCHIVED timetables
        if self.timetable_id and self.timetable.status == Timetable.Status.ARCHIVED:
            raise ValidationError({"timetable": "Cannot create or modify slots for an ARCHIVED timetable."})

        # Context validation: division must belong to timetable's semester
        if self.division_id and self.timetable_id:
            if self.division.semester_id != self.timetable.semester_id:
                raise ValidationError(
                    {"division": "Selected division does not belong to the timetable's semester."}
                )

        # Batch validation: batch must belong to division
        if self.batch_id and self.division_id:
            if self.batch.division_id != self.division_id:
                raise ValidationError(
                    {"batch": "Selected batch does not belong to the specified division."}
                )

        # Practical vs Lecture resource validation
        if self.session_type == self.SessionType.PRACTICAL:
            if not self.laboratory_id and not self.classroom_id:
                raise ValidationError({"laboratory": "Practical sessions should have an assigned laboratory."})
        elif self.session_type in (self.SessionType.LECTURE, self.SessionType.TUTORIAL):
            if not self.classroom_id and not self.laboratory_id:
                raise ValidationError({"classroom": "Lecture and tutorial sessions should have an assigned classroom."})

    def save(self, *args, **kwargs):
        if self.day:
            self.day = self.day.strip().upper()
        if self.session_type:
            self.session_type = self.session_type.strip().upper()
        if self.status:
            self.status = self.status.strip().upper()
        super().save(*args, **kwargs)


class TimetableConflict(models.Model):
    """
    Detected clash/conflict record within a Timetable.
    """

    class ConflictType(models.TextChoices):
        TEACHER_CLASH = "TEACHER_CLASH", "Teacher Clash"
        CLASSROOM_CLASH = "CLASSROOM_CLASH", "Classroom Clash"
        LAB_CLASH = "LAB_CLASH", "Laboratory Clash"
        DIVISION_CLASH = "DIVISION_CLASH", "Division Clash"
        BATCH_CLASH = "BATCH_CLASH", "Batch Clash"

    class Severity(models.TextChoices):
        HIGH = "HIGH", "High"
        MEDIUM = "MEDIUM", "Medium"
        LOW = "LOW", "Low"

    class Status(models.TextChoices):
        DETECTED = "DETECTED", "Detected"
        RESOLVED = "RESOLVED", "Resolved"
        IGNORED = "IGNORED", "Ignored"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timetable = models.ForeignKey(
        Timetable,
        on_delete=models.CASCADE,
        related_name="conflicts",
        help_text="Associated timetable",
    )
    slot = models.ForeignKey(
        TimetableSlot,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conflicts",
        help_text="Primary timetable slot involved in this conflict",
    )
    conflicting_slot = models.ForeignKey(
        TimetableSlot,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reverse_conflicts",
        help_text="Secondary timetable slot involved in this conflict",
    )
    conflict_type = models.CharField(
        max_length=20,
        choices=ConflictType.choices,
        help_text="Type of conflict detected",
    )
    severity = models.CharField(
        max_length=10,
        choices=Severity.choices,
        default=Severity.HIGH,
        help_text="Severity level of the conflict",
    )
    description = models.TextField(
        help_text="Detailed description of the clash/conflict",
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.DETECTED,
        help_text="Current conflict status",
    )
    resolved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_conflicts",
        help_text="Staff user who resolved this conflict",
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the conflict was marked resolved",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-severity", "-created_at"]
        verbose_name = "Timetable Conflict"
        verbose_name_plural = "Timetable Conflicts"
        constraints = [
            models.UniqueConstraint(
                fields=["timetable", "conflict_type", "slot", "conflicting_slot"],
                name="unique_timetable_conflict_pair",
            ),
        ]

    def __str__(self):
        return f"[{self.severity}] {self.conflict_type} on {self.timetable} ({self.status})"

    def clean(self):
        super().clean()
        if self.slot_id and self.conflicting_slot_id:
            if str(self.slot_id) > str(self.conflicting_slot_id):
                s1, s2 = self.slot, self.conflicting_slot
                self.slot = s2
                self.conflicting_slot = s1

    def save(self, *args, **kwargs):
        if self.slot_id and self.conflicting_slot_id:
            if str(self.slot_id) > str(self.conflicting_slot_id):
                s1, s2 = self.slot, self.conflicting_slot
                self.slot = s2
                self.conflicting_slot = s1
        super().save(*args, **kwargs)


class TeacherSubstitution(models.Model):
    """
    Represents a temporary substitution/replacement assignment for a TimetableSlot.
    Preserves original TimetableSlot historically while designating the active substitute.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"
        DECLINED = "DECLINED", "Declined"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timetable_slot = models.ForeignKey(
        "academics.TimetableSlot",
        on_delete=models.CASCADE,
        related_name="substitutions",
        help_text="The affected timetable slot",
    )
    absent_teacher = models.ForeignKey(
        "accounts.TeacherProfile",
        on_delete=models.CASCADE,
        related_name="absences_substituted",
        help_text="The original teacher who is absent",
    )
    substitute_teacher = models.ForeignKey(
        "accounts.TeacherProfile",
        on_delete=models.CASCADE,
        related_name="substitutions_assigned",
        help_text="The assigned replacement teacher",
    )
    teacher_leave = models.ForeignKey(
        "academics.TeacherLeave",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="substitutions",
        help_text="Associated approved leave request if applicable",
    )
    reason = models.TextField(
        blank=True,
        default="",
        help_text="Reason for the substitution assignment",
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.CONFIRMED,
        help_text="Status of the substitution (PENDING, CONFIRMED, CANCELLED, DECLINED)",
    )
    assigned_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_substitutions",
        help_text="Staff user who confirmed the substitution",
    )
    assigned_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the substitution was confirmed",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-assigned_at", "-created_at"]
        verbose_name = "Teacher Substitution"
        verbose_name_plural = "Teacher Substitutions"
        constraints = [
            models.UniqueConstraint(
                fields=["timetable_slot"],
                condition=models.Q(status="CONFIRMED"),
                name="unique_active_substitution_per_slot",
            ),
        ]

    def __str__(self):
        return (
            f"Sub: {self.substitute_teacher.employee_code} for "
            f"{self.absent_teacher.employee_code} on Slot {self.timetable_slot_id} [{self.status}]"
        )


class Notification(models.Model):
    """
    Represents an internal system notification for a user (e.g. substitute assignments, confirmations, declines).
    """

    class NotificationType(models.TextChoices):
        SUBSTITUTION_ASSIGNED = "SUBSTITUTION_ASSIGNED", "Substitution Assigned"
        SUBSTITUTION_ACCEPTED = "SUBSTITUTION_ACCEPTED", "Substitution Accepted"
        SUBSTITUTION_DECLINED = "SUBSTITUTION_DECLINED", "Substitution Declined"
        GENERAL = "GENERAL", "General"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="notifications",
        help_text="User who receives the notification",
    )
    notification_type = models.CharField(
        max_length=35,
        choices=NotificationType.choices,
        default=NotificationType.GENERAL,
        help_text="Type of notification",
    )
    title = models.CharField(
        max_length=255,
        help_text="Notification headline/title",
    )
    message = models.TextField(
        help_text="Notification message body",
    )
    related_substitution = models.ForeignKey(
        "academics.TeacherSubstitution",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
        help_text="Associated substitution if applicable",
    )
    is_read = models.BooleanField(
        default=False,
        help_text="Whether notification has been read",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when notification was marked as read",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"

    def __str__(self):
        return f"Notification to {self.recipient.username}: {self.title} [{'READ' if self.is_read else 'UNREAD'}]"

    def mark_as_read(self):
        self.is_read = True
        self.read_at = timezone.now()
        self.save(update_fields=["is_read", "read_at"])



