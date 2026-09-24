from django.test import Client, TestCase
from django.urls import reverse
from accounts.models import User


class StaffWebAuthenticationTests(TestCase):
    """
    Focused Phase 16A Test Suite: Django Staff Web Authentication + Base Layout.
    Tests session-based authentication, role enforcement, CSRF protection,
    and non-regression with existing JWT REST APIs.
    """

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

        # 1. Test Users
        self.staff_user = User.objects.create_user(
            username="staff_admin",
            email="staff.admin@smarttime.ai",
            password="StaffPassword123!",
            role=User.Role.STAFF,
            first_name="Staff",
            last_name="Admin",
        )
        self.teacher_user = User.objects.create_user(
            username="teacher_user",
            email="teacher@smarttime.ai",
            password="TeacherPassword123!",
            role=User.Role.TEACHER,
            first_name="Prof",
            last_name="Teacher",
        )
        self.student_user = User.objects.create_user(
            username="student_user",
            email="student@smarttime.ai",
            password="StudentPassword123!",
            role=User.Role.STUDENT,
            first_name="John",
            last_name="Student",
        )

        # URLs
        self.login_url = reverse("staff:login")
        self.logout_url = reverse("staff:logout")
        self.dashboard_url = reverse("staff:dashboard")

    def test_01_get_staff_login_page_returns_200(self):
        """1. GET /staff/login/ returns 200 OK with login form."""
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staff Web Portal")
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_02_valid_staff_username_login_succeeds(self):
        """2. Valid Staff username login succeeds, sets session, and redirects to dashboard."""
        # Get CSRF token
        get_res = self.client.get(self.login_url)
        csrf_token = get_res.cookies["csrftoken"].value

        response = self.client.post(
            self.login_url,
            {
                "username": "staff_admin",
                "password": "StaffPassword123!",
                "csrfmiddlewaretoken": csrf_token,
            },
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.dashboard_url)

        # Verify session is authenticated
        self.assertTrue("_auth_user_id" in self.client.session)
        self.assertEqual(
            str(self.client.session["_auth_user_id"]),
            str(self.staff_user.id),
        )

    def test_03_valid_staff_email_login_succeeds(self):
        """3. Valid Staff email login succeeds and creates a valid session."""
        get_res = self.client.get(self.login_url)
        csrf_token = get_res.cookies["csrftoken"].value

        response = self.client.post(
            self.login_url,
            {
                "username": "staff.admin@smarttime.ai",
                "password": "StaffPassword123!",
                "csrfmiddlewaretoken": csrf_token,
            },
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.dashboard_url)
        self.assertTrue("_auth_user_id" in self.client.session)

    def test_04_invalid_password_fails(self):
        """4. Invalid password fails with controlled error and does not create session."""
        get_res = self.client.get(self.login_url)
        csrf_token = get_res.cookies["csrftoken"].value

        response = self.client.post(
            self.login_url,
            {
                "username": "staff_admin",
                "password": "WrongPassword!",
                "csrfmiddlewaretoken": csrf_token,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid username/email or password.")
        self.assertFalse("_auth_user_id" in self.client.session)

    def test_05_teacher_cannot_access_staff_login_or_session(self):
        """5. Teacher credentials in staff login are rejected without creating session."""
        get_res = self.client.get(self.login_url)
        csrf_token = get_res.cookies["csrftoken"].value

        response = self.client.post(
            self.login_url,
            {
                "username": "teacher_user",
                "password": "TeacherPassword123!",
                "csrfmiddlewaretoken": csrf_token,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Access restricted. Only staff members can log into the staff portal.")
        self.assertFalse("_auth_user_id" in self.client.session)

    def test_06_student_cannot_access_staff_login_or_session(self):
        """6. Student credentials in staff login are rejected without creating session."""
        get_res = self.client.get(self.login_url)
        csrf_token = get_res.cookies["csrftoken"].value

        response = self.client.post(
            self.login_url,
            {
                "username": "student_user",
                "password": "StudentPassword123!",
                "csrfmiddlewaretoken": csrf_token,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Access restricted. Only staff members can log into the staff portal.")
        self.assertFalse("_auth_user_id" in self.client.session)

    def test_07_unauthenticated_user_accessing_staff_root_redirects_to_login(self):
        """7. Unauthenticated user accessing /staff/ is redirected to /staff/login/?next=/staff/."""
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(self.login_url))

    def test_08_authenticated_staff_can_access_staff_root(self):
        """8. Authenticated Staff user can access /staff/ successfully."""
        self.client.force_login(self.staff_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard")
        self.assertContains(response, "Staff workspace")
        self.assertContains(response, "Staff Admin")

    def test_09_authenticated_teacher_cannot_access_staff_root(self):
        """9. Authenticated Teacher accessing /staff/ is forbidden (403)."""
        self.client.force_login(self.teacher_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 403)

    def test_10_authenticated_student_cannot_access_staff_root(self):
        """10. Authenticated Student accessing /staff/ is forbidden (403)."""
        self.client.force_login(self.student_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 403)

    def test_11_post_logout_clears_session(self):
        """11. POST /staff/logout/ clears session and redirects to login."""
        self.client.force_login(self.staff_user)
        self.assertTrue("_auth_user_id" in self.client.session)

        # Get CSRF cookie for POST
        get_res = self.client.get(self.dashboard_url)
        csrf_token = get_res.cookies.get("csrftoken")
        csrf_val = csrf_token.value if csrf_token else ""

        response = self.client.post(
            self.logout_url,
            {"csrfmiddlewaretoken": csrf_val},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.login_url)
        self.assertFalse("_auth_user_id" in self.client.session)

    def test_12_csrf_protection_remains_enforced(self):
        """12. POST without CSRF token fails with 403 Forbidden."""
        client_no_csrf = Client(enforce_csrf_checks=True)
        response = client_no_csrf.post(
            self.login_url,
            {
                "username": "staff_admin",
                "password": "StaffPassword123!",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_13_authenticated_staff_visiting_login_redirects_to_dashboard(self):
        """13. Authenticated Staff user opening /staff/login/ is redirected to /staff/."""
        self.client.force_login(self.staff_user)
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.dashboard_url)

    def test_14_existing_jwt_api_authentication_still_works(self):
        """14. Existing REST API JWT login endpoint continues to operate identically."""
        from rest_framework.test import APIClient
        api_client = APIClient()

        # Login via REST API with username
        res_username = api_client.post(
            "/api/v1/auth/login/",
            {"username": "staff_admin", "password": "StaffPassword123!"},
            format="json",
        )
        self.assertEqual(res_username.status_code, 200)
        self.assertIn("tokens", res_username.data)
        self.assertIn("access", res_username.data["tokens"])
        self.assertIn("refresh", res_username.data["tokens"])

        # Login via REST API with email
        res_email = api_client.post(
            "/api/v1/auth/login/",
            {"username": "staff.admin@smarttime.ai", "password": "StaffPassword123!"},
            format="json",
        )
        self.assertEqual(res_email.status_code, 200)
        self.assertIn("tokens", res_email.data)
