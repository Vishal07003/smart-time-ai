from django.contrib import admin

from .models import (
    Department,
    Division,
    PracticalBatch,
    Program,
    Semester,
    Subject,
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "created_at", "updated_at")
    search_fields = ("name", "code")
    ordering = ("name",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "department",
        "duration_years",
        "created_at",
    )
    list_filter = ("department", "duration_years")
    search_fields = ("name", "code", "department__name", "department__code")
    ordering = ("department", "name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = (
        "program",
        "number",
        "academic_year",
        "created_at",
    )
    list_filter = ("academic_year", "number", "program__department", "program")
    search_fields = ("program__name", "program__code", "academic_year")
    ordering = ("academic_year", "program", "number")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Division)
class DivisionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "semester",
        "capacity",
        "created_at",
    )
    list_filter = (
        "semester__academic_year",
        "semester__program__department",
        "semester__program",
    )
    search_fields = ("name", "semester__program__name", "semester__program__code")
    ordering = ("semester", "name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(PracticalBatch)
class PracticalBatchAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "division",
        "capacity",
        "created_at",
    )
    list_filter = (
        "division__semester__academic_year",
        "division__semester__program",
    )
    search_fields = ("name", "division__name")
    ordering = ("division", "name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "program",
        "type",
        "credits",
        "weekly_lectures",
        "weekly_practicals",
        "duration_minutes",
    )
    list_filter = ("type", "program__department", "program")
    search_fields = ("name", "code", "program__name", "program__code")
    ordering = ("program", "code")
    readonly_fields = ("id", "created_at", "updated_at")
