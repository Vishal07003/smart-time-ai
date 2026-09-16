import logging
import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import EmailVerification, User
from .validators import normalize_email

logger = logging.getLogger(__name__)

OTP_EXPIRY_MINUTES = 10
OTP_MAX_ATTEMPTS = 5


def generate_otp() -> str:
    """
    Generates a cryptographically secure 6-digit OTP using Python's secrets module.
    Produces a value between 100000 and 999999 inclusive.
    """
    return f"{secrets.randbelow(900000) + 100000}"


def create_email_verification(user: User, otp: str) -> EmailVerification:
    """
    Invalidates previous active OTPs for the user, securely hashes the new OTP,
    and stores it with a 10-minute expiry.
    """
    # Invalidate previous unused codes for this user
    EmailVerification.objects.filter(user=user, is_used=False).update(is_used=True)

    otp_hash = make_password(otp)
    expires_at = timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)

    return EmailVerification.objects.create(
        user=user,
        otp_hash=otp_hash,
        expires_at=expires_at,
        is_used=False,
        attempts=0,
    )


def send_otp_email(email: str, otp: str) -> None:
    """
    Dispatches the 6-digit OTP to the student's registered email address.
    Supports both HTML formatting and plain-text fallback.
    Never logs the OTP itself in application logs.
    """
    subject = "SMART-TIME AI - Verify Your Email"
    message = (
        f"Hello,\n\n"
        f"Your verification code is: {otp}\n\n"
        f"This code expires in 10 minutes.\n"
        f"If you did not request this verification code, please ignore this email.\n\n"
        f"SMART-TIME AI Team"
    )
    html_message = (
        f"<div style='font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px; background-color: #ffffff;'>"
        f"<div style='margin-bottom: 20px; text-align: center;'>"
        f"<h2 style='color: #4f46e5; margin: 0;'>SMART-TIME AI</h2>"
        f"<p style='color: #64748b; font-size: 14px; margin-top: 4px;'>Smart Timetable & Academic Management System</p>"
        f"</div>"
        f"<div style='border-top: 1px solid #f1f5f9; padding-top: 16px;'>"
        f"<p style='color: #334155; font-size: 15px;'>Thank you for registering with SMART-TIME AI. Please use the following one-time verification code to verify your email address:</p>"
        f"<div style='background-color: #f8fafc; border: 2px dashed #cbd5e1; padding: 18px; border-radius: 8px; text-align: center; margin: 24px 0;'>"
        f"<span style='font-size: 34px; font-weight: 700; letter-spacing: 8px; color: #1e293b;'>{otp}</span>"
        f"</div>"
        f"<p style='color: #64748b; font-size: 13px; margin-bottom: 8px;'>This code is valid for <strong>10 minutes</strong> and can only be used once.</p>"
        f"<p style='color: #94a3b8; font-size: 12px; margin-top: 24px; border-top: 1px solid #f1f5f9; padding-top: 12px;'>If you did not create an account, you can safely ignore this email.</p>"
        f"</div>"
        f"</div>"
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            html_message=html_message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@smarttime.ai"),
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception as e:
        logger.warning(f"Failed to dispatch OTP verification email: {e}")


def verify_student_otp(email: str, otp: str) -> tuple[bool, str]:
    """
    Verifies the provided 6-digit OTP for a student.
    Enforces expiry, one-time use, attempt counting (max 5), and secure hash matching.
    Activates the user account upon successful verification.
    """
    cleaned_email = normalize_email(email)
    try:
        user = User.objects.get(email__iexact=cleaned_email, role=User.Role.STUDENT)
    except User.DoesNotExist:
        return False, "Invalid email or verification code."

    if user.email_verified:
        return False, "Email is already verified. Please log in."

    verification = (
        EmailVerification.objects.filter(user=user, is_used=False)
        .order_by("-created_at")
        .first()
    )

    if not verification:
        return False, "No active verification code found. Please request a new code."

    if verification.attempts >= OTP_MAX_ATTEMPTS:
        verification.is_used = True
        verification.save(update_fields=["is_used"])
        return False, "Verification code has exceeded maximum attempts. Please request a new code."

    if timezone.now() > verification.expires_at:
        verification.is_used = True
        verification.save(update_fields=["is_used"])
        return False, "Verification code has expired. Please request a new code."

    if not check_password(otp, verification.otp_hash):
        verification.attempts += 1
        verification.save(update_fields=["attempts"])
        return False, "Invalid verification code."

    with transaction.atomic():
        verification.is_used = True
        verification.save(update_fields=["is_used"])
        user.email_verified = True
        user.is_active = True
        user.save(update_fields=["email_verified", "is_active", "updated_at"])

    return True, "Email verified successfully. You can now log in."


def resend_student_otp(email: str) -> None:
    """
    Generates and sends a new OTP for unverified student accounts.
    Invalidates previous OTPs and executes email sending post-transaction commit.
    Maintains anti-enumeration by silently returning on missing/ineligible users.
    """
    cleaned_email = normalize_email(email)
    try:
        user = User.objects.get(email__iexact=cleaned_email, role=User.Role.STUDENT)
        if not user.email_verified:
            with transaction.atomic():
                otp = generate_otp()
                create_email_verification(user, otp)
                transaction.on_commit(lambda: send_otp_email(user.email, otp))
    except User.DoesNotExist:
        pass  # Anti-enumeration
