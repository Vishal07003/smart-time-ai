import uuid
from django.contrib.auth.models import AbstractUser, UserManager as BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from .validators import (
    normalize_email,
    normalize_indian_phone,
    normalize_name,
    normalize_username,
    validate_email_custom,
    validate_indian_phone,
    validate_name_custom,
    validate_role_custom,
    validate_username_custom,
)


class UserManager(BaseUserManager):
    """
    Custom user manager to handle user creation with roles, validation, and UUID primary key.
    """

    def create_user(self, username, email=None, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set.")
        email = normalize_email(email)
        username = normalize_username(username)

        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        if "role" not in extra_fields or not extra_fields["role"]:
            extra_fields["role"] = User.Role.STUDENT

        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.full_clean()
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.STAFF)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(username, email, password, **extra_fields)


class User(AbstractUser):
    """
    Unified User model for SMART-TIME AI supporting STAFF, TEACHER, and STUDENT roles.
    Staff is the highest application role (no separate Admin role).
    """

    class Role(models.TextChoices):
        STAFF = "STAFF", "Staff"
        TEACHER = "TEACHER", "Teacher"
        STUDENT = "STUDENT", "Student"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    username = models.CharField(
        max_length=30,
        unique=True,
        validators=[validate_username_custom],
        help_text="Required. 3-30 characters. Letters, numbers, underscore, and dot only.",
        error_messages={
            "unique": "A user with that username already exists.",
        },
    )

    email = models.EmailField(
        max_length=254,
        unique=True,
        validators=[validate_email_custom],
        error_messages={
            "unique": "A user with that email already exists.",
        },
    )

    first_name = models.CharField(
        max_length=50,
        blank=True,
        default="",
        validators=[validate_name_custom],
        help_text="Optional. Maximum 50 alphabetic characters.",
    )

    last_name = models.CharField(
        max_length=50,
        blank=True,
        default="",
        validators=[validate_name_custom],
        help_text="Optional. Maximum 50 alphabetic characters.",
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STUDENT,
        validators=[validate_role_custom],
        help_text="Application role: STAFF, TEACHER, or STUDENT",
    )

    phone = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        validators=[validate_indian_phone],
        help_text="Optional 10-digit Indian mobile number starting with 6, 7, 8, or 9.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    REQUIRED_FIELDS = ["email"]

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "User"
        verbose_name_plural = "Users"
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="unique_lower_email",
            ),
            models.UniqueConstraint(
                Lower("username"),
                name="unique_lower_username",
            ),
        ]

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    def clean(self):
        super().clean()

        # Email normalization and validation
        if self.email:
            self.email = normalize_email(self.email)
            validate_email_custom(self.email)

            # Case-insensitive uniqueness check
            email_qs = User.objects.filter(email__iexact=self.email)
            if self.pk:
                email_qs = email_qs.exclude(pk=self.pk)
            if email_qs.exists():
                raise ValidationError({"email": "A user with that email already exists."})

        # Username normalization and validation
        if self.username:
            self.username = normalize_username(self.username)
            validate_username_custom(self.username)

            # Case-insensitive uniqueness check
            username_qs = User.objects.filter(username__iexact=self.username)
            if self.pk:
                username_qs = username_qs.exclude(pk=self.pk)
            if username_qs.exists():
                raise ValidationError(
                    {"username": "A user with that username already exists."}
                )

        # Phone normalization and validation
        if self.phone:
            cleaned_phone = normalize_indian_phone(self.phone)
            validate_indian_phone(cleaned_phone)
            self.phone = cleaned_phone
        else:
            self.phone = None

        # First and last name normalization and validation
        if self.first_name:
            cleaned_first = normalize_name(self.first_name)
            validate_name_custom(cleaned_first)
            self.first_name = cleaned_first
        else:
            self.first_name = ""

        if self.last_name:
            cleaned_last = normalize_name(self.last_name)
            validate_name_custom(cleaned_last)
            self.last_name = cleaned_last
        else:
            self.last_name = ""

        # Role validation
        if self.role:
            self.role = validate_role_custom(self.role)

    def save(self, *args, **kwargs):
        # Apply normalization prior to saving
        if self.email:
            self.email = normalize_email(self.email)
        if self.username:
            self.username = normalize_username(self.username)
        if self.phone:
            self.phone = normalize_indian_phone(self.phone)
        if self.first_name:
            self.first_name = normalize_name(self.first_name)
        if self.last_name:
            self.last_name = normalize_name(self.last_name)
        if self.role:
            self.role = self.role.upper()
        super().save(*args, **kwargs)

    @property
    def is_staff_role(self):
        return self.role == self.Role.STAFF

    @property
    def is_teacher_role(self):
        return self.role == self.Role.TEACHER

    @property
    def is_student_role(self):
        return self.role == self.Role.STUDENT


class TeacherProfile(models.Model):
    """
    Teacher profile associated with accounts.User (role=TEACHER).
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="teacher_profile",
        help_text="Associated user account with TEACHER role",
    )
    employee_code = models.CharField(
        max_length=30,
        unique=True,
        help_text="Unique employee code for the teacher",
    )
    department = models.ForeignKey(
        "academics.Department",
        on_delete=models.PROTECT,
        related_name="teachers",
        help_text="Department to which teacher belongs",
    )
    designation = models.CharField(
        max_length=100,
        help_text="Designation (e.g. Professor, Assistant Professor, Lecturer)",
    )
    joining_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date of joining the institution",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        help_text="Current employment status",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Teacher Profile"
        verbose_name_plural = "Teacher Profiles"
        constraints = [
            models.UniqueConstraint(
                Lower("employee_code"),
                name="unique_lower_employee_code",
            ),
        ]

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.employee_code})"

    def clean(self):
        super().clean()
        if hasattr(self, "user") and self.user and self.user.role != User.Role.TEACHER:
            raise ValidationError(
                {"user": "Teacher profile can only be associated with a user having the TEACHER role."}
            )

        if self.employee_code:
            self.employee_code = self.employee_code.strip()
            qs = TeacherProfile.objects.filter(employee_code__iexact=self.employee_code)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({"employee_code": "A teacher with this employee code already exists."})

    def save(self, *args, **kwargs):
        if self.employee_code:
            self.employee_code = self.employee_code.strip()
        super().save(*args, **kwargs)


class StudentProfile(models.Model):
    """
    Student profile associated with accounts.User (role=STUDENT).
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        GRADUATED = "GRADUATED", "Graduated"
        LEFT = "LEFT", "Left"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="student_profile",
        help_text="Associated user account with STUDENT role",
    )
    student_code = models.CharField(
        max_length=30,
        unique=True,
        help_text="Unique student registration/enrollment code",
    )
    roll_number = models.CharField(
        max_length=30,
        help_text="Roll number within division (unique per division)",
    )
    division = models.ForeignKey(
        "academics.Division",
        on_delete=models.PROTECT,
        related_name="students",
        help_text="Division to which student belongs",
    )
    batch = models.ForeignKey(
        "academics.PracticalBatch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="students",
        help_text="Optional practical batch within the division",
    )
    admission_year = models.PositiveIntegerField(
        help_text="Year of admission (e.g. 2024)",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        help_text="Current student status",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["division", "roll_number"]
        verbose_name = "Student Profile"
        verbose_name_plural = "Student Profiles"
        constraints = [
            models.UniqueConstraint(
                Lower("student_code"),
                name="unique_lower_student_code",
            ),
            models.UniqueConstraint(
                fields=["division", "roll_number"],
                name="unique_roll_number_per_division",
            ),
        ]

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} (Roll: {self.roll_number}, Code: {self.student_code})"

    def clean(self):
        super().clean()
        if hasattr(self, "user") and self.user and self.user.role != User.Role.STUDENT:
            raise ValidationError(
                {"user": "Student profile can only be associated with a user having the STUDENT role."}
            )

        if self.student_code:
            self.student_code = self.student_code.strip()
            qs = StudentProfile.objects.filter(student_code__iexact=self.student_code)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({"student_code": "A student with this student code already exists."})

        if self.roll_number:
            self.roll_number = str(self.roll_number).strip()
            if self.division_id:
                roll_qs = StudentProfile.objects.filter(
                    division_id=self.division_id,
                    roll_number__iexact=self.roll_number,
                )
                if self.pk:
                    roll_qs = roll_qs.exclude(pk=self.pk)
                if roll_qs.exists():
                    raise ValidationError(
                        {"roll_number": "A student with this roll number already exists in this division."}
                    )

        if self.batch_id and self.division_id:
            if self.batch.division_id != self.division_id:
                raise ValidationError(
                    {"batch": "The selected practical batch does not belong to the selected division."}
                )

    def save(self, *args, **kwargs):
        if self.student_code:
            self.student_code = self.student_code.strip()
        if self.roll_number:
            self.roll_number = str(self.roll_number).strip()
        super().save(*args, **kwargs)
