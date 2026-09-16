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
        extra_fields.setdefault("email_verified", True)
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
        extra_fields.setdefault("email_verified", True)

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

    email_verified = models.BooleanField(
        default=True,
        help_text="Designates whether the user has verified their email address.",
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


class EmailVerification(models.Model):
    """
    Stores cryptographically hashed OTPs for student email verification.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="email_verifications",
    )
    otp_hash = models.CharField(max_length=255)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Email Verification"
        verbose_name_plural = "Email Verifications"
        indexes = [
            models.Index(fields=["user", "is_used", "expires_at"]),
        ]

    def __str__(self):
        return f"EmailVerification for {self.user.email} (Used: {self.is_used})"