from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    ChangePasswordView,
    ForgotPasswordView,
    LoginView,
    LogoutView,
    MeView,
    ResetPasswordView,
    StudentRegisterView,
    StudentResendOTPView,
    StudentVerifyEmailView,
)

app_name = "accounts"

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("student-register/", StudentRegisterView.as_view(), name="student_register"),
    path(
        "student-verify-email/",
        StudentVerifyEmailView.as_view(),
        name="student_verify_email",
    ),
    path(
        "student-resend-otp/",
        StudentResendOTPView.as_view(),
        name="student_resend_otp",
    ),
    path("me/", MeView.as_view(), name="me"),
    path("change-password/", ChangePasswordView.as_view(), name="change_password"),
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot_password"),
    path("reset-password/", ResetPasswordView.as_view(), name="reset_password"),
]
