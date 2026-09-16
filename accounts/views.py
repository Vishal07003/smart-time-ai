import logging
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    LoginSerializer,
    LogoutSerializer,
    ResetPasswordSerializer,
    StudentRegisterSerializer,
    StudentResendOTPSerializer,
    StudentVerifyEmailSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from .services import resend_student_otp, verify_student_otp

logger = logging.getLogger(__name__)


class LoginView(APIView):
    """
    POST /api/v1/auth/login/
    Authenticates user via username or email and password.
    Returns access & refresh JWT tokens and user profile (with role).
    """

    permission_classes = [AllowAny]
    throttle_scope = "auth_login"

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        tokens = LoginSerializer.get_tokens_for_user(user)

        return Response(
            {
                "success": True,
                "message": "Login successful.",
                "user": UserSerializer(user).data,
                "tokens": tokens,
            },
            status=status.HTTP_200_OK,
        )


class StudentRegisterView(APIView):
    """
    POST /api/v1/auth/student-register/
    Public registration endpoint strictly for STUDENTS.
    Creates unverified user account, generates 6-digit OTP, and dispatches verification email.
    """

    permission_classes = [AllowAny]
    throttle_scope = "student_register"

    def post(self, request):
        serializer = StudentRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        return Response(
            {
                "success": True,
                "message": "Registration successful. A verification code has been sent to your email.",
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class StudentVerifyEmailView(APIView):
    """
    POST /api/v1/auth/student-verify-email/
    Verifies student's email address using the 6-digit OTP.
    Activates account upon successful verification.
    """

    permission_classes = [AllowAny]
    throttle_scope = "student_verify_otp"

    def post(self, request):
        serializer = StudentVerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        otp = serializer.validated_data["otp"]

        success, message = verify_student_otp(email, otp)

        if not success:
            return Response(
                {
                    "success": False,
                    "message": message,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "success": True,
                "message": message,
            },
            status=status.HTTP_200_OK,
        )


class StudentResendOTPView(APIView):
    """
    POST /api/v1/auth/student-resend-otp/
    Resends a new 6-digit verification code to the student's email.
    Invalidates any previous OTP and maintains anti-enumeration.
    """

    permission_classes = [AllowAny]
    throttle_scope = "student_resend_otp"

    def post(self, request):
        serializer = StudentResendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        resend_student_otp(email)

        return Response(
            {
                "success": True,
                "message": "If the account is eligible, a verification code has been sent.",
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/
    Blacklists the given refresh token, logging out the user.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data["refresh"]
        token.blacklist()

        return Response(
            {
                "success": True,
                "message": "Logout successful. Token has been blacklisted.",
            },
            status=status.HTTP_200_OK,
        )


class MeView(APIView):
    """
    GET /api/v1/auth/me/
    Returns profile information of the currently authenticated user.

    PATCH /api/v1/auth/me/
    Allows updating editable personal details (first_name, last_name, phone).
    Protected fields (role, is_active, email_verified, username, email) cannot be altered.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(
            {
                "success": True,
                "user": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request):
        serializer = UserUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {
                "success": True,
                "message": "Profile updated successfully.",
                "user": UserSerializer(request.user).data,
            },
            status=status.HTTP_200_OK,
        )


class ChangePasswordView(APIView):
    """
    POST /api/v1/auth/change-password/
    Allows an authenticated user to change their password.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {
                "success": True,
                "message": "Password changed successfully.",
            },
            status=status.HTTP_200_OK,
        )


class ForgotPasswordView(APIView):
    """
    POST /api/v1/auth/forgot-password/
    Initiates password reset process for a given email.
    Always returns a generic success message to prevent email enumeration.
    """

    permission_classes = [AllowAny]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.context.get("user")

        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)

            # Dispatch password reset email
            try:
                subject = "Password Reset Request - SMART-TIME AI"
                message = (
                    f"Hello {user.username},\n\n"
                    f"Use the following credentials to reset your password:\n"
                    f"UID: {uid}\n"
                    f"Token: {token}\n\n"
                    f"If you did not request this, please ignore this email."
                )
                send_mail(
                    subject,
                    message,
                    getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@smarttime.ai"),
                    [user.email],
                    fail_silently=True,
                )
            except Exception as e:
                logger.warning(f"Failed to dispatch password reset email: {e}")

        return Response(
            {
                "success": True,
                "message": "If an account with that email exists, password reset instructions have been sent.",
            },
            status=status.HTTP_200_OK,
        )


class ResetPasswordView(APIView):
    """
    POST /api/v1/auth/reset-password/
    Resets the user's password using the UID and token.
    """

    permission_classes = [AllowAny]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {
                "success": True,
                "message": "Password has been reset successfully. You can now log in with your new password.",
            },
            status=status.HTTP_200_OK,
        )