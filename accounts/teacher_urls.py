from django.urls import path
from .profile_views import (
    TeacherDetailView,
    TeacherListCreateView,
    TeacherMeView,
)

app_name = "teachers"

urlpatterns = [
    path("", TeacherListCreateView.as_view(), name="teacher_list_create"),
    path("me/", TeacherMeView.as_view(), name="teacher_me"),
    path("<uuid:pk>/", TeacherDetailView.as_view(), name="teacher_detail"),
]
