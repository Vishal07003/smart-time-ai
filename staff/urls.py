from django.urls import path
from .views import (
    StaffDashboardHomeView,
    StaffLoginView,
    StaffLogoutView,
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
]
