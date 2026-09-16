from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import EmailVerification, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Custom UserAdmin for the unified SMART-TIME AI User model.
    """

    list_display = (
        "username",
        "email",
        "role",
        "first_name",
        "last_name",
        "phone",
        "email_verified",
        "is_active",
        "is_staff",
        "created_at",
    )
    list_filter = (
        "role",
        "email_verified",
        "is_active",
        "is_staff",
        "is_superuser",
    )
    search_fields = (
        "username",
        "email",
        "first_name",
        "last_name",
        "phone",
    )
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "last_login",
        "date_joined",
    )

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            "Personal Information",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "email",
                    "phone",
                )
            },
        ),
        (
            "Role & Verification",
            {
                "fields": (
                    "role",
                    "email_verified",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (
            "Metadata & Timestamps",
            {
                "fields": (
                    "id",
                    "last_login",
                    "date_joined",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "email",
                    "role",
                    "password",
                    "first_name",
                    "last_name",
                    "phone",
                    "email_verified",
                    "is_active",
                    "is_staff",
                ),
            },
        ),
    )


@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    """
    Admin configuration for inspecting EmailVerification records.
    """

    list_display = (
        "id",
        "user",
        "is_used",
        "attempts",
        "expires_at",
        "created_at",
    )
    list_filter = (
        "is_used",
        "created_at",
        "expires_at",
    )
    search_fields = (
        "user__username",
        "user__email",
    )
    readonly_fields = (
        "id",
        "user",
        "otp_hash",
        "expires_at",
        "is_used",
        "attempts",
        "created_at",
    )
    ordering = ("-created_at",)
