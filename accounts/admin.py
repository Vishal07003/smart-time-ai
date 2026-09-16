from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import StudentProfile, TeacherProfile, User


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
        "is_active",
        "is_staff",
        "created_at",
    )
    list_filter = (
        "role",
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
            "Role & Permissions",
            {
                "fields": (
                    "role",
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
                    "is_active",
                    "is_staff",
                ),
            },
        ),
    )


@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    """
    Admin configuration for TeacherProfile.
    """

    list_display = (
        "employee_code",
        "get_username",
        "get_full_name",
        "department",
        "designation",
        "status",
        "joining_date",
        "created_at",
    )
    list_filter = (
        "status",
        "department",
        "designation",
    )
    search_fields = (
        "employee_code",
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
        "designation",
    )
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at", "updated_at")

    @admin.display(description="Username")
    def get_username(self, obj):
        return obj.user.username

    @admin.display(description="Full Name")
    def get_full_name(self, obj):
        return obj.user.get_full_name() or "-"


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    """
    Admin configuration for StudentProfile.
    """

    list_display = (
        "student_code",
        "roll_number",
        "get_username",
        "get_full_name",
        "division",
        "batch",
        "admission_year",
        "status",
        "created_at",
    )
    list_filter = (
        "status",
        "division__semester__program",
        "division",
        "admission_year",
    )
    search_fields = (
        "student_code",
        "roll_number",
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
    )
    ordering = ("division", "roll_number")
    readonly_fields = ("id", "created_at", "updated_at")

    @admin.display(description="Username")
    def get_username(self, obj):
        return obj.user.username

    @admin.display(description="Full Name")
    def get_full_name(self, obj):
        return obj.user.get_full_name() or "-"
