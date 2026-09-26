from unittest.mock import patch
from django.test import Client, TestCase
from django.urls import reverse
from accounts.models import User, TeacherProfile

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


class StaffDashboardWebTests(TestCase):
    """
    Focused Phase 16B Test Suite: Staff Dashboard Functional Integration.
    Tests dynamic data binding from StaffDashboardService, hero personalization,
    summary cards, today's timetable classifications, conflict mismatch handling,
    recent activity, empty states, security boundaries, and non-regression of REST API.
    """

    def setUp(self):
        from unittest.mock import patch
        self.client = Client()

        # Users
        self.staff_user = User.objects.create_user(
            username="staff_coordinator",
            email="coordinator@smarttime.ai",
            password="SecureStaffPass123!",
            role=User.Role.STAFF,
            first_name="Eleanor",
            last_name="Vance",
            phone="9876543210",
        )
        self.teacher_user = User.objects.create_user(
            username="teacher_smith",
            email="smith@smarttime.ai",
            password="SecureTeacherPass123!",
            role=User.Role.TEACHER,
            first_name="Alan",
            last_name="Smith",
            phone="9876543211",
        )
        self.student_user = User.objects.create_user(
            username="student_clara",
            email="clara@smarttime.ai",
            password="SecureStudentPass123!",
            role=User.Role.STUDENT,
            first_name="Clara",
            last_name="Oswald",
            phone="9876543212",
        )

        self.dashboard_url = reverse("staff:dashboard")
        self.login_url = reverse("staff:login")
        self.rest_dashboard_url = "/api/v1/staff/dashboard/"

    def test_01_staff_can_access_dashboard(self):
        """1. Authenticated Staff can access /staff/ with HTTP 200 OK."""
        self.client.force_login(self.staff_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "staff/dashboard.html")
        self.assertIn("dashboard", response.context)
        self.assertIn("summary", response.context)

    def test_02_unauthenticated_user_redirects_to_staff_login(self):
        """2. Unauthenticated request to /staff/ redirects to /staff/login/?next=/staff/."""
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(self.login_url))
        self.assertIn("next=/staff/", response.url)

    def test_03_teacher_receives_403_forbidden(self):
        """3. Authenticated Teacher receives 403 Forbidden on /staff/."""
        self.client.force_login(self.teacher_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 403)

    def test_04_student_receives_403_forbidden(self):
        """4. Authenticated Student receives 403 Forbidden on /staff/."""
        self.client.force_login(self.student_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 403)

    def test_05_staff_name_rendered_dynamically(self):
        """5. Staff full name is rendered dynamically in the Hero banner."""
        self.client.force_login(self.staff_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Eleanor Vance")
        self.assertContains(response, "System Online")

    @patch("academics.services.staff_dashboard_service.StaffDashboardService.get_dashboard_data")
    def test_06_summary_metrics_rendered_from_service(self, mock_service):
        """6. Summary metrics on 6 cards match the exact values from StaffDashboardService."""
        mock_service.return_value = {
            "summary": {
                "active_teachers_count": 42,
                "active_students_count": 1280,
                "today_classes_count": 36,
                "unresolved_conflicts_count": 7,
                "pending_leaves_count": 5,
                "pending_substitutions_count": 3,
            },
            "today": {
                "day": "MONDAY",
                "date": "2026-09-28",
                "current_time": "10:30",
                "classes": [],
                "current": [],
                "upcoming": [],
                "completed": [],
            },
            "conflicts": [],
            "teacher_leaves": [],
            "substitutions": [],
            "recent_changes": [],
            "quick_actions": {},
        }

        self.client.force_login(self.staff_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        # Check summary numbers rendered in HTML
        self.assertContains(response, "42")
        self.assertContains(response, "1280")
        self.assertContains(response, "36")
        self.assertContains(response, "7")
        self.assertContains(response, "5")
        self.assertContains(response, "3")

    @patch("academics.services.staff_dashboard_service.StaffDashboardService.get_dashboard_data")
    def test_07_todays_classes_rendered_from_service(self, mock_service):
        """7. Today's classes render subject, code, teacher, division, room, and time."""
        sample_slot = {
            "id": "slot-uuid-1",
            "timetable_id": "tt-uuid-1",
            "subject": {"id": "sub-1", "name": "Distributed Systems", "code": "CS801"},
            "teacher": {"id": "t-1", "name": "Prof. Alan Smith", "employee_code": "EMP001"},
            "division": {"id": "div-1", "name": "Division B"},
            "batch": {"id": "b-1", "name": "Batch B1"},
            "classroom": {"id": "cr-1", "name": "Hall-101", "room_number": "101"},
            "laboratory": None,
            "day": "MONDAY",
            "start_time": "09:00",
            "end_time": "10:00",
            "session_type": "LECTURE",
            "status": "SCHEDULED",
        }
        mock_service.return_value = {
            "summary": {
                "active_teachers_count": 10,
                "active_students_count": 200,
                "today_classes_count": 1,
                "unresolved_conflicts_count": 0,
                "pending_leaves_count": 0,
                "pending_substitutions_count": 0,
            },
            "today": {
                "day": "MONDAY",
                "date": "2026-09-28",
                "current_time": "08:30",
                "classes": [sample_slot],
                "current": [],
                "upcoming": [sample_slot],
                "completed": [],
            },
            "conflicts": [],
            "teacher_leaves": [],
            "substitutions": [],
            "recent_changes": [],
            "quick_actions": {},
        }

        self.client.force_login(self.staff_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Distributed Systems")
        self.assertContains(response, "CS801")
        self.assertContains(response, "Prof. Alan Smith")
        self.assertContains(response, "Division B")
        self.assertContains(response, "Batch B1")
        self.assertContains(response, "101")
        self.assertContains(response, "09:00 - 10:00")

    @patch("academics.services.staff_dashboard_service.StaffDashboardService.get_dashboard_data")
    def test_08_current_upcoming_completed_classification_renders_correctly(self, mock_service):
        """8. Current, upcoming, and completed classes render distinct highlight/status badges."""
        current_slot = {
            "id": "slot-curr",
            "timetable_id": "tt-1",
            "subject": {"id": "s1", "name": "Current Cloud Computing", "code": "CS701"},
            "teacher": {"id": "t1", "name": "Prof. Current"},
            "division": {"id": "d1", "name": "Div A"},
            "batch": None,
            "classroom": {"room_number": "201"},
            "laboratory": None,
            "start_time": "10:00",
            "end_time": "11:00",
            "session_type": "LECTURE",
            "status": "IN_PROGRESS",
        }
        completed_slot = {
            "id": "slot-comp",
            "timetable_id": "tt-1",
            "subject": {"id": "s2", "name": "Completed Data Mining", "code": "CS702"},
            "teacher": {"id": "t2", "name": "Prof. Past"},
            "division": {"id": "d1", "name": "Div A"},
            "batch": None,
            "classroom": {"room_number": "202"},
            "laboratory": None,
            "start_time": "08:00",
            "end_time": "09:00",
            "session_type": "LECTURE",
            "status": "COMPLETED",
        }
        upcoming_slot = {
            "id": "slot-up",
            "timetable_id": "tt-1",
            "subject": {"id": "s3", "name": "Upcoming Artificial Intelligence", "code": "CS703"},
            "teacher": {"id": "t3", "name": "Prof. Future"},
            "division": {"id": "d1", "name": "Div A"},
            "batch": None,
            "classroom": {"room_number": "203"},
            "laboratory": None,
            "start_time": "14:00",
            "end_time": "15:00",
            "session_type": "LECTURE",
            "status": "SCHEDULED",
        }

        mock_service.return_value = {
            "summary": {
                "active_teachers_count": 5,
                "active_students_count": 100,
                "today_classes_count": 3,
                "unresolved_conflicts_count": 0,
                "pending_leaves_count": 0,
                "pending_substitutions_count": 0,
            },
            "today": {
                "day": "MONDAY",
                "date": "2026-09-28",
                "current_time": "10:30",
                "classes": [completed_slot, current_slot, upcoming_slot],
                "current": [current_slot],
                "upcoming": [upcoming_slot],
                "completed": [completed_slot],
            },
            "conflicts": [],
            "teacher_leaves": [],
            "substitutions": [],
            "recent_changes": [],
            "quick_actions": {},
        }

        self.client.force_login(self.staff_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "In progress")
        self.assertContains(response, "Completed")
        self.assertContains(response, "Scheduled")
        self.assertContains(response, "Current Cloud Computing")
        self.assertContains(response, "Completed Data Mining")
        self.assertContains(response, "Upcoming Artificial Intelligence")

    @patch("academics.services.staff_dashboard_service.StaffDashboardService.get_dashboard_data")
    def test_09_conflicts_rendered_from_service(self, mock_service):
        """9. Unresolved conflicts render type, severity badge, and description."""
        conflict_item = {
            "id": "c-1",
            "timetable_id": "tt-1",
            "conflict_type": "TEACHER_OVERLAP",
            "severity": "HARD",
            "description": "Prof. Alan Smith is assigned to two concurrent classes in Room 101 and Room 204.",
            "status": "DETECTED",
            "created_at": "2026-09-28T10:00:00",
        }
        mock_service.return_value = {
            "summary": {
                "active_teachers_count": 5,
                "active_students_count": 100,
                "today_classes_count": 0,
                "unresolved_conflicts_count": 1,
                "pending_leaves_count": 0,
                "pending_substitutions_count": 0,
            },
            "today": {"day": "MONDAY", "date": "2026-09-28", "classes": [], "current": [], "upcoming": [], "completed": []},
            "conflicts": [conflict_item],
            "teacher_leaves": [],
            "substitutions": [],
            "recent_changes": [],
            "quick_actions": {},
        }

        self.client.force_login(self.staff_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Teacher_Overlap")
        self.assertContains(response, "HARD")
        self.assertContains(response, "Prof. Alan Smith is assigned to two concurrent classes")

    @patch("academics.services.staff_dashboard_service.StaffDashboardService.get_dashboard_data")
    def test_10_conflict_count_and_list_mismatch_represented_correctly(self, mock_service):
        """10. Total active conflict count (18) and limited display (4) explicitly indicates 'Showing 4 of 18'."""
        conflicts = [
            {
                "id": f"c-{i}",
                "timetable_id": "tt-1",
                "conflict_type": "ROOM_CLASH",
                "severity": "HARD",
                "description": f"Classroom double-booked in Room {100 + i}",
                "status": "DETECTED",
                "created_at": "2026-09-28T10:00:00",
            }
            for i in range(1, 16)
        ]
        mock_service.return_value = {
            "summary": {
                "active_teachers_count": 10,
                "active_students_count": 100,
                "today_classes_count": 0,
                "unresolved_conflicts_count": 18,
                "pending_leaves_count": 0,
                "pending_substitutions_count": 0,
            },
            "today": {"day": "MONDAY", "date": "2026-09-28", "classes": [], "current": [], "upcoming": [], "completed": []},
            "conflicts": conflicts,
            "teacher_leaves": [],
            "substitutions": [],
            "recent_changes": [],
            "quick_actions": {},
        }

        self.client.force_login(self.staff_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "18 Active")
        self.assertContains(response, "Showing 4 of 18 active conflicts")

    @patch("academics.services.staff_dashboard_service.StaffDashboardService.get_dashboard_data")
    def test_11_recent_activity_rendered_from_service(self, mock_service):
        """11. Recent timetable mutation change logs render action, version, author, and reason."""
        recent_log = {
            "id": "log-1",
            "action": "SLOT_RESCHEDULED",
            "timetable": {
                "id": "tt-1",
                "version": 3,
                "academic_year": "2026-2027",
                "status": "PUBLISHED",
            },
            "changed_by": {"id": "u-1", "name": "Dr. Eleanor Vance"},
            "reason": "Faculty medical emergency swap",
            "created_at": "2026-09-28T12:00:00",
        }
        mock_service.return_value = {
            "summary": {
                "active_teachers_count": 5,
                "active_students_count": 50,
                "today_classes_count": 0,
                "unresolved_conflicts_count": 0,
                "pending_leaves_count": 0,
                "pending_substitutions_count": 0,
            },
            "today": {"day": "MONDAY", "date": "2026-09-28", "classes": [], "current": [], "upcoming": [], "completed": []},
            "conflicts": [],
            "teacher_leaves": [],
            "substitutions": [],
            "recent_changes": [recent_log],
            "quick_actions": {},
        }

        self.client.force_login(self.staff_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Slot_Rescheduled")
        self.assertContains(response, "Faculty medical emergency swap")
        self.assertContains(response, "v3 (2026-2027)")
        self.assertContains(response, "Dr. Eleanor Vance")

    @patch("academics.services.staff_dashboard_service.StaffDashboardService.get_dashboard_data")
    def test_12_empty_dashboard_state_renders_safely(self, mock_service):
        """12. Clean empty states render safely when no classes, conflicts, or logs exist."""
        mock_service.return_value = {
            "summary": {
                "active_teachers_count": 0,
                "active_students_count": 0,
                "today_classes_count": 0,
                "unresolved_conflicts_count": 0,
                "pending_leaves_count": 0,
                "pending_substitutions_count": 0,
            },
            "today": {"day": "SUNDAY", "date": "2026-09-27", "classes": [], "current": [], "upcoming": [], "completed": []},
            "conflicts": [],
            "teacher_leaves": [],
            "substitutions": [],
            "recent_changes": [],
            "quick_actions": {},
        }

        self.client.force_login(self.staff_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No classes scheduled today")
        self.assertContains(response, "No active conflicts")
        self.assertContains(response, "No recent activity recorded")

    def test_13_sensitive_private_data_not_leaked(self):
        """13. Ensure sensitive credentials, password hashes, and tokens are never leaked."""
        self.client.force_login(self.staff_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertNotIn("SecureStaffPass123!", content)
        self.assertNotIn("SecureTeacherPass123!", content)
        self.assertNotIn("SecureStudentPass123!", content)
        self.assertNotIn("pbkdf2_sha256", content)
        self.assertNotIn("access_token", content)
        self.assertNotIn("refresh_token", content)

    def test_14_existing_rest_api_dashboard_endpoint_unchanged(self):
        """14. GET /api/v1/staff/dashboard/ returns HTTP 200 with standard schema."""
        from rest_framework.test import APIClient
        api_client = APIClient()
        api_client.force_authenticate(user=self.staff_user)
        response = api_client.get(self.rest_dashboard_url)
        self.assertEqual(response.status_code, 200)
        for key in ["summary", "today", "conflicts", "teacher_leaves", "substitutions", "recent_changes", "quick_actions"]:
            self.assertIn(key, response.data)

    @patch("academics.services.staff_dashboard_service.StaffDashboardService.get_dashboard_data")
    def test_15_service_controlled_error_renders_safe_dashboard(self, mock_service):
        """15. Controlled domain error in StaffDashboardService renders a safe fallback without tracebacks."""
        mock_service.side_effect = RuntimeError("Database connection glitch")
        self.client.force_login(self.staff_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Operational dashboard data is currently unavailable.")
        self.assertNotContains(response, "Traceback")
        self.assertNotContains(response, "RuntimeError: Database connection glitch")


class StaffTeacherManagementWebTests(TestCase):
    """
    Focused Phase 16C Test Suite: Staff Web Teacher Management.
    Tests viewing, searching, filtering, server-side pagination, detail,
    create, edit, status toggle, CSRF, and security.
    """

    def setUp(self):
        import datetime
        self.client = Client(enforce_csrf_checks=True)

        # 1. Base Users
        self.staff_user = User.objects.create_user(
            username="staff_mgr",
            email="staff.mgr@smarttime.ai",
            password="StaffPassword123!",
            role=User.Role.STAFF,
            first_name="Staff",
            last_name="Manager",
        )
        self.teacher_user = User.objects.create_user(
            username="alan_turing",
            email="alan.turing@smarttime.ai",
            password="TeacherPassword123!",
            role=User.Role.TEACHER,
            first_name="Alan",
            last_name="Turing",
            phone="9876543210",
        )
        self.student_user = User.objects.create_user(
            username="student_ada",
            email="student.ada@smarttime.ai",
            password="StudentPassword123!",
            role=User.Role.STUDENT,
            first_name="Ada",
            last_name="Lovelace",
        )

        # 2. Departments
        from academics.models import Department, Program, Subject, TeacherSubject, TeacherAvailability, TeacherLeave
        from accounts.models import TeacherProfile

        self.dept_cs = Department.objects.create(name="Computer Science", code="CS")
        self.dept_ee = Department.objects.create(name="Electrical Engineering", code="EE")

        # 3. Teacher Profile
        self.teacher_profile_1 = TeacherProfile.objects.create(
            user=self.teacher_user,
            employee_code="EMP-CS-001",
            department=self.dept_cs,
            designation="Associate Professor",
            status=TeacherProfile.Status.ACTIVE,
            joining_date=datetime.date(2023, 7, 1),
        )

        # 4. Program & Subject
        self.program = Program.objects.create(
            department=self.dept_cs,
            name="Bachelor of Computer Science",
            code="BCS",
            duration_years=4,
        )
        self.subject_dsa = Subject.objects.create(
            program=self.program,
            name="Data Structures and Algorithms",
            code="CS201",
            type=Subject.Type.LECTURE,
            credits=4.0,
        )

        # URLs
        self.teachers_list_url = reverse("staff:teachers")
        self.teacher_create_url = reverse("staff:teacher_create")
        self.teacher_detail_url = reverse("staff:teacher_detail", kwargs={"id": self.teacher_profile_1.id})
        self.teacher_edit_url = reverse("staff:teacher_edit", kwargs={"id": self.teacher_profile_1.id})
        self.teacher_toggle_url = reverse("staff:teacher_toggle_status", kwargs={"id": self.teacher_profile_1.id})

    def _get_csrf_token(self, url=None):
        target = url or self.teachers_list_url
        res = self.client.get(target)
        token = res.cookies.get("csrftoken")
        return token.value if token else ""

    def test_01_staff_can_access_teacher_list(self):
        """1. Staff can access teacher list."""
        self.client.force_login(self.staff_user)
        response = self.client.get(self.teachers_list_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "staff/teachers/list.html")
        self.assertContains(response, "Faculty Members")
        self.assertContains(response, "Add Teacher")

    def test_02_unauthenticated_user_redirects_to_login(self):
        """2. Unauthenticated user redirects to login."""
        response = self.client.get(self.teachers_list_url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("staff:login")))

    def test_03_teacher_role_receives_403(self):
        """3. Teacher role receives 403."""
        self.client.force_login(self.teacher_user)
        response = self.client.get(self.teachers_list_url)
        self.assertEqual(response.status_code, 403)

    def test_04_student_role_receives_403(self):
        """4. Student role receives 403."""
        self.client.force_login(self.student_user)
        response = self.client.get(self.teachers_list_url)
        self.assertEqual(response.status_code, 403)

    def test_05_teacher_list_renders(self):
        """5. Teacher list renders faculty information, code, designation, and department."""
        self.client.force_login(self.staff_user)
        response = self.client.get(self.teachers_list_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "EMP-CS-001")
        self.assertContains(response, "Alan Turing")
        self.assertContains(response, "Associate Professor")
        self.assertContains(response, "Computer Science")
        self.assertContains(response, "ACTIVE")

    def test_06_search_by_teacher_name_works(self):
        """6. Search by teacher name works case-insensitively and filters correctly."""
        from accounts.models import TeacherProfile
        user2 = User.objects.create_user(
            username="grace_hopper",
            email="grace.hopper@smarttime.ai",
            password="TeacherPassword123!",
            role=User.Role.TEACHER,
            first_name="Grace",
            last_name="Hopper",
        )
        TeacherProfile.objects.create(
            user=user2,
            employee_code="EMP-CS-002",
            department=self.dept_cs,
            designation="Professor",
            status=TeacherProfile.Status.ACTIVE,
        )

        self.client.force_login(self.staff_user)
        response = self.client.get(f"{self.teachers_list_url}?q=grace")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "EMP-CS-002")
        self.assertContains(response, "Grace Hopper")
        self.assertNotContains(response, "EMP-CS-001")

    def test_07_search_by_email_works(self):
        """7. Search by email works."""
        self.client.force_login(self.staff_user)
        response = self.client.get(f"{self.teachers_list_url}?q=alan.turing@smarttime.ai")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "EMP-CS-001")
        self.assertContains(response, "alan.turing@smarttime.ai")

    def test_08_search_by_employee_code_works(self):
        """8. Search by employee code works."""
        self.client.force_login(self.staff_user)
        response = self.client.get(f"{self.teachers_list_url}?q=EMP-CS-001")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "EMP-CS-001")

    def test_09_department_filter_works(self):
        """9. Department filter works."""
        from accounts.models import TeacherProfile
        user_ee = User.objects.create_user(
            username="claude_shannon",
            email="claude.shannon@smarttime.ai",
            password="TeacherPassword123!",
            role=User.Role.TEACHER,
            first_name="Claude",
            last_name="Shannon",
        )
        TeacherProfile.objects.create(
            user=user_ee,
            employee_code="EMP-EE-001",
            department=self.dept_ee,
            designation="Professor",
            status=TeacherProfile.Status.ACTIVE,
        )

        self.client.force_login(self.staff_user)
        response = self.client.get(f"{self.teachers_list_url}?department={self.dept_ee.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "EMP-EE-001")
        self.assertContains(response, "Claude Shannon")
        self.assertNotContains(response, "EMP-CS-001")

    def test_10_status_filter_works(self):
        """10. Status filter works."""
        from accounts.models import TeacherProfile
        user_inactive = User.objects.create_user(
            username="inactive_prof",
            email="inactive.prof@smarttime.ai",
            password="TeacherPassword123!",
            role=User.Role.TEACHER,
            first_name="Inactive",
            last_name="Prof",
            is_active=False,
        )
        TeacherProfile.objects.create(
            user=user_inactive,
            employee_code="EMP-CS-999",
            department=self.dept_cs,
            designation="Adjunct Lecturer",
            status=TeacherProfile.Status.INACTIVE,
        )

        self.client.force_login(self.staff_user)
        response = self.client.get(f"{self.teachers_list_url}?status=INACTIVE")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "EMP-CS-999")
        self.assertNotContains(response, "EMP-CS-001")

    def test_11_pagination_works(self):
        """11. Server-side pagination defaults to 20 per page."""
        from accounts.models import TeacherProfile
        # Create 22 more teachers so total is 23
        for i in range(2, 24):
            u = User.objects.create_user(
                username=f"teacher_batch_{i}",
                email=f"teacher{i}@smarttime.ai",
                password="TeacherPassword123!",
                role=User.Role.TEACHER,
                first_name="Faculty",
                last_name="Member",
            )
            TeacherProfile.objects.create(
                user=u,
                employee_code=f"EMP-BATCH-{i:03d}",
                department=self.dept_cs,
                designation="Lecturer",
                status=TeacherProfile.Status.ACTIVE,
            )

        self.client.force_login(self.staff_user)
        res_page1 = self.client.get(f"{self.teachers_list_url}?page=1")
        self.assertEqual(res_page1.status_code, 200)
        self.assertEqual(len(res_page1.context["teachers"]), 20)

        res_page2 = self.client.get(f"{self.teachers_list_url}?page=2")
        self.assertEqual(res_page2.status_code, 200)
        self.assertEqual(len(res_page2.context["teachers"]), 3)

    def test_12_add_teacher_succeeds(self):
        """12. Add teacher succeeds and creates user and profile atomically."""
        from accounts.models import TeacherProfile
        self.client.force_login(self.staff_user)
        csrf = self._get_csrf_token(self.teacher_create_url)

        payload = {
            "username": "margaret_hamilton",
            "email": "margaret.hamilton@smarttime.ai",
            "first_name": "Margaret",
            "last_name": "Hamilton",
            "phone": "9876543211",
            "password": "TeacherPassword123!",
            "confirm_password": "TeacherPassword123!",
            "employee_code": "EMP-CS-005",
            "department": str(self.dept_cs.id),
            "designation": "Director of Software Engineering",
            "joining_date": "2024-08-15",
            "status": "ACTIVE",
            "csrfmiddlewaretoken": csrf,
        }

        response = self.client.post(self.teacher_create_url, payload, follow=False)
        self.assertEqual(response.status_code, 302)

        created_teacher = TeacherProfile.objects.get(user__username="margaret_hamilton")
        self.assertEqual(response.url, reverse("staff:teacher_detail", kwargs={"id": created_teacher.id}))
        self.assertEqual(created_teacher.user.username, "margaret_hamilton")
        self.assertEqual(created_teacher.user.role, User.Role.TEACHER)
        self.assertTrue(created_teacher.user.is_active)
        self.assertEqual(created_teacher.status, TeacherProfile.Status.ACTIVE)
        # Server-side generated teacher code
        self.assertTrue(created_teacher.employee_code.startswith("T-"))

    def test_13_duplicate_username_is_rejected(self):
        """13. Duplicate username is rejected."""
        self.client.force_login(self.staff_user)
        csrf = self._get_csrf_token(self.teacher_create_url)

        payload = {
            "username": "alan_turing",  # Existing username
            "email": "unique.email@smarttime.ai",
            "password": "TeacherPassword123!",
            "confirm_password": "TeacherPassword123!",
            "employee_code": "EMP-NEW-99",
            "department": str(self.dept_cs.id),
            "designation": "Assistant Professor",
            "csrfmiddlewaretoken": csrf,
        }

        response = self.client.post(self.teacher_create_url, payload)
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertTrue(form.errors)
        self.assertIn("A user with that username already exists.", form.errors.get("username", []))

    def test_14_duplicate_email_is_rejected(self):
        """14. Duplicate email is rejected."""
        self.client.force_login(self.staff_user)
        csrf = self._get_csrf_token(self.teacher_create_url)

        payload = {
            "username": "unique_username_99",
            "email": "alan.turing@smarttime.ai",  # Existing email
            "password": "TeacherPassword123!",
            "confirm_password": "TeacherPassword123!",
            "employee_code": "EMP-NEW-99",
            "department": str(self.dept_cs.id),
            "designation": "Assistant Professor",
            "csrfmiddlewaretoken": csrf,
        }

        response = self.client.post(self.teacher_create_url, payload)
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertTrue(form.errors)
        self.assertIn("A user with that email already exists.", form.errors.get("email", []))

    def test_15_duplicate_employee_code_is_rejected(self):
        """15. Client-submitted employee code cannot create duplicate; server safely generates unique sequential code."""
        self.client.force_login(self.staff_user)
        csrf = self._get_csrf_token(self.teacher_create_url)

        payload = {
            "username": "unique_username_88",
            "email": "unique.user88@smarttime.ai",
            "password": "TeacherPassword123!",
            "confirm_password": "TeacherPassword123!",
            "employee_code": "EMP-CS-001",  # Client tries to force duplicate of existing employee code
            "department": str(self.dept_cs.id),
            "designation": "Assistant Professor",
            "csrfmiddlewaretoken": csrf,
        }

        response = self.client.post(self.teacher_create_url, payload, follow=False)
        self.assertEqual(response.status_code, 302)
        created = TeacherProfile.objects.get(user__username="unique_username_88")
        self.assertNotEqual(created.employee_code, "EMP-CS-001")
        self.assertTrue(created.employee_code.startswith("T-"))

    def test_16_invalid_password_confirmation_is_rejected(self):
        """16. Invalid password confirmation is rejected."""
        self.client.force_login(self.staff_user)
        csrf = self._get_csrf_token(self.teacher_create_url)

        payload = {
            "username": "pass_mismatch_user",
            "email": "mismatch@smarttime.ai",
            "password": "TeacherPassword123!",
            "confirm_password": "DifferentPassword456!",
            "employee_code": "EMP-MISMATCH-1",
            "department": str(self.dept_cs.id),
            "designation": "Lecturer",
            "csrfmiddlewaretoken": csrf,
        }

        response = self.client.post(self.teacher_create_url, payload)
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertTrue(form.errors)
        self.assertIn("Passwords do not match.", form.errors.get("confirm_password", []))

    def test_17_teacher_detail_page_works(self):
        """17. Teacher detail page works and renders profile information."""
        self.client.force_login(self.staff_user)
        response = self.client.get(self.teacher_detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "staff/teachers/detail.html")
        self.assertContains(response, "EMP-CS-001")
        self.assertContains(response, "Alan Turing")
        self.assertContains(response, "alan.turing@smarttime.ai")
        self.assertContains(response, "Associate Professor")
        self.assertContains(response, "Computer Science")

    def test_18_teacher_edit_works(self):
        """18. Teacher edit works and preserves employee code without exposing passwords."""
        from accounts.models import TeacherProfile
        self.client.force_login(self.staff_user)
        csrf = self._get_csrf_token(self.teacher_edit_url)

        original_code = self.teacher_profile_1.employee_code

        payload = {
            "first_name": "Alan",
            "last_name": "Mathison Turing",
            "email": "alan.turing.updated@smarttime.ai",
            "phone": "9876543212",
            "employee_code": "EMP-TAMPERED-999",  # Attempt to tamper with employee code
            "department": str(self.dept_cs.id),
            "designation": "Full Professor & Chair",
            "status": "ACTIVE",
            "csrfmiddlewaretoken": csrf,
        }

        response = self.client.post(self.teacher_edit_url, payload, follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.teacher_detail_url)

        self.teacher_profile_1.refresh_from_db()
        self.assertEqual(self.teacher_profile_1.employee_code, original_code)
        self.assertEqual(self.teacher_profile_1.designation, "Full Professor & Chair")
        self.assertEqual(self.teacher_profile_1.user.last_name, "Mathison Turing")
        self.assertEqual(self.teacher_profile_1.user.email, "alan.turing.updated@smarttime.ai")

    def test_19_activate_deactivate_requires_post(self):
        """19. Activate/deactivate requires POST and toggles teacher and user status."""
        from accounts.models import TeacherProfile
        self.client.force_login(self.staff_user)

        # GET should be rejected / redirect without toggling
        res_get = self.client.get(self.teacher_toggle_url)
        self.assertEqual(res_get.status_code, 302)
        self.teacher_profile_1.refresh_from_db()
        self.assertEqual(self.teacher_profile_1.status, TeacherProfile.Status.ACTIVE)

        # POST 1: Toggle ACTIVE -> INACTIVE
        csrf = self._get_csrf_token()
        res_post1 = self.client.post(self.teacher_toggle_url, {"csrfmiddlewaretoken": csrf}, follow=False)
        self.assertEqual(res_post1.status_code, 302)
        self.teacher_profile_1.refresh_from_db()
        self.assertEqual(self.teacher_profile_1.status, TeacherProfile.Status.INACTIVE)
        self.assertFalse(self.teacher_profile_1.user.is_active)

        # POST 2: Toggle INACTIVE -> ACTIVE
        res_post2 = self.client.post(self.teacher_toggle_url, {"csrfmiddlewaretoken": csrf}, follow=False)
        self.assertEqual(res_post2.status_code, 302)
        self.teacher_profile_1.refresh_from_db()
        self.assertEqual(self.teacher_profile_1.status, TeacherProfile.Status.ACTIVE)
        self.assertTrue(self.teacher_profile_1.user.is_active)

    def test_20_csrf_protection_remains_enabled(self):
        """20. CSRF protection remains enabled on teacher management POST endpoints."""
        client_no_csrf = Client(enforce_csrf_checks=True)
        client_no_csrf.force_login(self.staff_user)

        # Missing CSRF on toggle status
        response = client_no_csrf.post(self.teacher_toggle_url, {})
        self.assertEqual(response.status_code, 403)

        # Missing CSRF on teacher create
        response_create = client_no_csrf.post(self.teacher_create_url, {"username": "foo"})
        self.assertEqual(response_create.status_code, 403)

    def test_21_teacher_passwords_are_never_exposed_in_html(self):
        """21. Teacher passwords, hashes, and secrets are never exposed in HTML."""
        self.client.force_login(self.staff_user)

        # Detail view check
        res_detail = self.client.get(self.teacher_detail_url)
        content_detail = res_detail.content.decode("utf-8")
        self.assertNotIn("TeacherPassword123!", content_detail)
        self.assertNotIn("pbkdf2_sha256", content_detail)

        # Edit view check
        res_edit = self.client.get(self.teacher_edit_url)
        content_edit = res_edit.content.decode("utf-8")
        self.assertNotIn("TeacherPassword123!", content_edit)
        self.assertNotIn("pbkdf2_sha256", content_edit)

        # List view check
        res_list = self.client.get(self.teachers_list_url)
        content_list = res_list.content.decode("utf-8")
        self.assertNotIn("TeacherPassword123!", content_list)
        self.assertNotIn("pbkdf2_sha256", content_list)

    def test_22_teacher_subject_assignments_are_displayed(self):
        """22. Teacher subject assignments are displayed on detail page."""
        from academics.models import TeacherSubject
        TeacherSubject.objects.create(
            teacher=self.teacher_profile_1,
            subject=self.subject_dsa,
            priority=1,
        )

        self.client.force_login(self.staff_user)
        response = self.client.get(self.teacher_detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Data Structures and Algorithms")
        self.assertContains(response, "CS201")
        self.assertContains(response, "Priority 1")
        self.assertContains(response, "1 Assigned")

    def test_23_teacher_availability_is_displayed(self):
        """23. Teacher availability is displayed on detail page."""
        import datetime
        from academics.models import TeacherAvailability
        TeacherAvailability.objects.create(
            teacher=self.teacher_profile_1,
            day=TeacherAvailability.Day.MONDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
            is_available=True,
        )

        self.client.force_login(self.staff_user)
        response = self.client.get(self.teacher_detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Monday")
        self.assertContains(response, "09:00")
        self.assertContains(response, "17:00")
        self.assertContains(response, "Available")

    def test_24_teacher_leave_information_is_displayed(self):
        """24. Teacher leave information is displayed on detail page."""
        import datetime
        from academics.models import TeacherLeave
        TeacherLeave.objects.create(
            teacher=self.teacher_profile_1,
            start_date=datetime.date(2026, 10, 1),
            end_date=datetime.date(2026, 10, 3),
            reason="Attending ACM Computing Conference",
            status=TeacherLeave.Status.APPROVED,
        )

        self.client.force_login(self.staff_user)
        response = self.client.get(self.teacher_detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Attending ACM Computing Conference")
        self.assertContains(response, "APPROVED")

    def test_25_existing_rest_teacher_apis_remain_unchanged(self):
        """25. Existing REST teacher APIs remain unchanged."""
        from rest_framework.test import APIClient
        api_client = APIClient()
        api_client.force_authenticate(user=self.staff_user)
        response = api_client.get("/api/v1/teachers/")
        self.assertEqual(response.status_code, 200)

    def test_26_existing_staff_web_authentication_tests_continue_passing(self):
        """26. Existing staff authentication rules continue passing."""
        self.client.force_login(self.staff_user)
        res_dash = self.client.get(reverse("staff:dashboard"))
        self.assertEqual(res_dash.status_code, 200)
        self.assertContains(res_dash, "Staff workspace")

    def test_27_employee_code_auto_generated_in_sequential_order(self):
        """27. Teacher code is automatically generated in sequential order (T-001, T-002, T-003)."""
        from staff.utils import generate_next_employee_code
        from accounts.models import TeacherProfile

        # When only non-T prefixed codes exist, next sequence starts at T-001
        code1 = generate_next_employee_code()
        self.assertEqual(code1, "T-001")

        # Create teacher with T-001
        u1 = User.objects.create_user(username="prof_seq1", email="seq1@smarttime.ai", password="Pass123!Password", role=User.Role.TEACHER)
        TeacherProfile.objects.create(user=u1, employee_code="T-001", department=self.dept_cs, designation="Lecturer")

        # Next sequence should be T-002
        code2 = generate_next_employee_code()
        self.assertEqual(code2, "T-002")

        # Create teacher with T-002
        u2 = User.objects.create_user(username="prof_seq2", email="seq2@smarttime.ai", password="Pass123!Password", role=User.Role.TEACHER)
        TeacherProfile.objects.create(user=u2, employee_code="T-002", department=self.dept_cs, designation="Lecturer")

        # Next sequence should be T-003
        code3 = generate_next_employee_code()
        self.assertEqual(code3, "T-003")

    def test_28_first_available_sequence_generated_correctly(self):
        """28. First available sequence is generated correctly on form creation."""
        from accounts.models import TeacherProfile
        self.client.force_login(self.staff_user)
        csrf = self._get_csrf_token(self.teacher_create_url)

        payload = {
            "username": "prof_first_seq",
            "email": "first.seq@smarttime.ai",
            "first_name": "First",
            "last_name": "Sequence",
            "password": "Password123!Pass",
            "confirm_password": "Password123!Pass",
            "department": str(self.dept_cs.id),
            "designation": "Assistant Professor",
            "csrfmiddlewaretoken": csrf,
        }
        res = self.client.post(self.teacher_create_url, payload, follow=False)
        self.assertEqual(res.status_code, 302)
        teacher = TeacherProfile.objects.get(user__username="prof_first_seq")
        self.assertEqual(teacher.employee_code, "T-001")

    def test_29_existing_employee_codes_not_overwritten(self):
        """29. Existing custom employee codes are not overwritten when generating new codes."""
        from accounts.models import TeacherProfile
        self.client.force_login(self.staff_user)
        csrf = self._get_csrf_token(self.teacher_create_url)

        original_code = self.teacher_profile_1.employee_code  # EMP-CS-001

        payload = {
            "username": "prof_another",
            "email": "another@smarttime.ai",
            "password": "Password123!Pass",
            "confirm_password": "Password123!Pass",
            "department": str(self.dept_cs.id),
            "designation": "Professor",
            "csrfmiddlewaretoken": csrf,
        }
        self.client.post(self.teacher_create_url, payload, follow=False)

        self.teacher_profile_1.refresh_from_db()
        self.assertEqual(self.teacher_profile_1.employee_code, original_code)

    def test_30_department_searchable_field_rendered_and_validated(self):
        """30. Department searchable combobox is rendered and foreign key validation is enforced."""
        self.client.force_login(self.staff_user)
        response = self.client.get(self.teacher_create_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="departmentSearchInput"')
        self.assertContains(response, 'id="id_department"')
        self.assertContains(response, 'id="departmentDropdown"')
        self.assertContains(response, self.dept_cs.name)
        self.assertContains(response, f"({self.dept_cs.code})")

        # Invalid department submission should trigger validation error
        csrf = self._get_csrf_token(self.teacher_create_url)
        payload = {
            "username": "prof_bad_dept",
            "email": "bad.dept@smarttime.ai",
            "password": "Password123!Pass",
            "confirm_password": "Password123!Pass",
            "department": "00000000-0000-0000-0000-000000000000",
            "designation": "Professor",
            "csrfmiddlewaretoken": csrf,
        }
        res_post = self.client.post(self.teacher_create_url, payload)
        self.assertEqual(res_post.status_code, 200)
        self.assertTrue(res_post.context["form"].errors.get("department"))

    def test_31_designation_searchable_field_rendered_and_validated(self):
        """31. Designation searchable combobox is rendered and handles both selection and custom typing."""
        self.client.force_login(self.staff_user)
        response = self.client.get(self.teacher_create_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="id_designation"')
        self.assertContains(response, 'id="designationDropdown"')
        self.assertContains(response, "Associate Professor")

        # Blank designation triggers error
        csrf = self._get_csrf_token(self.teacher_create_url)
        payload = {
            "username": "prof_no_desig",
            "email": "no.desig@smarttime.ai",
            "password": "Password123!Pass",
            "confirm_password": "Password123!Pass",
            "department": str(self.dept_cs.id),
            "designation": "",
            "csrfmiddlewaretoken": csrf,
        }
        res_post = self.client.post(self.teacher_create_url, payload)
        self.assertEqual(res_post.status_code, 200)
        self.assertTrue(res_post.context["form"].errors.get("designation"))

    def test_32_joining_date_and_status_in_same_desktop_row(self):
        """32. Joining date and Employment status fields are present and configured."""
        self.client.force_login(self.staff_user)
        response = self.client.get(self.teacher_create_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="joining_date"')
        self.assertContains(response, 'name="status"')
        self.assertContains(response, "Active")
        self.assertContains(response, "Inactive")



