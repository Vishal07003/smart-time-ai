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
    AcademicSubjectCreateView,
    AcademicSubjectDetailView,
    AcademicSubjectEditView,
    AcademicSubjectListView,
    ClassroomCreateView,
    ClassroomDetailView,
    ClassroomEditView,
    ClassroomListView,
    LaboratoryCreateView,
    LaboratoryDetailView,
    LaboratoryEditView,
    LaboratoryListView,
    StaffDashboardHomeView,
    StaffLoginView,
    StaffLogoutView,
    StudentBatchesApiView,
    StudentCreateView,
    StudentDetailView,
    StudentEditView,
    StudentListView,
    StudentToggleStatusView,
    TeacherAvailabilityDeleteView,
    TeacherAvailabilityManageView,
    TeacherCreateView,
    TeacherDetailView,
    TeacherEditView,
    TeacherLeaveManageView,
    TeacherLeaveStatusUpdateView,
    TeacherListView,
    TeacherSubjectAssignView,
    TeacherSubjectDeleteView,
    TeacherToggleStatusView,
    TimetableChangeLogView,
    TimetableConflictListView,
    TimetableCreateView,
    TimetableDetailView,
    TimetableGenerateView,
    TimetableListView,
    TimetableOptimizeView,
    TimetablePublishView,
    TimetableSlotCreateView,
    TimetableSlotDeleteView,
    TimetableSlotEditView,
    TimetableVersionHistoryView,
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

    # Teacher Operations: Subject Assignment, Availability, Leave
    path("teachers/<uuid:teacher_id>/subjects/assign/", TeacherSubjectAssignView.as_view(), name="teacher_subject_assign"),
    path("teachers/<uuid:teacher_id>/subjects/<uuid:assignment_id>/edit/", TeacherSubjectAssignView.as_view(), name="teacher_subject_edit"),
    path("teachers/<uuid:teacher_id>/subjects/<uuid:assignment_id>/delete/", TeacherSubjectDeleteView.as_view(), name="teacher_subject_delete"),

    path("teachers/<uuid:teacher_id>/availability/", TeacherAvailabilityManageView.as_view(), name="teacher_availability"),
    path("teachers/<uuid:teacher_id>/availability/<uuid:availability_id>/edit/", TeacherAvailabilityManageView.as_view(), name="teacher_availability_edit"),
    path("teachers/<uuid:teacher_id>/availability/<uuid:availability_id>/delete/", TeacherAvailabilityDeleteView.as_view(), name="teacher_availability_delete"),

    path("teachers/<uuid:teacher_id>/leave/", TeacherLeaveManageView.as_view(), name="teacher_leave"),
    path("teachers/<uuid:teacher_id>/leave/<uuid:leave_id>/edit/", TeacherLeaveManageView.as_view(), name="teacher_leave_edit"),
    path("teachers/<uuid:teacher_id>/leave/<uuid:leave_id>/status/", TeacherLeaveStatusUpdateView.as_view(), name="teacher_leave_status"),

    path("students/", StudentListView.as_view(), name="students"),
    path("students/create/", StudentCreateView.as_view(), name="student_create"),
    path("students/<uuid:id>/", StudentDetailView.as_view(), name="student_detail"),
    path("students/<uuid:id>/edit/", StudentEditView.as_view(), name="student_edit"),
    path("students/<uuid:id>/toggle-status/", StudentToggleStatusView.as_view(), name="student_toggle_status"),
    path("api/batches-by-division/", StudentBatchesApiView.as_view(), name="api_batches_by_division"),

    # Resource Management: Classrooms
    path("resources/classrooms/", ClassroomListView.as_view(), name="classrooms"),
    path("resources/classrooms/create/", ClassroomCreateView.as_view(), name="classroom_create"),
    path("resources/classrooms/<uuid:id>/", ClassroomDetailView.as_view(), name="classroom_detail"),
    path("resources/classrooms/<uuid:id>/edit/", ClassroomEditView.as_view(), name="classroom_edit"),

    # Resource Management: Laboratories
    path("resources/laboratories/", LaboratoryListView.as_view(), name="laboratories"),
    path("resources/laboratories/create/", LaboratoryCreateView.as_view(), name="laboratory_create"),
    path("resources/laboratories/<uuid:id>/", LaboratoryDetailView.as_view(), name="laboratory_detail"),
    path("resources/laboratories/<uuid:id>/edit/", LaboratoryEditView.as_view(), name="laboratory_edit"),

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

    path("academic/subjects/", AcademicSubjectListView.as_view(), name="academic_subjects"),
    path("academic/subjects/create/", AcademicSubjectCreateView.as_view(), name="academic_subject_create"),
    path("academic/subjects/<uuid:id>/", AcademicSubjectDetailView.as_view(), name="academic_subject_detail"),
    path("academic/subjects/<uuid:id>/edit/", AcademicSubjectEditView.as_view(), name="academic_subject_edit"),

    # Guided Academic Structure Wizard Flow
    path("academic/structure/create/", AcademicStructureWizardView.as_view(), name="academic_structure_create"),
    path("api/academic/hierarchy/", AcademicHierarchyApiView.as_view(), name="api_academic_hierarchy"),

    # Timetable Management Routes
    path("timetables/", TimetableListView.as_view(), name="timetables"),
    path("timetables/create/", TimetableCreateView.as_view(), name="timetable_create"),
    path("timetables/generate/", TimetableGenerateView.as_view(), name="timetable_generate"),
    path("timetables/conflicts/", TimetableConflictListView.as_view(), name="timetable_conflicts"),
    path("timetables/history/", TimetableChangeLogView.as_view(), name="timetable_history"),
    path("timetables/<uuid:id>/", TimetableDetailView.as_view(), name="timetable_detail"),
    path("timetables/<uuid:id>/optimize/", TimetableOptimizeView.as_view(), name="timetable_optimize"),
    path("timetables/<uuid:id>/publish/", TimetablePublishView.as_view(), name="timetable_publish"),
    path("timetables/<uuid:id>/versions/", TimetableVersionHistoryView.as_view(), name="timetable_versions"),

    # Timetable Slot CRUD
    path("timetables/<uuid:timetable_id>/slots/create/", TimetableSlotCreateView.as_view(), name="timetable_slot_create"),
    path("timetables/<uuid:timetable_id>/slots/<uuid:slot_id>/edit/", TimetableSlotEditView.as_view(), name="timetable_slot_edit"),
    path("timetables/<uuid:timetable_id>/slots/<uuid:slot_id>/delete/", TimetableSlotDeleteView.as_view(), name="timetable_slot_delete"),
]


