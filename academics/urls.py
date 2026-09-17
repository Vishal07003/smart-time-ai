from rest_framework.routers import DefaultRouter

from .views import (
    ClassroomViewSet,
    DepartmentViewSet,
    DivisionViewSet,
    LaboratoryViewSet,
    PracticalBatchViewSet,
    ProgramViewSet,
    SemesterViewSet,
    SubjectViewSet,
    TeacherAvailabilityViewSet,
    TeacherLeaveViewSet,
    TeacherSubjectViewSet,
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

urlpatterns = router.urls
