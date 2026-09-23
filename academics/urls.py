from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ClassroomViewSet,
    ConstraintGenerateTimetableView,
    ConstraintParseAndValidateView,
    DepartmentViewSet,
    DivisionViewSet,
    LaboratoryViewSet,
    NotificationViewSet,
    PracticalBatchViewSet,
    ProgramViewSet,
    SemesterViewSet,
    SubjectViewSet,
    SubstituteSuggestionsView,
    TeacherAvailabilityViewSet,
    TeacherLeaveViewSet,
    TeacherSubjectViewSet,
    TeacherSubstitutionViewSet,
    TimetableConflictViewSet,
    TimetableSlotViewSet,
    TimetableViewSet,
)

app_name = "academics"

router = DefaultRouter()
router.register("departments", DepartmentViewSet, basename="department")
router.register("programs", ProgramViewSet, basename="program")
router.register("semesters", SemesterViewSet, basename="semester")
router.register("divisions", DivisionViewSet, basename="division")
router.register("batches", PracticalBatchViewSet, basename="batch")
router.register("practical-batches", PracticalBatchViewSet, basename="practical-batch")
router.register("subjects", SubjectViewSet, basename="subject")
router.register("teacher-subjects", TeacherSubjectViewSet, basename="teacher-subject")
router.register("teacher-availability", TeacherAvailabilityViewSet, basename="teacher-availability")
router.register("teacher-leaves", TeacherLeaveViewSet, basename="teacher-leave")
router.register("classrooms", ClassroomViewSet, basename="classroom")
router.register("laboratories", LaboratoryViewSet, basename="laboratory")
router.register("timetables", TimetableViewSet, basename="timetable")
router.register("timetable-slots", TimetableSlotViewSet, basename="timetable-slot")
router.register("timetable-conflicts", TimetableConflictViewSet, basename="timetable-conflict")
router.register("substitutions", TeacherSubstitutionViewSet, basename="substitution")
router.register("notifications", NotificationViewSet, basename="notification")

urlpatterns = [
    path(
        "constraints/parse-and-validate/",
        ConstraintParseAndValidateView.as_view(),
        name="constraint-parse-and-validate",
    ),
    path(
        "constraints/generate-timetable/",
        ConstraintGenerateTimetableView.as_view(),
        name="constraint-generate-timetable",
    ),
    path(
        "substitutions/suggestions/",
        SubstituteSuggestionsView.as_view(),
        name="substitute-suggestions",
    ),
] + router.urls


