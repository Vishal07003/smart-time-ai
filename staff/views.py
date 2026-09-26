from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

import logging

from academics.models import Department, TeacherAvailability, TeacherLeave, TeacherSubject
from academics.services.staff_dashboard_service import StaffDashboardService
from accounts.models import TeacherProfile, User
from .forms import StaffLoginForm, TeacherCreateForm, TeacherEditForm
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

