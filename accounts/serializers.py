from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
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


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for the unified User model representing all public attributes.
    Excludes sensitive password and hash fields.
    """

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "role",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "role",
            "is_active",
            "created_at",
            "updated_at",
        ]


class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating user profile via /me/ endpoint.
    Strictly permits only first_name, last_name, and phone.
    Role, is_active, username, and email are strictly protected and cannot be changed here.
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
        model = User
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


class LoginSerializer(serializers.Serializer):
    """
    Serializer for authenticating users via username or email and password.
    Returns JWT tokens along with the user's role and profile details.
    """

    username = serializers.CharField(
        required=True,
        write_only=True,
        help_text="Enter your username or email address",
    )
    password = serializers.CharField(
        required=True,
        write_only=True,
        style={"input_type": "password"},
        help_text="Enter your password",
    )

    def validate(self, attrs):
        raw_identifier = attrs.get("username", "")
        identifier = raw_identifier.strip()
        password = attrs.get("password")

        user = None

        # Check if identifier is an email or username (case-insensitive)
        if "@" in identifier:
            email_normalized = normalize_email(identifier)
            try:
                user_obj = User.objects.get(email__iexact=email_normalized)
                user = authenticate(username=user_obj.username, password=password)
            except User.DoesNotExist:
                user = None
        else:
            username_normalized = normalize_username(identifier)
            try:
                user_obj = User.objects.get(username__iexact=username_normalized)
                user = authenticate(username=user_obj.username, password=password)
            except User.DoesNotExist:
                user = None

        if not user:
            raise serializers.ValidationError(
                "Invalid credentials. Please check your username/email and password."
            )

        if not user.is_active:
            raise serializers.ValidationError(
                "This account is inactive. Please contact support or staff."
            )

        attrs["user"] = user
        return attrs

    @classmethod
    def get_tokens_for_user(cls, user: User) -> dict:
        """
        Generate JWT refresh and access tokens with custom claims for user identification and role.
        """
        refresh = RefreshToken.for_user(user)

        # Embed custom claims into the JWT token payload
        refresh["role"] = user.role
        refresh["email"] = user.email
        refresh["username"] = user.username

        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }


class LogoutSerializer(serializers.Serializer):
    """
    Serializer for blacklisting the refresh token on logout.
    """

    refresh = serializers.CharField(
        required=True,
        help_text="The refresh token to be blacklisted",
    )

    def validate_refresh(self, value):
        try:
            token = RefreshToken(value)
            return token
        except Exception:
            raise serializers.ValidationError("Invalid or expired refresh token.")


class ChangePasswordSerializer(serializers.Serializer):
    """
    Serializer for changing password for authenticated users.
    Enforces current password verification and Django password validation.
    """

    old_password = serializers.CharField(
        required=True,
        write_only=True,
        style={"input_type": "password"},
    )
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        style={"input_type": "password"},
    )
    confirm_password = serializers.CharField(
        required=True,
        write_only=True,
        style={"input_type": "password"},
    )

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate(self, attrs):
        new_password = attrs.get("new_password")
        confirm_password = attrs.get("confirm_password")
        old_password = attrs.get("old_password")

        if new_password != confirm_password:
            raise serializers.ValidationError(
                {"confirm_password": "New passwords do not match."}
            )

        if new_password == old_password:
            raise serializers.ValidationError(
                {"new_password": "New password cannot be the same as the old password."}
            )

        # Validate with Django's password validation rules (similarity, min length, common password, numeric)
        user = self.context["request"].user
        validate_password(new_password, user=user)

        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save()
        return user


class ForgotPasswordSerializer(serializers.Serializer):
    """
    Serializer for initiating password reset by validating email format.
    Does not expose whether the email exists to prevent enumeration attacks.
    """

    email = serializers.CharField(
        required=True,
        validators=[validate_email_custom],
    )

    def validate_email(self, value):
        cleaned_email = normalize_email(value)
        validate_email_custom(cleaned_email)
        try:
            user = User.objects.get(email__iexact=cleaned_email)
            if user.is_active:
                self.context["user"] = user
            else:
                self.context["user"] = None
        except User.DoesNotExist:
            self.context["user"] = None
        return cleaned_email


class ResetPasswordSerializer(serializers.Serializer):
    """
    Serializer for confirming password reset with uid, token, and new password.
    """

    uid = serializers.CharField(required=True)
    token = serializers.CharField(required=True)
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        style={"input_type": "password"},
    )
    confirm_password = serializers.CharField(
        required=True,
        write_only=True,
        style={"input_type": "password"},
    )

    def validate(self, attrs):
        uid = attrs.get("uid")
        token = attrs.get("token")
        new_password = attrs.get("new_password")
        confirm_password = attrs.get("confirm_password")

        if new_password != confirm_password:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )

        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError({"uid": "Invalid reset link or user ID."})

        if not default_token_generator.check_token(user, token):
            raise serializers.ValidationError(
                {"token": "Password reset token is invalid or has expired."}
            )

        validate_password(new_password, user=user)

        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save()
        return user