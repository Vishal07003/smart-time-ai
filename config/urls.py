from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("accounts.urls")),
    path("api/v1/teachers/", include("accounts.teacher_urls")),
    path("api/v1/students/", include("accounts.student_urls")),
    path("api/v1/", include("academics.urls")),
]