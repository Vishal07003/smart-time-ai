from django.contrib import admin

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


@admin.register(TeacherSubject)
class TeacherSubjectAdmin(admin.ModelAdmin):
    list_display = (
        "teacher",
        "subject",
        "priority",
        "created_at",
    )
    list_filter = (
        "priority",
        "subject__program",
    )
    search_fields = (
        "teacher__employee_code",
        "teacher__user__first_name",
        "teacher__user__last_name",
        "subject__name",
        "subject__code",
    )
    ordering = ("teacher", "priority")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(TeacherAvailability)
class TeacherAvailabilityAdmin(admin.ModelAdmin):
    list_display = (
        "teacher",
        "day",
        "start_time",
        "end_time",
        "is_available",
        "created_at",
    )
    list_filter = (
        "day",
        "is_available",
        "teacher__department",
    )
    search_fields = (
        "teacher__employee_code",
        "teacher__user__first_name",
        "teacher__user__last_name",
    )
    ordering = ("day", "start_time")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(TeacherLeave)
class TeacherLeaveAdmin(admin.ModelAdmin):
    list_display = (
        "teacher",
        "start_date",
        "end_date",
        "status",
        "created_at",
    )
    list_filter = (
        "status",
        "teacher__department",
        "start_date",
        "end_date",
    )
    search_fields = (
        "teacher__employee_code",
        "teacher__user__first_name",
        "teacher__user__last_name",
        "reason",
    )
    ordering = ("-start_date", "-created_at")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = (
        "building",
        "room_number",
        "floor",
        "capacity",
        "status",
        "created_at",
    )
    list_filter = (
        "status",
        "building",
        "floor",
    )
    search_fields = (
        "building",
        "room_number",
    )
    ordering = ("building", "room_number")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Laboratory)
class LaboratoryAdmin(admin.ModelAdmin):
    list_display = (
        "building",
        "lab_number",
        "name",
        "floor",
        "capacity",
        "status",
        "created_at",
    )
    list_filter = (
        "status",
        "building",
        "floor",
    )
    search_fields = (
        "building",
        "lab_number",
        "name",
    )
    ordering = ("building", "lab_number")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Timetable)
class TimetableAdmin(admin.ModelAdmin):
    list_display = (
        "semester",
        "academic_year",
        "version",
        "status",
        "created_by",
        "published_at",
        "created_at",
    )
    list_filter = (
        "status",
        "academic_year",
        "semester__program__department",
        "semester__program",
    )
    search_fields = (
        "semester__program__name",
        "semester__program__code",
        "academic_year",
    )
    ordering = ("-academic_year", "semester", "-version")
    readonly_fields = ("id", "published_at", "created_at", "updated_at")


@admin.register(TimetableSlot)
class TimetableSlotAdmin(admin.ModelAdmin):
    list_display = (
        "timetable",
        "division",
        "batch",
        "subject",
        "teacher",
        "day",
        "start_time",
        "end_time",
        "session_type",
        "status",
    )
    list_filter = (
        "day",
        "session_type",
        "status",
        "timetable__semester__program",
    )
    search_fields = (
        "subject__name",
        "subject__code",
        "teacher__employee_code",
        "teacher__user__first_name",
        "teacher__user__last_name",
        "division__name",
    )
    ordering = ("timetable", "day", "start_time")
    readonly_fields = ("id", "created_at", "updated_at")

