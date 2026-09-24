from django.urls import path
from .views import StaffDashboardHomeView, StaffLoginView, StaffLogoutView

app_name = "staff"

urlpatterns = [
    path("", StaffDashboardHomeView.as_view(), name="dashboard"),
    path("login/", StaffLoginView.as_view(), name="login"),
    path("logout/", StaffLogoutView.as_view(), name="logout"),
]
