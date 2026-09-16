from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

from academics.models import Department, Division, PracticalBatch
from .models import StudentProfile, TeacherProfile, User
from .serializers import UserSerializer
from .validators import (
    normalize_email,
    normalize_indian_phone,
    normalize_name,
    normalize_username,
    validate_email_custom,
    validate_indian_phone,
    validate_name_custom,
    validate_username_custom,
)


class TeacherProfileSerializer(serializers.ModelSerializer):
    """
    Read/Representation serializer for TeacherProfile.
    """

    user = UserSerializer(read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    department_code = serializers.CharField(source="department.code", read_only=True)

    class Meta:
        model = TeacherProfile
        fields = [
            "id",
            "user",
            "employee_code",
            "department",
            "department_name",
            "department_code",
            "designation",
            "joining_date",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "created_at",
            "updated_at",
        ]


class TeacherProfileCreateSerializer(serializers.Serializer):
    """
    Serializer used by Staff to create a new Teacher (User + TeacherProfile).
    """

    username = serializers.CharField(
        required=True,
        validators=[validate_username_custom],
    )
    email = serializers.CharField(
        required=True,
        validators=[validate_email_custom],
    )
    password = serializers.CharField(
        required=True,
        write_only=True,
        style={"input_type": "password"},
    )
    first_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=50,
        validators=[validate_name_custom],
    )
    last_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=50,
        validators=[validate_name_custom],
    )
    phone = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        max_length=15,
        validators=[validate_indian_phone],
    )

    employee_code = serializers.CharField(required=True, max_length=30)
    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(),
        required=True,
    )
    designation = serializers.CharField(required=True, max_length=100)
    joining_date = serializers.DateField(required=False, allow_null=True, default=None)
    status = serializers.ChoiceField(
        choices=TeacherProfile.Status.choices,
        default=TeacherProfile.Status.ACTIVE,
    )

    def validate_username(self, value):
        cleaned = normalize_username(value)
        validate_username_custom(cleaned)
        if User.objects.filter(username__iexact=cleaned).exists():
            raise serializers.ValidationError("A user with that username already exists.")
        return cleaned

    def validate_email(self, value):
        cleaned = normalize_email(value)
        validate_email_custom(cleaned)
        if User.objects.filter(email__iexact=cleaned).exists():
            raise serializers.ValidationError("A user with that email already exists.")
        return cleaned

    def validate_employee_code(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Employee code is required.")
        if TeacherProfile.objects.filter(employee_code__iexact=cleaned).exists():
            raise serializers.ValidationError("A teacher with this employee code already exists.")
        return cleaned

    def validate_first_name(self, value):
        if not value:
            return ""
        cleaned = normalize_name(value)
        validate_name_custom(cleaned)
        return cleaned

    def validate_last_name(self, value):
        if not value:
            return ""
        cleaned = normalize_name(value)
        validate_name_custom(cleaned)
        return cleaned

    def validate_phone(self, value):
        if not value:
            return None
        cleaned = normalize_indian_phone(value)
        validate_indian_phone(cleaned)
        return cleaned

    def validate_designation(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Designation is required.")
        return cleaned

    def validate(self, attrs):
        password = attrs.get("password")
        validate_password(password)
        return attrs

    def create(self, validated_data):
        with transaction.atomic():
            user = User.objects.create_user(
                username=validated_data["username"],
                email=validated_data["email"],
                password=validated_data["password"],
                first_name=validated_data.get("first_name", ""),
                last_name=validated_data.get("last_name", ""),
                phone=validated_data.get("phone", None),
                role=User.Role.TEACHER,
                is_active=True,
            )
            teacher = TeacherProfile.objects.create(
                user=user,
                employee_code=validated_data["employee_code"],
                department=validated_data["department"],
                designation=validated_data["designation"],
                joining_date=validated_data.get("joining_date"),
                status=validated_data.get("status", TeacherProfile.Status.ACTIVE),
            )
            return teacher


class TeacherProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer used by Staff to update an existing TeacherProfile and associated User details.
    """

    first_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        validators=[validate_name_custom],
    )
    last_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        validators=[validate_name_custom],
    )
    phone = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=15,
        validators=[validate_indian_phone],
    )
    is_active = serializers.BooleanField(required=False)

    class Meta:
        model = TeacherProfile
        fields = [
            "employee_code",
            "department",
            "designation",
            "joining_date",
            "status",
            "first_name",
            "last_name",
            "phone",
            "is_active",
        ]

    def validate_employee_code(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Employee code cannot be empty.")
        qs = TeacherProfile.objects.filter(employee_code__iexact=cleaned)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A teacher with this employee code already exists.")
        return cleaned

    def validate_first_name(self, value):
        if not value:
            return ""
        cleaned = normalize_name(value)
        validate_name_custom(cleaned)
        return cleaned

    def validate_last_name(self, value):
        if not value:
            return ""
        cleaned = normalize_name(value)
        validate_name_custom(cleaned)
        return cleaned

    def validate_phone(self, value):
        if not value:
            return None
        cleaned = normalize_indian_phone(value)
        validate_indian_phone(cleaned)
        return cleaned

    def update(self, instance, validated_data):
        user = instance.user
        user_updated = False

        if "first_name" in validated_data:
            user.first_name = validated_data.pop("first_name")
            user_updated = True
        if "last_name" in validated_data:
            user.last_name = validated_data.pop("last_name")
            user_updated = True
        if "phone" in validated_data:
            user.phone = validated_data.pop("phone")
            user_updated = True
        if "is_active" in validated_data:
            user.is_active = validated_data.pop("is_active")
            user_updated = True

        with transaction.atomic():
            if user_updated:
                user.save()

            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

        return instance


class TeacherMeUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for Teachers updating their own profile via /api/v1/teachers/me/.
    Strictly permits only personal user details.
    """

    first_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        validators=[validate_name_custom],
    )
    last_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        validators=[validate_name_custom],
    )
    phone = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=15,
        validators=[validate_indian_phone],
    )

    class Meta:
        model = TeacherProfile
        fields = [
            "first_name",
            "last_name",
            "phone",
        ]

    def validate_first_name(self, value):
        if not value:
            return ""
        cleaned = normalize_name(value)
        validate_name_custom(cleaned)
        return cleaned

    def validate_last_name(self, value):
        if not value:
            return ""
        cleaned = normalize_name(value)
        validate_name_custom(cleaned)
        return cleaned

    def validate_phone(self, value):
        if not value:
            return None
        cleaned = normalize_indian_phone(value)
        validate_indian_phone(cleaned)
        return cleaned

    def update(self, instance, validated_data):
        user = instance.user
        if "first_name" in validated_data:
            user.first_name = validated_data["first_name"]
        if "last_name" in validated_data:
            user.last_name = validated_data["last_name"]
        if "phone" in validated_data:
            user.phone = validated_data["phone"]
        user.save()
        return instance


# =========================================================================
# STUDENT PROFILE SERIALIZERS
# =========================================================================


class StudentProfileSerializer(serializers.ModelSerializer):
    """
    Read/Representation serializer for StudentProfile.
    """

    user = UserSerializer(read_only=True)
    division_name = serializers.CharField(source="division.name", read_only=True)
    batch_name = serializers.CharField(source="batch.name", read_only=True, default=None)

    class Meta:
        model = StudentProfile
        fields = [
            "id",
            "user",
            "student_code",
            "roll_number",
            "division",
            "division_name",
            "batch",
            "batch_name",
            "admission_year",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "created_at",
            "updated_at",
        ]


class StudentProfileCreateSerializer(serializers.Serializer):
    """
    Serializer used by Staff to create a new Student (User + StudentProfile).
    """

    username = serializers.CharField(
        required=True,
        validators=[validate_username_custom],
    )
    email = serializers.CharField(
        required=True,
        validators=[validate_email_custom],
    )
    password = serializers.CharField(
        required=True,
        write_only=True,
        style={"input_type": "password"},
    )
    first_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=50,
        validators=[validate_name_custom],
    )
    last_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=50,
        validators=[validate_name_custom],
    )
    phone = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        max_length=15,
        validators=[validate_indian_phone],
    )

    student_code = serializers.CharField(required=True, max_length=30)
    roll_number = serializers.CharField(required=True, max_length=30)
    division = serializers.PrimaryKeyRelatedField(
        queryset=Division.objects.all(),
        required=True,
    )
    batch = serializers.PrimaryKeyRelatedField(
        queryset=PracticalBatch.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )
    admission_year = serializers.IntegerField(required=True, min_value=1900, max_value=2100)
    status = serializers.ChoiceField(
        choices=StudentProfile.Status.choices,
        default=StudentProfile.Status.ACTIVE,
    )

    def validate_username(self, value):
        cleaned = normalize_username(value)
        validate_username_custom(cleaned)
        if User.objects.filter(username__iexact=cleaned).exists():
            raise serializers.ValidationError("A user with that username already exists.")
        return cleaned

    def validate_email(self, value):
        cleaned = normalize_email(value)
        validate_email_custom(cleaned)
        if User.objects.filter(email__iexact=cleaned).exists():
            raise serializers.ValidationError("A user with that email already exists.")
        return cleaned

    def validate_student_code(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Student code is required.")
        if StudentProfile.objects.filter(student_code__iexact=cleaned).exists():
            raise serializers.ValidationError("A student with this student code already exists.")
        return cleaned

    def validate_first_name(self, value):
        if not value:
            return ""
        cleaned = normalize_name(value)
        validate_name_custom(cleaned)
        return cleaned

    def validate_last_name(self, value):
        if not value:
            return ""
        cleaned = normalize_name(value)
        validate_name_custom(cleaned)
        return cleaned

    def validate_phone(self, value):
        if not value:
            return None
        cleaned = normalize_indian_phone(value)
        validate_indian_phone(cleaned)
        return cleaned

    def validate(self, attrs):
        password = attrs.get("password")
        validate_password(password)

        division = attrs.get("division")
        batch = attrs.get("batch")
        roll_number = str(attrs.get("roll_number", "")).strip()

        if not roll_number:
            raise serializers.ValidationError({"roll_number": "Roll number is required."})

        # Roll number uniqueness within division
        if division and StudentProfile.objects.filter(
            division=division,
            roll_number__iexact=roll_number,
        ).exists():
            raise serializers.ValidationError(
                {"roll_number": "A student with this roll number already exists in this division."}
            )

        # Batch validation
        if batch and division and batch.division_id != division.id:
            raise serializers.ValidationError(
                {"batch": "The selected practical batch does not belong to the selected division."}
            )

        return attrs

    def create(self, validated_data):
        with transaction.atomic():
            user = User.objects.create_user(
                username=validated_data["username"],
                email=validated_data["email"],
                password=validated_data["password"],
                first_name=validated_data.get("first_name", ""),
                last_name=validated_data.get("last_name", ""),
                phone=validated_data.get("phone", None),
                role=User.Role.STUDENT,
                is_active=True,
            )
            student = StudentProfile.objects.create(
                user=user,
                student_code=validated_data["student_code"],
                roll_number=str(validated_data["roll_number"]).strip(),
                division=validated_data["division"],
                batch=validated_data.get("batch"),
                admission_year=validated_data["admission_year"],
                status=validated_data.get("status", StudentProfile.Status.ACTIVE),
            )
            return student


class StudentProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer used by Staff to update an existing StudentProfile and associated User details.
    """

    first_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        validators=[validate_name_custom],
    )
    last_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        validators=[validate_name_custom],
    )
    phone = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=15,
        validators=[validate_indian_phone],
    )
    is_active = serializers.BooleanField(required=False)

    class Meta:
        model = StudentProfile
        fields = [
            "student_code",
            "roll_number",
            "division",
            "batch",
            "admission_year",
            "status",
            "first_name",
            "last_name",
            "phone",
            "is_active",
        ]

    def validate_student_code(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Student code cannot be empty.")
        qs = StudentProfile.objects.filter(student_code__iexact=cleaned)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A student with this student code already exists.")
        return cleaned

    def validate_first_name(self, value):
        if not value:
            return ""
        cleaned = normalize_name(value)
        validate_name_custom(cleaned)
        return cleaned

    def validate_last_name(self, value):
        if not value:
            return ""
        cleaned = normalize_name(value)
        validate_name_custom(cleaned)
        return cleaned

    def validate_phone(self, value):
        if not value:
            return None
        cleaned = normalize_indian_phone(value)
        validate_indian_phone(cleaned)
        return cleaned

    def validate(self, attrs):
        division = attrs.get("division", getattr(self.instance, "division", None))
        batch = attrs.get("batch", getattr(self.instance, "batch", None))
        roll_number = attrs.get("roll_number", getattr(self.instance, "roll_number", None))

        if roll_number is not None:
            roll_number = str(roll_number).strip()
            if not roll_number:
                raise serializers.ValidationError({"roll_number": "Roll number cannot be empty."})

            if division:
                roll_qs = StudentProfile.objects.filter(
                    division=division,
                    roll_number__iexact=roll_number,
                )
                if self.instance:
                    roll_qs = roll_qs.exclude(pk=self.instance.pk)
                if roll_qs.exists():
                    raise serializers.ValidationError(
                        {"roll_number": "A student with this roll number already exists in this division."}
                    )

        if batch and division and batch.division_id != division.id:
            raise serializers.ValidationError(
                {"batch": "The selected practical batch does not belong to the selected division."}
            )

        return attrs

    def update(self, instance, validated_data):
        user = instance.user
        user_updated = False

        if "first_name" in validated_data:
            user.first_name = validated_data.pop("first_name")
            user_updated = True
        if "last_name" in validated_data:
            user.last_name = validated_data.pop("last_name")
            user_updated = True
        if "phone" in validated_data:
            user.phone = validated_data.pop("phone")
            user_updated = True
        if "is_active" in validated_data:
            user.is_active = validated_data.pop("is_active")
            user_updated = True

        with transaction.atomic():
            if user_updated:
                user.save()

            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

        return instance


class StudentMeUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for Students updating their own profile via /api/v1/students/me/.
    Strictly permits only personal user details.
    """

    first_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        validators=[validate_name_custom],
    )
    last_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        validators=[validate_name_custom],
    )
    phone = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=15,
        validators=[validate_indian_phone],
    )

    class Meta:
        model = StudentProfile
        fields = [
            "first_name",
            "last_name",
            "phone",
        ]

    def validate_first_name(self, value):
        if not value:
            return ""
        cleaned = normalize_name(value)
        validate_name_custom(cleaned)
        return cleaned

    def validate_last_name(self, value):
        if not value:
            return ""
        cleaned = normalize_name(value)
        validate_name_custom(cleaned)
        return cleaned

    def validate_phone(self, value):
        if not value:
            return None
        cleaned = normalize_indian_phone(value)
        validate_indian_phone(cleaned)
        return cleaned

    def update(self, instance, validated_data):
        user = instance.user
        if "first_name" in validated_data:
            user.first_name = validated_data["first_name"]
        if "last_name" in validated_data:
            user.last_name = validated_data["last_name"]
        if "phone" in validated_data:
            user.phone = validated_data["phone"]
        user.save()
        return instance
