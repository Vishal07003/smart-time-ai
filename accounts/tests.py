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


class TeacherProfileAPITests(APITestCase):
    """
    Tests for TeacherProfile CRUD and /me/ endpoints.
    """

    def setUp(self):
        from academics.models import Department
        from accounts.models import TeacherProfile

        self.dept = Department.objects.create(name="Computer Science", code="CS")
        self.staff_user = UserModel.objects.create_user(
            username="staff_admin",
            email="staff_admin@smarttime.ai",
            password="Password123!",
            role=User.Role.STAFF,
        )
        self.teacher_user = UserModel.objects.create_user(
            username="prof_john",
            email="john@smarttime.ai",
            password="Password123!",
            role=User.Role.TEACHER,
        )
        self.teacher_profile = TeacherProfile.objects.create(
            user=self.teacher_user,
            employee_code="EMP001",
            department=self.dept,
            designation="Professor",
        )
        self.student_user = UserModel.objects.create_user(
            username="student_sam",
            email="sam@smarttime.ai",
            password="Password123!",
            role=User.Role.STUDENT,
        )

        self.teachers_url = reverse("teachers:teacher_list_create")
        self.teacher_me_url = reverse("teachers:teacher_me")
        self.teacher_detail_url = reverse(
            "teachers:teacher_detail", kwargs={"pk": self.teacher_profile.pk}
        )

    def test_staff_create_teacher_success(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        payload = {
            "username": "prof_alice",
            "email": "alice@smarttime.ai",
            "password": "SecurePassword123!",
            "first_name": "Alice",
            "last_name": "Smith",
            "employee_code": "EMP002",
            "department": str(self.dept.id),
            "designation": "Assistant Professor",
        }
        response = self.client.post(self.teachers_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["teacher"]["user"]["role"], "TEACHER")
        self.assertNotIn("password", response.data["teacher"]["user"])

        # Check DB
        user = UserModel.objects.get(username="prof_alice")
        self.assertEqual(user.role, User.Role.TEACHER)
        self.assertEqual(user.teacher_profile.employee_code, "EMP002")

    def test_duplicate_employee_code_case_insensitive(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        payload = {
            "username": "prof_duplicate",
            "email": "dup@smarttime.ai",
            "password": "SecurePassword123!",
            "employee_code": "emp001",  # matches EMP001
            "department": str(self.dept.id),
            "designation": "Lecturer",
        }
        response = self.client.post(self.teachers_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("employee_code", response.data)

    def test_teacher_can_access_only_own_profile(self):
        refresh = RefreshToken.for_user(self.teacher_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # Teacher GET /me/
        res_me = self.client.get(self.teacher_me_url)
        self.assertEqual(res_me.status_code, status.HTTP_200_OK)
        self.assertEqual(res_me.data["teacher"]["employee_code"], "EMP001")

        # Teacher PATCH /me/
        res_patch = self.client.patch(
            self.teacher_me_url,
            {"first_name": "Jonathan"},
            format="json",
        )
        self.assertEqual(res_patch.status_code, status.HTTP_200_OK)
        self.teacher_user.refresh_from_db()
        self.assertEqual(self.teacher_user.first_name, "Jonathan")

        # Teacher cannot access staff CRUD
        res_list = self.client.get(self.teachers_url)
        self.assertEqual(res_list.status_code, status.HTTP_403_FORBIDDEN)


class StudentProfileAPITests(APITestCase):
    """
    Tests for StudentProfile CRUD and /me/ endpoints.
    """

    def setUp(self):
        from academics.models import (
            Department,
            Division,
            PracticalBatch,
            Program,
            Semester,
        )
        from accounts.models import StudentProfile

        self.dept = Department.objects.create(name="Computer Science", code="CS")
        self.prog = Program.objects.create(
            department=self.dept, name="B.Tech CS", code="BTECH_CS"
        )
        self.sem = Semester.objects.create(
            program=self.prog, number=1, academic_year="2024-2025"
        )
        self.div_a = Division.objects.create(semester=self.sem, name="A")
        self.div_b = Division.objects.create(semester=self.sem, name="B")
        self.batch_a1 = PracticalBatch.objects.create(division=self.div_a, name="A1")
        self.batch_b1 = PracticalBatch.objects.create(division=self.div_b, name="B1")

        self.staff_user = UserModel.objects.create_user(
            username="staff_admin2",
            email="staff2@smarttime.ai",
            password="Password123!",
            role=User.Role.STAFF,
        )
        self.student_user = UserModel.objects.create_user(
            username="student_bob",
            email="bob@smarttime.ai",
            password="Password123!",
            role=User.Role.STUDENT,
        )
        self.student_profile = StudentProfile.objects.create(
            user=self.student_user,
            student_code="STU001",
            roll_number="101",
            division=self.div_a,
            batch=self.batch_a1,
            admission_year=2024,
        )

        self.students_url = reverse("students:student_list_create")
        self.student_me_url = reverse("students:student_me")
        self.student_detail_url = reverse(
            "students:student_detail", kwargs={"pk": self.student_profile.pk}
        )

    def test_staff_create_student_success(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        payload = {
            "username": "student_charlie",
            "email": "charlie@smarttime.ai",
            "password": "SecurePassword123!",
            "first_name": "Charlie",
            "last_name": "Brown",
            "student_code": "STU002",
            "roll_number": "102",
            "division": str(self.div_a.id),
            "batch": str(self.batch_a1.id),
            "admission_year": 2024,
        }
        response = self.client.post(self.students_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["student"]["user"]["role"], "STUDENT")

        user = UserModel.objects.get(username="student_charlie")
        self.assertEqual(user.role, User.Role.STUDENT)
        self.assertEqual(user.student_profile.student_code, "STU002")

    def test_batch_must_belong_to_division(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # Batch B1 is in Division B, but division provided is Division A
        payload = {
            "username": "student_invalid_batch",
            "email": "inv_batch@smarttime.ai",
            "password": "SecurePassword123!",
            "student_code": "STU003",
            "roll_number": "103",
            "division": str(self.div_a.id),
            "batch": str(self.batch_b1.id),
            "admission_year": 2024,
        }
        response = self.client.post(self.students_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("batch", response.data)

    def test_same_roll_number_allowed_in_different_divisions(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # Student Bob has roll 101 in Division A. Creating roll 101 in Division B should succeed.
        payload = {
            "username": "student_div_b",
            "email": "div_b@smarttime.ai",
            "password": "SecurePassword123!",
            "student_code": "STU004",
            "roll_number": "101",
            "division": str(self.div_b.id),
            "admission_year": 2024,
        }
        response = self.client.post(self.students_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_duplicate_roll_number_in_same_division_fails(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # Roll 101 already in Division A
        payload = {
            "username": "student_duplicate_roll",
            "email": "dup_roll@smarttime.ai",
            "password": "SecurePassword123!",
            "student_code": "STU005",
            "roll_number": "101",
            "division": str(self.div_a.id),
            "admission_year": 2024,
        }
        response = self.client.post(self.students_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("roll_number", response.data)

    def test_student_can_access_only_own_profile(self):
        refresh = RefreshToken.for_user(self.student_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # Student GET /me/
        res_me = self.client.get(self.student_me_url)
        self.assertEqual(res_me.status_code, status.HTTP_200_OK)
        self.assertEqual(res_me.data["student"]["student_code"], "STU001")

        # Student cannot access staff CRUD
        res_list = self.client.get(self.students_url)
        self.assertEqual(res_list.status_code, status.HTTP_403_FORBIDDEN)

