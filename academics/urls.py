from rest_framework.routers import DefaultRouter

from .views import (
    DepartmentViewSet,
    DivisionViewSet,
    PracticalBatchViewSet,
    ProgramViewSet,
    SemesterViewSet,
    SubjectViewSet,
)

app_name = "academics"

router = DefaultRouter()
router.register("departments", DepartmentViewSet, basename="department")
router.register("programs", ProgramViewSet, basename="program")
router.register("semesters", SemesterViewSet, basename="semester")
router.register("divisions", DivisionViewSet, basename="division")
router.register("batches", PracticalBatchViewSet, basename="batch")
router.register("subjects", SubjectViewSet, basename="subject")

urlpatterns = router.urls
