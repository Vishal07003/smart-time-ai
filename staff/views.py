from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

import logging

from academics.models import (
    Department,
    Division,
    PracticalBatch,
    Program,
    Semester,
    TeacherAvailability,
    TeacherLeave,
    TeacherSubject,
)
from academics.services.staff_dashboard_service import StaffDashboardService
from accounts.models import StudentProfile, TeacherProfile, User
from .forms import (
    DepartmentForm,
    DivisionForm,
    PracticalBatchForm,
    ProgramForm,
    SemesterForm,
    StaffLoginForm,
    StudentCreateForm,
    StudentEditForm,
    TeacherCreateForm,
    TeacherEditForm,
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




