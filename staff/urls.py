from django.urls import path
from .views import (
    AcademicBatchCreateView,
    AcademicBatchEditView,
    AcademicBatchListView,
    AcademicDepartmentCreateView,
    AcademicDepartmentEditView,
    AcademicDepartmentListView,
    AcademicDivisionCreateView,
    AcademicDivisionEditView,
    AcademicDivisionListView,
    AcademicProgramCreateView,
    AcademicProgramEditView,
    AcademicProgramListView,
    AcademicSemesterCreateView,
    AcademicSemesterEditView,
    AcademicSemesterListView,
    AcademicStructureWizardView,
    AcademicHierarchyApiView,
    StaffDashboardHomeView,
    StaffLoginView,
    StaffLogoutView,
    StudentBatchesApiView,
    StudentCreateView,
    StudentDetailView,
    StudentEditView,
    StudentListView,
    StudentToggleStatusView,
    TeacherCreateView,
    TeacherDetailView,
    TeacherEditView,
    TeacherListView,
    TeacherToggleStatusView,
)

app_name = "staff"

urlpatterns = [
    path("", StaffDashboardHomeView.as_view(), name="dashboard"),
    path("login/", StaffLoginView.as_view(), name="login"),
    path("logout/", StaffLogoutView.as_view(), name="logout"),
    path("teachers/", TeacherListView.as_view(), name="teachers"),
    path("teachers/create/", TeacherCreateView.as_view(), name="teacher_create"),
    path("teachers/<uuid:id>/", TeacherDetailView.as_view(), name="teacher_detail"),
    path("teachers/<uuid:id>/edit/", TeacherEditView.as_view(), name="teacher_edit"),
    path("teachers/<uuid:id>/toggle-status/", TeacherToggleStatusView.as_view(), name="teacher_toggle_status"),
    path("students/", StudentListView.as_view(), name="students"),
    path("students/create/", StudentCreateView.as_view(), name="student_create"),
    path("students/<uuid:id>/", StudentDetailView.as_view(), name="student_detail"),
    path("students/<uuid:id>/edit/", StudentEditView.as_view(), name="student_edit"),
    path("students/<uuid:id>/toggle-status/", StudentToggleStatusView.as_view(), name="student_toggle_status"),
    path("api/batches-by-division/", StudentBatchesApiView.as_view(), name="api_batches_by_division"),

    # Academic Management Routes
    path("academic/departments/", AcademicDepartmentListView.as_view(), name="academic_departments"),
    path("academic/departments/create/", AcademicDepartmentCreateView.as_view(), name="academic_department_create"),
    path("academic/departments/<uuid:id>/edit/", AcademicDepartmentEditView.as_view(), name="academic_department_edit"),

    path("academic/programs/", AcademicProgramListView.as_view(), name="academic_programs"),
    path("academic/programs/create/", AcademicProgramCreateView.as_view(), name="academic_program_create"),
    path("academic/programs/<uuid:id>/edit/", AcademicProgramEditView.as_view(), name="academic_program_edit"),

    path("academic/semesters/", AcademicSemesterListView.as_view(), name="academic_semesters"),
    path("academic/semesters/create/", AcademicSemesterCreateView.as_view(), name="academic_semester_create"),
    path("academic/semesters/<uuid:id>/edit/", AcademicSemesterEditView.as_view(), name="academic_semester_edit"),

    path("academic/divisions/", AcademicDivisionListView.as_view(), name="academic_divisions"),
    path("academic/divisions/create/", AcademicDivisionCreateView.as_view(), name="academic_division_create"),
    path("academic/divisions/<uuid:id>/edit/", AcademicDivisionEditView.as_view(), name="academic_division_edit"),

    path("academic/batches/", AcademicBatchListView.as_view(), name="academic_batches"),
    path("academic/batches/create/", AcademicBatchCreateView.as_view(), name="academic_batch_create"),
    path("academic/batches/<uuid:id>/edit/", AcademicBatchEditView.as_view(), name="academic_batch_edit"),

    # Guided Academic Structure Wizard Flow
    path("academic/structure/create/", AcademicStructureWizardView.as_view(), name="academic_structure_create"),
    path("api/academic/hierarchy/", AcademicHierarchyApiView.as_view(), name="api_academic_hierarchy"),
]


