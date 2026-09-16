import uuid
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.models import User
from accounts.permissions import (
    IsStaffOrTeacher,
    IsStaffRole,
    IsStudentRole,
    IsTeacherRole,
)
from accounts.validators import (
    normalize_email,
    normalize_indian_phone,
    normalize_name,
    normalize_username,
    validate_email_custom,
    validate_indian_phone,
    validate_name_custom,
    validate_role_custom,
    validate_username_custom,
)

UserModel = get_user_model()


class UnitValidatorTests(APITestCase):
    """
    Direct unit tests for accounts/validators.py functions.
    """

    def test_valid_email(self):
        valid_emails = [
            "student@smarttime.ai",
            "john.doe@example.com",
            "user_123@sub.domain.co.in",
        ]
        for email in valid_emails:
            self.assertEqual(validate_email_custom(email), email.lower().strip())

    def test_invalid_email(self):
        invalid_emails = [
            "",
            "   ",
            "not-an-email",
            "@missinguser.com",
            "user@",
            "user@.com",
            "user@domain",
            "user name@domain.com",
        ]
        for email in invalid_emails:
            with self.assertRaises(ValidationError):
                validate_email_custom(email)

    def test_email_whitespace_and_normalization(self):
        raw = "  STUDENT@SmartTime.AI  "
        self.assertEqual(normalize_email(raw), "student@smarttime.ai")
        self.assertEqual(validate_email_custom(raw), "student@smarttime.ai")

    def test_valid_indian_phone(self):
        valid_phones = [
            ("9876543210", "9876543210"),
            ("+919876543210", "9876543210"),
            ("91 9876543210", "9876543210"),
            ("09876543210", "9876543210"),
            ("8123456789", "8123456789"),
            ("7123456789", "7123456789"),
            ("6123456789", "6123456789"),
            ("+91 (987) 654-3210", "9876543210"),
        ]
        for raw, expected in valid_phones:
            self.assertEqual(validate_indian_phone(raw), expected)

    def test_invalid_phone(self):
        invalid_phones = [
            "1234567890",  # starts with 1
            "0000000000",  # all zeros
            "9999999999",  # identical repeated
            "98765",  # too short
            "987654321000",  # too long
            "98765abcde",  # letters
            "98765@#$10",  # special characters
        ]
        for phone in invalid_phones:
            with self.assertRaises(ValidationError):
                validate_indian_phone(phone)

    def test_phone_with_letters(self):
        with self.assertRaises(ValidationError):
            validate_indian_phone("98765abcd0")

    def test_phone_with_wrong_starting_digit(self):
        for invalid_start in ["1987654321", "2987654321", "3987654321", "4987654321", "5987654321"]:
            with self.assertRaises(ValidationError):
                validate_indian_phone(invalid_start)

    def test_username_validation(self):
        valid_usernames = ["user_1", "john.doe", "Student99", "admin_user.01"]
        for u in valid_usernames:
            self.assertEqual(validate_username_custom(u), u)

        invalid_usernames = [
            "ab",  # too short (<3)
            "a" * 31,  # too long (>30)
            "user name",  # contains spaces
            "user@123",  # special char @
            "user#tag",  # special char #
            "user-dash",  # hyphen not allowed (only letters, numbers, _, .)
            "",  # empty
            "   ",  # whitespace
        ]
        for u in invalid_usernames:
            with self.assertRaises(ValidationError):
                validate_username_custom(u)

    def test_first_last_name_validation(self):
        valid_names = ["John", "Mary Jane", "O'Connor", "Jean-Luc"]
        for name in valid_names:
            self.assertEqual(validate_name_custom(name), normalize_name(name))

        invalid_names = [
            "John123",  # contains numbers
            "John@Doe",  # special characters
            "A" * 51,  # exceeds 50 chars
        ]
        for name in invalid_names:
            with self.assertRaises(ValidationError):
                validate_name_custom(name)

    def test_whitespace_only_values(self):
        self.assertEqual(validate_name_custom("   "), "")
        self.assertEqual(validate_indian_phone("   "), "")

    def test_invalid_role(self):
        for invalid_role in ["ADMIN", "MANAGER", "SUPERUSER", "unknown", ""]:
            with self.assertRaises(ValidationError):
                validate_role_custom(invalid_role)


class UserModelValidationTests(APITestCase):
    """
    Model-level validation and constraint tests.
    """

    def test_create_valid_user(self):
        user = UserModel.objects.create_user(
            username="student_valid",
            email="STUDENT_VALID@SmartTime.AI",
            password="SecurePassword123!",
            first_name="  Alex  ",
            last_name="  Smith  ",
            phone="+91 9876543210",
            role=User.Role.STUDENT,
        )
        self.assertEqual(user.email, "student_valid@smarttime.ai")
        self.assertEqual(user.username, "student_valid")
        self.assertEqual(user.first_name, "Alex")
        self.assertEqual(user.last_name, "Smith")
        self.assertEqual(user.phone, "9876543210")
        self.assertEqual(user.role, "STUDENT")

    def test_duplicate_email(self):
        UserModel.objects.create_user(
            username="user_a",
            email="duplicate@smarttime.ai",
            password="SecurePassword123!",
        )
        with self.assertRaises((ValidationError, IntegrityError)):
            UserModel.objects.create_user(
                username="user_b",
                email="duplicate@smarttime.ai",
                password="SecurePassword123!",
            )

    def test_duplicate_email_with_different_case(self):
        UserModel.objects.create_user(
            username="user_c",
            email="TestUser@SmartTime.AI",
            password="SecurePassword123!",
        )
        with self.assertRaises((ValidationError, IntegrityError)):
            UserModel.objects.create_user(
                username="user_d",
                email="testuser@smarttime.ai",
                password="SecurePassword123!",
            )

    def test_duplicate_username_with_different_case(self):
        UserModel.objects.create_user(
            username="SmartUser",
            email="smartuser1@smarttime.ai",
            password="SecurePassword123!",
        )
        with self.assertRaises((ValidationError, IntegrityError)):
            UserModel.objects.create_user(
                username="smartuser",
                email="smartuser2@smarttime.ai",
                password="SecurePassword123!",
            )

    def test_create_superuser_defaults_to_staff(self):
        superuser = UserModel.objects.create_superuser(
            username="super_staff",
            email="super_staff@smarttime.ai",
            password="StaffAdminPass123!",
        )
        self.assertEqual(superuser.role, User.Role.STAFF)
        self.assertTrue(superuser.is_staff)
        self.assertTrue(superuser.is_superuser)


class AuthAPITests(APITestCase):
    """
    API endpoint validation and security tests.
    """

    def setUp(self):
        self.password = "ComplexPass123!"
        self.staff_user = UserModel.objects.create_user(
            username="staff_user",
            email="staff@smarttime.ai",
            password=self.password,
            first_name="Staff",
            last_name="Member",
            phone="9876543210",
            role=User.Role.STAFF,
        )
        self.teacher_user = UserModel.objects.create_user(
            username="teacher_user",
            email="teacher@smarttime.ai",
            password=self.password,
            first_name="Teacher",
            last_name="One",
            phone="8765432109",
            role=User.Role.TEACHER,
        )
        self.student_user = UserModel.objects.create_user(
            username="student_user",
            email="student@smarttime.ai",
            password=self.password,
            first_name="Student",
            last_name="One",
            phone="7654321098",
            role=User.Role.STUDENT,
        )
        self.inactive_user = UserModel.objects.create_user(
            username="inactive_user",
            email="inactive@smarttime.ai",
            password=self.password,
            is_active=False,
        )

        self.login_url = reverse("accounts:login")
        self.refresh_url = reverse("accounts:token_refresh")
        self.logout_url = reverse("accounts:logout")
        self.me_url = reverse("accounts:me")
        self.change_password_url = reverse("accounts:change_password")
        self.forgot_password_url = reverse("accounts:forgot_password")
        self.reset_password_url = reverse("accounts:reset_password")

    def test_login_success_with_username_and_email(self):
        # Login with username
        res1 = self.client.post(
            self.login_url,
            {"username": "staff_user", "password": self.password},
            format="json",
        )
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res1.data["user"]["role"], "STAFF")

        # Login with email
        res2 = self.client.post(
            self.login_url,
            {"username": "STAFF@smarttime.ai", "password": self.password},
            format="json",
        )
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["user"]["role"], "STAFF")

    def test_password_never_returned_in_api(self):
        res = self.client.post(
            self.login_url,
            {"username": "staff_user", "password": self.password},
            format="json",
        )
        user_data = res.data["user"]
        self.assertNotIn("password", user_data)
        self.assertNotIn("password_hash", user_data)

        # Also check /me/ endpoint
        access_token = res.data["tokens"]["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        me_res = self.client.get(self.me_url)
        self.assertNotIn("password", me_res.data["user"])

    def test_login_invalid_credentials_returns_generic_error(self):
        response = self.client.post(
            self.login_url,
            {"username": "non_existent_user", "password": "WrongPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_inactive_user(self):
        response = self.client.post(
            self.login_url,
            {"username": "inactive_user", "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_me_cannot_change_role(self):
        refresh = RefreshToken.for_user(self.student_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # Attempt to escalate role to STAFF
        response = self.client.patch(
            self.me_url,
            {"role": "STAFF"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.student_user.refresh_from_db()
        self.assertEqual(self.student_user.role, User.Role.STUDENT)

    def test_me_cannot_change_is_active(self):
        refresh = RefreshToken.for_user(self.student_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        response = self.client.patch(
            self.me_url,
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.student_user.refresh_from_db()
        self.assertTrue(self.student_user.is_active)

    def test_update_profile_validation(self):
        refresh = RefreshToken.for_user(self.teacher_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # Valid update
        res = self.client.patch(
            self.me_url,
            {
                "first_name": "  Professor  ",
                "last_name": "  Oak  ",
                "phone": "+91 9988776655",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["user"]["first_name"], "Professor")
        self.assertEqual(res.data["user"]["last_name"], "Oak")
        self.assertEqual(res.data["user"]["phone"], "9988776655")

        # Invalid phone update
        res_err = self.client.patch(
            self.me_url,
            {"phone": "invalid_number_123"},
            format="json",
        )
        self.assertEqual(res_err.status_code, status.HTTP_400_BAD_REQUEST)

        # Invalid name update (numbers in name)
        res_name_err = self.client.patch(
            self.me_url,
            {"first_name": "Professor123"},
            format="json",
        )
        self.assertEqual(res_name_err.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_password_weak_and_similar(self):
        refresh = RefreshToken.for_user(self.student_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # 1. Weak password (too short)
        res_short = self.client.post(
            self.change_password_url,
            {
                "old_password": self.password,
                "new_password": "short",
                "confirm_password": "short",
            },
            format="json",
        )
        self.assertEqual(res_short.status_code, status.HTTP_400_BAD_REQUEST)

        # 2. Common password
        res_common = self.client.post(
            self.change_password_url,
            {
                "old_password": self.password,
                "new_password": "password123",
                "confirm_password": "password123",
            },
            format="json",
        )
        self.assertEqual(res_common.status_code, status.HTTP_400_BAD_REQUEST)

        # 3. Similar to username
        res_similar = self.client.post(
            self.change_password_url,
            {
                "old_password": self.password,
                "new_password": "student_user123!",
                "confirm_password": "student_user123!",
            },
            format="json",
        )
        self.assertEqual(res_similar.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_password_success(self):
        refresh = RefreshToken.for_user(self.student_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        new_pwd = "StrongNewSecretPwd456!"
        res = self.client.post(
            self.change_password_url,
            {
                "old_password": self.password,
                "new_password": new_pwd,
                "confirm_password": new_pwd,
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])

        # Login works with new password
        login_res = self.client.post(
            self.login_url,
            {"username": "student_user", "password": new_pwd},
            format="json",
        )
        self.assertEqual(login_res.status_code, status.HTTP_200_OK)

    def test_forgot_and_reset_password_security(self):
        # Forgot password for non-existent email returns same 200 OK (anti-enumeration)
        res_fake = self.client.post(
            self.forgot_password_url,
            {"email": "nonexistent@smarttime.ai"},
            format="json",
        )
        self.assertEqual(res_fake.status_code, status.HTTP_200_OK)
        self.assertNotIn("data", res_fake.data)

        # Forgot password for existing email returns same 200 OK
        res_real = self.client.post(
            self.forgot_password_url,
            {"email": "staff@smarttime.ai"},
            format="json",
        )
        self.assertEqual(res_real.status_code, status.HTTP_200_OK)
        self.assertNotIn("data", res_real.data)

        # Reset password with token
        uid = urlsafe_base64_encode(force_bytes(self.staff_user.pk))
        token = default_token_generator.make_token(self.staff_user)

        new_pwd = "ResetSecurePassword999!"
        reset_res = self.client.post(
            self.reset_password_url,
            {
                "uid": uid,
                "token": token,
                "new_password": new_pwd,
                "confirm_password": new_pwd,
            },
            format="json",
        )
        self.assertEqual(reset_res.status_code, status.HTTP_200_OK)

        # Login with newly reset password
        login_res = self.client.post(
            self.login_url,
            {"username": "staff_user", "password": new_pwd},
            format="json",
        )
        self.assertEqual(login_res.status_code, status.HTTP_200_OK)

    def test_permissions_classes(self):
        class MockRequest:
            def __init__(self, user):
                self.user = user

        staff_req = MockRequest(self.staff_user)
        teacher_req = MockRequest(self.teacher_user)
        student_req = MockRequest(self.student_user)

        self.assertTrue(IsStaffRole().has_permission(staff_req, None))
        self.assertFalse(IsStaffRole().has_permission(teacher_req, None))
        self.assertFalse(IsStaffRole().has_permission(student_req, None))

        self.assertTrue(IsTeacherRole().has_permission(teacher_req, None))
        self.assertFalse(IsTeacherRole().has_permission(staff_req, None))

        self.assertTrue(IsStudentRole().has_permission(student_req, None))
        self.assertFalse(IsStudentRole().has_permission(teacher_req, None))

        self.assertTrue(IsStaffOrTeacher().has_permission(staff_req, None))
        self.assertTrue(IsStaffOrTeacher().has_permission(teacher_req, None))
        self.assertFalse(IsStaffOrTeacher().has_permission(student_req, None))


class StudentRegistrationAPITests(APITestCase):
    """
    Tests for POST /api/v1/auth/student-register/
    """

    def setUp(self):
        self.register_url = reverse("accounts:student_register")
        self.valid_payload = {
            "username": "fresh_student",
            "email": "fresh_student@smarttime.ai",
            "password": "StrongStudentPass123!",
            "confirm_password": "StrongStudentPass123!",
        }

    def test_successful_student_registration(self):
        response = self.client.post(self.register_url, self.valid_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["role"], "STUDENT")
        self.assertFalse(response.data["user"]["email_verified"])
        self.assertFalse(response.data["user"]["is_active"])

        # Never return password, hash, or OTP
        self.assertNotIn("password", response.data["user"])
        self.assertNotIn("password_hash", response.data["user"])
        self.assertNotIn("otp", response.data)

        # Verify DB state
        user = User.objects.get(username="fresh_student")
        self.assertEqual(user.email, "fresh_student@smarttime.ai")
        self.assertEqual(user.role, User.Role.STUDENT)
        self.assertFalse(user.email_verified)
        self.assertFalse(user.is_active)
        self.assertTrue(user.check_password("StrongStudentPass123!"))

        # Verify EmailVerification record created
        verification = user.email_verifications.first()
        self.assertIsNotNone(verification)
        self.assertFalse(verification.is_used)
        self.assertEqual(verification.attempts, 0)
        self.assertNotEqual(verification.otp_hash, "")

    def test_registration_rejects_role_field(self):
        # Attempt to inject role=STAFF
        payload_staff = self.valid_payload.copy()
        payload_staff["role"] = "STAFF"
        res_staff = self.client.post(self.register_url, payload_staff, format="json")
        self.assertEqual(res_staff.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("role", res_staff.data)

        # Attempt to inject role=TEACHER
        payload_teacher = self.valid_payload.copy()
        payload_teacher["role"] = "TEACHER"
        res_teacher = self.client.post(self.register_url, payload_teacher, format="json")
        self.assertEqual(res_teacher.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("role", res_teacher.data)

    def test_registration_duplicate_email_case_insensitive(self):
        User.objects.create_user(
            username="existing_user",
            email="fresh_student@smarttime.ai",
            password="SomePassword123!",
        )
        payload = self.valid_payload.copy()
        payload["email"] = "FRESH_STUDENT@SMARTTIME.AI"
        payload["username"] = "different_user"
        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_registration_duplicate_username_case_insensitive(self):
        User.objects.create_user(
            username="Fresh_Student",
            email="other@smarttime.ai",
            password="SomePassword123!",
        )
        payload = self.valid_payload.copy()
        payload["username"] = "fresh_student"
        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", response.data)

    def test_registration_invalid_email(self):
        payload = self.valid_payload.copy()
        payload["email"] = "invalid-email-address"
        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_registration_invalid_username(self):
        payload = self.valid_payload.copy()
        payload["username"] = "ab"  # Too short (<3)
        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_registration_password_mismatch(self):
        payload = self.valid_payload.copy()
        payload["confirm_password"] = "MismatchPassword123!"
        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("confirm_password", response.data)

    def test_registration_weak_password(self):
        payload = self.valid_payload.copy()
        payload["password"] = "short"
        payload["confirm_password"] = "short"
        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class EmailOTPVerificationAPITests(APITestCase):
    """
    Tests for POST /api/v1/auth/student-verify-email/ and POST /api/v1/auth/student-resend-otp/
    """

    def setUp(self):
        from datetime import timedelta
        from django.contrib.auth.hashers import make_password
        from django.utils import timezone
        from accounts.models import EmailVerification

        self.verify_url = reverse("accounts:student_verify_email")
        self.resend_url = reverse("accounts:student_resend_otp")

        self.student = User.objects.create_user(
            username="unverified_student",
            email="unverified@smarttime.ai",
            password="SecurePass123!",
            role=User.Role.STUDENT,
            email_verified=False,
            is_active=False,
        )
        self.plain_otp = "482913"
        self.verification = EmailVerification.objects.create(
            user=self.student,
            otp_hash=make_password(self.plain_otp),
            expires_at=timezone.now() + timedelta(minutes=10),
            is_used=False,
            attempts=0,
        )

    def test_successful_otp_verification(self):
        response = self.client.post(
            self.verify_url,
            {"email": "unverified@smarttime.ai", "otp": self.plain_otp},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        # Check user is now verified and active
        self.student.refresh_from_db()
        self.assertTrue(self.student.email_verified)
        self.assertTrue(self.student.is_active)

        # Check verification is marked used
        self.verification.refresh_from_db()
        self.assertTrue(self.verification.is_used)

    def test_otp_verification_case_insensitive_email(self):
        response = self.client.post(
            self.verify_url,
            {"email": "UNVERIFIED@SMARTTIME.AI", "otp": self.plain_otp},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.student.refresh_from_db()
        self.assertTrue(self.student.email_verified)

    def test_wrong_otp_increments_attempts(self):
        response = self.client.post(
            self.verify_url,
            {"email": "unverified@smarttime.ai", "otp": "999999"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])

        self.verification.refresh_from_db()
        self.assertEqual(self.verification.attempts, 1)
        self.assertFalse(self.verification.is_used)

        self.student.refresh_from_db()
        self.assertFalse(self.student.email_verified)

    def test_expired_otp_fails(self):
        from datetime import timedelta
        from django.utils import timezone

        self.verification.expires_at = timezone.now() - timedelta(minutes=1)
        self.verification.save()

        response = self.client.post(
            self.verify_url,
            {"email": "unverified@smarttime.ai", "otp": self.plain_otp},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.student.refresh_from_db()
        self.assertFalse(self.student.email_verified)

    def test_reused_otp_fails(self):
        self.verification.is_used = True
        self.verification.save()

        response = self.client.post(
            self.verify_url,
            {"email": "unverified@smarttime.ai", "otp": self.plain_otp},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_otp_format(self):
        # Letters or length != 6
        for invalid_otp in ["12345", "1234567", "abcdef", "12a456"]:
            response = self.client.post(
                self.verify_url,
                {"email": "unverified@smarttime.ai", "otp": invalid_otp},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_max_attempts_exceeded_invalidates_otp(self):
        self.verification.attempts = 5
        self.verification.save()

        response = self.client.post(
            self.verify_url,
            {"email": "unverified@smarttime.ai", "otp": self.plain_otp},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.verification.refresh_from_db()
        self.assertTrue(self.verification.is_used)

    def test_already_verified_account_reverification_rejected(self):
        self.student.email_verified = True
        self.student.is_active = True
        self.student.save()

        response = self.client.post(
            self.verify_url,
            {"email": "unverified@smarttime.ai", "otp": self.plain_otp},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_resend_otp_invalidates_previous_otp(self):
        resend_res = self.client.post(
            self.resend_url,
            {"email": "unverified@smarttime.ai"},
            format="json",
        )
        self.assertEqual(resend_res.status_code, status.HTTP_200_OK)
        self.assertTrue(resend_res.data["success"])

        # Previous verification must now be is_used=True
        self.verification.refresh_from_db()
        self.assertTrue(self.verification.is_used)

        # Old OTP no longer works
        old_otp_res = self.client.post(
            self.verify_url,
            {"email": "unverified@smarttime.ai", "otp": self.plain_otp},
            format="json",
        )
        self.assertEqual(old_otp_res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_resend_otp_anti_enumeration(self):
        # Non-existent email returns same 200 OK generic response
        res = self.client.post(
            self.resend_url,
            {"email": "nonexistent@smarttime.ai"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])


class LoginIdentifierAPITests(APITestCase):
    """
    Tests for POST /api/v1/auth/login/ supporting identifier (email or username).
    """

    def setUp(self):
        self.login_url = reverse("accounts:login")
        self.password = "SecurePassword123!"

        self.student_user = User.objects.create_user(
            username="john_student",
            email="john@smarttime.ai",
            password=self.password,
            role=User.Role.STUDENT,
            email_verified=True,
            is_active=True,
        )
        self.unverified_student = User.objects.create_user(
            username="unverified_bob",
            email="bob@smarttime.ai",
            password=self.password,
            role=User.Role.STUDENT,
            email_verified=False,
            is_active=True,
        )
        self.staff_user = User.objects.create_user(
            username="jane_staff",
            email="jane@smarttime.ai",
            password=self.password,
            role=User.Role.STAFF,
            email_verified=True,
            is_active=True,
        )

    def test_login_with_email_identifier(self):
        response = self.client.post(
            self.login_url,
            {"identifier": "john@smarttime.ai", "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["username"], "john_student")
        self.assertIn("access", response.data["tokens"])
        self.assertIn("refresh", response.data["tokens"])

    def test_login_with_username_identifier(self):
        response = self.client.post(
            self.login_url,
            {"identifier": "john_student", "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["email"], "john@smarttime.ai")

    def test_login_email_case_insensitivity(self):
        response = self.client.post(
            self.login_url,
            {"identifier": "JOHN@SmartTime.AI", "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_login_username_case_insensitivity(self):
        response = self.client.post(
            self.login_url,
            {"identifier": "JOHN_STUDENT", "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unverified_student_cannot_login(self):
        response = self.client.post(
            self.login_url,
            {"identifier": "bob@smarttime.ai", "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Please verify your email", str(response.data))

    def test_wrong_password_generic_error(self):
        response = self.client.post(
            self.login_url,
            {"identifier": "john@smarttime.ai", "password": "WrongPassword999!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid credentials", str(response.data))

    def test_unknown_identifier_generic_error(self):
        response = self.client.post(
            self.login_url,
            {"identifier": "nobody@smarttime.ai", "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid credentials", str(response.data))

    def test_staff_login_unrestricted(self):
        response = self.client.post(
            self.login_url,
            {"identifier": "jane@smarttime.ai", "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["role"], "STAFF")


class ServicesUnitTests(APITestCase):
    """
    Unit tests for accounts/services.py
    """

    def test_generate_otp_is_6_digits(self):
        from accounts.services import generate_otp

        for _ in range(50):
            otp = generate_otp()
            self.assertEqual(len(otp), 6)
            self.assertTrue(otp.isdigit())
            self.assertTrue(100000 <= int(otp) <= 999999)

    def test_otp_hash_storage_security(self):
        from django.contrib.auth.hashers import check_password
        from accounts.services import create_email_verification

        user = User.objects.create_user(
            username="service_test_user",
            email="service_test@smarttime.ai",
            password="Password123!",
        )
        otp = "654321"
        verification = create_email_verification(user, otp)

        # Plain text OTP must NOT be stored
        self.assertNotEqual(verification.otp_hash, otp)
        self.assertTrue(check_password(otp, verification.otp_hash))

