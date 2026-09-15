import uuid
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower

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
