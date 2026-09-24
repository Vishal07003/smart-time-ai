from django.contrib.auth import login as auth_login, logout as auth_logout
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

from academics.services.staff_dashboard_service import StaffDashboardService
from accounts.models import User
from .forms import StaffLoginForm
from .mixins import StaffRequiredMixin


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
        except Exception:
            context["dashboard"] = {}
            context["summary"] = {}
            context["today"] = {}
            context["conflicts"] = []
            context["recent_changes"] = []
            context["teacher_leaves"] = []
            context["substitutions"] = []
            context["quick_actions"] = {}
        return context
