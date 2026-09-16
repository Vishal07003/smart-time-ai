from django.urls import path
from .profile_views import (
    StudentDetailView,
    StudentListCreateView,
    StudentMeView,
)

app_name = "students"

urlpatterns = [
    path("", StudentListCreateView.as_view(), name="student_list_create"),
    path("me/", StudentMeView.as_view(), name="student_me"),
    path("<uuid:pk>/", StudentDetailView.as_view(), name="student_detail"),
]
