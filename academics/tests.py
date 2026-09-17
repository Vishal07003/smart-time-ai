import uuid
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from academics.models import (
    Department,
    Division,
    PracticalBatch,
    Program,
    Semester,
    Subject,
)
from academics.validators import (
    validate_academic_year,
    validate_code_format,
    validate_non_empty_name,
    validate_positive_integer,
)
from accounts.models import User

UserModel = get_user_model()


class AcademicValidatorTests(APITestCase):
    """
    Unit tests for academics/validators.py
    """

    def test_valid_academic_year(self):
        self.assertEqual(validate_academic_year("2025-2026"), "2025-2026")
        self.assertEqual(validate_academic_year("  2026-2027  "), "2026-2027")

    def test_invalid_academic_year(self):
        invalid_years = [
            "2025-2025",  # same year
            "2025-2027",  # non-consecutive
            "25-26",  # 2 digits
            "2025/2026",  # wrong separator
            "2025 - 2026",  # internal spaces
            "invalid",
            "",
        ]
        for yr in invalid_years:
            with self.assertRaises(ValidationError):
                validate_academic_year(yr)

    def test_code_format_validation(self):
        self.assertEqual(validate_code_format("cs_101"), "CS_101")
        self.assertEqual(validate_code_format("btech-cs"), "BTECH-CS")
        self.assertEqual(validate_code_format("it.302"), "IT.302")

        invalid_codes = ["", " ", "a", "code with spaces", "code@123", "a" * 31]
        for c in invalid_codes:
            with self.assertRaises(ValidationError):
                validate_code_format(c)

    def test_positive_integer_validation(self):
        self.assertEqual(validate_positive_integer(10), 10)
        with self.assertRaises(ValidationError):
            validate_positive_integer(0)
        with self.assertRaises(ValidationError):
            validate_positive_integer(-5)


class AcademicModelTests(APITestCase):
    """
    Model creation, relationship, and constraint tests.
    """

    def setUp(self):
        self.dept = Department.objects.create(
            name="Computer Engineering",
            code="COMP",
        )
        self.program = Program.objects.create(
            department=self.dept,
            name="B.Tech Computer Science",
            code="BTECH-CS",
            duration_years=4,
        )
        self.semester = Semester.objects.create(
            program=self.program,
            number=3,
            academic_year="2025-2026",
        )
        self.division = Division.objects.create(
            semester=self.semester,
            name="A",
            capacity=60,
        )
        self.batch = PracticalBatch.objects.create(
            division=self.division,
            name="B1",
            capacity=20,
        )
        self.subject = Subject.objects.create(
            program=self.program,
            name="Data Structures & Algorithms",
            code="CS301",
            type=Subject.Type.LECTURE,
            credits=Decimal("4.0"),
            weekly_lectures=4,
            weekly_practicals=2,
            duration_minutes=60,
        )

    def test_model_uuid_primary_keys(self):
        self.assertIsInstance(self.dept.id, uuid.UUID)
        self.assertIsInstance(self.program.id, uuid.UUID)
        self.assertIsInstance(self.semester.id, uuid.UUID)
        self.assertIsInstance(self.division.id, uuid.UUID)
        self.assertIsInstance(self.batch.id, uuid.UUID)
        self.assertIsInstance(self.subject.id, uuid.UUID)

    def test_model_string_representations(self):
        self.assertEqual(str(self.dept), "Computer Engineering (COMP)")
        self.assertEqual(str(self.program), "B.Tech Computer Science (BTECH-CS)")
        self.assertIn("Sem 3", str(self.semester))
        self.assertIn("Div A", str(self.division))
        self.assertIn("B1", str(self.batch))
        self.assertIn("CS301", str(self.subject))

    def test_duplicate_department_code_case_insensitive(self):
        with self.assertRaises((ValidationError, IntegrityError)):
            d = Department(name="Duplicate Dept", code="comp")
            d.full_clean()
            d.save()

    def test_duplicate_program_code_case_insensitive(self):
        with self.assertRaises((ValidationError, IntegrityError)):
            p = Program(department=self.dept, name="Duplicate Prog", code="btech-cs")
            p.full_clean()
            p.save()

    def test_duplicate_semester_unique_constraint(self):
        with self.assertRaises((ValidationError, IntegrityError)):
            s = Semester(program=self.program, number=3, academic_year="2025-2026")
            s.full_clean()
            s.save()

    def test_duplicate_division_unique_constraint(self):
        with self.assertRaises((ValidationError, IntegrityError)):
            d = Division(semester=self.semester, name="A", capacity=50)
            d.full_clean()
            d.save()

    def test_duplicate_batch_unique_constraint(self):
        with self.assertRaises((ValidationError, IntegrityError)):
            b = PracticalBatch(division=self.division, name="B1", capacity=15)
            b.full_clean()
            b.save()

    def test_duplicate_subject_code_case_insensitive(self):
        with self.assertRaises((ValidationError, IntegrityError)):
            sub = Subject(
                program=self.program,
                name="Duplicate Subject",
                code="cs301",
                type=Subject.Type.PRACTICAL,
            )
            sub.full_clean()
            sub.save()


class AcademicAPITests(APITestCase):
    """
    Comprehensive REST API tests for Departments, Programs, Semesters, Divisions, Batches, Subjects.
    Includes filtering and role-based permissions.
    """

    def setUp(self):
        self.password = "SecurePassword123!"

        self.staff_user = UserModel.objects.create_user(
            username="staff_admin",
            email="staff_admin@smarttime.ai",
            password=self.password,
            role=User.Role.STAFF,
            is_staff=True,
        )
        self.teacher_user = UserModel.objects.create_user(
            username="teacher_user",
            email="teacher_user@smarttime.ai",
            password=self.password,
            role=User.Role.TEACHER,
        )
        self.student_user = UserModel.objects.create_user(
            username="student_user",
            email="student_user@smarttime.ai",
            password=self.password,
            role=User.Role.STUDENT,
        )

        # Initial Academic Data
        self.dept1 = Department.objects.create(name="Computer Engineering", code="CE")
        self.dept2 = Department.objects.create(name="Information Technology", code="IT")

        self.prog1 = Program.objects.create(
            department=self.dept1, name="B.Tech CE", code="BTECH-CE", duration_years=4
        )
        self.prog2 = Program.objects.create(
            department=self.dept2, name="B.Tech IT", code="BTECH-IT", duration_years=4
        )

        self.sem1 = Semester.objects.create(
            program=self.prog1, number=1, academic_year="2025-2026"
        )
        self.sem2 = Semester.objects.create(
            program=self.prog2, number=1, academic_year="2025-2026"
        )

        self.div1 = Division.objects.create(semester=self.sem1, name="A", capacity=60)
        self.div2 = Division.objects.create(semester=self.sem1, name="B", capacity=60)

        self.batch1 = PracticalBatch.objects.create(
            division=self.div1, name="A1", capacity=20
        )
        self.batch2 = PracticalBatch.objects.create(
            division=self.div1, name="A2", capacity=20
        )

        self.sub_lec = Subject.objects.create(
            program=self.prog1,
            name="Algorithms",
            code="CS101",
            type=Subject.Type.LECTURE,
            credits=Decimal("3.0"),
            weekly_lectures=3,
            weekly_practicals=0,
            duration_minutes=60,
        )
        self.sub_prac = Subject.objects.create(
            program=self.prog1,
            name="Algorithms Lab",
            code="CS101P",
            type=Subject.Type.PRACTICAL,
            credits=Decimal("1.5"),
            weekly_lectures=0,
            weekly_practicals=2,
            duration_minutes=120,
        )

        # Helper URLs
        self.dept_list_url = reverse("academics:department-list")
        self.prog_list_url = reverse("academics:program-list")
        self.sem_list_url = reverse("academics:semester-list")
        self.div_list_url = reverse("academics:division-list")
        self.batch_list_url = reverse("academics:batch-list")
        self.subject_list_url = reverse("academics:subject-list")

    def authenticate_as(self, user):
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    # --- Department Tests ---
    def test_department_crud_as_staff(self):
        self.authenticate_as(self.staff_user)

        # Create
        res = self.client.post(
            self.dept_list_url,
            {"name": "Mechanical Engineering", "code": "MECH"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        dept_id = res.data["id"]

        # Read
        detail_url = reverse("academics:department-detail", kwargs={"pk": dept_id})
        res_get = self.client.get(detail_url)
        self.assertEqual(res_get.status_code, status.HTTP_200_OK)
        self.assertEqual(res_get.data["code"], "MECH")

        # Update
        res_patch = self.client.patch(
            detail_url,
            {"name": "Mechanical & Aerospace Engineering"},
            format="json",
        )
        self.assertEqual(res_patch.status_code, status.HTTP_200_OK)
        self.assertEqual(res_patch.data["name"], "Mechanical & Aerospace Engineering")

        # Delete
        res_del = self.client.delete(detail_url)
        self.assertEqual(res_del.status_code, status.HTTP_204_NO_CONTENT)

    # --- Program Tests & Query Param Filtering ---
    def test_program_filtering_by_department(self):
        self.authenticate_as(self.teacher_user)

        res = self.client.get(f"{self.prog_list_url}?department={self.dept1.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        # Should only contain prog1
        ids = [item["id"] for item in res.data["results"] if "results" in res.data] if "results" in res.data else [item["id"] for item in res.data]
        self.assertIn(str(self.prog1.id), ids)
        self.assertNotIn(str(self.prog2.id), ids)

    # --- Semester Tests & Query Param Filtering ---
    def test_semester_filtering_by_program(self):
        self.authenticate_as(self.student_user)

        res = self.client.get(f"{self.sem_list_url}?program={self.prog1.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        items = res.data["results"] if "results" in res.data else res.data
        for item in items:
            self.assertEqual(item["program"], self.prog1.id)

    # --- Division Tests & Query Param Filtering ---
    def test_division_filtering_by_semester(self):
        self.authenticate_as(self.staff_user)

        res = self.client.get(f"{self.div_list_url}?semester={self.sem1.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        items = res.data["results"] if "results" in res.data else res.data
        self.assertEqual(len(items), 2)

    # --- Practical Batch Tests & Filtering ---
    def test_batch_filtering_by_division(self):
        self.authenticate_as(self.teacher_user)

        res = self.client.get(f"{self.batch_list_url}?division={self.div1.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        items = res.data["results"] if "results" in res.data else res.data
        self.assertEqual(len(items), 2)

    # --- Subject Tests & Filtering by Program and Type ---
    def test_subject_filtering_by_type_and_program(self):
        self.authenticate_as(self.staff_user)

        # Filter by type PRACTICAL
        res = self.client.get(f"{self.subject_list_url}?type=PRACTICAL")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        items = res.data["results"] if "results" in res.data else res.data
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["code"], "CS101P")

        # Filter by program
        res_prog = self.client.get(f"{self.subject_list_url}?program={self.prog1.id}")
        self.assertEqual(res_prog.status_code, status.HTTP_200_OK)
        items_prog = res_prog.data["results"] if "results" in res_prog.data else res_prog.data
        self.assertEqual(len(items_prog), 2)

    # --- Role-Based Permissions Tests ---
    def test_teacher_read_only_access(self):
        self.authenticate_as(self.teacher_user)

        # GET should succeed (200 OK)
        res_get = self.client.get(self.dept_list_url)
        self.assertEqual(res_get.status_code, status.HTTP_200_OK)

        # POST should be forbidden (403 Forbidden)
        res_post = self.client.post(
            self.dept_list_url,
            {"name": "Electrical Engineering", "code": "EE"},
            format="json",
        )
        self.assertEqual(res_post.status_code, status.HTTP_403_FORBIDDEN)

        # DELETE should be forbidden (403 Forbidden)
        detail_url = reverse("academics:department-detail", kwargs={"pk": self.dept1.id})
        res_del = self.client.delete(detail_url)
        self.assertEqual(res_del.status_code, status.HTTP_403_FORBIDDEN)

    def test_student_read_only_access(self):
        self.authenticate_as(self.student_user)

        # GET should succeed (200 OK)
        res_get = self.client.get(self.subject_list_url)
        self.assertEqual(res_get.status_code, status.HTTP_200_OK)

        # POST should be forbidden (403 Forbidden)
        res_post = self.client.post(
            self.subject_list_url,
            {
                "program": str(self.prog1.id),
                "name": "New Subject",
                "code": "CS999",
                "type": "LECTURE",
            },
            format="json",
        )
        self.assertEqual(res_post.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_access_denied(self):
        self.client.credentials()  # Clear auth credentials

        res = self.client.get(self.dept_list_url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class TeacherSubjectAPITests(APITestCase):
    """
    Staff-only CRUD tests for TeacherSubject assignment API.
    """

    def setUp(self):
        from accounts.models import TeacherProfile
        from academics.models import Department, Program, Subject, TeacherSubject

        self.staff_user = UserModel.objects.create_user(
            username="ts_staff",
            email="ts_staff@smarttime.ai",
            password="Password123!",
            role=User.Role.STAFF,
        )
        self.teacher_user = UserModel.objects.create_user(
            username="ts_teacher",
            email="ts_teacher@smarttime.ai",
            password="Password123!",
            role=User.Role.TEACHER,
        )
        self.student_user = UserModel.objects.create_user(
            username="ts_student",
            email="ts_student@smarttime.ai",
            password="Password123!",
            role=User.Role.STUDENT,
        )

        self.dept = Department.objects.create(name="Computer Science", code="CS_TS")
        self.prog = Program.objects.create(
            department=self.dept, name="B.Tech CS", code="BTECH_CS_TS"
        )
        self.subj1 = Subject.objects.create(
            program=self.prog, name="Operating Systems", code="CS_OS"
        )
        self.subj2 = Subject.objects.create(
            program=self.prog, name="Database Systems", code="CS_DB"
        )

        self.teacher_profile = TeacherProfile.objects.create(
            user=self.teacher_user,
            employee_code="EMP_TS_01",
            department=self.dept,
            designation="Assistant Professor",
        )

        self.assignment = TeacherSubject.objects.create(
            teacher=self.teacher_profile,
            subject=self.subj1,
            priority=1,
        )

        self.list_url = reverse("academics:teacher-subject-list")
        self.detail_url = reverse(
            "academics:teacher-subject-detail", kwargs={"pk": self.assignment.id}
        )

    def test_staff_list_and_create_teacher_subject(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # List
        res_list = self.client.get(self.list_url)
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_list.data), 1)

        # Create
        res_create = self.client.post(
            self.list_url,
            {
                "teacher": str(self.teacher_profile.id),
                "subject": str(self.subj2.id),
                "priority": 2,
            },
            format="json",
        )
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_create.data["priority"], 2)

    def test_duplicate_assignment_fails(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        res = self.client.post(
            self.list_url,
            {
                "teacher": str(self.teacher_profile.id),
                "subject": str(self.subj1.id),
                "priority": 1,
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_staff_forbidden(self):
        # Teacher
        refresh_t = RefreshToken.for_user(self.teacher_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh_t.access_token}")
        res_t = self.client.get(self.list_url)
        self.assertEqual(res_t.status_code, status.HTTP_403_FORBIDDEN)

        # Student
        refresh_s = RefreshToken.for_user(self.student_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh_s.access_token}")
        res_s = self.client.get(self.list_url)
        self.assertEqual(res_s.status_code, status.HTTP_403_FORBIDDEN)


class TeacherAvailabilityAPITests(APITestCase):
    """
    CRUD and permission tests for TeacherAvailability endpoints.
    """

    def setUp(self):
        from accounts.models import TeacherProfile
        from academics.models import Department, TeacherAvailability

        self.staff_user = UserModel.objects.create_user(
            username="avail_staff",
            email="avail_staff@smarttime.ai",
            password="Password123!",
            role=User.Role.STAFF,
        )
        self.teacher1_user = UserModel.objects.create_user(
            username="avail_teacher1",
            email="avail_teacher1@smarttime.ai",
            password="Password123!",
            role=User.Role.TEACHER,
        )
        self.teacher2_user = UserModel.objects.create_user(
            username="avail_teacher2",
            email="avail_teacher2@smarttime.ai",
            password="Password123!",
            role=User.Role.TEACHER,
        )
        self.student_user = UserModel.objects.create_user(
            username="avail_student",
            email="avail_student@smarttime.ai",
            password="Password123!",
            role=User.Role.STUDENT,
        )

        self.dept = Department.objects.create(name="IT Dept", code="IT_AVAIL")

        self.teacher1_profile = TeacherProfile.objects.create(
            user=self.teacher1_user,
            employee_code="EMP_AV_01",
            department=self.dept,
            designation="Professor",
        )
        self.teacher2_profile = TeacherProfile.objects.create(
            user=self.teacher2_user,
            employee_code="EMP_AV_02",
            department=self.dept,
            designation="Assistant Professor",
        )

        self.avail1 = TeacherAvailability.objects.create(
            teacher=self.teacher1_profile,
            day="MONDAY",
            start_time="09:00:00",
            end_time="11:00:00",
            is_available=True,
        )
        self.avail2 = TeacherAvailability.objects.create(
            teacher=self.teacher2_profile,
            day="MONDAY",
            start_time="10:00:00",
            end_time="12:00:00",
            is_available=True,
        )

        self.list_url = reverse("academics:teacher-availability-list")
        self.detail_url1 = reverse(
            "academics:teacher-availability-detail", kwargs={"pk": self.avail1.id}
        )
        self.detail_url2 = reverse(
            "academics:teacher-availability-detail", kwargs={"pk": self.avail2.id}
        )

    def test_staff_can_view_all_and_create(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # List should return both availabilities
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 2)

        # Create availability for teacher 1 on Tuesday
        create_res = self.client.post(
            self.list_url,
            {
                "teacher": str(self.teacher1_profile.id),
                "day": "TUESDAY",
                "start_time": "14:00:00",
                "end_time": "16:00:00",
                "is_available": True,
            },
            format="json",
        )
        self.assertEqual(create_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_res.data["day"], "TUESDAY")

    def test_teacher_can_only_view_and_manage_own(self):
        refresh = RefreshToken.for_user(self.teacher1_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # List should return ONLY teacher 1's availability
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]["id"], str(self.avail1.id))

        # Teacher 1 cannot view or modify teacher 2's availability
        res_get2 = self.client.get(self.detail_url2)
        self.assertEqual(res_get2.status_code, status.HTTP_404_NOT_FOUND)

        res_patch2 = self.client.patch(
            self.detail_url2,
            {"is_available": False},
            format="json",
        )
        self.assertEqual(res_patch2.status_code, status.HTTP_404_NOT_FOUND)

        # Teacher 1 can update their own availability
        res_patch1 = self.client.patch(
            self.detail_url1,
            {"is_available": False},
            format="json",
        )
        self.assertEqual(res_patch1.status_code, status.HTTP_200_OK)
        self.assertEqual(res_patch1.data["is_available"], False)

        # Teacher 1 creates their own availability (auto-bound to teacher1)
        res_create = self.client.post(
            self.list_url,
            {
                "day": "WEDNESDAY",
                "start_time": "10:00:00",
                "end_time": "12:00:00",
            },
            format="json",
        )
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(res_create.data["teacher"]), str(self.teacher1_profile.id))

    def test_student_and_anon_forbidden(self):
        # Anonymous
        self.client.credentials()
        res_anon = self.client.get(self.list_url)
        self.assertEqual(res_anon.status_code, status.HTTP_401_UNAUTHORIZED)

        # Student
        refresh_s = RefreshToken.for_user(self.student_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh_s.access_token}")
        res_s = self.client.get(self.list_url)
        self.assertEqual(res_s.status_code, status.HTTP_403_FORBIDDEN)

    def test_validation_start_time_before_end_time(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        res = self.client.post(
            self.list_url,
            {
                "teacher": str(self.teacher1_profile.id),
                "day": "THURSDAY",
                "start_time": "14:00:00",
                "end_time": "12:00:00",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("end_time", res.data)

    def test_validation_invalid_day(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        res = self.client.post(
            self.list_url,
            {
                "teacher": str(self.teacher1_profile.id),
                "day": "FUNDAY",
                "start_time": "10:00:00",
                "end_time": "12:00:00",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("day", res.data)

    def test_prevent_overlapping_availability(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # self.avail1 is MONDAY 09:00:00 - 11:00:00
        # Overlap attempt: MONDAY 10:00:00 - 11:30:00 for teacher1
        res = self.client.post(
            self.list_url,
            {
                "teacher": str(self.teacher1_profile.id),
                "day": "MONDAY",
                "start_time": "10:00:00",
                "end_time": "11:30:00",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("overlaps", str(res.data))

        # Non-overlapping attempt: MONDAY 11:00:00 - 12:00:00 (adjacent) -> should SUCCEED
        res_adj = self.client.post(
            self.list_url,
            {
                "teacher": str(self.teacher1_profile.id),
                "day": "MONDAY",
                "start_time": "11:00:00",
                "end_time": "12:00:00",
            },
            format="json",
        )
        self.assertEqual(res_adj.status_code, status.HTTP_201_CREATED)


class TeacherLeaveAPITests(APITestCase):
    """
    CRUD, permission, approval, and overlap tests for TeacherLeave endpoints.
    """

    def setUp(self):
        from accounts.models import TeacherProfile
        from academics.models import Department, TeacherLeave

        self.staff_user = UserModel.objects.create_user(
            username="leave_staff",
            email="leave_staff@smarttime.ai",
            password="Password123!",
            role=User.Role.STAFF,
        )
        self.teacher1_user = UserModel.objects.create_user(
            username="leave_teacher1",
            email="leave_teacher1@smarttime.ai",
            password="Password123!",
            role=User.Role.TEACHER,
        )
        self.teacher2_user = UserModel.objects.create_user(
            username="leave_teacher2",
            email="leave_teacher2@smarttime.ai",
            password="Password123!",
            role=User.Role.TEACHER,
        )
        self.student_user = UserModel.objects.create_user(
            username="leave_student",
            email="leave_student@smarttime.ai",
            password="Password123!",
            role=User.Role.STUDENT,
        )

        self.dept = Department.objects.create(name="Leave Dept", code="LV_DEPT")

        self.teacher1_profile = TeacherProfile.objects.create(
            user=self.teacher1_user,
            employee_code="EMP_LV_01",
            department=self.dept,
            designation="Professor",
        )
        self.teacher2_profile = TeacherProfile.objects.create(
            user=self.teacher2_user,
            employee_code="EMP_LV_02",
            department=self.dept,
            designation="Assistant Professor",
        )

        self.leave1 = TeacherLeave.objects.create(
            teacher=self.teacher1_profile,
            start_date="2026-10-01",
            end_date="2026-10-05",
            reason="Medical leave",
            status=TeacherLeave.Status.PENDING,
        )
        self.leave2 = TeacherLeave.objects.create(
            teacher=self.teacher2_profile,
            start_date="2026-10-01",
            end_date="2026-10-03",
            reason="Conference attendance",
            status=TeacherLeave.Status.PENDING,
        )

        self.list_url = reverse("academics:teacher-leave-list")
        self.detail_url1 = reverse(
            "academics:teacher-leave-detail", kwargs={"pk": self.leave1.id}
        )
        self.detail_url2 = reverse(
            "academics:teacher-leave-detail", kwargs={"pk": self.leave2.id}
        )

    def test_staff_can_view_all_and_approve_reject(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # List returns both
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 2)

        # Staff approves leave1
        res_approve = self.client.patch(
            self.detail_url1,
            {"status": "APPROVED"},
            format="json",
        )
        self.assertEqual(res_approve.status_code, status.HTTP_200_OK)
        self.assertEqual(res_approve.data["status"], "APPROVED")

        # Staff rejects leave2
        res_reject = self.client.patch(
            self.detail_url2,
            {"status": "REJECTED"},
            format="json",
        )
        self.assertEqual(res_reject.status_code, status.HTTP_200_OK)
        self.assertEqual(res_reject.data["status"], "REJECTED")

    def test_teacher_can_only_view_and_manage_own(self):
        refresh = RefreshToken.for_user(self.teacher1_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # List returns only own leave
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]["id"], str(self.leave1.id))

        # Teacher 1 cannot view or modify teacher 2's leave
        res_get2 = self.client.get(self.detail_url2)
        self.assertEqual(res_get2.status_code, status.HTTP_404_NOT_FOUND)

        res_patch2 = self.client.patch(
            self.detail_url2,
            {"reason": "Hacked reason"},
            format="json",
        )
        self.assertEqual(res_patch2.status_code, status.HTTP_404_NOT_FOUND)

        # Teacher 1 creates their own leave (status should be PENDING)
        res_create = self.client.post(
            self.list_url,
            {
                "start_date": "2026-11-01",
                "end_date": "2026-11-03",
                "reason": "Family function",
            },
            format="json",
        )
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(res_create.data["teacher"]), str(self.teacher1_profile.id))
        self.assertEqual(res_create.data["status"], "PENDING")

        # Teacher cannot self-approve leave
        res_self_approve = self.client.patch(
            self.detail_url1,
            {"status": "APPROVED"},
            format="json",
        )
        self.assertEqual(res_self_approve.status_code, status.HTTP_400_BAD_REQUEST)

    def test_student_and_anon_forbidden(self):
        # Anon
        self.client.credentials()
        res_anon = self.client.get(self.list_url)
        self.assertEqual(res_anon.status_code, status.HTTP_401_UNAUTHORIZED)

        # Student
        refresh_s = RefreshToken.for_user(self.student_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh_s.access_token}")
        res_s = self.client.get(self.list_url)
        self.assertEqual(res_s.status_code, status.HTTP_403_FORBIDDEN)

    def test_validation_date_order(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        res = self.client.post(
            self.list_url,
            {
                "teacher": str(self.teacher1_profile.id),
                "start_date": "2026-12-10",
                "end_date": "2026-12-05",
                "reason": "Invalid dates",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("end_date", res.data)

    def test_validation_overlapping_leaves(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # self.leave1 is 2026-10-01 to 2026-10-05
        # Attempt overlap: 2026-10-03 to 2026-10-07
        res = self.client.post(
            self.list_url,
            {
                "teacher": str(self.teacher1_profile.id),
                "start_date": "2026-10-03",
                "end_date": "2026-10-07",
                "reason": "Overlap attempt",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("overlaps", str(res.data))

    def test_staff_update_status_endpoint(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        status_url = reverse("academics:teacher-leave-status", kwargs={"pk": self.leave1.id})
        res = self.client.patch(status_url, {"status": "APPROVED"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "APPROVED")

        # Invalid status
        res_invalid = self.client.patch(status_url, {"status": "UNKNOWN"}, format="json")
        self.assertEqual(res_invalid.status_code, status.HTTP_400_BAD_REQUEST)


class ClassroomAndLaboratoryAPITests(APITestCase):
    """
    CRUD and permission tests for Classroom and Laboratory endpoints.
    """

    def setUp(self):
        from academics.models import Classroom, Laboratory

        self.staff_user = UserModel.objects.create_user(
            username="res_staff",
            email="res_staff@smarttime.ai",
            password="Password123!",
            role=User.Role.STAFF,
        )
        self.teacher_user = UserModel.objects.create_user(
            username="res_teacher",
            email="res_teacher@smarttime.ai",
            password="Password123!",
            role=User.Role.TEACHER,
        )
        self.student_user = UserModel.objects.create_user(
            username="res_student",
            email="res_student@smarttime.ai",
            password="Password123!",
            role=User.Role.STUDENT,
        )

        self.classroom = Classroom.objects.create(
            building="Main Building",
            room_number="101",
            floor=1,
            capacity=60,
            status=Classroom.Status.AVAILABLE,
        )
        self.laboratory = Laboratory.objects.create(
            building="Tech Block",
            lab_number="LAB-01",
            name="AI Lab",
            floor=2,
            capacity=30,
            status=Laboratory.Status.AVAILABLE,
        )

        self.cr_list_url = reverse("academics:classroom-list")
        self.cr_detail_url = reverse(
            "academics:classroom-detail", kwargs={"pk": self.classroom.id}
        )
        self.lab_list_url = reverse("academics:laboratory-list")
        self.lab_detail_url = reverse(
            "academics:laboratory-detail", kwargs={"pk": self.laboratory.id}
        )

    def test_classroom_crud_and_permissions(self):
        # Staff full CRUD
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        res_list = self.client.get(self.cr_list_url)
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_list.data), 1)

        res_create = self.client.post(
            self.cr_list_url,
            {
                "building": "Main Building",
                "room_number": "102",
                "floor": 1,
                "capacity": 70,
                "status": "AVAILABLE",
            },
            format="json",
        )
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)

        # Duplicate classroom in same building fails
        res_dup = self.client.post(
            self.cr_list_url,
            {
                "building": "Main Building",
                "room_number": "101",
                "floor": 1,
                "capacity": 50,
            },
            format="json",
        )
        self.assertEqual(res_dup.status_code, status.HTTP_400_BAD_REQUEST)

        # Teacher read-only
        refresh_t = RefreshToken.for_user(self.teacher_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh_t.access_token}")
        res_t_get = self.client.get(self.cr_detail_url)
        self.assertEqual(res_t_get.status_code, status.HTTP_200_OK)

        res_t_post = self.client.post(
            self.cr_list_url,
            {"building": "Block B", "room_number": "201", "capacity": 40},
            format="json",
        )
        self.assertEqual(res_t_post.status_code, status.HTTP_403_FORBIDDEN)

    def test_laboratory_crud_and_permissions(self):
        # Staff full CRUD
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        res_list = self.client.get(self.lab_list_url)
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_list.data), 1)

        res_create = self.client.post(
            self.lab_list_url,
            {
                "building": "Tech Block",
                "lab_number": "LAB-02",
                "name": "Robotics Lab",
                "floor": 2,
                "capacity": 25,
            },
            format="json",
        )
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)

        # Duplicate lab in same building fails
        res_dup = self.client.post(
            self.lab_list_url,
            {
                "building": "Tech Block",
                "lab_number": "LAB-01",
                "name": "Duplicate Lab",
                "capacity": 30,
            },
            format="json",
        )
        self.assertEqual(res_dup.status_code, status.HTTP_400_BAD_REQUEST)

        # Student read-only
        refresh_s = RefreshToken.for_user(self.student_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh_s.access_token}")
        res_s_get = self.client.get(self.lab_detail_url)
        self.assertEqual(res_s_get.status_code, status.HTTP_200_OK)

        res_s_delete = self.client.delete(self.lab_detail_url)
        self.assertEqual(res_s_delete.status_code, status.HTTP_403_FORBIDDEN)


class TimetableAndSlotAPITests(APITestCase):
    """
    CRUD, permission, and workflow tests for Timetable and TimetableSlot.
    """

    def setUp(self):
        from accounts.models import StudentProfile, TeacherProfile
        from academics.models import (
            Classroom,
            Department,
            Division,
            Laboratory,
            PracticalBatch,
            Program,
            Semester,
            Subject,
            Timetable,
            TimetableSlot,
        )

        self.staff_user = UserModel.objects.create_user(
            username="tt_staff",
            email="tt_staff@smarttime.ai",
            password="Password123!",
            role=User.Role.STAFF,
        )
        self.teacher_user = UserModel.objects.create_user(
            username="tt_teacher",
            email="tt_teacher@smarttime.ai",
            password="Password123!",
            role=User.Role.TEACHER,
        )
        self.student_user = UserModel.objects.create_user(
            username="tt_student",
            email="tt_student@smarttime.ai",
            password="Password123!",
            role=User.Role.STUDENT,
        )

        self.dept = Department.objects.create(name="Computer Engg", code="CE_TT")
        self.prog = Program.objects.create(department=self.dept, name="B.Tech CE", code="BTECH_CE")
        self.semester = Semester.objects.create(program=self.prog, number=4, academic_year="2025-2026")
        self.division = Division.objects.create(semester=self.semester, name="Div-A", capacity=60)
        self.batch = PracticalBatch.objects.create(division=self.division, name="B1", capacity=20)
        self.subject = Subject.objects.create(program=self.prog, name="Algorithms", code="CE_ALG")

        self.teacher_profile = TeacherProfile.objects.create(
            user=self.teacher_user,
            employee_code="EMP_TT_01",
            department=self.dept,
            designation="Associate Professor",
        )
        self.student_profile = StudentProfile.objects.create(
            user=self.student_user,
            roll_number="ROLL_TT_01",
            admission_year=2025,
            division=self.division,
            batch=self.batch,
        )

        self.classroom = Classroom.objects.create(
            building="Academic Block", room_number="CR-201", capacity=60
        )
        self.laboratory = Laboratory.objects.create(
            building="Academic Block", lab_number="LAB-101", name="Algorithm Lab", capacity=30
        )

        self.timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2025-2026",
            version=1,
            status=Timetable.Status.DRAFT,
            created_by=self.staff_user,
        )

        self.slot = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            subject=self.subject,
            teacher=self.teacher_profile,
            classroom=self.classroom,
            day="MONDAY",
            start_time="09:00:00",
            end_time="10:00:00",
            session_type="LECTURE",
        )

        self.tt_list_url = reverse("academics:timetable-list")
        self.tt_detail_url = reverse("academics:timetable-detail", kwargs={"pk": self.timetable.id})
        self.slot_list_url = reverse("academics:timetable-slot-list")
        self.slot_detail_url = reverse("academics:timetable-slot-detail", kwargs={"pk": self.slot.id})

    def test_timetable_crud_and_publishing_workflow(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # Staff can list drafts
        res_list = self.client.get(self.tt_list_url)
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_list.data), 1)

        # Teacher cannot see draft timetable
        refresh_t = RefreshToken.for_user(self.teacher_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh_t.access_token}")
        res_t_list = self.client.get(self.tt_list_url)
        self.assertEqual(res_t_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_t_list.data), 0)

        # Staff publishes timetable via action
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        publish_url = reverse("academics:timetable-publish", kwargs={"pk": self.timetable.id})
        res_pub = self.client.post(publish_url)
        self.assertEqual(res_pub.status_code, status.HTTP_200_OK)
        self.assertEqual(res_pub.data["status"], "PUBLISHED")
        self.assertIsNotNone(res_pub.data["published_at"])

        # Teacher can now view published timetable
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh_t.access_token}")
        res_t_pub = self.client.get(self.tt_list_url)
        self.assertEqual(res_t_pub.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_t_pub.data), 1)

        # Student can view slots in published timetable
        refresh_s = RefreshToken.for_user(self.student_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh_s.access_token}")
        res_s_slots = self.client.get(self.slot_list_url)
        self.assertEqual(res_s_slots.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_s_slots.data), 1)

    def test_timetable_slot_validation(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # Invalid start_time >= end_time
        res_invalid_time = self.client.post(
            self.slot_list_url,
            {
                "timetable": str(self.timetable.id),
                "division": str(self.division.id),
                "subject": str(self.subject.id),
                "teacher": str(self.teacher_profile.id),
                "classroom": str(self.classroom.id),
                "day": "TUESDAY",
                "start_time": "11:00:00",
                "end_time": "10:00:00",
                "session_type": "LECTURE",
            },
            format="json",
        )
        self.assertEqual(res_invalid_time.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("end_time", res_invalid_time.data)

