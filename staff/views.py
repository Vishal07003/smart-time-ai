from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

import logging

from academics.models import (
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
    TimetableChangeLog,
    TimetableConflict,
    TimetableSlot,
)
from academics.services.conflict_detection import ConflictDetectionService
from academics.services.staff_dashboard_service import StaffDashboardService
from academics.services.timetable_generator import TimetableGenerationService
from academics.services.timetable_history_service import TimetableHistoryService
from academics.services.timetable_solver import SolverConfig, TimetableSolver
from accounts.models import StudentProfile, TeacherProfile, User
from .forms import (
    ClassroomForm,
    DepartmentForm,
    DivisionForm,
    LaboratoryForm,
    PracticalBatchForm,
    ProgramForm,
    SemesterForm,
    StaffLoginForm,
    StudentCreateForm,
    StudentEditForm,
    SubjectForm,
    TeacherAvailabilityForm,
    TeacherCreateForm,
    TeacherEditForm,
    TeacherLeaveForm,
    TeacherSubjectForm,
    TimetableForm,
    TimetableGenerateForm,
    TimetableSlotForm,
)
from .mixins import StaffRequiredMixin

logger = logging.getLogger(__name__)


class StaffLoginView(View):
    """
    Handles staff session login.
    Redirects already authenticated staff to the dashboard.
    """

    template_name = "staff/auth/login.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if getattr(request.user, "role", None) == User.Role.STAFF:
                return redirect("staff:dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        form = StaffLoginForm(request=request)
        return render(request, self.template_name, {"form": form})

    def post(self, request, *args, **kwargs):
        form = StaffLoginForm(request=request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            auth_login(request, user)

            next_url = request.GET.get("next") or request.POST.get("next")
            if next_url and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}
            ):
                return redirect(next_url)
            return redirect("staff:dashboard")

        return render(request, self.template_name, {"form": form})


class StaffLogoutView(View):
    """
    Handles POST logout for the staff web portal.
    """

    def post(self, request, *args, **kwargs):
        auth_logout(request)
        return redirect("staff:login")

    def get(self, request, *args, **kwargs):
        return redirect("staff:login")


class StaffDashboardHomeView(StaffRequiredMixin, TemplateView):
    """
    Protected root landing page for authenticated staff members.
    Supplies real-time operational dashboard metrics and today's schedule.
    """

    template_name = "staff/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["staff_user"] = self.request.user
        try:
            dashboard_data = StaffDashboardService.get_dashboard_data(user=self.request.user)
            context["dashboard"] = dashboard_data
            context["summary"] = dashboard_data.get("summary", {})
            context["today"] = dashboard_data.get("today", {})
            context["conflicts"] = dashboard_data.get("conflicts", [])
            context["recent_changes"] = dashboard_data.get("recent_changes", [])
            context["teacher_leaves"] = dashboard_data.get("teacher_leaves", [])
            context["substitutions"] = dashboard_data.get("substitutions", [])
            context["quick_actions"] = dashboard_data.get("quick_actions", {})
        except Exception as exc:
            logger.error("Error generating staff dashboard data: %s", exc, exc_info=True)
            context["dashboard"] = {}
            context["summary"] = {
                "active_teachers_count": 0,
                "active_students_count": 0,
                "today_classes_count": 0,
                "unresolved_conflicts_count": 0,
                "pending_leaves_count": 0,
                "pending_substitutions_count": 0,
            }
            context["today"] = {
                "classes": [],
                "current": [],
                "upcoming": [],
                "completed": [],
                "day": "Today",
                "date": "",
            }
            context["conflicts"] = []
            context["recent_changes"] = []
            context["teacher_leaves"] = []
            context["substitutions"] = []
            context["quick_actions"] = {}
            context["dashboard_error"] = "Operational dashboard data is currently unavailable."
        return context


class TeacherListView(StaffRequiredMixin, View):
    """
    Renders paginated, searchable, and filterable faculty list for Staff users.
    """

    template_name = "staff/teachers/list.html"

    def get(self, request, *args, **kwargs):
        queryset = (
            TeacherProfile.objects.select_related("user", "department")
            .prefetch_related("teacher_subjects__subject")
            .order_by("-created_at")
        )

        # Search parameter (name, username, email, employee code)
        q = request.GET.get("q", "").strip()
        if q:
            queryset = queryset.filter(
                Q(user__first_name__icontains=q)
                | Q(user__last_name__icontains=q)
                | Q(user__username__icontains=q)
                | Q(user__email__icontains=q)
                | Q(employee_code__icontains=q)
            )

        # Department filter
        dept_id = request.GET.get("department", "").strip()
        if dept_id:
            queryset = queryset.filter(department_id=dept_id)

        # Status filter
        status = request.GET.get("status", "").strip().upper()
        if status in [TeacherProfile.Status.ACTIVE, TeacherProfile.Status.INACTIVE]:
            queryset = queryset.filter(status=status)

        # Designation filter
        designation = request.GET.get("designation", "").strip()
        if designation:
            queryset = queryset.filter(designation__iexact=designation)

        # Summary statistics
        total_teachers_count = TeacherProfile.objects.count()
        active_teachers_count = TeacherProfile.objects.filter(
            status=TeacherProfile.Status.ACTIVE
        ).count()
        inactive_teachers_count = TeacherProfile.objects.filter(
            status=TeacherProfile.Status.INACTIVE
        ).count()

        # Pagination (20 per page)
        paginator = Paginator(queryset, 20)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        # Query string preservation for pagination links
        query_params = request.GET.copy()
        if "page" in query_params:
            query_params.pop("page")
        preserved_querystring = query_params.urlencode()

        departments = Department.objects.all().order_by("name")
        designations = (
            TeacherProfile.objects.exclude(designation="")
            .values_list("designation", flat=True)
            .distinct()
            .order_by("designation")
        )

        context = {
            "teachers": page_obj,
            "page_obj": page_obj,
            "paginator": paginator,
            "q": q,
            "current_department": dept_id,
            "current_status": status,
            "current_designation": designation,
            "departments": departments,
            "designations": designations,
            "status_choices": TeacherProfile.Status.choices,
            "total_teachers_count": total_teachers_count,
            "active_teachers_count": active_teachers_count,
            "inactive_teachers_count": inactive_teachers_count,
            "preserved_querystring": preserved_querystring,
        }
        return render(request, self.template_name, context)


class TeacherCreateView(StaffRequiredMixin, View):
    """
    Handles creating a new Teacher user account and faculty profile.
    """

    template_name = "staff/teachers/form.html"

    def get(self, request, *args, **kwargs):
        form = TeacherCreateForm()
        return render(request, self.template_name, {"form": form, "is_edit": False})

    def post(self, request, *args, **kwargs):
        form = TeacherCreateForm(data=request.POST)
        if form.is_valid():
            teacher = form.save()
            messages.success(request, "Teacher created successfully.")
            return redirect("staff:teacher_detail", id=teacher.id)
        return render(request, self.template_name, {"form": form, "is_edit": False})


class TeacherEditView(StaffRequiredMixin, View):
    """
    Handles editing an existing Teacher profile and user details.
    """

    template_name = "staff/teachers/form.html"

    def get(self, request, id, *args, **kwargs):
        teacher = get_object_or_404(
            TeacherProfile.objects.select_related("user", "department"), id=id
        )
        form = TeacherEditForm(teacher=teacher)
        return render(
            request,
            self.template_name,
            {"form": form, "teacher": teacher, "is_edit": True},
        )

    def post(self, request, id, *args, **kwargs):
        teacher = get_object_or_404(
            TeacherProfile.objects.select_related("user", "department"), id=id
        )
        form = TeacherEditForm(teacher=teacher, data=request.POST)
        if form.is_valid():
            teacher = form.save()
            messages.success(request, "Teacher updated successfully.")
            return redirect("staff:teacher_detail", id=teacher.id)
        return render(
            request,
            self.template_name,
            {"form": form, "teacher": teacher, "is_edit": True},
        )


class TeacherDetailView(StaffRequiredMixin, View):
    """
    Renders detailed profile, assigned subjects, weekly availability, and recent leave requests for a teacher.
    """

    template_name = "staff/teachers/detail.html"

    def get(self, request, id, *args, **kwargs):
        teacher = get_object_or_404(
            TeacherProfile.objects.select_related("user", "department"), id=id
        )
        assigned_subjects = (
            TeacherSubject.objects.filter(teacher=teacher)
            .select_related("subject", "subject__program")
            .order_by("priority", "created_at")
        )
        availabilities = (
            TeacherAvailability.objects.filter(teacher=teacher)
            .order_by("day", "start_time")
        )
        leaves = (
            TeacherLeave.objects.filter(teacher=teacher)
            .order_by("-created_at")[:10]
        )

        context = {
            "teacher": teacher,
            "assigned_subjects": assigned_subjects,
            "availabilities": availabilities,
            "leaves": leaves,
        }
        return render(request, self.template_name, context)


class TeacherToggleStatusView(StaffRequiredMixin, View):
    """
    Handles activating or deactivating a teacher profile via POST only.
    """

    def post(self, request, id, *args, **kwargs):
        teacher = get_object_or_404(
            TeacherProfile.objects.select_related("user"), id=id
        )
        if teacher.status == TeacherProfile.Status.ACTIVE:
            teacher.status = TeacherProfile.Status.INACTIVE
            teacher.user.is_active = False
            teacher.save(update_fields=["status"])
            teacher.user.save(update_fields=["is_active"])
            messages.success(request, "Teacher deactivated successfully.")
        else:
            teacher.status = TeacherProfile.Status.ACTIVE
            teacher.user.is_active = True
            teacher.save(update_fields=["status"])
            teacher.user.save(update_fields=["is_active"])
            messages.success(request, "Teacher activated successfully.")

        next_url = request.POST.get("next") or request.META.get("HTTP_REFERER")
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}
        ):
            return redirect(next_url)
        return redirect("staff:teacher_detail", id=teacher.id)

    def get(self, request, id, *args, **kwargs):
        messages.error(request, "Status change requires a valid POST request.")
        return redirect("staff:teacher_detail", id=id)


# ==================== STUDENT MANAGEMENT VIEWS ====================


class StudentListView(StaffRequiredMixin, View):
    """
    Staff Web Student Directory:
    List, search, filter, and paginate student accounts.
    """

    template_name = "staff/students/list.html"

    def get(self, request, *args, **kwargs):
        queryset = (
            StudentProfile.objects.select_related("user", "division", "division__semester", "division__semester__program", "batch")
            .order_by("division__name", "roll_number")
        )

        # Search filter
        q = request.GET.get("q", "").strip()
        if q:
            queryset = queryset.filter(
                Q(user__first_name__icontains=q)
                | Q(user__last_name__icontains=q)
                | Q(user__username__icontains=q)
                | Q(user__email__icontains=q)
                | Q(student_code__icontains=q)
                | Q(roll_number__icontains=q)
            )

        # Division filter
        div_id = request.GET.get("division", "").strip()
        if div_id:
            queryset = queryset.filter(division_id=div_id)

        # Batch filter
        batch_id = request.GET.get("batch", "").strip()
        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)

        # Status filter
        status = request.GET.get("status", "").strip().upper()
        if status in [s[0] for s in StudentProfile.Status.choices]:
            queryset = queryset.filter(status=status)

        # Admission Year filter
        admission_year = request.GET.get("admission_year", "").strip()
        if admission_year and admission_year.isdigit():
            queryset = queryset.filter(admission_year=int(admission_year))

        # Statistics
        total_students_count = StudentProfile.objects.count()
        active_students_count = StudentProfile.objects.filter(
            status=StudentProfile.Status.ACTIVE
        ).count()
        inactive_students_count = StudentProfile.objects.filter(
            status=StudentProfile.Status.INACTIVE
        ).count()

        # Pagination (20 per page)
        paginator = Paginator(queryset, 20)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        # Query string preservation for pagination links
        query_params = request.GET.copy()
        if "page" in query_params:
            query_params.pop("page")
        preserved_querystring = query_params.urlencode()

        divisions = Division.objects.select_related("semester", "semester__program").order_by("name")
        batches = PracticalBatch.objects.all().order_by("name")
        if div_id:
            batches = batches.filter(division_id=div_id)

        admission_years = (
            StudentProfile.objects.values_list("admission_year", flat=True)
            .distinct()
            .order_by("-admission_year")
        )

        context = {
            "students": page_obj,
            "page_obj": page_obj,
            "paginator": paginator,
            "q": q,
            "current_division": div_id,
            "current_batch": batch_id,
            "current_status": status,
            "current_admission_year": admission_year,
            "divisions": divisions,
            "batches": batches,
            "admission_years": admission_years,
            "status_choices": StudentProfile.Status.choices,
            "total_students_count": total_students_count,
            "active_students_count": active_students_count,
            "inactive_students_count": inactive_students_count,
            "preserved_querystring": preserved_querystring,
        }
        return render(request, self.template_name, context)


class StudentCreateView(StaffRequiredMixin, View):
    """
    Handles creating a new Student user account and student profile.
    """

    template_name = "staff/students/form.html"

    def get(self, request, *args, **kwargs):
        form = StudentCreateForm()
        divisions = Division.objects.select_related("semester", "semester__program").order_by("name")
        batches = PracticalBatch.objects.all().order_by("name")
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "is_edit": False,
                "divisions": divisions,
                "batches": batches,
            },
        )

    def post(self, request, *args, **kwargs):
        form = StudentCreateForm(data=request.POST)
        if form.is_valid():
            student = form.save()
            messages.success(request, "Student created successfully.")
            return redirect("staff:student_detail", id=student.id)
        divisions = Division.objects.select_related("semester", "semester__program").order_by("name")
        batches = PracticalBatch.objects.all().order_by("name")
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "is_edit": False,
                "divisions": divisions,
                "batches": batches,
            },
        )


class StudentEditView(StaffRequiredMixin, View):
    """
    Handles editing an existing Student profile and user details.
    """

    template_name = "staff/students/form.html"

    def get(self, request, id, *args, **kwargs):
        student = get_object_or_404(
            StudentProfile.objects.select_related("user", "division", "batch"), id=id
        )
        form = StudentEditForm(student=student)
        divisions = Division.objects.select_related("semester", "semester__program").order_by("name")
        batches = PracticalBatch.objects.all().order_by("name")
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "student": student,
                "is_edit": True,
                "divisions": divisions,
                "batches": batches,
            },
        )

    def post(self, request, id, *args, **kwargs):
        student = get_object_or_404(
            StudentProfile.objects.select_related("user", "division", "batch"), id=id
        )
        form = StudentEditForm(student=student, data=request.POST)
        if form.is_valid():
            student = form.save()
            messages.success(request, "Student profile updated successfully.")
            return redirect("staff:student_detail", id=student.id)
        divisions = Division.objects.select_related("semester", "semester__program").order_by("name")
        batches = PracticalBatch.objects.all().order_by("name")
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "student": student,
                "is_edit": True,
                "divisions": divisions,
                "batches": batches,
            },
        )


class StudentDetailView(StaffRequiredMixin, View):
    """
    Detailed profile view for a specific Student.
    Exposes no password or authentication secrets.
    """

    template_name = "staff/students/detail.html"

    def get(self, request, id, *args, **kwargs):
        student = get_object_or_404(
            StudentProfile.objects.select_related(
                "user",
                "division",
                "division__semester",
                "division__semester__program",
                "batch",
            ),
            id=id,
        )
        context = {
            "student": student,
        }
        return render(request, self.template_name, context)


class StudentToggleStatusView(StaffRequiredMixin, View):
    """
    Toggles a Student's status between ACTIVE and INACTIVE via POST request.
    Does not hard-delete student records.
    """

    def post(self, request, id, *args, **kwargs):
        student = get_object_or_404(
            StudentProfile.objects.select_related("user"), id=id
        )
        if student.status == StudentProfile.Status.ACTIVE:
            student.status = StudentProfile.Status.INACTIVE
            student.user.is_active = False
            student.save(update_fields=["status"])
            student.user.save(update_fields=["is_active"])
            messages.success(request, f"Student {student.user.get_full_name() or student.user.username} deactivated successfully.")
        else:
            student.status = StudentProfile.Status.ACTIVE
            student.user.is_active = True
            student.save(update_fields=["status"])
            student.user.save(update_fields=["is_active"])
            messages.success(request, f"Student {student.user.get_full_name() or student.user.username} activated successfully.")

        next_url = request.POST.get("next") or request.META.get("HTTP_REFERER")
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}
        ):
            return redirect(next_url)
        return redirect("staff:student_detail", id=student.id)

    def get(self, request, id, *args, **kwargs):
        messages.error(request, "Status change requires a valid POST request.")
        return redirect("staff:student_detail", id=id)


class StudentBatchesApiView(StaffRequiredMixin, View):
    """
    Returns practical batches for a given division in JSON format
    for dynamic combobox filtering.
    """

    def get(self, request, *args, **kwargs):
        division_id = request.GET.get("division_id")
        if not division_id:
            return JsonResponse({"batches": []})
        batches = PracticalBatch.objects.filter(division_id=division_id).order_by("name")
        data = [{"id": str(b.id), "name": b.name, "capacity": b.capacity} for b in batches]
        return JsonResponse({"batches": data})


# ==============================================================================
# ACADEMIC MANAGEMENT VIEWS (Department -> Program -> Semester -> Division -> PracticalBatch)
# ==============================================================================

class AcademicDepartmentListView(StaffRequiredMixin, View):
    """
    Lists all Academic Departments with search, statistics, and program counts.
    """

    template_name = "staff/academic/departments/list.html"

    def get(self, request, *args, **kwargs):
        queryset = Department.objects.prefetch_related("programs", "teachers").order_by("name")

        q = request.GET.get("q", "").strip()
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q)
                | Q(code__icontains=q)
            )

        total_departments_count = Department.objects.count()

        paginator = Paginator(queryset, 20)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        query_params = request.GET.copy()
        if "page" in query_params:
            query_params.pop("page")
        preserved_querystring = query_params.urlencode()

        context = {
            "departments": page_obj,
            "page_obj": page_obj,
            "paginator": paginator,
            "q": q,
            "total_departments_count": total_departments_count,
            "preserved_querystring": preserved_querystring,
        }
        return render(request, self.template_name, context)


class AcademicDepartmentCreateView(StaffRequiredMixin, View):
    """
    Handles creating a new Academic Department.
    """

    template_name = "staff/academic/departments/form.html"

    def get(self, request, *args, **kwargs):
        form = DepartmentForm()
        return render(request, self.template_name, {"form": form, "is_edit": False})

    def post(self, request, *args, **kwargs):
        form = DepartmentForm(data=request.POST)
        if form.is_valid():
            department = form.save()
            messages.success(request, f"Department '{department.name}' ({department.code}) created successfully.")
            return redirect("staff:academic_departments")
        return render(request, self.template_name, {"form": form, "is_edit": False})


class AcademicDepartmentEditView(StaffRequiredMixin, View):
    """
    Handles editing an existing Academic Department.
    Preserves relationships with Teachers and Programs.
    """

    template_name = "staff/academic/departments/form.html"

    def get(self, request, id, *args, **kwargs):
        department = get_object_or_404(Department, id=id)
        form = DepartmentForm(instance=department)
        return render(request, self.template_name, {"form": form, "department": department, "is_edit": True})

    def post(self, request, id, *args, **kwargs):
        department = get_object_or_404(Department, id=id)
        form = DepartmentForm(instance=department, data=request.POST)
        if form.is_valid():
            department = form.save()
            messages.success(request, f"Department '{department.name}' ({department.code}) updated successfully.")
            return redirect("staff:academic_departments")
        return render(request, self.template_name, {"form": form, "department": department, "is_edit": True})


class AcademicProgramListView(StaffRequiredMixin, View):
    """
    Lists all Academic Programs with search, department filtering, and statistics.
    """

    template_name = "staff/academic/programs/list.html"

    def get(self, request, *args, **kwargs):
        queryset = Program.objects.select_related("department").prefetch_related("semesters").order_by("name")

        q = request.GET.get("q", "").strip()
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q)
                | Q(code__icontains=q)
                | Q(department__name__icontains=q)
                | Q(department__code__icontains=q)
            )

        dept_id = request.GET.get("department", "").strip()
        if dept_id:
            queryset = queryset.filter(department_id=dept_id)

        duration = request.GET.get("duration", "").strip()
        if duration.isdigit():
            queryset = queryset.filter(duration_years=int(duration))

        total_programs_count = Program.objects.count()
        departments = Department.objects.all().order_by("name")

        paginator = Paginator(queryset, 20)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        query_params = request.GET.copy()
        if "page" in query_params:
            query_params.pop("page")
        preserved_querystring = query_params.urlencode()

        context = {
            "programs": page_obj,
            "page_obj": page_obj,
            "paginator": paginator,
            "q": q,
            "current_department": dept_id,
            "current_duration": duration,
            "departments": departments,
            "total_programs_count": total_programs_count,
            "preserved_querystring": preserved_querystring,
        }
        return render(request, self.template_name, context)


class AcademicProgramCreateView(StaffRequiredMixin, View):
    """
    Handles creating a new Academic Program.
    """

    template_name = "staff/academic/programs/form.html"

    def get(self, request, *args, **kwargs):
        form = ProgramForm()
        return render(request, self.template_name, {"form": form, "is_edit": False})

    def post(self, request, *args, **kwargs):
        form = ProgramForm(data=request.POST)
        if form.is_valid():
            program = form.save()
            messages.success(request, f"Program '{program.name}' created successfully.")
            return redirect("staff:academic_programs")
        return render(request, self.template_name, {"form": form, "is_edit": False})


class AcademicProgramEditView(StaffRequiredMixin, View):
    """
    Handles editing an existing Academic Program.
    """

    template_name = "staff/academic/programs/form.html"

    def get(self, request, id, *args, **kwargs):
        program = get_object_or_404(Program.objects.select_related("department"), id=id)
        form = ProgramForm(instance=program)
        return render(request, self.template_name, {"form": form, "program": program, "is_edit": True})

    def post(self, request, id, *args, **kwargs):
        program = get_object_or_404(Program.objects.select_related("department"), id=id)
        form = ProgramForm(instance=program, data=request.POST)
        if form.is_valid():
            program = form.save()
            messages.success(request, f"Program '{program.name}' updated successfully.")
            return redirect("staff:academic_programs")
        return render(request, self.template_name, {"form": form, "program": program, "is_edit": True})


class AcademicSemesterListView(StaffRequiredMixin, View):
    """
    Lists all Academic Semesters with program filtering, academic year filtering, and search.
    """

    template_name = "staff/academic/semesters/list.html"

    def get(self, request, *args, **kwargs):
        queryset = Semester.objects.select_related("program", "program__department").prefetch_related("divisions").order_by("program__name", "number")

        q = request.GET.get("q", "").strip()
        if q:
            queryset = queryset.filter(
                Q(program__name__icontains=q)
                | Q(program__code__icontains=q)
                | Q(academic_year__icontains=q)
            )

        prog_id = request.GET.get("program", "").strip()
        if prog_id:
            queryset = queryset.filter(program_id=prog_id)

        acad_year = request.GET.get("academic_year", "").strip()
        if acad_year:
            queryset = queryset.filter(academic_year__iexact=acad_year)

        total_semesters_count = Semester.objects.count()
        programs = Program.objects.select_related("department").all().order_by("name")
        academic_years = (
            Semester.objects.values_list("academic_year", flat=True)
            .distinct()
            .order_by("-academic_year")
        )

        paginator = Paginator(queryset, 20)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        query_params = request.GET.copy()
        if "page" in query_params:
            query_params.pop("page")
        preserved_querystring = query_params.urlencode()

        context = {
            "semesters": page_obj,
            "page_obj": page_obj,
            "paginator": paginator,
            "q": q,
            "current_program": prog_id,
            "current_academic_year": acad_year,
            "programs": programs,
            "academic_years": academic_years,
            "total_semesters_count": total_semesters_count,
            "preserved_querystring": preserved_querystring,
        }
        return render(request, self.template_name, context)


class AcademicSemesterCreateView(StaffRequiredMixin, View):
    """
    Handles creating a new Academic Semester.
    """

    template_name = "staff/academic/semesters/form.html"

    def get(self, request, *args, **kwargs):
        initial = {}
        prog_id = request.GET.get("program")
        if prog_id:
            initial["program"] = prog_id
        form = SemesterForm(initial=initial)
        return render(request, self.template_name, {"form": form, "is_edit": False})

    def post(self, request, *args, **kwargs):
        form = SemesterForm(data=request.POST)
        if form.is_valid():
            semester = form.save()
            messages.success(request, f"Semester {semester.number} for '{semester.program.code}' created successfully.")
            return redirect("staff:academic_semesters")
        return render(request, self.template_name, {"form": form, "is_edit": False})


class AcademicSemesterEditView(StaffRequiredMixin, View):
    """
    Handles editing an existing Academic Semester.
    """

    template_name = "staff/academic/semesters/form.html"

    def get(self, request, id, *args, **kwargs):
        semester = get_object_or_404(Semester.objects.select_related("program"), id=id)
        form = SemesterForm(instance=semester)
        return render(request, self.template_name, {"form": form, "semester": semester, "is_edit": True})

    def post(self, request, id, *args, **kwargs):
        semester = get_object_or_404(Semester.objects.select_related("program"), id=id)
        form = SemesterForm(instance=semester, data=request.POST)
        if form.is_valid():
            semester = form.save()
            messages.success(request, f"Semester {semester.number} for '{semester.program.code}' updated successfully.")
            return redirect("staff:academic_semesters")
        return render(request, self.template_name, {"form": form, "semester": semester, "is_edit": True})


class AcademicDivisionListView(StaffRequiredMixin, View):
    """
    Lists all Class Divisions with semester filtering, program filtering, and search.
    """

    template_name = "staff/academic/divisions/list.html"

    def get(self, request, *args, **kwargs):
        queryset = Division.objects.select_related(
            "semester", "semester__program", "semester__program__department"
        ).prefetch_related("batches").order_by("semester__program__name", "semester__number", "name")

        q = request.GET.get("q", "").strip()
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q)
                | Q(semester__program__name__icontains=q)
                | Q(semester__program__code__icontains=q)
                | Q(semester__program__department__name__icontains=q)
                | Q(semester__program__department__code__icontains=q)
                | Q(semester__academic_year__icontains=q)
            )

        prog_id = request.GET.get("program", "").strip()
        if prog_id:
            queryset = queryset.filter(semester__program_id=prog_id)

        sem_id = request.GET.get("semester", "").strip()
        if sem_id:
            queryset = queryset.filter(semester_id=sem_id)

        total_divisions_count = Division.objects.count()
        programs = Program.objects.select_related("department").all().order_by("name")
        semesters = Semester.objects.select_related("program").all().order_by("program__name", "number")
        if prog_id:
            semesters = semesters.filter(program_id=prog_id)

        paginator = Paginator(queryset, 20)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        query_params = request.GET.copy()
        if "page" in query_params:
            query_params.pop("page")
        preserved_querystring = query_params.urlencode()

        context = {
            "divisions": page_obj,
            "page_obj": page_obj,
            "paginator": paginator,
            "q": q,
            "current_program": prog_id,
            "current_semester": sem_id,
            "programs": programs,
            "semesters": semesters,
            "total_divisions_count": total_divisions_count,
            "preserved_querystring": preserved_querystring,
        }
        return render(request, self.template_name, context)


class AcademicDivisionCreateView(StaffRequiredMixin, View):
    """
    Handles creating a new Class Division.
    """

    template_name = "staff/academic/divisions/form.html"

    def get(self, request, *args, **kwargs):
        initial = {}
        sem_id = request.GET.get("semester")
        if sem_id:
            initial["semester"] = sem_id
        form = DivisionForm(initial=initial)
        return render(request, self.template_name, {"form": form, "is_edit": False})

    def post(self, request, *args, **kwargs):
        form = DivisionForm(data=request.POST)
        if form.is_valid():
            division = form.save()
            messages.success(request, f"Division '{division.name}' for {division.semester} created successfully.")
            return redirect("staff:academic_divisions")
        return render(request, self.template_name, {"form": form, "is_edit": False})


class AcademicDivisionEditView(StaffRequiredMixin, View):
    """
    Handles editing an existing Class Division.
    """

    template_name = "staff/academic/divisions/form.html"

    def get(self, request, id, *args, **kwargs):
        division = get_object_or_404(Division.objects.select_related("semester", "semester__program"), id=id)
        form = DivisionForm(instance=division)
        return render(request, self.template_name, {"form": form, "division": division, "is_edit": True})

    def post(self, request, id, *args, **kwargs):
        division = get_object_or_404(Division.objects.select_related("semester", "semester__program"), id=id)
        form = DivisionForm(instance=division, data=request.POST)
        if form.is_valid():
            division = form.save()
            messages.success(request, f"Division '{division.name}' for {division.semester} updated successfully.")
            return redirect("staff:academic_divisions")
        return render(request, self.template_name, {"form": form, "division": division, "is_edit": True})


class AcademicBatchListView(StaffRequiredMixin, View):
    """
    Lists all Practical / Lab Batches with division filtering, semester filtering, and search.
    """

    template_name = "staff/academic/batches/list.html"

    def get(self, request, *args, **kwargs):
        queryset = PracticalBatch.objects.select_related(
            "division", "division__semester", "division__semester__program"
        ).order_by("division__semester__program__name", "division__name", "name")

        q = request.GET.get("q", "").strip()
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q)
                | Q(division__name__icontains=q)
                | Q(division__semester__program__name__icontains=q)
                | Q(division__semester__program__code__icontains=q)
            )

        prog_id = request.GET.get("program", "").strip()
        if prog_id:
            queryset = queryset.filter(division__semester__program_id=prog_id)

        div_id = request.GET.get("division", "").strip()
        if div_id:
            queryset = queryset.filter(division_id=div_id)

        total_batches_count = PracticalBatch.objects.count()
        programs = Program.objects.select_related("department").all().order_by("name")
        divisions = Division.objects.select_related("semester", "semester__program").all().order_by("name")
        if prog_id:
            divisions = divisions.filter(semester__program_id=prog_id)

        paginator = Paginator(queryset, 20)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        query_params = request.GET.copy()
        if "page" in query_params:
            query_params.pop("page")
        preserved_querystring = query_params.urlencode()

        context = {
            "batches": page_obj,
            "page_obj": page_obj,
            "paginator": paginator,
            "q": q,
            "current_program": prog_id,
            "current_division": div_id,
            "programs": programs,
            "divisions": divisions,
            "total_batches_count": total_batches_count,
            "preserved_querystring": preserved_querystring,
        }
        return render(request, self.template_name, context)


class AcademicBatchCreateView(StaffRequiredMixin, View):
    """
    Handles creating a new Practical / Lab Batch.
    """

    template_name = "staff/academic/batches/form.html"

    def get(self, request, *args, **kwargs):
        initial = {}
        div_id = request.GET.get("division")
        if div_id:
            initial["division"] = div_id
        form = PracticalBatchForm(initial=initial)
        return render(request, self.template_name, {"form": form, "is_edit": False})

    def post(self, request, *args, **kwargs):
        form = PracticalBatchForm(data=request.POST)
        if form.is_valid():
            batch = form.save()
            messages.success(request, f"Practical Batch '{batch.name}' for {batch.division} created successfully.")
            return redirect("staff:academic_batches")
        return render(request, self.template_name, {"form": form, "is_edit": False})


class AcademicBatchEditView(StaffRequiredMixin, View):
    """
    Handles editing an existing Practical / Lab Batch.
    """

    template_name = "staff/academic/batches/form.html"

    def get(self, request, id, *args, **kwargs):
        batch = get_object_or_404(
            PracticalBatch.objects.select_related("division", "division__semester", "division__semester__program"),
            id=id,
        )
        form = PracticalBatchForm(instance=batch)
        return render(request, self.template_name, {"form": form, "batch": batch, "is_edit": True})

    def post(self, request, id, *args, **kwargs):
        batch = get_object_or_404(
            PracticalBatch.objects.select_related("division", "division__semester", "division__semester__program"),
            id=id,
        )
        form = PracticalBatchForm(instance=batch, data=request.POST)
        if form.is_valid():
            batch = form.save()
            messages.success(request, f"Practical Batch '{batch.name}' for {batch.division} updated successfully.")
            return redirect("staff:academic_batches")
        return render(request, self.template_name, {"form": form, "batch": batch, "is_edit": True})


# ==============================================================================
# SUBJECT MANAGEMENT VIEWS
# ==============================================================================

class AcademicSubjectListView(StaffRequiredMixin, View):
    """
    Lists all Curricular Subjects / Courses with program filtering, type filtering, and search.
    """

    template_name = "staff/academic/subjects/list.html"

    def get(self, request, *args, **kwargs):
        queryset = Subject.objects.select_related(
            "program", "program__department"
        ).prefetch_related("teacher_subjects__teacher__user").order_by("program__name", "code")

        q = request.GET.get("q", "").strip()
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q)
                | Q(code__icontains=q)
                | Q(program__name__icontains=q)
                | Q(program__code__icontains=q)
                | Q(program__department__name__icontains=q)
                | Q(program__department__code__icontains=q)
            )

        prog_id = request.GET.get("program", "").strip()
        if prog_id:
            queryset = queryset.filter(program_id=prog_id)

        subj_type = request.GET.get("type", "").strip().upper()
        if subj_type in [choice[0] for choice in Subject.Type.choices]:
            queryset = queryset.filter(type=subj_type)

        total_subjects_count = Subject.objects.count()
        lecture_count = Subject.objects.filter(
            Q(weekly_lectures__gt=0) | Q(type=Subject.Type.LECTURE)
        ).distinct().count()
        practical_count = Subject.objects.filter(
            Q(weekly_practicals__gt=0) | Q(type=Subject.Type.PRACTICAL)
        ).distinct().count()
        tutorial_count = Subject.objects.filter(
            type=Subject.Type.TUTORIAL
        ).distinct().count()

        programs = Program.objects.select_related("department").all().order_by("name")

        paginator = Paginator(queryset, 20)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        query_params = request.GET.copy()
        if "page" in query_params:
            query_params.pop("page")
        preserved_querystring = query_params.urlencode()

        context = {
            "subjects": page_obj,
            "page_obj": page_obj,
            "paginator": paginator,
            "q": q,
            "current_program": prog_id,
            "current_type": subj_type,
            "programs": programs,
            "type_choices": Subject.Type.choices,
            "total_subjects_count": total_subjects_count,
            "lecture_count": lecture_count,
            "practical_count": practical_count,
            "tutorial_count": tutorial_count,
            "preserved_querystring": preserved_querystring,
        }
        return render(request, self.template_name, context)


class AcademicSubjectCreateView(StaffRequiredMixin, View):
    """
    Handles creating a new Curricular Subject.
    """

    template_name = "staff/academic/subjects/form.html"

    def get(self, request, *args, **kwargs):
        initial = {}
        prog_id = request.GET.get("program")
        if prog_id:
            initial["program"] = prog_id
        form = SubjectForm(initial=initial)
        return render(request, self.template_name, {"form": form, "is_edit": False})

    def post(self, request, *args, **kwargs):
        form = SubjectForm(data=request.POST)
        if form.is_valid():
            subject = form.save()
            messages.success(request, f"Subject '{subject.name}' ({subject.code}) created successfully.")
            return redirect("staff:academic_subjects")
        return render(request, self.template_name, {"form": form, "is_edit": False})


class AcademicSubjectEditView(StaffRequiredMixin, View):
    """
    Handles editing an existing Curricular Subject.
    """

    template_name = "staff/academic/subjects/form.html"

    def get(self, request, id, *args, **kwargs):
        subject = get_object_or_404(
            Subject.objects.select_related("program", "program__department"),
            id=id,
        )
        form = SubjectForm(instance=subject)
        return render(request, self.template_name, {"form": form, "subject": subject, "is_edit": True})

    def post(self, request, id, *args, **kwargs):
        subject = get_object_or_404(
            Subject.objects.select_related("program", "program__department"),
            id=id,
        )
        form = SubjectForm(instance=subject, data=request.POST)
        if form.is_valid():
            subject = form.save()
            messages.success(request, f"Subject '{subject.name}' ({subject.code}) updated successfully.")
            return redirect("staff:academic_subjects")
        return render(request, self.template_name, {"form": form, "subject": subject, "is_edit": True})


class AcademicSubjectDetailView(StaffRequiredMixin, View):
    """
    Displays detailed academic information for a subject, including assigned teachers and timetable slots.
    """

    template_name = "staff/academic/subjects/detail.html"

    def get(self, request, id, *args, **kwargs):
        subject = get_object_or_404(
            Subject.objects.select_related("program", "program__department"),
            id=id,
        )
        assigned_teachers = (
            TeacherSubject.objects.filter(subject=subject)
            .select_related("teacher", "teacher__user", "teacher__department")
            .order_by("priority", "created_at")
        )
        timetable_slots = (
            subject.timetable_slots.select_related("timetable", "teacher", "classroom", "division", "batch")
            .order_by("day", "start_time")[:15]
        )

        context = {
            "subject": subject,
            "assigned_teachers": assigned_teachers,
            "timetable_slots": timetable_slots,
        }
        return render(request, self.template_name, context)



# ==============================================================================
# GUIDED ACADEMIC STRUCTURE WIZARD
# Department -> Program -> Semester -> Division -> Practical Batch (optional)
# ==============================================================================

class AcademicStructureWizardView(StaffRequiredMixin, View):
    """
    Step-by-step guided flow to configure a complete Academic Structure:
    Department -> Program -> Semester -> Division -> Practical Batch (optional)
    """

    template_name = "staff/academic/wizard.html"

    def get_initial_hierarchy(self):
        departments = Department.objects.all().order_by("name")
        data = []
        for d in departments:
            d_programs = []
            for p in d.programs.all().order_by("name"):
                p_semesters = []
                for s in p.semesters.all().order_by("number"):
                    s_divisions = []
                    for div in s.divisions.all().order_by("name"):
                        div_batches = [
                            {"id": str(b.id), "name": b.name, "capacity": b.capacity}
                            for b in div.batches.all().order_by("name")
                        ]
                        s_divisions.append({
                            "id": str(div.id),
                            "name": div.name,
                            "capacity": div.capacity,
                            "batches": div_batches,
                        })
                    p_semesters.append({
                        "id": str(s.id),
                        "number": s.number,
                        "academic_year": s.academic_year,
                        "display_name": f"Semester {s.number} ({s.academic_year})",
                        "divisions": s_divisions,
                    })
                d_programs.append({
                    "id": str(p.id),
                    "name": p.name,
                    "code": p.code,
                    "duration_years": p.duration_years,
                    "display_name": f"{p.name} ({p.code})",
                    "semesters": p_semesters,
                })
            data.append({
                "id": str(d.id),
                "name": d.name,
                "code": d.code,
                "display_name": f"{d.name} ({d.code})",
                "programs": d_programs,
            })
        return data

    def get(self, request, *args, **kwargs):
        hierarchy_data = self.get_initial_hierarchy()
        context = {
            "hierarchy_json": hierarchy_data,
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        import json
        from django.db import transaction

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({"success": False, "error": "Invalid JSON payload."}, status=400)

        # Extraction
        dept_mode = payload.get("dept_mode", "select")
        dept_id = payload.get("dept_id")
        dept_data = payload.get("dept_data", {})

        prog_mode = payload.get("prog_mode", "select")
        prog_id = payload.get("prog_id")
        prog_data = payload.get("prog_data", {})

        sem_mode = payload.get("sem_mode", "select")
        sem_id = payload.get("sem_id")
        sem_data = payload.get("sem_data", {})

        div_mode = payload.get("div_mode", "select")
        div_id = payload.get("div_id")
        div_data = payload.get("div_data", {})

        batch_create = payload.get("batch_create", False)
        batch_data = payload.get("batch_data", {})

        errors = {}

        try:
            with transaction.atomic():
                # 1. DEPARTMENT
                department = None
                if dept_mode == "select":
                    if not dept_id:
                        errors["dept"] = "Please select a department."
                    else:
                        department = Department.objects.filter(id=dept_id).first()
                        if not department:
                            errors["dept"] = "Selected department does not exist."
                else:
                    dept_form = DepartmentForm(data=dept_data)
                    if dept_form.is_valid():
                        department = dept_form.save()
                    else:
                        errors["dept"] = dept_form.errors

                if errors:
                    raise ValueError("Department error")

                # 2. PROGRAM
                program = None
                if prog_mode == "select":
                    if not prog_id:
                        errors["prog"] = "Please select a program."
                    else:
                        program = Program.objects.filter(id=prog_id, department=department).first()
                        if not program:
                            # Also check if it exists in another department or general
                            program = Program.objects.filter(id=prog_id).first()
                            if not program:
                                errors["prog"] = "Selected program does not exist."
                else:
                    p_data = dict(prog_data)
                    p_data["department"] = str(department.id)
                    prog_form = ProgramForm(data=p_data)
                    if prog_form.is_valid():
                        program = prog_form.save()
                    else:
                        errors["prog"] = prog_form.errors

                if errors:
                    raise ValueError("Program error")

                # 3. SEMESTER
                semester = None
                if sem_mode == "select":
                    if not sem_id:
                        errors["sem"] = "Please select a semester."
                    else:
                        semester = Semester.objects.filter(id=sem_id).first()
                        if not semester:
                            errors["sem"] = "Selected semester does not exist."
                else:
                    s_data = dict(sem_data)
                    s_data["program"] = str(program.id)
                    sem_form = SemesterForm(data=s_data)
                    if sem_form.is_valid():
                        semester = sem_form.save()
                    else:
                        errors["sem"] = sem_form.errors

                if errors:
                    raise ValueError("Semester error")

                # 4. DIVISION
                division = None
                if div_mode == "select":
                    if not div_id:
                        errors["div"] = "Please select a division."
                    else:
                        division = Division.objects.filter(id=div_id).first()
                        if not division:
                            errors["div"] = "Selected division does not exist."
                else:
                    d_data = dict(div_data)
                    d_data["semester"] = str(semester.id)
                    div_form = DivisionForm(data=d_data)
                    if div_form.is_valid():
                        division = div_form.save()
                    else:
                        errors["div"] = div_form.errors

                if errors:
                    raise ValueError("Division error")

                # 5. PRACTICAL BATCH (Optional)
                batch = None
                if batch_create:
                    b_data = dict(batch_data)
                    b_data["division"] = str(division.id)
                    batch_form = PracticalBatchForm(data=b_data)
                    if batch_form.is_valid():
                        batch = batch_form.save()
                    else:
                        errors["batch"] = batch_form.errors

                if errors:
                    raise ValueError("Batch error")

        except ValueError:
            return JsonResponse({"success": False, "errors": errors}, status=400)
        except Exception as e:
            logger.exception("Error executing academic structure wizard.")
            return JsonResponse({"success": False, "error": str(e)}, status=500)

        # Success message
        msg = f"Academic Structure for '{department.name} > {program.name} > Semester {semester.number} > Div {division.name}' successfully configured."
        if batch:
            msg += f" Practical Batch '{batch.name}' was also created."
        messages.success(request, msg)

        return JsonResponse({
            "success": True,
            "redirect_url": reverse("staff:academic_departments"),
            "data": {
                "department": {"id": str(department.id), "name": department.name, "code": department.code},
                "program": {"id": str(program.id), "name": program.name, "code": program.code},
                "semester": {"id": str(semester.id), "number": semester.number, "academic_year": semester.academic_year},
                "division": {"id": str(division.id), "name": division.name, "capacity": division.capacity},
                "batch": {"id": str(batch.id), "name": batch.name, "capacity": batch.capacity} if batch else None,
            }
        })


class AcademicHierarchyApiView(StaffRequiredMixin, View):
    """
    Returns the dynamic hierarchical academic structure in JSON format
    for client-side comboboxes and filters.
    """

    def get(self, request, *args, **kwargs):
        wizard = AcademicStructureWizardView()
        return JsonResponse({"departments": wizard.get_initial_hierarchy()})


# ==================== TEACHER OPERATIONS VIEWS ====================

class TeacherSubjectAssignView(StaffRequiredMixin, View):
    """
    Assigns a Subject to a Teacher or edits an existing assignment.
    """

    template_name = "staff/teachers/assignment_form.html"

    def get(self, request, teacher_id, assignment_id=None, *args, **kwargs):
        teacher = get_object_or_404(
            TeacherProfile.objects.select_related("user", "department"), id=teacher_id
        )
        assignment = None
        if assignment_id:
            assignment = get_object_or_404(TeacherSubject, id=assignment_id, teacher=teacher)
        form = TeacherSubjectForm(instance=assignment, teacher=teacher)
        return render(
            request,
            self.template_name,
            {"form": form, "teacher": teacher, "assignment": assignment, "is_edit": bool(assignment)},
        )

    def post(self, request, teacher_id, assignment_id=None, *args, **kwargs):
        teacher = get_object_or_404(
            TeacherProfile.objects.select_related("user", "department"), id=teacher_id
        )
        assignment = None
        if assignment_id:
            assignment = get_object_or_404(TeacherSubject, id=assignment_id, teacher=teacher)
        form = TeacherSubjectForm(instance=assignment, teacher=teacher, data=request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.teacher = teacher
            obj.save()
            messages.success(
                request,
                f"Subject '{obj.subject.name}' ({obj.subject.code}) assigned to {teacher.user.get_full_name() or teacher.employee_code}.",
            )
            return redirect("staff:teacher_detail", id=teacher.id)
        return render(
            request,
            self.template_name,
            {"form": form, "teacher": teacher, "assignment": assignment, "is_edit": bool(assignment)},
        )


class TeacherSubjectDeleteView(StaffRequiredMixin, View):
    """
    Removes a Subject assignment from a Teacher (POST only).
    """

    def post(self, request, teacher_id, assignment_id, *args, **kwargs):
        teacher = get_object_or_404(TeacherProfile, id=teacher_id)
        assignment = get_object_or_404(TeacherSubject, id=assignment_id, teacher=teacher)
        subj_name = assignment.subject.name
        assignment.delete()
        messages.success(request, f"Assignment for '{subj_name}' was successfully removed.")
        return redirect("staff:teacher_detail", id=teacher.id)

    def get(self, request, teacher_id, assignment_id, *args, **kwargs):
        return redirect("staff:teacher_detail", id=teacher_id)


class TeacherAvailabilityManageView(StaffRequiredMixin, View):
    """
    Manages and creates availability time slots for a teacher.
    """

    template_name = "staff/teachers/availability_form.html"

    def get(self, request, teacher_id, availability_id=None, *args, **kwargs):
        teacher = get_object_or_404(
            TeacherProfile.objects.select_related("user", "department"), id=teacher_id
        )
        availability = None
        if availability_id:
            availability = get_object_or_404(TeacherAvailability, id=availability_id, teacher=teacher)
        form = TeacherAvailabilityForm(instance=availability, teacher=teacher)
        availabilities = TeacherAvailability.objects.filter(teacher=teacher).order_by("day", "start_time")
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "teacher": teacher,
                "availability": availability,
                "availabilities": availabilities,
                "is_edit": bool(availability),
            },
        )

    def post(self, request, teacher_id, availability_id=None, *args, **kwargs):
        teacher = get_object_or_404(
            TeacherProfile.objects.select_related("user", "department"), id=teacher_id
        )
        availability = None
        if availability_id:
            availability = get_object_or_404(TeacherAvailability, id=availability_id, teacher=teacher)
        form = TeacherAvailabilityForm(instance=availability, teacher=teacher, data=request.POST)
        if form.is_valid():
            slot = form.save(commit=False)
            slot.teacher = teacher
            slot.save()
            messages.success(
                request,
                f"Availability slot for {slot.day} ({slot.start_time.strftime('%H:%M')} - {slot.end_time.strftime('%H:%M')}) saved.",
            )
            return redirect("staff:teacher_availability", teacher_id=teacher.id)
        availabilities = TeacherAvailability.objects.filter(teacher=teacher).order_by("day", "start_time")
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "teacher": teacher,
                "availability": availability,
                "availabilities": availabilities,
                "is_edit": bool(availability),
            },
        )


class TeacherAvailabilityDeleteView(StaffRequiredMixin, View):
    """
    Deletes an availability slot (POST only).
    """

    def post(self, request, teacher_id, availability_id, *args, **kwargs):
        teacher = get_object_or_404(TeacherProfile, id=teacher_id)
        slot = get_object_or_404(TeacherAvailability, id=availability_id, teacher=teacher)
        slot.delete()
        messages.success(request, "Availability slot removed successfully.")
        return redirect("staff:teacher_availability", teacher_id=teacher.id)

    def get(self, request, teacher_id, availability_id, *args, **kwargs):
        return redirect("staff:teacher_availability", teacher_id=teacher_id)


class TeacherLeaveManageView(StaffRequiredMixin, View):
    """
    Manages and creates leave requests for a teacher.
    """

    template_name = "staff/teachers/leave_form.html"

    def get(self, request, teacher_id, leave_id=None, *args, **kwargs):
        teacher = get_object_or_404(
            TeacherProfile.objects.select_related("user", "department"), id=teacher_id
        )
        leave = None
        if leave_id:
            leave = get_object_or_404(TeacherLeave, id=leave_id, teacher=teacher)
        form = TeacherLeaveForm(instance=leave, teacher=teacher)
        leaves = TeacherLeave.objects.filter(teacher=teacher).order_by("-start_date")
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "teacher": teacher,
                "leave": leave,
                "leaves": leaves,
                "is_edit": bool(leave),
            },
        )

    def post(self, request, teacher_id, leave_id=None, *args, **kwargs):
        teacher = get_object_or_404(
            TeacherProfile.objects.select_related("user", "department"), id=teacher_id
        )
        leave = None
        if leave_id:
            leave = get_object_or_404(TeacherLeave, id=leave_id, teacher=teacher)
        form = TeacherLeaveForm(instance=leave, teacher=teacher, data=request.POST)
        if form.is_valid():
            l_obj = form.save(commit=False)
            l_obj.teacher = teacher
            l_obj.save()
            messages.success(
                request,
                f"Leave record from {l_obj.start_date} to {l_obj.end_date} [{l_obj.status}] saved successfully.",
            )
            return redirect("staff:teacher_leave", teacher_id=teacher.id)
        leaves = TeacherLeave.objects.filter(teacher=teacher).order_by("-start_date")
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "teacher": teacher,
                "leave": leave,
                "leaves": leaves,
                "is_edit": bool(leave),
            },
        )


class TeacherLeaveStatusUpdateView(StaffRequiredMixin, View):
    """
    Quick status transition for leave (APPROVE/REJECT/PENDING) via POST.
    """

    def post(self, request, teacher_id, leave_id, *args, **kwargs):
        teacher = get_object_or_404(TeacherProfile, id=teacher_id)
        leave = get_object_or_404(TeacherLeave, id=leave_id, teacher=teacher)
        new_status = request.POST.get("status", "").strip().upper()
        if new_status in TeacherLeave.Status.values:
            leave.status = new_status
            leave.save(update_fields=["status", "updated_at"])
            messages.success(request, f"Leave status updated to {new_status}.")
        return redirect("staff:teacher_leave", teacher_id=teacher.id)

    def get(self, request, teacher_id, leave_id, *args, **kwargs):
        return redirect("staff:teacher_leave", teacher_id=teacher_id)


# ==================== RESOURCE MANAGEMENT: CLASSROOMS ====================

class ClassroomListView(StaffRequiredMixin, View):
    """
    Classroom resource directory: search, status filter, and pagination.
    """

    template_name = "staff/resources/classrooms/list.html"

    def get(self, request, *args, **kwargs):
        queryset = Classroom.objects.all().order_by("building", "room_number")

        q = request.GET.get("q", "").strip()
        if q:
            queryset = queryset.filter(
                Q(building__icontains=q)
                | Q(room_number__icontains=q)
            )

        building_filter = request.GET.get("building", "").strip()
        if building_filter:
            queryset = queryset.filter(building__iexact=building_filter)

        status_filter = request.GET.get("status", "").strip().upper()
        if status_filter in Classroom.Status.values:
            queryset = queryset.filter(status=status_filter)

        buildings = Classroom.objects.values_list("building", flat=True).distinct().order_by("building")
        total_classrooms = Classroom.objects.count()
        available_count = Classroom.objects.filter(status=Classroom.Status.AVAILABLE).count()
        maintenance_count = Classroom.objects.filter(status=Classroom.Status.MAINTENANCE).count()

        paginator = Paginator(queryset, 20)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        query_params = request.GET.copy()
        if "page" in query_params:
            query_params.pop("page")
        preserved_querystring = query_params.urlencode()

        context = {
            "classrooms": page_obj,
            "page_obj": page_obj,
            "paginator": paginator,
            "q": q,
            "current_building": building_filter,
            "current_status": status_filter,
            "buildings": buildings,
            "status_choices": Classroom.Status.choices,
            "total_classrooms": total_classrooms,
            "available_count": available_count,
            "maintenance_count": maintenance_count,
            "preserved_querystring": preserved_querystring,
        }
        return render(request, self.template_name, context)


class ClassroomCreateView(StaffRequiredMixin, View):
    """
    Creates a new Classroom resource.
    """

    template_name = "staff/resources/classrooms/form.html"

    def get(self, request, *args, **kwargs):
        form = ClassroomForm()
        return render(request, self.template_name, {"form": form, "is_edit": False})

    def post(self, request, *args, **kwargs):
        form = ClassroomForm(data=request.POST)
        if form.is_valid():
            cr = form.save()
            messages.success(request, f"Classroom '{cr.building} - {cr.room_number}' created successfully.")
            return redirect("staff:classrooms")
        return render(request, self.template_name, {"form": form, "is_edit": False})


class ClassroomEditView(StaffRequiredMixin, View):
    """
    Edits an existing Classroom resource.
    """

    template_name = "staff/resources/classrooms/form.html"

    def get(self, request, id, *args, **kwargs):
        classroom = get_object_or_404(Classroom, id=id)
        form = ClassroomForm(instance=classroom)
        return render(request, self.template_name, {"form": form, "classroom": classroom, "is_edit": True})

    def post(self, request, id, *args, **kwargs):
        classroom = get_object_or_404(Classroom, id=id)
        form = ClassroomForm(instance=classroom, data=request.POST)
        if form.is_valid():
            cr = form.save()
            messages.success(request, f"Classroom '{cr.building} - {cr.room_number}' updated successfully.")
            return redirect("staff:classroom_detail", id=cr.id)
        return render(request, self.template_name, {"form": form, "classroom": classroom, "is_edit": True})


class ClassroomDetailView(StaffRequiredMixin, View):
    """
    Renders detailed view for a Classroom resource including current schedule.
    """

    template_name = "staff/resources/classrooms/detail.html"

    def get(self, request, id, *args, **kwargs):
        classroom = get_object_or_404(Classroom, id=id)
        slots = classroom.timetable_slots.select_related("timetable", "subject", "teacher", "division").order_by("day", "start_time")
        return render(request, self.template_name, {"classroom": classroom, "slots": slots})


# ==================== RESOURCE MANAGEMENT: LABORATORIES ====================

class LaboratoryListView(StaffRequiredMixin, View):
    """
    Laboratory resource directory: search, status filter, and pagination.
    """

    template_name = "staff/resources/laboratories/list.html"

    def get(self, request, *args, **kwargs):
        queryset = Laboratory.objects.all().order_by("building", "lab_number")

        q = request.GET.get("q", "").strip()
        if q:
            queryset = queryset.filter(
                Q(building__icontains=q)
                | Q(lab_number__icontains=q)
                | Q(name__icontains=q)
            )

        building_filter = request.GET.get("building", "").strip()
        if building_filter:
            queryset = queryset.filter(building__iexact=building_filter)

        status_filter = request.GET.get("status", "").strip().upper()
        if status_filter in Laboratory.Status.values:
            queryset = queryset.filter(status=status_filter)

        buildings = Laboratory.objects.values_list("building", flat=True).distinct().order_by("building")
        total_laboratories = Laboratory.objects.count()
        available_count = Laboratory.objects.filter(status=Laboratory.Status.AVAILABLE).count()
        maintenance_count = Laboratory.objects.filter(status=Laboratory.Status.MAINTENANCE).count()

        paginator = Paginator(queryset, 20)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        query_params = request.GET.copy()
        if "page" in query_params:
            query_params.pop("page")
        preserved_querystring = query_params.urlencode()

        context = {
            "laboratories": page_obj,
            "page_obj": page_obj,
            "paginator": paginator,
            "q": q,
            "current_building": building_filter,
            "current_status": status_filter,
            "buildings": buildings,
            "status_choices": Laboratory.Status.choices,
            "total_laboratories": total_laboratories,
            "available_count": available_count,
            "maintenance_count": maintenance_count,
            "preserved_querystring": preserved_querystring,
        }
        return render(request, self.template_name, context)


class LaboratoryCreateView(StaffRequiredMixin, View):
    """
    Creates a new Laboratory resource.
    """

    template_name = "staff/resources/laboratories/form.html"

    def get(self, request, *args, **kwargs):
        form = LaboratoryForm()
        return render(request, self.template_name, {"form": form, "is_edit": False})

    def post(self, request, *args, **kwargs):
        form = LaboratoryForm(data=request.POST)
        if form.is_valid():
            lab = form.save()
            messages.success(request, f"Laboratory '{lab.name}' ({lab.building} - {lab.lab_number}) created successfully.")
            return redirect("staff:laboratories")
        return render(request, self.template_name, {"form": form, "is_edit": False})


class LaboratoryEditView(StaffRequiredMixin, View):
    """
    Edits an existing Laboratory resource.
    """

    template_name = "staff/resources/laboratories/form.html"

    def get(self, request, id, *args, **kwargs):
        lab = get_object_or_404(Laboratory, id=id)
        form = LaboratoryForm(instance=lab)
        return render(request, self.template_name, {"form": form, "laboratory": lab, "is_edit": True})

    def post(self, request, id, *args, **kwargs):
        lab = get_object_or_404(Laboratory, id=id)
        form = LaboratoryForm(instance=lab, data=request.POST)
        if form.is_valid():
            lab = form.save()
            messages.success(request, f"Laboratory '{lab.name}' ({lab.building} - {lab.lab_number}) updated successfully.")
            return redirect("staff:laboratory_detail", id=lab.id)
        return render(request, self.template_name, {"form": form, "laboratory": lab, "is_edit": True})


class LaboratoryDetailView(StaffRequiredMixin, View):
    """
    Renders detailed view for a Laboratory resource including practical batch allocations.
    """

    template_name = "staff/resources/laboratories/detail.html"

    def get(self, request, id, *args, **kwargs):
        lab = get_object_or_404(Laboratory, id=id)
        slots = lab.timetable_slots.select_related("timetable", "subject", "teacher", "division", "batch").order_by("day", "start_time")
        return render(request, self.template_name, {"laboratory": lab, "slots": slots})


# ==============================================================================
# STAFF TIMETABLE MANAGEMENT VIEWS
# ==============================================================================

class TimetableListView(StaffRequiredMixin, View):
    """
    Renders the Timetable List page with filtering by Program, Semester, Academic Year,
    Status, and search. Displays version, status badges, and actions.
    """

    template_name = "staff/timetables/list.html"

    def get(self, request, *args, **kwargs):
        queryset = Timetable.objects.select_related("semester", "semester__program", "semester__program__department", "created_by").all().order_by("-academic_year", "semester__program__name", "semester__number", "-version")

        q = request.GET.get("q", "").strip()
        program_id = request.GET.get("program", "").strip()
        semester_id = request.GET.get("semester", "").strip()
        status_param = request.GET.get("status", "").strip().upper()
        academic_year = request.GET.get("academic_year", "").strip()

        if q:
            queryset = queryset.filter(
                Q(semester__program__name__icontains=q)
                | Q(semester__program__code__icontains=q)
                | Q(academic_year__icontains=q)
            )

        if program_id:
            queryset = queryset.filter(semester__program_id=program_id)

        if semester_id:
            queryset = queryset.filter(semester_id=semester_id)

        if status_param and status_param in Timetable.Status.values:
            queryset = queryset.filter(status=status_param)

        if academic_year:
            queryset = queryset.filter(academic_year__icontains=academic_year)

        # Statistics
        total_timetables = Timetable.objects.count()
        published_count = Timetable.objects.filter(status=Timetable.Status.PUBLISHED).count()
        draft_count = Timetable.objects.filter(status=Timetable.Status.DRAFT).count()
        review_count = Timetable.objects.filter(status__in=[Timetable.Status.GENERATED, Timetable.Status.REVIEW]).count()

        paginator = Paginator(queryset, 10)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        # Query param persistence
        query_params = request.GET.copy()
        if "page" in query_params:
            del query_params["page"]
        preserved_querystring = query_params.urlencode()

        programs = Program.objects.all().order_by("name")
        semesters = Semester.objects.select_related("program").all().order_by("program__name", "number")

        context = {
            "page_obj": page_obj,
            "paginator": paginator,
            "q": q,
            "current_program": program_id,
            "current_semester": semester_id,
            "current_status": status_param,
            "current_academic_year": academic_year,
            "programs": programs,
            "semesters": semesters,
            "total_timetables": total_timetables,
            "published_count": published_count,
            "draft_count": draft_count,
            "review_count": review_count,
            "preserved_querystring": preserved_querystring,
            "status_choices": Timetable.Status.choices,
        }
        return render(request, self.template_name, context)


class TimetableCreateView(StaffRequiredMixin, View):
    """
    Creates a new Timetable container. Automates next version for the semester and year.
    """

    template_name = "staff/timetables/form.html"

    def get(self, request, *args, **kwargs):
        form = TimetableForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request, *args, **kwargs):
        form = TimetableForm(data=request.POST)
        if form.is_valid():
            semester = form.cleaned_data["semester"]
            academic_year = form.cleaned_data["academic_year"]
            status_val = form.cleaned_data.get("status") or Timetable.Status.DRAFT

            from django.db.models import Max
            max_ver = (
                Timetable.objects.filter(
                    semester=semester, academic_year=academic_year
                ).aggregate(Max("version"))["version__max"]
                or 0
            )
            timetable = Timetable.objects.create(
                semester=semester,
                academic_year=academic_year,
                version=max_ver + 1,
                status=status_val,
                created_by=request.user,
            )
            TimetableHistoryService.log_timetable_created(timetable, changed_by=request.user)
            messages.success(request, f"Timetable {timetable.semester} ({timetable.academic_year}) v{timetable.version} created.")
            return redirect("staff:timetable_detail", id=timetable.id)

        return render(request, self.template_name, {"form": form})


class TimetableDetailView(StaffRequiredMixin, View):
    """
    Renders weekly grid (Monday–Saturday) showing time-slot matrix,
    lecture vs practical styling, lab/room info, conflict warnings, and actions.
    """

    template_name = "staff/timetables/detail.html"

    def get(self, request, id, *args, **kwargs):
        timetable = get_object_or_404(
            Timetable.objects.select_related(
                "semester", "semester__program", "semester__program__department", "created_by"
            ),
            id=id,
        )

        division_filter = request.GET.get("division", "").strip()

        slots_qs = (
            TimetableSlot.objects.filter(timetable=timetable)
            .select_related(
                "division", "batch", "subject", "teacher", "teacher__user", "classroom", "laboratory"
            )
            .order_by("start_time")
        )

        if division_filter:
            slots_qs = slots_qs.filter(division_id=division_filter)

        slots = list(slots_qs)

        # Collect unique time bands across all slots, or provide default standard time bands
        default_bands = [
            ("09:00:00", "10:00:00", "09:00 - 10:00"),
            ("10:00:00", "11:00:00", "10:00 - 11:00"),
            ("11:00:00", "12:00:00", "11:00 - 12:00"),
            ("12:00:00", "13:00:00", "12:00 - 13:00"),
            ("13:00:00", "14:00:00", "13:00 - 14:00"),
            ("14:00:00", "15:00:00", "14:00 - 15:00"),
            ("15:00:00", "16:00:00", "15:00 - 16:00"),
            ("16:00:00", "17:00:00", "16:00 - 17:00"),
        ]

        slot_times = set()
        for s in slots:
            slot_times.add((s.start_time.strftime("%H:%M:%S"), s.end_time.strftime("%H:%M:%S")))

        if slot_times:
            sorted_times = sorted(list(slot_times), key=lambda x: x[0])
            time_bands = [
                (t[0], t[1], f"{t[0][:5]} - {t[1][:5]}") for t in sorted_times
            ]
        else:
            time_bands = default_bands

        days = [
            ("MONDAY", "Monday"),
            ("TUESDAY", "Tuesday"),
            ("WEDNESDAY", "Wednesday"),
            ("THURSDAY", "Thursday"),
            ("FRIDAY", "Friday"),
            ("SATURDAY", "Saturday"),
        ]

        # Group slots by (day, start_time_str)
        grid = {}
        for day_code, _ in days:
            grid[day_code] = {}
            for start_str, _, _ in time_bands:
                grid[day_code][start_str] = []

        for s in slots:
            s_day = s.day
            s_start = s.start_time.strftime("%H:%M:%S")
            if s_day in grid:
                if s_start not in grid[s_day]:
                    grid[s_day][s_start] = []
                grid[s_day][s_start].append(s)

        # Conflict count
        conflict_count = TimetableConflict.objects.filter(
            timetable=timetable, status=TimetableConflict.Status.DETECTED
        ).count()

        divisions = Division.objects.filter(semester=timetable.semester).order_by("name")

        # Other versions of this semester
        other_versions = Timetable.objects.filter(
            semester=timetable.semester, academic_year=timetable.academic_year
        ).order_by("-version")

        context = {
            "timetable": timetable,
            "days": days,
            "time_bands": time_bands,
            "grid": grid,
            "slots": slots,
            "total_slots": len(slots),
            "conflict_count": conflict_count,
            "divisions": divisions,
            "current_division": division_filter,
            "other_versions": other_versions,
        }
        return render(request, self.template_name, context)


class TimetableSlotCreateView(StaffRequiredMixin, View):
    """
    Adds a new manual slot to a timetable.
    """

    template_name = "staff/timetables/slot_form.html"

    def get(self, request, timetable_id, *args, **kwargs):
        timetable = get_object_or_404(Timetable, id=timetable_id)
        if timetable.status == Timetable.Status.ARCHIVED:
            messages.error(request, "Cannot add slots to an ARCHIVED timetable.")
            return redirect("staff:timetable_detail", id=timetable.id)

        form = TimetableSlotForm(timetable=timetable)
        return render(request, self.template_name, {"form": form, "timetable": timetable, "is_edit": False})

    def post(self, request, timetable_id, *args, **kwargs):
        timetable = get_object_or_404(Timetable, id=timetable_id)
        if timetable.status == Timetable.Status.ARCHIVED:
            messages.error(request, "Cannot add slots to an ARCHIVED timetable.")
            return redirect("staff:timetable_detail", id=timetable.id)

        form = TimetableSlotForm(data=request.POST, timetable=timetable)
        if form.is_valid():
            slot = form.save(commit=False)
            slot.timetable = timetable
            slot.save()

            # Run conflict detection to update clash records
            ConflictDetectionService(timetable).detect_conflicts()

            # Audit log
            TimetableHistoryService.log_event(
                timetable=timetable,
                action=TimetableChangeLog.Action.SLOT_CREATED,
                timetable_slot=slot,
                changed_by=request.user,
                reason="Slot manually created by staff",
                new_data=TimetableHistoryService.slot_to_dict(slot),
            )
            messages.success(request, f"Scheduled slot added: {slot.subject.code} on {slot.day} {slot.start_time.strftime('%H:%M')}.")
            return redirect("staff:timetable_detail", id=timetable.id)

        return render(request, self.template_name, {"form": form, "timetable": timetable, "is_edit": False})


class TimetableSlotEditView(StaffRequiredMixin, View):
    """
    Edits an existing slot in a timetable.
    """

    template_name = "staff/timetables/slot_form.html"

    def get(self, request, timetable_id, slot_id, *args, **kwargs):
        timetable = get_object_or_404(Timetable, id=timetable_id)
        slot = get_object_or_404(TimetableSlot, id=slot_id, timetable=timetable)

        if timetable.status == Timetable.Status.ARCHIVED:
            messages.error(request, "Cannot modify slots for an ARCHIVED timetable.")
            return redirect("staff:timetable_detail", id=timetable.id)

        form = TimetableSlotForm(instance=slot, timetable=timetable)
        return render(request, self.template_name, {"form": form, "timetable": timetable, "slot": slot, "is_edit": True})

    def post(self, request, timetable_id, slot_id, *args, **kwargs):
        timetable = get_object_or_404(Timetable, id=timetable_id)
        slot = get_object_or_404(TimetableSlot, id=slot_id, timetable=timetable)

        if timetable.status == Timetable.Status.ARCHIVED:
            messages.error(request, "Cannot modify slots for an ARCHIVED timetable.")
            return redirect("staff:timetable_detail", id=timetable.id)

        old_data = TimetableHistoryService.slot_to_dict(slot)
        form = TimetableSlotForm(data=request.POST, instance=slot, timetable=timetable)
        if form.is_valid():
            updated_slot = form.save()

            ConflictDetectionService(timetable).detect_conflicts()

            TimetableHistoryService.log_event(
                timetable=timetable,
                action=TimetableChangeLog.Action.SLOT_UPDATED,
                timetable_slot=updated_slot,
                changed_by=request.user,
                reason="Slot updated by staff",
                old_data=old_data,
                new_data=TimetableHistoryService.slot_to_dict(updated_slot),
            )
            messages.success(request, f"Slot updated: {updated_slot.subject.code} on {updated_slot.day}.")
            return redirect("staff:timetable_detail", id=timetable.id)

        return render(request, self.template_name, {"form": form, "timetable": timetable, "slot": slot, "is_edit": True})


class TimetableSlotDeleteView(StaffRequiredMixin, View):
    """
    Deletes an individual slot from a timetable.
    """

    def post(self, request, timetable_id, slot_id, *args, **kwargs):
        timetable = get_object_or_404(Timetable, id=timetable_id)
        slot = get_object_or_404(TimetableSlot, id=slot_id, timetable=timetable)

        if timetable.status == Timetable.Status.ARCHIVED:
            messages.error(request, "Cannot remove slots from an ARCHIVED timetable.")
            return redirect("staff:timetable_detail", id=timetable.id)

        old_data = TimetableHistoryService.slot_to_dict(slot)
        slot_desc = f"{slot.subject.code} ({slot.day} {slot.start_time.strftime('%H:%M')})"
        slot.delete()

        ConflictDetectionService(timetable).detect_conflicts()

        TimetableHistoryService.log_event(
            timetable=timetable,
            action=TimetableChangeLog.Action.SLOT_CANCELLED,
            changed_by=request.user,
            reason=f"Slot removed: {slot_desc}",
            old_data=old_data,
        )
        messages.success(request, f"Slot '{slot_desc}' removed successfully.")
        return redirect("staff:timetable_detail", id=timetable.id)


class TimetableGenerateView(StaffRequiredMixin, View):
    """
    Staff screen for launching the AI Timetable Generation service.
    Can be invoked with a pre-selected timetable/semester or standalone.
    """

    template_name = "staff/timetables/generate.html"

    def get(self, request, *args, **kwargs):
        timetable_id = request.GET.get("timetable_id")
        initial_data = {}
        target_timetable = None

        if timetable_id:
            target_timetable = get_object_or_404(Timetable, id=timetable_id)
            initial_data = {
                "semester": target_timetable.semester,
                "academic_year": target_timetable.academic_year,
            }

        form = TimetableGenerateForm(initial=initial_data)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "target_timetable": target_timetable,
                "interpreted_constraints": [],
            },
        )

    def _build_parsing_context(self, semester):
        """Constructs ParsingContext with active teachers, subjects, and divisions for semester."""
        from academics.services.constraint_parser import ParsingContext
        subjects_qs = Subject.objects.filter(program=semester.program)
        subjects_data = [{"id": str(s.id), "name": s.name, "code": s.code} for s in subjects_qs]

        teachers_qs = TeacherProfile.objects.filter(
            status=TeacherProfile.Status.ACTIVE,
            user__is_active=True,
            teacher_subjects__subject__in=subjects_qs,
        ).select_related("user").distinct()
        teachers_data = [
            {
                "id": str(t.id),
                "name": t.user.get_full_name() or t.user.username,
                "employee_code": t.employee_code,
            }
            for t in teachers_qs
        ]

        divisions_qs = Division.objects.filter(semester=semester)
        divisions_data = [{"id": str(d.id), "name": d.name} for d in divisions_qs]

        return ParsingContext(
            teachers=teachers_data,
            subjects=subjects_data,
            divisions=divisions_data,
            allowed_days=["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"],
        )

    def _parse_nl_requirements(self, text, semester, parsing_context):
        """
        Parses multi-clause or multi-line natural language text into validated StructuredConstraints.
        Returns (interpreted_list, validation_errors_list).
        """
        import re
        from academics.services.constraint_parser import ConstraintParserService
        from academics.services.constraint_validator import ConstraintValidatorService

        if not text or not text.strip():
            return [], []

        parser = ConstraintParserService()
        validator = ConstraintValidatorService()

        # Split on newlines or semicolons or full stops followed by space/newline
        raw_clauses = [c.strip() for c in re.split(r"[;\n]+|\.\s+", text) if c.strip() and len(c.strip()) > 3]
        interpreted = []
        parse_errors = []

        for clause in raw_clauses:
            parse_res = parser.parse(clause, context=parsing_context)
            if parse_res.success and parse_res.constraint:
                val_res = validator.validate(parse_res.constraint.to_dict(), semester=semester)
                if val_res.valid and val_res.constraint:
                    c_dict = val_res.constraint
                    c_dict["raw_instruction"] = clause
                    interpreted.append(c_dict)
                else:
                    for err in val_res.errors:
                        parse_errors.append(f"'{clause}': {err.message}")
            else:
                for err in parse_res.errors:
                    parse_errors.append(f"'{clause}': {err}")

        return interpreted, parse_errors

    def post(self, request, *args, **kwargs):
        form = TimetableGenerateForm(data=request.POST)
        action = request.POST.get("action", "generate")

        if form.is_valid():
            semester = form.cleaned_data["semester"]
            academic_year = form.cleaned_data["academic_year"]
            division = form.cleaned_data.get("division")
            working_days = form.cleaned_data.get("working_days", ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"])
            start_time = form.cleaned_data.get("daily_start_time", "09:00").strip()
            end_time = form.cleaned_data.get("daily_end_time", "17:00").strip()
            slot_duration = form.cleaned_data.get("slot_duration_minutes", 60)
            lunch_start = form.cleaned_data.get("lunch_break_start", "").strip()
            lunch_end = form.cleaned_data.get("lunch_break_end", "").strip()

            prefer_practicals = form.cleaned_data.get("prefer_practicals_period", "AFTERNOON")
            avoid_consecutive = form.cleaned_data.get("avoid_teacher_consecutive", True)
            avoid_gaps = form.cleaned_data.get("avoid_division_gaps", True)
            subject_dist = form.cleaned_data.get("subject_distribution", True)
            nl_text = form.cleaned_data.get("natural_language_requirements", "").strip()

            # Ensure start/end time have seconds
            if len(start_time) == 5:
                start_time = f"{start_time}:00"
            if len(end_time) == 5:
                end_time = f"{end_time}:00"

            parsing_context = self._build_parsing_context(semester)
            interpreted_constraints, parse_errors = self._parse_nl_requirements(nl_text, semester, parsing_context)

            # Build structured constraints from form toggles
            all_constraints = list(interpreted_constraints)

            # 1. Lunch Break Constraint (Exclude lunch interval across divisions or target division)
            if lunch_start and lunch_end:
                l_s = f"{lunch_start}:00" if len(lunch_start) == 5 else lunch_start
                l_e = f"{lunch_end}:00" if len(lunch_end) == 5 else lunch_end
                div_ids = [division.id] if division else [d.id for d in Division.objects.filter(semester=semester)]
                for d_id in div_ids:
                    for d_day in working_days:
                        all_constraints.append({
                            "constraint_type": "DIVISION_TIME_RESTRICTION",
                            "division_id": str(d_id),
                            "day": d_day,
                            "start_time": l_s,
                            "end_time": l_e,
                            "mode": "AVOID",
                            "raw_instruction": f"Scheduled lunch break from {lunch_start} to {lunch_end}",
                        })

            # 2. Practical Period Preference
            if prefer_practicals in ("AFTERNOON", "MORNING"):
                all_constraints.append({
                    "constraint_type": "SESSION_TIME_PREFERENCE",
                    "session_type": "PRACTICAL",
                    "time_range": prefer_practicals,
                    "mode": "PREFER",
                    "raw_instruction": f"Prefer practical sessions in the {prefer_practicals.lower()}",
                })

            # Handle PREVIEW action (Staff reviewing understood constraints without generating yet)
            if action == "parse_preview":
                return render(
                    request,
                    self.template_name,
                    {
                        "form": form,
                        "preview_mode": True,
                        "interpreted_constraints": all_constraints,
                        "parse_errors": parse_errors,
                    },
                )

            # ACTION == "generate"
            from academics.services.timetable_solver import OptimizationConfig
            opt_config = OptimizationConfig(
                enabled=True,
                teacher_consecutive_weight=20 if avoid_consecutive else 0,
                division_gap_weight=25 if avoid_gaps else 0,
                subject_distribution_weight=15 if subject_dist else 0,
            )

            solver_config = SolverConfig(
                days=list(working_days),
                daily_start_time=start_time,
                daily_end_time=end_time,
                slot_duration_minutes=slot_duration,
                optimization=opt_config,
            )

            service = TimetableGenerationService(
                semester_id=semester.id,
                academic_year=academic_year,
                created_by=request.user,
                config=solver_config,
                constraints=all_constraints,
                division_id=division.id if division else None,
            )
            result = service.generate()

            status_res = result.get("status")
            if status_res in (TimetableSolver.STATUS_OPTIMAL, TimetableSolver.STATUS_FEASIBLE):
                new_tt_id = result.get("timetable_id")
                messages.success(
                    request,
                    f"Timetable generated successfully ({status_res})! Created {result.get('total_slots', 0)} slots."
                )
                return redirect("staff:timetable_detail", id=new_tt_id)
            else:
                errors = result.get("errors", ["Infeasible timetable."])
                conflicts = result.get("conflicts", [])
                return render(
                    request,
                    self.template_name,
                    {
                        "form": form,
                        "generation_failed": True,
                        "errors": errors,
                        "conflicts": conflicts,
                        "interpreted_constraints": all_constraints,
                        "parse_errors": parse_errors,
                    },
                )

        return render(request, self.template_name, {"form": form})


class TimetableConflictListView(StaffRequiredMixin, View):
    """
    Shows detected conflicts across all timetables or for a specific timetable.
    Allows staff to trigger on-demand conflict detection or mark conflicts as resolved/ignored.
    """

    template_name = "staff/timetables/conflicts.html"

    def get(self, request, *args, **kwargs):
        timetable_id = request.GET.get("timetable")
        status_filter = request.GET.get("status", TimetableConflict.Status.DETECTED)
        conflict_type = request.GET.get("type", "")

        conflicts_qs = TimetableConflict.objects.select_related(
            "timetable",
            "timetable__semester",
            "timetable__semester__program",
            "slot",
            "slot__subject",
            "slot__teacher",
            "slot__teacher__user",
            "slot__classroom",
            "slot__laboratory",
            "slot__division",
            "conflicting_slot",
            "conflicting_slot__subject",
            "conflicting_slot__teacher",
            "conflicting_slot__teacher__user",
            "conflicting_slot__classroom",
            "conflicting_slot__laboratory",
            "conflicting_slot__division",
            "resolved_by",
        ).all().order_by("-severity", "-created_at")

        target_timetable = None
        if timetable_id:
            target_timetable = get_object_or_404(Timetable, id=timetable_id)
            conflicts_qs = conflicts_qs.filter(timetable=target_timetable)

        if status_filter:
            conflicts_qs = conflicts_qs.filter(status=status_filter)

        if conflict_type:
            conflicts_qs = conflicts_qs.filter(conflict_type=conflict_type)

        timetables = Timetable.objects.select_related("semester", "semester__program").filter(
            status__in=[Timetable.Status.DRAFT, Timetable.Status.GENERATED, Timetable.Status.REVIEW, Timetable.Status.PUBLISHED]
        ).order_by("-updated_at")

        paginator = Paginator(conflicts_qs, 15)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        context = {
            "page_obj": page_obj,
            "paginator": paginator,
            "target_timetable": target_timetable,
            "timetables": timetables,
            "current_timetable": timetable_id,
            "current_status": status_filter,
            "current_type": conflict_type,
            "conflict_types": TimetableConflict.ConflictType.choices,
            "status_choices": TimetableConflict.Status.choices,
            "total_conflicts": conflicts_qs.count(),
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        # Action handler: re-run conflict detection or update status
        action = request.POST.get("action")
        timetable_id = request.POST.get("timetable_id")

        if action == "run_check" and timetable_id:
            tt = get_object_or_404(Timetable, id=timetable_id)
            service = ConflictDetectionService(tt)
            found = service.detect_conflicts()
            messages.success(request, f"Conflict check completed for {tt.semester} v{tt.version}. Found {len(found)} clash(es).")
            return redirect(f"{reverse('staff:timetable_conflicts')}?timetable={tt.id}")

        conflict_id = request.POST.get("conflict_id")
        if conflict_id and action in ("resolve", "ignore"):
            conflict = get_object_or_404(TimetableConflict, id=conflict_id)
            new_status = TimetableConflict.Status.RESOLVED if action == "resolve" else TimetableConflict.Status.IGNORED
            conflict.status = new_status
            conflict.resolved_by = request.user
            from django.utils import timezone
            conflict.resolved_at = timezone.now()
            conflict.save()
            messages.success(request, f"Conflict marked as {new_status.lower()}.")

        redirect_url = request.META.get("HTTP_REFERER") or reverse("staff:timetable_conflicts")
        return redirect(redirect_url)


class TimetableOptimizeView(StaffRequiredMixin, View):
    """
    Staff action to re-run optimization on a generated/review timetable.
    """

    def post(self, request, id, *args, **kwargs):
        timetable = get_object_or_404(Timetable, id=id)

        if timetable.status == Timetable.Status.PUBLISHED:
            messages.error(request, "Cannot re-optimize an already PUBLISHED timetable.")
            return redirect("staff:timetable_detail", id=timetable.id)

        if timetable.status == Timetable.Status.ARCHIVED:
            messages.error(request, "Cannot optimize an ARCHIVED timetable.")
            return redirect("staff:timetable_detail", id=timetable.id)

        # Run solver with optimization enabled
        service = TimetableGenerationService(
            semester_id=timetable.semester_id,
            academic_year=timetable.academic_year,
            created_by=request.user,
        )
        result = service.generate()

        if result.get("status") in (TimetableSolver.STATUS_OPTIMAL, TimetableSolver.STATUS_FEASIBLE):
            messages.success(request, f"Timetable optimized successfully! New version created: v{result.get('version')}.")
            return redirect("staff:timetable_detail", id=result.get("timetable_id"))
        else:
            messages.error(request, f"Optimization could not find a feasible solution: {', '.join(result.get('errors', []))}")
            return redirect("staff:timetable_detail", id=timetable.id)


class TimetablePublishView(StaffRequiredMixin, View):
    """
    Publishes a Timetable, atomically archiving prior published versions for the semester & academic year.
    """

    def post(self, request, id, *args, **kwargs):
        timetable = get_object_or_404(Timetable, id=id)

        if timetable.status == Timetable.Status.PUBLISHED:
            messages.info(request, "This timetable is already published.")
            return redirect("staff:timetable_detail", id=timetable.id)

        # Ensure timetable has slots
        if not timetable.slots.exists():
            messages.error(request, "Cannot publish a timetable with no scheduled slots.")
            return redirect("staff:timetable_detail", id=timetable.id)

        with transaction.atomic():
            # 1. Archive previous published versions
            prev_published = list(
                Timetable.objects.filter(
                    semester=timetable.semester,
                    academic_year=timetable.academic_year,
                    status=Timetable.Status.PUBLISHED,
                ).exclude(pk=timetable.pk)
            )
            for prev in prev_published:
                prev.status = Timetable.Status.ARCHIVED
                prev.save(update_fields=["status", "updated_at"])
                TimetableHistoryService.log_timetable_archived(prev, changed_by=request.user)

            old_status = timetable.status
            timetable.status = Timetable.Status.PUBLISHED
            from django.utils import timezone
            timetable.published_at = timezone.now()
            timetable.save(update_fields=["status", "published_at", "updated_at"])

            TimetableHistoryService.log_timetable_published(
                timetable, changed_by=request.user, old_status=old_status
            )

        messages.success(request, f"Timetable {timetable.semester} ({timetable.academic_year}) v{timetable.version} has been published!")
        return redirect("staff:timetable_detail", id=timetable.id)


class TimetableVersionHistoryView(StaffRequiredMixin, View):
    """
    Lists all versions for a given semester and academic year.
    """

    template_name = "staff/timetables/versions.html"

    def get(self, request, id, *args, **kwargs):
        timetable = get_object_or_404(Timetable.objects.select_related("semester", "semester__program"), id=id)
        versions = (
            Timetable.objects.filter(
                semester=timetable.semester, academic_year=timetable.academic_year
            )
            .select_related("created_by")
            .order_by("-version")
        )

        context = {
            "timetable": timetable,
            "versions": versions,
        }
        return render(request, self.template_name, context)


class TimetableChangeLogView(StaffRequiredMixin, View):
    """
    Renders audit activity log history for a specific timetable or across all timetables.
    """

    template_name = "staff/timetables/history.html"

    def get(self, request, *args, **kwargs):
        timetable_id = request.GET.get("timetable")
        target_timetable = None

        logs_qs = (
            TimetableChangeLog.objects.select_related(
                "timetable",
                "timetable__semester",
                "timetable__semester__program",
                "timetable_slot",
                "timetable_slot__subject",
                "changed_by",
            )
            .all()
            .order_by("-created_at")
        )

        if timetable_id:
            target_timetable = get_object_or_404(Timetable, id=timetable_id)
            logs_qs = logs_qs.filter(timetable=target_timetable)

        action_filter = request.GET.get("action", "")
        if action_filter:
            logs_qs = logs_qs.filter(action=action_filter)

        paginator = Paginator(logs_qs, 20)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        timetables = Timetable.objects.select_related("semester", "semester__program").order_by("-updated_at")

        context = {
            "page_obj": page_obj,
            "paginator": paginator,
            "target_timetable": target_timetable,
            "timetables": timetables,
            "current_timetable": timetable_id,
            "current_action": action_filter,
            "actions": TimetableChangeLog.Action.choices,
        }
        return render(request, self.template_name, context)






