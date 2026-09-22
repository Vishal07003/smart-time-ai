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
from academics.validators import (
    validate_academic_year,
    validate_code_format,
    validate_non_empty_name,
    validate_positive_integer,
)
from academics.services.constraint_integration import (
    ConstraintIntegrationService,
    SolverConstraintMap,
)
from academics.services.constraint_parser import StructuredConstraint
from academics.services.constraint_validator import (
    ConstraintValidatorService,
    ValidationErrorCode,
    ValidationErrorDetail,
    ValidationResult,
)
from academics.services.timetable_generator import TimetableGenerationService
from academics.services.timetable_solver import (
    OptimizationConfig,
    SolverConfig,
    TimetableSolver,
)
from accounts.models import TeacherProfile, User

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


class TimetableConflictDetectionAPITests(APITestCase):
    """
    Tests for ConflictDetectionService and conflict check endpoints.
    """

    def setUp(self):
        from accounts.models import TeacherProfile
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
            TimetableConflict,
            TimetableSlot,
        )

        self.staff_user = UserModel.objects.create_user(
            username="cd_staff",
            email="cd_staff@smarttime.ai",
            password="Password123!",
            role=User.Role.STAFF,
        )
        self.teacher1_user = UserModel.objects.create_user(
            username="cd_teacher1",
            email="cd_teacher1@smarttime.ai",
            password="Password123!",
            role=User.Role.TEACHER,
        )
        self.teacher2_user = UserModel.objects.create_user(
            username="cd_teacher2",
            email="cd_teacher2@smarttime.ai",
            password="Password123!",
            role=User.Role.TEACHER,
        )

        self.dept = Department.objects.create(name="Conflict Dept", code="CD_DEPT")
        self.prog = Program.objects.create(department=self.dept, name="B.Tech CD", code="BTECH_CD")
        self.semester = Semester.objects.create(program=self.prog, number=5, academic_year="2025-2026")
        self.division1 = Division.objects.create(semester=self.semester, name="Div-1", capacity=60)
        self.division2 = Division.objects.create(semester=self.semester, name="Div-2", capacity=60)
        self.batch1 = PracticalBatch.objects.create(division=self.division1, name="B1", capacity=20)
        self.batch2 = PracticalBatch.objects.create(division=self.division1, name="B2", capacity=20)

        self.subj1 = Subject.objects.create(program=self.prog, name="Data Structures", code="CD_DS")
        self.subj2 = Subject.objects.create(program=self.prog, name="Networks", code="CD_NET")

        self.teacher1 = TeacherProfile.objects.create(
            user=self.teacher1_user,
            employee_code="EMP_CD_01",
            department=self.dept,
            designation="Professor",
        )
        self.teacher2 = TeacherProfile.objects.create(
            user=self.teacher2_user,
            employee_code="EMP_CD_02",
            department=self.dept,
            designation="Assistant Professor",
        )

        self.classroom1 = Classroom.objects.create(building="Main", room_number="R101", capacity=60)
        self.classroom2 = Classroom.objects.create(building="Main", room_number="R102", capacity=60)
        self.lab1 = Laboratory.objects.create(building="Tech", lab_number="L1", name="Net Lab", capacity=30)
        self.lab2 = Laboratory.objects.create(building="Tech", lab_number="L2", name="Sys Lab", capacity=30)

        self.timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2025-2026",
            version=1,
            status=Timetable.Status.DRAFT,
            created_by=self.staff_user,
        )

    def test_conflict_detection_service_and_endpoints(self):
        from academics.models import TimetableConflict, TimetableSlot
        from academics.services.conflict_detection import ConflictDetectionService

        # Slot 1: Teacher 1 in Classroom 1, Div 1, MONDAY 09:00 - 10:30
        s1 = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division1,
            subject=self.subj1,
            teacher=self.teacher1,
            classroom=self.classroom1,
            day="MONDAY",
            start_time="09:00:00",
            end_time="10:30:00",
            session_type="LECTURE",
        )

        # Slot 2 (Overlapping with s1): Teacher 1 in Classroom 2, Div 2, MONDAY 10:00 - 11:00 -> TEACHER_CLASH
        s2 = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division2,
            subject=self.subj2,
            teacher=self.teacher1,
            classroom=self.classroom2,
            day="MONDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type="LECTURE",
        )

        # Slot 3 (Overlapping with s1): Teacher 2 in Classroom 1, Div 2, MONDAY 09:30 - 10:15 -> CLASSROOM_CLASH
        s3 = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division2,
            subject=self.subj2,
            teacher=self.teacher2,
            classroom=self.classroom1,
            day="MONDAY",
            start_time="09:30:00",
            end_time="10:15:00",
            session_type="LECTURE",
        )

        # Test via service
        service = ConflictDetectionService(self.timetable)
        conflicts = service.detect_conflicts()
        conflict_types = [c.conflict_type for c in conflicts]
        self.assertIn("TEACHER_CLASH", conflict_types)
        self.assertIn("CLASSROOM_CLASH", conflict_types)

        # Test via API check-conflicts endpoint
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        check_url = reverse("academics:timetable-check-conflicts", kwargs={"pk": self.timetable.id})
        res = self.client.post(check_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(res.data["total_conflicts"], 2)

        # Test GET conflicts endpoint
        conflicts_url = reverse("academics:timetable-conflicts", kwargs={"pk": self.timetable.id})
        res_get = self.client.get(conflicts_url)
        self.assertEqual(res_get.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_get.data), res.data["total_conflicts"])

    def test_unordered_slot_pair_single_conflict_and_idempotency(self):
        """
        Verify that overlapping slot pairs are treated as unordered, creating only ONE conflict
        record per conflict type, and repeated check-conflicts calls do not create duplicates.
        """
        from academics.models import TimetableConflict, TimetableSlot
        from academics.services.conflict_detection import ConflictDetectionService
        from django.db import IntegrityError

        # Create two slots with same teacher and same time
        s1 = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division1,
            subject=self.subj1,
            teacher=self.teacher1,
            classroom=self.classroom1,
            day="TUESDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type="LECTURE",
        )
        s2 = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division2,
            subject=self.subj2,
            teacher=self.teacher1,
            classroom=self.classroom2,
            day="TUESDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type="LECTURE",
        )

        service = ConflictDetectionService(self.timetable)
        conflicts_first = service.detect_conflicts()
        tuesday_teacher_conflicts = [
            c for c in conflicts_first
            if c.conflict_type == TimetableConflict.ConflictType.TEACHER_CLASH
            and {c.slot_id, c.conflicting_slot_id} == {s1.id, s2.id}
        ]
        # Exactly ONE conflict record for this slot pair
        self.assertEqual(len(tuesday_teacher_conflicts), 1)

        # Canonical ordering: slot.id < conflicting_slot.id
        c = tuesday_teacher_conflicts[0]
        self.assertTrue(str(c.slot_id) <= str(c.conflicting_slot_id))

        # Repeated detection calls do not duplicate records
        conflicts_second = service.detect_conflicts()
        tuesday_teacher_conflicts_2 = [
            c for c in conflicts_second
            if c.conflict_type == TimetableConflict.ConflictType.TEACHER_CLASH
            and {c.slot_id, c.conflicting_slot_id} == {s1.id, s2.id}
        ]
        self.assertEqual(len(tuesday_teacher_conflicts_2), 1)

        # Repeated API calls do not duplicate records
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        check_url = reverse("academics:timetable-check-conflicts", kwargs={"pk": self.timetable.id})
        res1 = self.client.post(check_url)
        res2 = self.client.post(check_url)
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res1.data["total_conflicts"], res2.data["total_conflicts"])

        # Test database constraint directly: creating duplicate reverse or identical pair violates constraint
        with self.assertRaises(IntegrityError):
            TimetableConflict.objects.create(
                timetable=self.timetable,
                slot=s1,
                conflicting_slot=s2,
                conflict_type=TimetableConflict.ConflictType.TEACHER_CLASH,
                description="Duplicate",
            )

    def test_different_conflict_types_for_same_pair_remain_separate(self):
        """
        Verify that different conflict types between the same two slots
        (e.g., TEACHER_CLASH and CLASSROOM_CLASH) produce distinct conflict records.
        """
        from academics.models import TimetableConflict, TimetableSlot
        from academics.services.conflict_detection import ConflictDetectionService

        # Two slots that share BOTH same teacher AND same classroom
        s1 = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division1,
            subject=self.subj1,
            teacher=self.teacher1,
            classroom=self.classroom1,
            day="WEDNESDAY",
            start_time="14:00:00",
            end_time="15:30:00",
            session_type="LECTURE",
        )
        s2 = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division2,
            subject=self.subj2,
            teacher=self.teacher1,
            classroom=self.classroom1,
            day="WEDNESDAY",
            start_time="14:30:00",
            end_time="16:00:00",
            session_type="LECTURE",
        )

        service = ConflictDetectionService(self.timetable)
        conflicts = service.detect_conflicts()
        wed_conflicts = [
            c for c in conflicts
            if {c.slot_id, c.conflicting_slot_id} == {s1.id, s2.id}
        ]
        conflict_types = {c.conflict_type for c in wed_conflicts}
        self.assertEqual(len(wed_conflicts), 2)
        self.assertIn(TimetableConflict.ConflictType.TEACHER_CLASH, conflict_types)
        self.assertIn(TimetableConflict.ConflictType.CLASSROOM_CLASH, conflict_types)

    def test_existing_resolved_and_ignored_conflicts_preserved(self):
        """
        Verify that RESOLVED and IGNORED conflicts are preserved and not duplicated or deleted.
        """
        from academics.models import TimetableConflict, TimetableSlot
        from academics.services.conflict_detection import ConflictDetectionService

        s1 = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division1,
            subject=self.subj1,
            teacher=self.teacher2,
            classroom=self.classroom2,
            day="THURSDAY",
            start_time="11:00:00",
            end_time="12:00:00",
            session_type="LECTURE",
        )
        s2 = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division2,
            subject=self.subj2,
            teacher=self.teacher2,
            classroom=self.classroom1,
            day="THURSDAY",
            start_time="11:30:00",
            end_time="12:30:00",
            session_type="LECTURE",
        )

        service = ConflictDetectionService(self.timetable)
        conflicts = service.detect_conflicts()
        thurs_conflict = [
            c for c in conflicts
            if {c.slot_id, c.conflicting_slot_id} == {s1.id, s2.id}
        ][0]

        # Mark conflict as RESOLVED
        thurs_conflict.status = TimetableConflict.Status.RESOLVED
        thurs_conflict.resolved_by = self.staff_user
        thurs_conflict.save()

        # Re-run detection service
        conflicts_after = service.detect_conflicts()
        thurs_conflicts_after = [
            c for c in conflicts_after
            if {c.slot_id, c.conflicting_slot_id} == {s1.id, s2.id}
        ]
        # Should still be exactly 1 record and its status remains RESOLVED
        self.assertEqual(len(thurs_conflicts_after), 1)
        self.assertEqual(thurs_conflicts_after[0].status, TimetableConflict.Status.RESOLVED)
        self.assertEqual(thurs_conflicts_after[0].id, thurs_conflict.id)


class TimetableCPSATSolverTests(APITestCase):
    """
    Focused test suite for Phase 6: OR-Tools CP-SAT Timetable Constraint Solver.
    """

    def setUp(self):
        self.teacher_id = "teach-001"
        self.teacher_2_id = "teach-002"
        self.subj_ds_id = "subj-ds"
        self.subj_net_id = "subj-net"
        self.div_1_id = "div-001"
        self.div_2_id = "div-002"
        self.batch_1_id = "batch-001"
        self.room_cr1_id = "room-cr1"
        self.room_cr2_id = "room-cr2"
        self.room_lab1_id = "room-lab1"

    def test_1_basic_feasible_schedule(self):
        from academics.services.timetable_solver import SolverConfig, TimetableSolver

        config = SolverConfig(
            days=["MONDAY"],
            daily_start_time="09:00:00",
            daily_end_time="11:00:00",
            slot_duration_minutes=60,
        )
        solver = TimetableSolver(config=config)

        input_data = {
            "divisions": [{"id": self.div_1_id, "name": "Div-A", "batch_ids": []}],
            "teachers": [
                {
                    "id": self.teacher_id,
                    "name": "Prof. Alan",
                    "employee_code": "EMP01",
                    "qualified_subject_ids": [self.subj_ds_id],
                }
            ],
            "rooms": [
                {"id": self.room_cr1_id, "name": "R101", "room_type": "CLASSROOM", "status": "AVAILABLE"}
            ],
            "sessions_to_schedule": [
                {
                    "id": "sess-1",
                    "subject_id": self.subj_ds_id,
                    "division_id": self.div_1_id,
                    "session_type": "LECTURE",
                }
            ],
        }

        result = solver.solve(input_data)
        self.assertIn(result["status"], [TimetableSolver.STATUS_FEASIBLE, TimetableSolver.STATUS_OPTIMAL])
        self.assertEqual(len(result["assignments"]), 1)
        assignment = result["assignments"][0]
        self.assertEqual(assignment["session_id"], "sess-1")
        self.assertEqual(assignment["teacher_id"], self.teacher_id)
        self.assertEqual(assignment["classroom_id"], self.room_cr1_id)
        self.assertIsNone(assignment["laboratory_id"])
        self.assertEqual(assignment["day"], "MONDAY")

    def test_2_teacher_overlap_prevention(self):
        from academics.services.timetable_solver import SolverConfig, TimetableSolver

        # Only 1 time slot available
        config = SolverConfig(
            days=["MONDAY"],
            daily_start_time="09:00:00",
            daily_end_time="10:00:00",
            slot_duration_minutes=60,
        )
        solver = TimetableSolver(config=config)

        # 2 sessions assigned to the same teacher in 1 time slot -> Infeasible
        input_data = {
            "divisions": [
                {"id": self.div_1_id, "name": "Div-A"},
                {"id": self.div_2_id, "name": "Div-B"},
            ],
            "teachers": [
                {
                    "id": self.teacher_id,
                    "name": "Prof. Alan",
                    "employee_code": "EMP01",
                    "qualified_subject_ids": [self.subj_ds_id, self.subj_net_id],
                }
            ],
            "rooms": [
                {"id": self.room_cr1_id, "name": "R101", "room_type": "CLASSROOM", "status": "AVAILABLE"},
                {"id": self.room_cr2_id, "name": "R102", "room_type": "CLASSROOM", "status": "AVAILABLE"},
            ],
            "sessions_to_schedule": [
                {"id": "sess-1", "subject_id": self.subj_ds_id, "division_id": self.div_1_id, "session_type": "LECTURE"},
                {"id": "sess-2", "subject_id": self.subj_net_id, "division_id": self.div_2_id, "session_type": "LECTURE"},
            ],
        }

        result = solver.solve(input_data)
        self.assertEqual(result["status"], TimetableSolver.STATUS_INFEASIBLE)

    def test_3_division_overlap_prevention(self):
        from academics.services.timetable_solver import SolverConfig, TimetableSolver

        # Only 1 time slot available
        config = SolverConfig(
            days=["MONDAY"],
            daily_start_time="09:00:00",
            daily_end_time="10:00:00",
            slot_duration_minutes=60,
        )
        solver = TimetableSolver(config=config)

        # 2 sessions for the SAME division with different teachers in 1 time slot -> Infeasible
        input_data = {
            "divisions": [{"id": self.div_1_id, "name": "Div-A"}],
            "teachers": [
                {"id": self.teacher_id, "name": "Prof. Alan", "employee_code": "EMP01", "qualified_subject_ids": [self.subj_ds_id]},
                {"id": self.teacher_2_id, "name": "Prof. Bob", "employee_code": "EMP02", "qualified_subject_ids": [self.subj_net_id]},
            ],
            "rooms": [
                {"id": self.room_cr1_id, "name": "R101", "room_type": "CLASSROOM", "status": "AVAILABLE"},
                {"id": self.room_cr2_id, "name": "R102", "room_type": "CLASSROOM", "status": "AVAILABLE"},
            ],
            "sessions_to_schedule": [
                {"id": "sess-1", "subject_id": self.subj_ds_id, "division_id": self.div_1_id, "session_type": "LECTURE"},
                {"id": "sess-2", "subject_id": self.subj_net_id, "division_id": self.div_1_id, "session_type": "LECTURE"},
            ],
        }

        result = solver.solve(input_data)
        self.assertEqual(result["status"], TimetableSolver.STATUS_INFEASIBLE)

    def test_4_classroom_overlap_prevention(self):
        from academics.services.timetable_solver import SolverConfig, TimetableSolver

        # 1 slot, 1 classroom, 2 different teachers and 2 different divisions -> Infeasible
        config = SolverConfig(
            days=["MONDAY"],
            daily_start_time="09:00:00",
            daily_end_time="10:00:00",
            slot_duration_minutes=60,
        )
        solver = TimetableSolver(config=config)

        input_data = {
            "divisions": [
                {"id": self.div_1_id, "name": "Div-A"},
                {"id": self.div_2_id, "name": "Div-B"},
            ],
            "teachers": [
                {"id": self.teacher_id, "name": "Prof. Alan", "employee_code": "EMP01", "qualified_subject_ids": [self.subj_ds_id]},
                {"id": self.teacher_2_id, "name": "Prof. Bob", "employee_code": "EMP02", "qualified_subject_ids": [self.subj_net_id]},
            ],
            "rooms": [
                {"id": self.room_cr1_id, "name": "R101", "room_type": "CLASSROOM", "status": "AVAILABLE"}
            ],
            "sessions_to_schedule": [
                {"id": "sess-1", "subject_id": self.subj_ds_id, "division_id": self.div_1_id, "session_type": "LECTURE"},
                {"id": "sess-2", "subject_id": self.subj_net_id, "division_id": self.div_2_id, "session_type": "LECTURE"},
            ],
        }

        result = solver.solve(input_data)
        self.assertEqual(result["status"], TimetableSolver.STATUS_INFEASIBLE)

    def test_5_laboratory_overlap_prevention(self):
        from academics.services.timetable_solver import SolverConfig, TimetableSolver

        # 1 slot, 1 lab, 2 practical sessions -> Infeasible
        config = SolverConfig(
            days=["MONDAY"],
            daily_start_time="09:00:00",
            daily_end_time="10:00:00",
            slot_duration_minutes=60,
        )
        solver = TimetableSolver(config=config)

        input_data = {
            "divisions": [
                {"id": self.div_1_id, "name": "Div-A", "batch_ids": [self.batch_1_id]},
                {"id": self.div_2_id, "name": "Div-B", "batch_ids": ["batch-002"]},
            ],
            "teachers": [
                {"id": self.teacher_id, "name": "Prof. Alan", "employee_code": "EMP01", "qualified_subject_ids": [self.subj_ds_id]},
                {"id": self.teacher_2_id, "name": "Prof. Bob", "employee_code": "EMP02", "qualified_subject_ids": [self.subj_net_id]},
            ],
            "rooms": [
                {"id": self.room_lab1_id, "name": "L1", "room_type": "LABORATORY", "status": "AVAILABLE"}
            ],
            "sessions_to_schedule": [
                {"id": "sess-p1", "subject_id": self.subj_ds_id, "division_id": self.div_1_id, "batch_id": self.batch_1_id, "session_type": "PRACTICAL"},
                {"id": "sess-p2", "subject_id": self.subj_net_id, "division_id": self.div_2_id, "batch_id": "batch-002", "session_type": "PRACTICAL"},
            ],
        }

        result = solver.solve(input_data)
        self.assertEqual(result["status"], TimetableSolver.STATUS_INFEASIBLE)

    def test_6_teacher_availability(self):
        from academics.services.timetable_solver import SolverConfig, TimetableSolver

        # 2 slots: 09:00-10:00 and 10:00-11:00. Teacher unavailable at 09:00-10:00.
        config = SolverConfig(
            days=["MONDAY"],
            daily_start_time="09:00:00",
            daily_end_time="11:00:00",
            slot_duration_minutes=60,
        )
        solver = TimetableSolver(config=config)

        input_data = {
            "divisions": [{"id": self.div_1_id, "name": "Div-A"}],
            "teachers": [
                {
                    "id": self.teacher_id,
                    "name": "Prof. Alan",
                    "employee_code": "EMP01",
                    "qualified_subject_ids": [self.subj_ds_id],
                    "unavailable_slots": [
                        {"day": "MONDAY", "start_time": "09:00:00", "end_time": "10:00:00"}
                    ],
                }
            ],
            "rooms": [{"id": self.room_cr1_id, "name": "R101", "room_type": "CLASSROOM", "status": "AVAILABLE"}],
            "sessions_to_schedule": [
                {"id": "sess-1", "subject_id": self.subj_ds_id, "division_id": self.div_1_id, "session_type": "LECTURE"}
            ],
        }

        result = solver.solve(input_data)
        self.assertIn(result["status"], [TimetableSolver.STATUS_FEASIBLE, TimetableSolver.STATUS_OPTIMAL])
        self.assertEqual(result["assignments"][0]["start_time"], "10:00:00")

    def test_7_teacher_leave(self):
        from academics.services.timetable_solver import SolverConfig, TimetableSolver

        # MONDAY and TUESDAY slots. Teacher is on approved leave on MONDAY.
        config = SolverConfig(
            days=["MONDAY", "TUESDAY"],
            daily_start_time="09:00:00",
            daily_end_time="10:00:00",
            slot_duration_minutes=60,
        )
        solver = TimetableSolver(config=config)

        input_data = {
            "divisions": [{"id": self.div_1_id, "name": "Div-A"}],
            "teachers": [
                {
                    "id": self.teacher_id,
                    "name": "Prof. Alan",
                    "employee_code": "EMP01",
                    "qualified_subject_ids": [self.subj_ds_id],
                    "leave_days": ["MONDAY"],
                }
            ],
            "rooms": [{"id": self.room_cr1_id, "name": "R101", "room_type": "CLASSROOM", "status": "AVAILABLE"}],
            "sessions_to_schedule": [
                {"id": "sess-1", "subject_id": self.subj_ds_id, "division_id": self.div_1_id, "session_type": "LECTURE"}
            ],
        }

        result = solver.solve(input_data)
        self.assertIn(result["status"], [TimetableSolver.STATUS_FEASIBLE, TimetableSolver.STATUS_OPTIMAL])
        self.assertEqual(result["assignments"][0]["day"], "TUESDAY")

    def test_8_invalid_teacher_subject_assignment(self):
        from academics.services.timetable_solver import SolverConfig, TimetableSolver

        config = SolverConfig(days=["MONDAY"])
        solver = TimetableSolver(config=config)

        # Teacher is qualified ONLY for subj_net_id, but session requires subj_ds_id
        input_data = {
            "divisions": [{"id": self.div_1_id, "name": "Div-A"}],
            "teachers": [
                {
                    "id": self.teacher_id,
                    "name": "Prof. Alan",
                    "employee_code": "EMP01",
                    "qualified_subject_ids": [self.subj_net_id],
                }
            ],
            "rooms": [{"id": self.room_cr1_id, "name": "R101", "room_type": "CLASSROOM", "status": "AVAILABLE"}],
            "sessions_to_schedule": [
                {"id": "sess-1", "subject_id": self.subj_ds_id, "division_id": self.div_1_id, "session_type": "LECTURE"}
            ],
        }

        result = solver.solve(input_data)
        self.assertEqual(result["status"], TimetableSolver.STATUS_INFEASIBLE)
        self.assertTrue(len(result["errors"]) > 0)

    def test_9_practical_session_without_lab(self):
        from academics.services.timetable_solver import SolverConfig, TimetableSolver

        config = SolverConfig(days=["MONDAY"])
        solver = TimetableSolver(config=config)

        # Practical session requires LABORATORY, but only CLASSROOM is provided
        input_data = {
            "divisions": [{"id": self.div_1_id, "name": "Div-A", "batch_ids": [self.batch_1_id]}],
            "teachers": [
                {
                    "id": self.teacher_id,
                    "name": "Prof. Alan",
                    "employee_code": "EMP01",
                    "qualified_subject_ids": [self.subj_ds_id],
                }
            ],
            "rooms": [{"id": self.room_cr1_id, "name": "R101", "room_type": "CLASSROOM", "status": "AVAILABLE"}],
            "sessions_to_schedule": [
                {"id": "sess-p1", "subject_id": self.subj_ds_id, "division_id": self.div_1_id, "batch_id": self.batch_1_id, "session_type": "PRACTICAL"}
            ],
        }

        result = solver.solve(input_data)
        self.assertEqual(result["status"], TimetableSolver.STATUS_INFEASIBLE)
        self.assertTrue(len(result["errors"]) > 0)

    def test_10_infeasible_scheduling_scenario(self):
        from academics.services.timetable_solver import SolverConfig, TimetableSolver

        # 2 total slots available, but 4 sessions need to be scheduled by 1 teacher
        config = SolverConfig(
            days=["MONDAY"],
            daily_start_time="09:00:00",
            daily_end_time="11:00:00",
            slot_duration_minutes=60,
        )
        solver = TimetableSolver(config=config)

        input_data = {
            "divisions": [{"id": self.div_1_id, "name": "Div-A"}],
            "teachers": [
                {
                    "id": self.teacher_id,
                    "name": "Prof. Alan",
                    "employee_code": "EMP01",
                    "qualified_subject_ids": [self.subj_ds_id],
                }
            ],
            "rooms": [{"id": self.room_cr1_id, "name": "R101", "room_type": "CLASSROOM", "status": "AVAILABLE"}],
            "sessions_to_schedule": [
                {"id": f"sess-{i}", "subject_id": self.subj_ds_id, "division_id": self.div_1_id, "session_type": "LECTURE"}
                for i in range(1, 5)
            ],
        }

        result = solver.solve(input_data)
        self.assertEqual(result["status"], TimetableSolver.STATUS_INFEASIBLE)


class TimetableGenerationAPITests(APITestCase):
    """
    Focused test suite for Phase 7: Timetable Generation Service & API Endpoint.
    """

    def setUp(self):
        from accounts.models import TeacherProfile
        from academics.models import (
            Classroom,
            Department,
            Division,
            Laboratory,
            PracticalBatch,
            Program,
            Semester,
            Subject,
            TeacherSubject,
            Timetable,
            TimetableSlot,
        )

        self.staff_user = UserModel.objects.create_user(
            username="gen_staff",
            email="gen_staff@smarttime.ai",
            password="Password123!",
            role=User.Role.STAFF,
        )
        self.teacher_user = UserModel.objects.create_user(
            username="gen_teacher",
            email="gen_teacher@smarttime.ai",
            password="Password123!",
            role=User.Role.TEACHER,
        )
        self.student_user = UserModel.objects.create_user(
            username="gen_student",
            email="gen_student@smarttime.ai",
            password="Password123!",
            role=User.Role.STUDENT,
        )

        self.dept = Department.objects.create(name="Gen Dept", code="GEN_DEPT")
        self.prog = Program.objects.create(department=self.dept, name="B.Tech Gen", code="BTECH_GEN")
        self.semester = Semester.objects.create(program=self.prog, number=1, academic_year="2026-2027")
        self.division = Division.objects.create(semester=self.semester, name="Div-G1", capacity=60)
        self.batch = PracticalBatch.objects.create(division=self.division, name="B1", capacity=20)

        self.subj_lec = Subject.objects.create(
            program=self.prog,
            name="Theory of Computation",
            code="GEN_TOC",
            type="LECTURE",
            weekly_lectures=2,
            weekly_practicals=0,
        )
        self.subj_prac = Subject.objects.create(
            program=self.prog,
            name="Operating Systems Lab",
            code="GEN_OSL",
            type="PRACTICAL",
            weekly_lectures=0,
            weekly_practicals=1,
        )

        self.teacher_profile = TeacherProfile.objects.create(
            user=self.teacher_user,
            employee_code="EMP_GEN_01",
            department=self.dept,
            designation="Associate Professor",
        )

        TeacherSubject.objects.create(teacher=self.teacher_profile, subject=self.subj_lec, priority=1)
        TeacherSubject.objects.create(teacher=self.teacher_profile, subject=self.subj_prac, priority=1)

        self.classroom = Classroom.objects.create(building="Academic Block", room_number="R201", capacity=60)
        self.laboratory = Laboratory.objects.create(building="Tech Block", lab_number="L101", name="OS Lab", capacity=30)

        self.generate_url = reverse("academics:timetable-generate")

    def test_1_staff_can_request_generation(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        payload = {"semester": str(self.semester.id), "academic_year": "2026-2027"}
        res = self.client.post(self.generate_url, payload, format="json")

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn(res.data["status"], ["FEASIBLE", "OPTIMAL"])
        self.assertIn("timetable_id", res.data)
        self.assertEqual(res.data["version"], 1)
        self.assertEqual(res.data["total_slots"], 3)  # 2 lectures + 1 practical

    def test_2_teacher_cannot_generate(self):
        refresh = RefreshToken.for_user(self.teacher_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        payload = {"semester": str(self.semester.id), "academic_year": "2026-2027"}
        res = self.client.post(self.generate_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_3_student_cannot_generate(self):
        refresh = RefreshToken.for_user(self.student_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        payload = {"semester": str(self.semester.id), "academic_year": "2026-2027"}
        res = self.client.post(self.generate_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_4_unauthenticated_cannot_generate(self):
        payload = {"semester": str(self.semester.id), "academic_year": "2026-2027"}
        res = self.client.post(self.generate_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_5_weekly_lecture_count_expands_correctly(self):
        from academics.services.timetable_generator import TimetableGenerationService
        from academics.models import TimetableSlot

        # subj_lec has weekly_lectures=2
        generator = TimetableGenerationService(
            semester_id=self.semester.id,
            academic_year="2026-2027",
            created_by=self.staff_user,
        )
        result = generator.generate()
        self.assertIn(result["status"], ["FEASIBLE", "OPTIMAL"])

        slots = TimetableSlot.objects.filter(timetable_id=result["timetable_id"], subject=self.subj_lec)
        self.assertEqual(slots.count(), 2)
        for s in slots:
            self.assertEqual(s.session_type, "LECTURE")
            self.assertEqual(s.classroom_id, self.classroom.id)

    def test_6_weekly_practical_count_expands_correctly(self):
        from academics.services.timetable_generator import TimetableGenerationService
        from academics.models import TimetableSlot

        # subj_prac has weekly_practicals=1, division has 1 batch
        generator = TimetableGenerationService(
            semester_id=self.semester.id,
            academic_year="2026-2027",
            created_by=self.staff_user,
        )
        result = generator.generate()
        self.assertIn(result["status"], ["FEASIBLE", "OPTIMAL"])

        slots = TimetableSlot.objects.filter(timetable_id=result["timetable_id"], subject=self.subj_prac)
        self.assertEqual(slots.count(), 1)
        slot = slots.first()
        self.assertEqual(slot.session_type, "PRACTICAL")
        self.assertEqual(slot.laboratory_id, self.laboratory.id)
        self.assertEqual(slot.batch_id, self.batch.id)

    def test_7_qualified_teacher_subject_mapping_respected(self):
        from accounts.models import TeacherProfile
        from academics.models import Subject, TeacherSubject, TimetableSlot
        from academics.services.timetable_generator import TimetableGenerationService

        teacher2_user = UserModel.objects.create_user(
            username="gen_teacher2",
            email="gen_teacher2@smarttime.ai",
            password="Password123!",
            role=User.Role.TEACHER,
        )
        teacher2 = TeacherProfile.objects.create(
            user=teacher2_user,
            employee_code="EMP_GEN_02",
            department=self.dept,
            designation="Lecturer",
        )

        subj_new = Subject.objects.create(
            program=self.prog,
            name="Computer Networks",
            code="GEN_NET",
            type="LECTURE",
            weekly_lectures=1,
        )
        TeacherSubject.objects.create(teacher=teacher2, subject=subj_new)

        generator = TimetableGenerationService(
            semester_id=self.semester.id,
            academic_year="2026-2027",
            created_by=self.staff_user,
        )
        result = generator.generate()
        self.assertIn(result["status"], ["FEASIBLE", "OPTIMAL"])

        slot = TimetableSlot.objects.get(timetable_id=result["timetable_id"], subject=subj_new)
        self.assertEqual(slot.teacher_id, teacher2.id)

    def test_8_missing_qualified_teacher_returns_infeasible_error(self):
        from academics.models import Subject
        from academics.services.timetable_generator import TimetableGenerationService

        # Subject without any TeacherSubject mapping
        Subject.objects.create(
            program=self.prog,
            name="Unassigned Subject",
            code="GEN_UNASSIGNED",
            type="LECTURE",
            weekly_lectures=2,
        )

        generator = TimetableGenerationService(
            semester_id=self.semester.id,
            academic_year="2026-2027",
            created_by=self.staff_user,
        )
        result = generator.generate()
        self.assertEqual(result["status"], "INFEASIBLE")
        self.assertTrue(len(result["errors"]) > 0)
        self.assertIn("No qualified teacher assigned", result["errors"][0])

    def test_9_feasible_generation_creates_timetable(self):
        from academics.models import Timetable
        from academics.services.timetable_generator import TimetableGenerationService

        generator = TimetableGenerationService(
            semester_id=self.semester.id,
            academic_year="2026-2027",
            created_by=self.staff_user,
        )
        result = generator.generate()
        self.assertIn(result["status"], ["FEASIBLE", "OPTIMAL"])

        tt = Timetable.objects.get(id=result["timetable_id"])
        self.assertEqual(tt.semester, self.semester)
        self.assertEqual(tt.academic_year, "2026-2027")
        self.assertEqual(tt.created_by, self.staff_user)

    def test_10_feasible_generation_creates_correct_timetable_slots(self):
        from academics.models import TimetableSlot
        from academics.services.timetable_generator import TimetableGenerationService

        generator = TimetableGenerationService(
            semester_id=self.semester.id,
            academic_year="2026-2027",
            created_by=self.staff_user,
        )
        result = generator.generate()
        self.assertIn(result["status"], ["FEASIBLE", "OPTIMAL"])

        slots = list(TimetableSlot.objects.filter(timetable_id=result["timetable_id"]))
        self.assertEqual(len(slots), 3)
        for s in slots:
            self.assertIn(s.day, ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"])
            self.assertTrue(s.start_time < s.end_time)
            self.assertEqual(s.status, TimetableSlot.Status.SCHEDULED)

    def test_11_generated_timetable_is_not_published_automatically(self):
        from academics.models import Timetable
        from academics.services.timetable_generator import TimetableGenerationService

        generator = TimetableGenerationService(
            semester_id=self.semester.id,
            academic_year="2026-2027",
            created_by=self.staff_user,
        )
        result = generator.generate()
        self.assertIn(result["status"], ["FEASIBLE", "OPTIMAL"])

        tt = Timetable.objects.get(id=result["timetable_id"])
        self.assertEqual(tt.status, Timetable.Status.GENERATED)
        self.assertIsNone(tt.published_at)

    def test_12_infeasible_generation_creates_no_timetable_or_slots(self):
        from academics.models import Classroom, Laboratory, Timetable, TimetableSlot
        from academics.services.timetable_generator import TimetableGenerationService

        # Disable all rooms
        Classroom.objects.all().update(status=Classroom.Status.MAINTENANCE)
        Laboratory.objects.all().update(status=Laboratory.Status.MAINTENANCE)

        initial_tt_count = Timetable.objects.count()
        initial_slot_count = TimetableSlot.objects.count()

        generator = TimetableGenerationService(
            semester_id=self.semester.id,
            academic_year="2026-2027",
            created_by=self.staff_user,
        )
        result = generator.generate()
        self.assertEqual(result["status"], "INFEASIBLE")

        self.assertEqual(Timetable.objects.count(), initial_tt_count)
        self.assertEqual(TimetableSlot.objects.count(), initial_slot_count)

    def test_13_existing_published_timetable_remains_unchanged(self):
        from academics.models import Timetable
        from academics.services.timetable_generator import TimetableGenerationService
        from django.utils import timezone

        # Create existing PUBLISHED version 1
        published_v1 = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=1,
            status=Timetable.Status.PUBLISHED,
            published_at=timezone.now(),
            created_by=self.staff_user,
        )

        generator = TimetableGenerationService(
            semester_id=self.semester.id,
            academic_year="2026-2027",
            created_by=self.staff_user,
        )
        result = generator.generate()
        self.assertIn(result["status"], ["FEASIBLE", "OPTIMAL"])
        self.assertEqual(result["version"], 2)

        published_v1.refresh_from_db()
        self.assertEqual(published_v1.status, Timetable.Status.PUBLISHED)
        self.assertEqual(published_v1.version, 1)

    def test_14_version_increments_correctly(self):
        from academics.services.timetable_generator import TimetableGenerationService

        gen1 = TimetableGenerationService(
            semester_id=self.semester.id,
            academic_year="2026-2027",
            created_by=self.staff_user,
        ).generate()
        self.assertEqual(gen1["version"], 1)

        gen2 = TimetableGenerationService(
            semester_id=self.semester.id,
            academic_year="2026-2027",
            created_by=self.staff_user,
        ).generate()
        self.assertEqual(gen2["version"], 2)

    def test_15_conflict_detection_result_is_included(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        payload = {"semester": str(self.semester.id), "academic_year": "2026-2027"}
        res = self.client.post(self.generate_url, payload, format="json")

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn("conflicts", res.data)
        self.assertIsInstance(res.data["conflicts"], list)

    def test_16_no_partial_timetable_remains_if_generation_fails(self):
        from academics.models import Timetable, TimetableSlot
        from academics.services.timetable_generator import TimetableGenerationService

        initial_tt_count = Timetable.objects.count()
        initial_slot_count = TimetableSlot.objects.count()

        # Non-existent semester ID
        generator = TimetableGenerationService(
            semester_id=uuid.uuid4(),
            academic_year="2026-2027",
            created_by=self.staff_user,
        )
        result = generator.generate()
        self.assertEqual(result["status"], "INFEASIBLE")

        self.assertEqual(Timetable.objects.count(), initial_tt_count)
        self.assertEqual(TimetableSlot.objects.count(), initial_slot_count)


class TimetableNestedSlotsAPITests(APITestCase):
    """
    Focused API tests for GET /api/v1/timetables/{id}/slots/
    """

    def setUp(self):
        from accounts.models import TeacherProfile
        from academics.models import (
            Classroom,
            Department,
            Division,
            Program,
            Semester,
            Subject,
            TeacherSubject,
            Timetable,
            TimetableSlot,
        )

        self.staff_user = UserModel.objects.create_user(
            username="slot_staff",
            email="slot_staff@smarttime.ai",
            password="Password123!",
            role=User.Role.STAFF,
        )
        self.teacher_user = UserModel.objects.create_user(
            username="slot_teacher",
            email="slot_teacher@smarttime.ai",
            password="Password123!",
            role=User.Role.TEACHER,
        )
        self.student_user = UserModel.objects.create_user(
            username="slot_student",
            email="slot_student@smarttime.ai",
            password="Password123!",
            role=User.Role.STUDENT,
        )

        self.dept = Department.objects.create(name="Slot Dept", code="SLOT_DEPT")
        self.prog = Program.objects.create(department=self.dept, name="B.Tech Slot", code="BTECH_SLOT")
        self.semester = Semester.objects.create(program=self.prog, number=1, academic_year="2026-2027")
        self.division = Division.objects.create(semester=self.semester, name="Div-S1", capacity=60)
        self.subj = Subject.objects.create(program=self.prog, name="Maths", code="SLOT_MATH", type="LECTURE")

        self.teacher_profile = TeacherProfile.objects.create(
            user=self.teacher_user,
            employee_code="EMP_SLOT_01",
            department=self.dept,
            designation="Professor",
        )
        TeacherSubject.objects.create(teacher=self.teacher_profile, subject=self.subj)
        self.classroom = Classroom.objects.create(building="Block A", room_number="101", capacity=60)

        # Draft Timetable
        self.draft_timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=1,
            status=Timetable.Status.DRAFT,
            created_by=self.staff_user,
        )
        self.draft_slot = TimetableSlot.objects.create(
            timetable=self.draft_timetable,
            division=self.division,
            subject=self.subj,
            teacher=self.teacher_profile,
            classroom=self.classroom,
            day="MONDAY",
            start_time="09:00:00",
            end_time="10:00:00",
            session_type="LECTURE",
        )

        # Published Timetable
        self.pub_timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=2,
            status=Timetable.Status.PUBLISHED,
            created_by=self.staff_user,
        )
        self.pub_slot = TimetableSlot.objects.create(
            timetable=self.pub_timetable,
            division=self.division,
            subject=self.subj,
            teacher=self.teacher_profile,
            classroom=self.classroom,
            day="TUESDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type="LECTURE",
        )

    def test_1_staff_can_get_timetable_slots(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        url = reverse("academics:timetable-slots", kwargs={"pk": self.draft_timetable.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]["id"], str(self.draft_slot.id))
        self.assertEqual(res.data[0]["day"], "MONDAY")

    def test_2_teacher_and_student_permission_behavior(self):
        # Teacher accessing DRAFT timetable -> 404 (hidden for non-staff)
        refresh_t = RefreshToken.for_user(self.teacher_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh_t.access_token}")

        draft_url = reverse("academics:timetable-slots", kwargs={"pk": self.draft_timetable.id})
        res_t_draft = self.client.get(draft_url)
        self.assertEqual(res_t_draft.status_code, status.HTTP_404_NOT_FOUND)

        # Teacher accessing PUBLISHED timetable -> 200 OK
        pub_url = reverse("academics:timetable-slots", kwargs={"pk": self.pub_timetable.id})
        res_t_pub = self.client.get(pub_url)
        self.assertEqual(res_t_pub.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_t_pub.data), 1)
        self.assertEqual(res_t_pub.data[0]["id"], str(self.pub_slot.id))

        # Student accessing DRAFT timetable -> 404
        refresh_s = RefreshToken.for_user(self.student_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh_s.access_token}")
        res_s_draft = self.client.get(draft_url)
        self.assertEqual(res_s_draft.status_code, status.HTTP_404_NOT_FOUND)

        # Student accessing PUBLISHED timetable -> 200 OK
        res_s_pub = self.client.get(pub_url)
        self.assertEqual(res_s_pub.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_s_pub.data), 1)

    def test_3_invalid_timetable_id_returns_404(self):
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        url = reverse("academics:timetable-slots", kwargs={"pk": uuid.uuid4()})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


class TimetablePublishingAPITests(APITestCase):
    """
    Focused API tests for timetable publishing lifecycle and archiving previous versions.
    """

    def setUp(self):
        from academics.models import (
            Department,
            Program,
            Semester,
            Timetable,
        )

        self.staff_user = UserModel.objects.create_user(
            username="pub_staff",
            email="pub_staff@smarttime.ai",
            password="Password123!",
            role=User.Role.STAFF,
        )
        refresh = RefreshToken.for_user(self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        self.dept = Department.objects.create(name="Publish Dept", code="PUB_DEPT")
        self.prog = Program.objects.create(department=self.dept, name="B.Tech Publish", code="BTECH_PUB")
        self.semester = Semester.objects.create(program=self.prog, number=1, academic_year="2026-2027")

        self.v1_timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=1,
            status=Timetable.Status.PUBLISHED,
            created_by=self.staff_user,
        )
        self.v1_published_at = self.v1_timetable.published_at

        self.v2_timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=2,
            status=Timetable.Status.DRAFT,
            created_by=self.staff_user,
        )

    def test_publishing_v2_archives_already_published_v1_and_v2_becomes_published(self):
        url = reverse("academics:timetable-publish", kwargs={"pk": self.v2_timetable.id})
        res = self.client.post(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.v1_timetable.refresh_from_db()
        self.v2_timetable.refresh_from_db()

        # v2 is now PUBLISHED
        self.assertEqual(self.v2_timetable.status, Timetable.Status.PUBLISHED)
        self.assertIsNotNone(self.v2_timetable.published_at)

        # v1 is now ARCHIVED
        self.assertEqual(self.v1_timetable.status, Timetable.Status.ARCHIVED)
        # v1 published_at is preserved as historical data
        self.assertEqual(self.v1_timetable.published_at, self.v1_published_at)

        # Only one PUBLISHED timetable exists for this semester + academic_year
        published_count = Timetable.objects.filter(
            semester=self.semester,
            academic_year="2026-2027",
            status=Timetable.Status.PUBLISHED,
        ).count()
        self.assertEqual(published_count, 1)

    def test_handles_multiple_existing_published_versions_cleanly(self):
        # Create a v3 that is also PUBLISHED to simulate dirty existing data
        v3_timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=3,
            status=Timetable.Status.PUBLISHED,
            created_by=self.staff_user,
        )
        # We now have v1 and v3 PUBLISHED, v2 DRAFT
        self.assertEqual(
            Timetable.objects.filter(
                semester=self.semester,
                academic_year="2026-2027",
                status=Timetable.Status.PUBLISHED,
            ).count(),
            2,
        )

        # Publish v2
        url = reverse("academics:timetable-publish", kwargs={"pk": self.v2_timetable.id})
        res = self.client.post(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.v1_timetable.refresh_from_db()
        self.v2_timetable.refresh_from_db()
        v3_timetable.refresh_from_db()

        self.assertEqual(self.v1_timetable.status, Timetable.Status.ARCHIVED)
        self.assertEqual(v3_timetable.status, Timetable.Status.ARCHIVED)
        self.assertEqual(self.v2_timetable.status, Timetable.Status.PUBLISHED)

        self.assertEqual(
            Timetable.objects.filter(
                semester=self.semester,
                academic_year="2026-2027",
                status=Timetable.Status.PUBLISHED,
            ).count(),
            1,
        )

    def test_publishing_already_published_timetable_is_safe_and_idempotent(self):
        # v1 is already PUBLISHED
        url = reverse("academics:timetable-publish", kwargs={"pk": self.v1_timetable.id})
        res = self.client.post(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.v1_timetable.refresh_from_db()
        self.assertEqual(self.v1_timetable.status, Timetable.Status.PUBLISHED)
        self.assertEqual(self.v1_timetable.published_at, self.v1_published_at)

        self.v2_timetable.refresh_from_db()
        self.assertEqual(self.v2_timetable.status, Timetable.Status.DRAFT)

        self.assertEqual(
            Timetable.objects.filter(
                semester=self.semester,
                academic_year="2026-2027",
                status=Timetable.Status.PUBLISHED,
            ).count(),
            1,
        )

    def test_transaction_rollback_on_failure(self):
        from unittest.mock import patch

        url = reverse("academics:timetable-publish", kwargs={"pk": self.v2_timetable.id})

        # Simulate unexpected error during save of timetable
        with patch.object(Timetable, "save", side_effect=RuntimeError("Simulated DB error")):
            with self.assertRaises(RuntimeError):
                self.client.post(url)

        self.v1_timetable.refresh_from_db()
        self.v2_timetable.refresh_from_db()

        # State remains unchanged due to rollback
        self.assertEqual(self.v1_timetable.status, Timetable.Status.PUBLISHED)
        self.assertEqual(self.v2_timetable.status, Timetable.Status.DRAFT)


class TimetableOptimizationSolverTests(APITestCase):
    """
    Phase 8: Tests for OR-Tools CP-SAT Soft Constraints and Timetable Optimization.
    """

    def setUp(self):
        self.teacher_1 = "t-11111111-1111-1111-1111-111111111111"
        self.teacher_2 = "t-22222222-2222-2222-2222-222222222222"
        self.room_cr1 = "r-cr111111-1111-1111-1111-111111111111"
        self.room_cr2 = "r-cr222222-2222-2222-2222-222222222222"
        self.div_1 = "d-11111111-1111-1111-1111-111111111111"
        self.div_2 = "d-22222222-2222-2222-2222-222222222222"
        self.subj_math = "s-math1111-1111-1111-1111-111111111111"
        self.subj_phy = "s-phy22222-2222-2222-2222-222222222222"

    def test_1_hard_constraints_enforced_under_optimization(self):
        """Hard constraints (e.g. teacher overlap) are strictly enforced even with optimization enabled."""
        from academics.services.timetable_solver import SolverConfig, TimetableSolver

        # 1 slot available, 2 sessions with same teacher -> Infeasible
        config = SolverConfig(
            days=["MONDAY"],
            daily_start_time="09:00:00",
            daily_end_time="10:00:00",
            slot_duration_minutes=60,
        )
        solver = TimetableSolver(config=config)
        input_data = {
            "divisions": [{"id": self.div_1, "name": "Div-A"}, {"id": self.div_2, "name": "Div-B"}],
            "teachers": [
                {
                    "id": self.teacher_1,
                    "name": "Prof. T1",
                    "employee_code": "T01",
                    "qualified_subject_ids": [self.subj_math],
                }
            ],
            "rooms": [
                {"id": self.room_cr1, "name": "CR1", "room_type": "CLASSROOM", "status": "AVAILABLE"},
                {"id": self.room_cr2, "name": "CR2", "room_type": "CLASSROOM", "status": "AVAILABLE"},
            ],
            "sessions_to_schedule": [
                {"id": "s1", "subject_id": self.subj_math, "division_id": self.div_1, "session_type": "LECTURE"},
                {"id": "s2", "subject_id": self.subj_math, "division_id": self.div_2, "session_type": "LECTURE"},
            ],
        }
        res = solver.solve(input_data)
        self.assertEqual(res["status"], TimetableSolver.STATUS_INFEASIBLE)

    def test_2_subject_distribution_soft_constraint(self):
        """Repeated sessions of the same subject are spread across different days when possible."""
        from academics.services.timetable_solver import (
            OptimizationConfig,
            SolverConfig,
            TimetableSolver,
        )

        # 2 days (MONDAY, TUESDAY), 2 slots each day (9-10, 10-11).
        # 2 sessions of Maths for Div-A.
        # Subject distribution should place them on 2 different days (cost = 0).
        config = SolverConfig(
            days=["MONDAY", "TUESDAY"],
            daily_start_time="09:00:00",
            daily_end_time="11:00:00",
            slot_duration_minutes=60,
            optimization=OptimizationConfig(
                enabled=True,
                subject_distribution_weight=50,
                consecutive_subject_weight=0,
                teacher_consecutive_weight=0,
                division_gap_weight=0,
                daily_load_balance_weight=0,
            ),
        )
        solver = TimetableSolver(config=config)
        input_data = {
            "divisions": [{"id": self.div_1, "name": "Div-A"}],
            "teachers": [
                {"id": self.teacher_1, "name": "Prof. T1", "employee_code": "T01", "qualified_subject_ids": [self.subj_math]}
            ],
            "rooms": [{"id": self.room_cr1, "name": "CR1", "room_type": "CLASSROOM", "status": "AVAILABLE"}],
            "sessions_to_schedule": [
                {"id": "m1", "subject_id": self.subj_math, "division_id": self.div_1, "session_type": "LECTURE"},
                {"id": "m2", "subject_id": self.subj_math, "division_id": self.div_1, "session_type": "LECTURE"},
            ],
        }
        res = solver.solve(input_data)
        self.assertEqual(res["status"], TimetableSolver.STATUS_OPTIMAL)
        self.assertEqual(res["objective_value"], 0)
        days = {a["day"] for a in res["assignments"]}
        self.assertEqual(len(days), 2)

    def test_3_consecutive_same_subject_penalty(self):
        """Consecutive sessions of the same subject receive a penalty."""
        from academics.services.timetable_solver import (
            OptimizationConfig,
            SolverConfig,
            TimetableSolver,
        )

        # 1 day (MONDAY), 3 slots (09-10, 10-11, 11-12).
        # Maths session 1, Maths session 2, Physics session 1 for Div-A.
        # Avoid consecutive Maths if interleaved with Physics: [Maths, Physics, Maths].
        config = SolverConfig(
            days=["MONDAY"],
            daily_start_time="09:00:00",
            daily_end_time="12:00:00",
            slot_duration_minutes=60,
            optimization=OptimizationConfig(
                enabled=True,
                subject_distribution_weight=0,
                consecutive_subject_weight=50,
                teacher_consecutive_weight=0,
                division_gap_weight=0,
                daily_load_balance_weight=0,
            ),
        )
        solver = TimetableSolver(config=config)
        input_data = {
            "divisions": [{"id": self.div_1, "name": "Div-A"}],
            "teachers": [
                {"id": self.teacher_1, "name": "Prof. T1", "employee_code": "T01", "qualified_subject_ids": [self.subj_math, self.subj_phy]}
            ],
            "rooms": [{"id": self.room_cr1, "name": "CR1", "room_type": "CLASSROOM", "status": "AVAILABLE"}],
            "sessions_to_schedule": [
                {"id": "m1", "subject_id": self.subj_math, "division_id": self.div_1, "session_type": "LECTURE"},
                {"id": "m2", "subject_id": self.subj_math, "division_id": self.div_1, "session_type": "LECTURE"},
                {"id": "p1", "subject_id": self.subj_phy, "division_id": self.div_1, "session_type": "LECTURE"},
            ],
        }
        res = solver.solve(input_data)
        self.assertEqual(res["status"], TimetableSolver.STATUS_OPTIMAL)
        self.assertEqual(res["objective_value"], 0)
        assignments_by_time = {a["start_time"]: a["subject_id"] for a in res["assignments"]}
        self.assertEqual(assignments_by_time["10:00:00"], self.subj_phy)

    def test_4_teacher_consecutive_classes_penalty(self):
        """Teacher back-to-back classes receive a penalty, favoring separated slots when available."""
        from academics.services.timetable_solver import (
            OptimizationConfig,
            SolverConfig,
            TimetableSolver,
        )

        config = SolverConfig(
            days=["MONDAY", "TUESDAY"],
            daily_start_time="09:00:00",
            daily_end_time="11:00:00",
            slot_duration_minutes=60,
            optimization=OptimizationConfig(
                enabled=True,
                subject_distribution_weight=0,
                consecutive_subject_weight=0,
                teacher_consecutive_weight=50,
                division_gap_weight=0,
                daily_load_balance_weight=0,
            ),
        )
        solver = TimetableSolver(config=config)
        input_data = {
            "divisions": [{"id": self.div_1, "name": "Div-A"}, {"id": self.div_2, "name": "Div-B"}],
            "teachers": [
                {"id": self.teacher_1, "name": "Prof. T1", "employee_code": "T01", "qualified_subject_ids": [self.subj_math]}
            ],
            "rooms": [{"id": self.room_cr1, "name": "CR1", "room_type": "CLASSROOM", "status": "AVAILABLE"}],
            "sessions_to_schedule": [
                {"id": "s1", "subject_id": self.subj_math, "division_id": self.div_1, "session_type": "LECTURE"},
                {"id": "s2", "subject_id": self.subj_math, "division_id": self.div_2, "session_type": "LECTURE"},
            ],
        }
        res = solver.solve(input_data)
        self.assertEqual(res["status"], TimetableSolver.STATUS_OPTIMAL)
        self.assertEqual(res["objective_value"], 0)

    def test_5_division_gaps_penalty(self):
        """Gaps between classes for a division receive a penalty, favoring contiguous schedules."""
        from academics.services.timetable_solver import (
            OptimizationConfig,
            SolverConfig,
            TimetableSolver,
        )

        config = SolverConfig(
            days=["MONDAY"],
            daily_start_time="09:00:00",
            daily_end_time="12:00:00",
            slot_duration_minutes=60,
            optimization=OptimizationConfig(
                enabled=True,
                subject_distribution_weight=0,
                consecutive_subject_weight=0,
                teacher_consecutive_weight=0,
                division_gap_weight=50,
                daily_load_balance_weight=0,
            ),
        )
        solver = TimetableSolver(config=config)
        input_data = {
            "divisions": [{"id": self.div_1, "name": "Div-A"}],
            "teachers": [
                {"id": self.teacher_1, "name": "Prof. T1", "employee_code": "T01", "qualified_subject_ids": [self.subj_math, self.subj_phy]}
            ],
            "rooms": [{"id": self.room_cr1, "name": "CR1", "room_type": "CLASSROOM", "status": "AVAILABLE"}],
            "sessions_to_schedule": [
                {"id": "s1", "subject_id": self.subj_math, "division_id": self.div_1, "session_type": "LECTURE"},
                {"id": "s2", "subject_id": self.subj_phy, "division_id": self.div_1, "session_type": "LECTURE"},
            ],
        }
        res = solver.solve(input_data)
        self.assertEqual(res["status"], TimetableSolver.STATUS_OPTIMAL)
        self.assertEqual(res["objective_value"], 0)
        times = sorted([a["start_time"] for a in res["assignments"]])
        self.assertIn(times, [["09:00:00", "10:00:00"], ["10:00:00", "11:00:00"]])

    def test_6_daily_load_imbalance_penalty(self):
        """Uneven daily load across days receives a penalty, favoring evenly balanced schedules."""
        from academics.services.timetable_solver import (
            OptimizationConfig,
            SolverConfig,
            TimetableSolver,
        )

        config = SolverConfig(
            days=["MONDAY", "TUESDAY"],
            daily_start_time="09:00:00",
            daily_end_time="11:00:00",
            slot_duration_minutes=60,
            optimization=OptimizationConfig(
                enabled=True,
                subject_distribution_weight=0,
                consecutive_subject_weight=0,
                teacher_consecutive_weight=0,
                division_gap_weight=0,
                daily_load_balance_weight=50,
            ),
        )
        solver = TimetableSolver(config=config)
        input_data = {
            "divisions": [{"id": self.div_1, "name": "Div-A"}],
            "teachers": [
                {"id": self.teacher_1, "name": "Prof. T1", "employee_code": "T01", "qualified_subject_ids": [self.subj_math, self.subj_phy]}
            ],
            "rooms": [{"id": self.room_cr1, "name": "CR1", "room_type": "CLASSROOM", "status": "AVAILABLE"}],
            "sessions_to_schedule": [
                {"id": "s1", "subject_id": self.subj_math, "division_id": self.div_1, "session_type": "LECTURE"},
                {"id": "s2", "subject_id": self.subj_phy, "division_id": self.div_1, "session_type": "LECTURE"},
            ],
        }
        res = solver.solve(input_data)
        self.assertEqual(res["status"], TimetableSolver.STATUS_OPTIMAL)
        self.assertEqual(res["objective_value"], 0)
        days = [a["day"] for a in res["assignments"]]
        self.assertIn("MONDAY", days)
        self.assertIn("TUESDAY", days)

    def test_7_optimization_does_not_make_infeasible_problem_feasible(self):
        """Infeasible hard constraints remain INFEASIBLE when optimization is enabled."""
        from academics.services.timetable_solver import (
            OptimizationConfig,
            SolverConfig,
            TimetableSolver,
        )

        config = SolverConfig(
            days=["MONDAY"],
            daily_start_time="09:00:00",
            daily_end_time="10:00:00",
            slot_duration_minutes=60,
            optimization=OptimizationConfig(enabled=True),
        )
        solver = TimetableSolver(config=config)
        input_data = {
            "divisions": [{"id": self.div_1, "name": "Div-A"}],
            "teachers": [{"id": self.teacher_1, "name": "Prof. T1", "employee_code": "T01", "qualified_subject_ids": [self.subj_math]}],
            "rooms": [{"id": self.room_cr1, "name": "CR1", "room_type": "CLASSROOM", "status": "AVAILABLE"}],
            "sessions_to_schedule": [
                {"id": "s1", "subject_id": self.subj_math, "division_id": self.div_1, "session_type": "LECTURE"},
                {"id": "s2", "subject_id": self.subj_math, "division_id": self.div_1, "session_type": "LECTURE"},
            ],
        }
        res = solver.solve(input_data)
        self.assertEqual(res["status"], TimetableSolver.STATUS_INFEASIBLE)

    def test_8_feasible_problem_returns_valid_solution_with_all_assignments(self):
        """A feasible problem returns all requested assignments correctly."""
        from academics.services.timetable_solver import (
            OptimizationConfig,
            SolverConfig,
            TimetableSolver,
        )

        config = SolverConfig(
            days=["MONDAY", "TUESDAY", "WEDNESDAY"],
            daily_start_time="09:00:00",
            daily_end_time="12:00:00",
            slot_duration_minutes=60,
            optimization=OptimizationConfig(enabled=True),
        )
        solver = TimetableSolver(config=config)
        input_data = {
            "divisions": [{"id": self.div_1, "name": "Div-A"}],
            "teachers": [
                {"id": self.teacher_1, "name": "Prof. T1", "employee_code": "T01", "qualified_subject_ids": [self.subj_math, self.subj_phy]}
            ],
            "rooms": [{"id": self.room_cr1, "name": "CR1", "room_type": "CLASSROOM", "status": "AVAILABLE"}],
            "sessions_to_schedule": [
                {"id": "s1", "subject_id": self.subj_math, "division_id": self.div_1, "session_type": "LECTURE"},
                {"id": "s2", "subject_id": self.subj_phy, "division_id": self.div_1, "session_type": "LECTURE"},
            ],
        }
        res = solver.solve(input_data)
        self.assertIn(res["status"], [TimetableSolver.STATUS_OPTIMAL, TimetableSolver.STATUS_FEASIBLE])
        self.assertEqual(len(res["assignments"]), 2)
        self.assertIsNotNone(res.get("objective_value"))

    def test_9_solver_status_reported_correctly(self):
        """Solver status accurately distinguishes between OPTIMAL, INFEASIBLE, and UNKNOWN."""
        from academics.services.timetable_solver import (
            OptimizationConfig,
            SolverConfig,
            TimetableSolver,
        )

        solver = TimetableSolver()
        input_data = {
            "divisions": [{"id": self.div_1, "name": "Div-A"}],
            "teachers": [{"id": self.teacher_1, "name": "Prof. T1", "employee_code": "T01", "qualified_subject_ids": [self.subj_math]}],
            "rooms": [{"id": self.room_cr1, "name": "CR1", "room_type": "CLASSROOM", "status": "AVAILABLE"}],
            "sessions_to_schedule": [
                {"id": "s1", "subject_id": self.subj_math, "division_id": self.div_1, "session_type": "LECTURE"}
            ],
        }
        res = solver.solve(input_data)
        self.assertEqual(res["status"], TimetableSolver.STATUS_OPTIMAL)

        input_infeasible = {
            "divisions": [{"id": self.div_1, "name": "Div-A"}],
            "teachers": [{"id": self.teacher_1, "name": "Prof. T1", "employee_code": "T01", "qualified_subject_ids": []}],
            "rooms": [{"id": self.room_cr1, "name": "CR1", "room_type": "CLASSROOM", "status": "AVAILABLE"}],
            "sessions_to_schedule": [
                {"id": "s1", "subject_id": self.subj_math, "division_id": self.div_1, "session_type": "LECTURE"}
            ],
        }
        res_inf = solver.solve(input_infeasible)
        self.assertEqual(res_inf["status"], TimetableSolver.STATUS_INFEASIBLE)

    def test_10_optimization_can_be_disabled_without_breaking_generation(self):
        """Optimization can be toggled off, reverting to pure constraint satisfaction mode."""
        from academics.services.timetable_solver import (
            OptimizationConfig,
            SolverConfig,
            TimetableSolver,
        )

        config = SolverConfig(optimization=OptimizationConfig(enabled=False))
        solver = TimetableSolver(config=config)
        input_data = {
            "divisions": [{"id": self.div_1, "name": "Div-A"}],
            "teachers": [{"id": self.teacher_1, "name": "Prof. T1", "employee_code": "T01", "qualified_subject_ids": [self.subj_math]}],
            "rooms": [{"id": self.room_cr1, "name": "CR1", "room_type": "CLASSROOM", "status": "AVAILABLE"}],
            "sessions_to_schedule": [
                {"id": "s1", "subject_id": self.subj_math, "division_id": self.div_1, "session_type": "LECTURE"}
            ],
        }
        res = solver.solve(input_data)
        self.assertIn(res["status"], [TimetableSolver.STATUS_OPTIMAL, TimetableSolver.STATUS_FEASIBLE])
        self.assertIsNone(res.get("objective_value"))
        self.assertEqual(len(res["assignments"]), 1)


class NaturalLanguageConstraintParserTests(APITestCase):
    """
    Phase 9A: Unit tests for Natural-Language Constraint Parsing and Validation.
    """

    def setUp(self):
        from academics.services.constraint_parser import (
            ConstraintMode,
            ConstraintParserService,
            ConstraintType,
            ParsingContext,
            StructuredConstraint,
            TimeRange,
        )

        self.parser = ConstraintParserService()
        self.context = ParsingContext(
            teachers=[
                {"id": "t-1", "name": "Amit Patil", "employee_code": "EMP01"},
                {"id": "t-2", "name": "Amit Sharma", "employee_code": "EMP02"},
                {"id": "t-3", "name": "Rohan Deshmukh", "employee_code": "EMP03"},
            ],
            subjects=[
                {"id": "s-1", "name": "Java Programming", "code": "CS801"},
                {"id": "s-2", "name": "Data Structures", "code": "CS802"},
            ],
            divisions=[
                {"id": "d-1", "name": "Div-A"},
                {"id": "d-2", "name": "Div-B"},
            ],
            allowed_days=["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"],
        )

    def test_1_valid_teacher_time_restriction(self):
        """Input: 'Amit Patil ko Monday morning classes mat do.' -> valid TEACHER_TIME_RESTRICTION"""
        res = self.parser.parse("Amit Patil ko Monday morning classes mat do.", context=self.context)
        self.assertTrue(res.success, f"Errors: {res.errors}")
        c = res.constraint
        self.assertEqual(c.constraint_type, "TEACHER_TIME_RESTRICTION")
        self.assertEqual(c.teacher, "Amit Patil")
        self.assertEqual(c.teacher_id, "t-1")
        self.assertEqual(c.day, "MONDAY")
        self.assertEqual(c.time_range, "MORNING")
        self.assertEqual(c.start_time, "09:00")
        self.assertEqual(c.end_time, "12:00")
        self.assertEqual(c.mode, "AVOID")

    def test_2_valid_subject_day_restriction(self):
        """Input: 'Java ko Monday ko avoid karo.' -> valid SUBJECT_DAY_RESTRICTION"""
        res = self.parser.parse("Java ko Monday ko avoid karo.", context=self.context)
        self.assertTrue(res.success, f"Errors: {res.errors}")
        c = res.constraint
        self.assertEqual(c.constraint_type, "SUBJECT_DAY_RESTRICTION")
        self.assertEqual(c.subject, "Java Programming")
        self.assertEqual(c.subject_id, "s-1")
        self.assertEqual(c.day, "MONDAY")
        self.assertEqual(c.mode, "AVOID")

    def test_3_valid_session_time_preference(self):
        """Input: 'Practical classes afternoon mein prefer karo.' -> valid SESSION_TIME_PREFERENCE"""
        res = self.parser.parse("Practical classes afternoon mein prefer karo.")
        self.assertTrue(res.success, f"Errors: {res.errors}")
        c = res.constraint
        self.assertEqual(c.constraint_type, "SESSION_TIME_PREFERENCE")
        self.assertEqual(c.session_type, "PRACTICAL")
        self.assertEqual(c.time_range, "AFTERNOON")
        self.assertEqual(c.start_time, "12:00")
        self.assertEqual(c.end_time, "16:00")
        self.assertEqual(c.mode, "PREFER")

    def test_4_invalid_day_returns_error(self):
        """Invalid day strings are rejected with structured errors."""
        data = {
            "constraint_type": "SUBJECT_DAY_RESTRICTION",
            "subject": "Java",
            "day": "FUNDAY",
            "mode": "AVOID",
        }
        res = self.parser.validate_constraint_data(data)
        self.assertFalse(res.success)
        self.assertTrue(any("Invalid day" in err for err in res.errors))

    def test_5_invalid_time_format_and_range_returns_error(self):
        """Malformed times or start_time >= end_time are rejected."""
        # Malformed time format
        data1 = {
            "constraint_type": "TEACHER_TIME_RESTRICTION",
            "teacher": "Rohan",
            "start_time": "25:00",
            "end_time": "12:00",
        }
        res1 = self.parser.validate_constraint_data(data1)
        self.assertFalse(res1.success)
        self.assertTrue(any("Invalid time" in err for err in res1.errors))

        # start_time >= end_time
        data2 = {
            "constraint_type": "TEACHER_TIME_RESTRICTION",
            "teacher": "Rohan",
            "start_time": "14:00",
            "end_time": "10:00",
        }
        res2 = self.parser.validate_constraint_data(data2)
        self.assertFalse(res2.success)
        self.assertTrue(any("strictly before" in err for err in res2.errors))

    def test_6_unsupported_constraint_type_returns_error(self):
        """Unsupported constraint types are rejected."""
        data = {
            "constraint_type": "RANDOM_UNSUPPORTED_TYPE",
            "teacher": "Amit",
        }
        res = self.parser.validate_constraint_data(data)
        self.assertFalse(res.success)
        self.assertTrue(any("Unsupported constraint_type" in err for err in res.errors))

    def test_7_ambiguous_and_unknown_entities(self):
        """Ambiguous or unknown entity references return structured validation errors."""
        # 'Amit' matches Amit Patil (t-1) and Amit Sharma (t-2) in context
        res_ambiguous = self.parser.parse("Amit ko Monday morning classes mat do.", context=self.context)
        self.assertFalse(res_ambiguous.success)
        self.assertTrue(any("Ambiguous teacher reference" in err for err in res_ambiguous.errors))

        # 'Prof. XYZ' does not exist in context
        res_unknown = self.parser.parse("Prof. XYZ ko Monday ko avoid karo.", context=self.context)
        self.assertFalse(res_unknown.success)
        self.assertTrue(any("Unknown teacher" in err for err in res_unknown.errors))

    def test_8_malformed_llm_output_handling(self):
        """Non-dictionary or invalid JSON LLM outputs are handled gracefully."""
        # Non-dict
        res1 = self.parser.parse("test", llm_output=["not a dict"])
        self.assertFalse(res1.success)
        self.assertTrue(any("Malformed constraint data" in err for err in res1.errors))

        # Invalid JSON string
        res2 = self.parser.parse("test", llm_output="{broken json")
        self.assertFalse(res2.success)
        self.assertTrue(any("Malformed LLM JSON output" in err for err in res2.errors))

    def test_9_avoid_vs_prefer_modes(self):
        """AVOID vs PREFER modes are preserved and validated correctly."""
        # PREFER mode
        data_pref = {
            "constraint_type": "SUBJECT_TIME_PREFERENCE",
            "subject": "Data Structures",
            "time_range": "MORNING",
            "mode": "PREFER",
        }
        res_pref = self.parser.validate_constraint_data(data_pref)
        self.assertTrue(res_pref.success)
        self.assertEqual(res_pref.constraint.mode, "PREFER")

        # Invalid mode
        data_inv = {
            "constraint_type": "SUBJECT_TIME_PREFERENCE",
            "subject": "Data Structures",
            "time_range": "MORNING",
            "mode": "INVALID_MODE",
        }
        res_inv = self.parser.validate_constraint_data(data_inv)
        self.assertFalse(res_inv.success)
        self.assertTrue(any("Invalid mode" in err for err in res_inv.errors))

    def test_10_llm_provider_integration(self):
        """Custom LLM provider hook is called and its output validated."""
        from academics.services.constraint_parser import ConstraintParserService

        def mock_llm_provider(text, context):
            return {
                "constraint_type": "DIVISION_TIME_RESTRICTION",
                "division": "Div-A",
                "day": "FRIDAY",
                "time_range": "AFTERNOON",
                "mode": "AVOID",
            }

        custom_parser = ConstraintParserService(llm_provider=mock_llm_provider)
        res = custom_parser.parse("Div-A Friday afternoon classes avoid karo.", context=self.context)
        self.assertTrue(res.success)
        self.assertEqual(res.constraint.constraint_type, "DIVISION_TIME_RESTRICTION")
        self.assertEqual(res.constraint.division, "Div-A")
        self.assertEqual(res.constraint.division_id, "d-1")
        self.assertEqual(res.constraint.day, "FRIDAY")
        self.assertEqual(res.constraint.time_range, "AFTERNOON")
        self.assertEqual(res.constraint.mode, "AVOID")


class ConstraintValidatorServiceTests(APITestCase):
    """
    Unit and integration tests for Phase 9B ConstraintValidatorService.
    """

    def setUp(self):
        self.validator = ConstraintValidatorService()

        # Create test department, program, semester
        self.dept = Department.objects.create(name="Computer Engineering", code="CE_V")
        self.program = Program.objects.create(
            department=self.dept,
            name="B.Tech CS",
            code="BTCS_V",
            duration_years=4,
        )
        self.semester = Semester.objects.create(
            program=self.program,
            number=5,
            academic_year="2026-2027",
        )

        # Create divisions and batches
        self.div_a = Division.objects.create(semester=self.semester, name="A", capacity=60)
        self.div_b = Division.objects.create(semester=self.semester, name="B", capacity=60)
        self.batch_a1 = PracticalBatch.objects.create(division=self.div_a, name="B1", capacity=20)
        self.batch_b1 = PracticalBatch.objects.create(division=self.div_b, name="B1", capacity=20)

        # Create subjects
        self.subject_dsa = Subject.objects.create(
            program=self.program,
            name="Data Structures",
            code="CS301_V",
            type=Subject.Type.LECTURE,
            credits=Decimal("4.0"),
            weekly_lectures=4,
        )
        self.subject_dbms = Subject.objects.create(
            program=self.program,
            name="Database Systems",
            code="CS302_V",
            type=Subject.Type.LECTURE,
            credits=Decimal("4.0"),
            weekly_lectures=4,
        )

        # Create teachers
        self.user_teacher_1 = UserModel.objects.create_user(
            username="teacher_amit_v",
            email="amit.v@example.com",
            first_name="Amit",
            last_name="Patil",
            role=UserModel.Role.TEACHER,
        )
        self.teacher_amit = TeacherProfile.objects.create(
            user=self.user_teacher_1,
            employee_code="EMP_AMIT_V",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )

        self.user_teacher_2 = UserModel.objects.create_user(
            username="teacher_amit_kumar_v",
            email="amit.k.v@example.com",
            first_name="Amit",
            last_name="Kumar",
            role=UserModel.Role.TEACHER,
        )
        self.teacher_amit_k = TeacherProfile.objects.create(
            user=self.user_teacher_2,
            employee_code="EMP_AMITK_V",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )

        self.user_inactive_teacher = UserModel.objects.create_user(
            username="teacher_inactive_v",
            email="inactive.v@example.com",
            first_name="Inactive",
            last_name="Teacher",
            role=UserModel.Role.TEACHER,
        )
        self.teacher_inactive = TeacherProfile.objects.create(
            user=self.user_inactive_teacher,
            employee_code="EMP_INACT_V",
            department=self.dept,
            status=TeacherProfile.Status.INACTIVE,
        )

    def test_1_valid_teacher_time_restriction(self):
        """1. Valid teacher time restriction normalizes to teacher_id and 24-hr times."""
        raw = {
            "constraint_type": "TEACHER_TIME_RESTRICTION",
            "teacher": "Amit Patil",
            "day": "MONDAY",
            "start_time": "09:00",
            "end_time": "12:00",
            "mode": "AVOID",
        }
        res = self.validator.validate(raw, semester=self.semester)
        self.assertTrue(res.valid)
        self.assertEqual(res.constraint["constraint_type"], "TEACHER_TIME_RESTRICTION")
        self.assertEqual(res.constraint["teacher_id"], str(self.teacher_amit.id))
        self.assertEqual(res.constraint["day"], "MONDAY")
        self.assertEqual(res.constraint["start_time"], "09:00")
        self.assertEqual(res.constraint["end_time"], "12:00")
        self.assertEqual(res.constraint["mode"], "AVOID")
        self.assertEqual(res.errors, [])

    def test_2_unknown_teacher(self):
        """2. Unknown teacher returns NOT_FOUND error."""
        raw = {
            "constraint_type": "TEACHER_TIME_RESTRICTION",
            "teacher": "NonExistentTeacher",
            "day": "MONDAY",
            "start_time": "09:00",
            "end_time": "12:00",
            "mode": "AVOID",
        }
        res = self.validator.validate(raw)
        self.assertFalse(res.valid)
        self.assertIsNone(res.constraint)
        self.assertTrue(any(e.code == "NOT_FOUND" and e.field == "teacher" for e in res.errors))

    def test_3_ambiguous_teacher_entity(self):
        """3. Ambiguous teacher name returns AMBIGUOUS error instead of picking arbitrarily."""
        raw = {
            "constraint_type": "TEACHER_TIME_RESTRICTION",
            "teacher": "Amit",  # Both Amit Patil and Amit Kumar match
            "day": "MONDAY",
            "start_time": "09:00",
            "end_time": "12:00",
            "mode": "AVOID",
        }
        res = self.validator.validate(raw)
        self.assertFalse(res.valid)
        self.assertIsNone(res.constraint)
        self.assertTrue(any(e.code == "AMBIGUOUS" and e.field == "teacher" for e in res.errors))

    def test_4_valid_subject_day_restriction(self):
        """4. Valid subject day restriction normalizes subject to subject_id."""
        raw = {
            "constraint_type": "SUBJECT_DAY_RESTRICTION",
            "subject": "CS301_V",
            "day": "FRIDAY",
            "mode": "AVOID",
        }
        res = self.validator.validate(raw, semester=self.semester)
        self.assertTrue(res.valid)
        self.assertEqual(res.constraint["subject_id"], str(self.subject_dsa.id))
        self.assertEqual(res.constraint["day"], "FRIDAY")
        self.assertEqual(res.constraint["mode"], "AVOID")

    def test_5_unknown_subject(self):
        """5. Unknown subject returns NOT_FOUND error."""
        raw = {
            "constraint_type": "SUBJECT_DAY_RESTRICTION",
            "subject": "Quantum Computing 999",
            "day": "FRIDAY",
            "mode": "AVOID",
        }
        res = self.validator.validate(raw, semester=self.semester)
        self.assertFalse(res.valid)
        self.assertTrue(any(e.code == "NOT_FOUND" and e.field == "subject" for e in res.errors))

    def test_6_valid_division_restriction(self):
        """6. Valid division restriction normalizes division to division_id."""
        raw = {
            "constraint_type": "DIVISION_TIME_RESTRICTION",
            "division": "Div A",
            "day": "TUESDAY",
            "start_time": "14:00",
            "end_time": "16:00",
            "mode": "AVOID",
        }
        res = self.validator.validate(raw, semester=self.semester)
        self.assertTrue(res.valid)
        self.assertEqual(res.constraint["division_id"], str(self.div_a.id))
        self.assertEqual(res.constraint["day"], "TUESDAY")
        self.assertEqual(res.constraint["start_time"], "14:00")
        self.assertEqual(res.constraint["end_time"], "16:00")

    def test_7_unknown_division(self):
        """7. Unknown division returns NOT_FOUND error."""
        raw = {
            "constraint_type": "DIVISION_TIME_RESTRICTION",
            "division": "Div Z",
            "day": "TUESDAY",
            "start_time": "14:00",
            "end_time": "16:00",
        }
        res = self.validator.validate(raw, semester=self.semester)
        self.assertFalse(res.valid)
        self.assertTrue(any(e.code == "NOT_FOUND" and e.field == "division" for e in res.errors))

    def test_8_batch_does_not_belong_to_division(self):
        """8. Practical batch belonging to another division returns RELATIONSHIP_MISMATCH."""
        raw = {
            "constraint_type": "DIVISION_TIME_RESTRICTION",
            "division_id": str(self.div_a.id),
            "batch_id": str(self.batch_b1.id),  # Belongs to Div B, not Div A
            "day": "WEDNESDAY",
            "start_time": "10:00",
            "end_time": "12:00",
        }
        res = self.validator.validate(raw, semester=self.semester)
        self.assertFalse(res.valid)
        self.assertTrue(any(e.code == "RELATIONSHIP_MISMATCH" and e.field == "batch" for e in res.errors))

    def test_9_invalid_day(self):
        """9. Invalid day value returns INVALID_VALUE error."""
        raw = {
            "constraint_type": "TEACHER_DAY_RESTRICTION",
            "teacher_id": str(self.teacher_amit.id),
            "day": "FUNDAY",
            "mode": "AVOID",
        }
        res = self.validator.validate(raw)
        self.assertFalse(res.valid)
        self.assertTrue(any(e.code == "INVALID_VALUE" and e.field == "day" for e in res.errors))

    def test_10_invalid_time_range(self):
        """10. Start time >= End time returns INVALID_TIME_RANGE error."""
        raw = {
            "constraint_type": "TEACHER_TIME_RESTRICTION",
            "teacher_id": str(self.teacher_amit.id),
            "day": "MONDAY",
            "start_time": "14:00",
            "end_time": "10:00",  # start > end
            "mode": "AVOID",
        }
        res = self.validator.validate(raw)
        self.assertFalse(res.valid)
        self.assertTrue(any(e.code == "INVALID_TIME_RANGE" and e.field == "time_range" for e in res.errors))

    def test_11_invalid_mode(self):
        """11. Invalid mode returns INVALID_MODE error."""
        raw = {
            "constraint_type": "TEACHER_DAY_RESTRICTION",
            "teacher_id": str(self.teacher_amit.id),
            "day": "MONDAY",
            "mode": "WANT_VERY_MUCH",
        }
        res = self.validator.validate(raw)
        self.assertFalse(res.valid)
        self.assertTrue(any(e.code == "INVALID_MODE" and e.field == "mode" for e in res.errors))

    def test_12_valid_prefer_constraint(self):
        """12. Valid PREFER constraint preserves mode=PREFER."""
        raw = {
            "constraint_type": "SUBJECT_TIME_PREFERENCE",
            "subject": "CS301_V",
            "time_range": "MORNING",
            "mode": "PREFER",
        }
        res = self.validator.validate(raw, semester=self.semester)
        self.assertTrue(res.valid)
        self.assertEqual(res.constraint["mode"], "PREFER")
        self.assertEqual(res.constraint["subject_id"], str(self.subject_dsa.id))
        self.assertEqual(res.constraint["start_time"], "09:00")
        self.assertEqual(res.constraint["end_time"], "12:00")

    def test_13_valid_avoid_constraint(self):
        """13. Valid AVOID constraint preserves mode=AVOID."""
        raw = {
            "constraint_type": "TEACHER_DAY_RESTRICTION",
            "teacher": "EMP_AMIT_V",
            "day": "THURSDAY",
            "mode": "AVOID",
        }
        res = self.validator.validate(raw)
        self.assertTrue(res.valid)
        self.assertEqual(res.constraint["mode"], "AVOID")
        self.assertEqual(res.constraint["teacher_id"], str(self.teacher_amit.id))
        self.assertEqual(res.constraint["day"], "THURSDAY")

    def test_14_normalization_resolves_names_and_codes_to_ids(self):
        """14. Normalization resolves names/codes to database UUID strings."""
        structured = StructuredConstraint(
            constraint_type="TEACHER_TIME_RESTRICTION",
            teacher="EMP_AMIT_V",
            day="MONDAY",
            time_range="MORNING",
            mode="AVOID",
        )
        res = self.validator.validate(structured)
        self.assertTrue(res.valid)
        self.assertEqual(res.constraint["teacher_id"], str(self.teacher_amit.id))
        self.assertEqual(res.constraint["start_time"], "09:00")
        self.assertEqual(res.constraint["end_time"], "12:00")
        self.assertEqual(res.constraint["day"], "MONDAY")

    def test_15_malformed_or_unsupported_constraint_type(self):
        """15. Malformed or unsupported constraint type returns UNSUPPORTED_TYPE error."""
        raw = {
            "constraint_type": "INVALID_CUSTOM_TYPE",
            "teacher": "Amit Patil",
        }
        res = self.validator.validate(raw)
        self.assertFalse(res.valid)
        self.assertTrue(any(e.code == "UNSUPPORTED_TYPE" and e.field == "constraint_type" for e in res.errors))

    def test_16_inactive_teacher_validation(self):
        """16. Inactive teacher returns INACTIVE_TEACHER validation error."""
        raw = {
            "constraint_type": "TEACHER_DAY_RESTRICTION",
            "teacher": "Inactive Teacher",
            "day": "MONDAY",
            "mode": "AVOID",
        }
        res = self.validator.validate(raw)
        self.assertFalse(res.valid)
        self.assertTrue(any(e.code == "INACTIVE_TEACHER" and e.field == "teacher" for e in res.errors))


class ConstraintIntegrationServiceTests(APITestCase):
    """
    Phase 9C: Integration tests for connecting natural-language constraints to OR-Tools solver.
    """

    def setUp(self):
        self.integration_service = ConstraintIntegrationService()

        # Create academic hierarchy
        self.dept = Department.objects.create(name="Computer Engineering", code="CE_9C")
        self.program = Program.objects.create(
            department=self.dept,
            name="B.Tech Computer Science",
            code="BTCS_9C",
            duration_years=4,
        )
        self.semester = Semester.objects.create(
            program=self.program,
            number=4,
            academic_year="2026-2027",
        )
        self.division = Division.objects.create(semester=self.semester, name="A", capacity=60)
        self.batch = PracticalBatch.objects.create(division=self.division, name="B1", capacity=20)

        # Create subjects
        self.subject_dsa = Subject.objects.create(
            program=self.program,
            name="Data Structures",
            code="CS401_9C",
            type=Subject.Type.LECTURE,
            credits=Decimal("4.0"),
            weekly_lectures=3,
        )
        self.subject_dbms = Subject.objects.create(
            program=self.program,
            name="Database Systems",
            code="CS402_9C",
            type=Subject.Type.LECTURE,
            credits=Decimal("4.0"),
            weekly_lectures=2,
        )

        # Create classrooms
        self.classroom = Classroom.objects.create(
            building="Main",
            room_number="401",
            capacity=60,
            status=Classroom.Status.AVAILABLE,
        )

        # Create teachers
        self.user_t1 = UserModel.objects.create_user(
            username="teacher_t1_9c",
            email="t1.9c@example.com",
            first_name="Amit",
            last_name="Patil",
            role=UserModel.Role.TEACHER,
        )
        self.teacher_1 = TeacherProfile.objects.create(
            user=self.user_t1,
            employee_code="EMP_T1_9C",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )

        self.user_t2 = UserModel.objects.create_user(
            username="teacher_t2_9c",
            email="t2.9c@example.com",
            first_name="Suresh",
            last_name="Raina",
            role=UserModel.Role.TEACHER,
        )
        self.teacher_2 = TeacherProfile.objects.create(
            user=self.user_t2,
            employee_code="EMP_T2_9C",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )

        # Base solver input
        self.base_solver_input = {
            "divisions": [
                {
                    "id": str(self.division.id),
                    "name": self.division.name,
                    "batch_ids": [str(self.batch.id)],
                }
            ],
            "teachers": [
                {
                    "id": str(self.teacher_1.id),
                    "name": "Amit Patil",
                    "employee_code": "EMP_T1_9C",
                    "qualified_subject_ids": [str(self.subject_dsa.id)],
                    "unavailable_slots": [],
                    "leave_days": [],
                },
                {
                    "id": str(self.teacher_2.id),
                    "name": "Suresh Raina",
                    "employee_code": "EMP_T2_9C",
                    "qualified_subject_ids": [str(self.subject_dbms.id)],
                    "unavailable_slots": [],
                    "leave_days": [],
                },
            ],
            "rooms": [
                {
                    "id": str(self.classroom.id),
                    "name": "Main-401",
                    "room_type": "CLASSROOM",
                    "capacity": 60,
                    "status": "AVAILABLE",
                }
            ],
            "sessions_to_schedule": [
                {
                    "id": f"s_dsa_{i}",
                    "subject_id": str(self.subject_dsa.id),
                    "division_id": str(self.division.id),
                    "batch_id": None,
                    "session_type": "LECTURE",
                    "duration_slots": 1,
                }
                for i in range(1, 4)
            ]
            + [
                {
                    "id": f"s_dbms_{j}",
                    "subject_id": str(self.subject_dbms.id),
                    "division_id": str(self.division.id),
                    "batch_id": None,
                    "session_type": "LECTURE",
                    "duration_slots": 1,
                }
                for j in range(1, 3)
            ],
        }

    def test_1_teacher_time_avoid_blocks_matching_slots(self):
        """1. Teacher time restriction with AVOID prevents teacher assignment in specified window."""
        constraint = {
            "constraint_type": "TEACHER_TIME_RESTRICTION",
            "teacher_id": str(self.teacher_1.id),
            "day": "MONDAY",
            "start_time": "09:00",
            "end_time": "12:00",
            "mode": "AVOID",
        }
        solver_input = dict(self.base_solver_input)
        solver_input["constraints"] = [constraint]

        solver = TimetableSolver()
        res = solver.solve(solver_input)

        self.assertIn(res["status"], [TimetableSolver.STATUS_OPTIMAL, TimetableSolver.STATUS_FEASIBLE])
        for a in res["assignments"]:
            if a["teacher_id"] == str(self.teacher_1.id) and a["day"] == "MONDAY":
                # Must not overlap 09:00 to 12:00
                self.assertFalse(
                    a["start_time"] < "12:00:00" and a["end_time"] > "09:00:00",
                    f"Teacher 1 assigned during banned time: {a}",
                )

    def test_2_teacher_day_avoid_blocks_entire_day(self):
        """2. Teacher day restriction with AVOID prevents teacher assignment on that day."""
        constraint = {
            "constraint_type": "TEACHER_DAY_RESTRICTION",
            "teacher_id": str(self.teacher_1.id),
            "day": "MONDAY",
            "mode": "AVOID",
        }
        solver_input = dict(self.base_solver_input)
        solver_input["constraints"] = [constraint]

        solver = TimetableSolver()
        res = solver.solve(solver_input)

        self.assertIn(res["status"], [TimetableSolver.STATUS_OPTIMAL, TimetableSolver.STATUS_FEASIBLE])
        for a in res["assignments"]:
            if a["teacher_id"] == str(self.teacher_1.id):
                self.assertNotEqual(a["day"], "MONDAY", f"Teacher 1 scheduled on banned day: {a}")

    def test_3_subject_day_avoid_blocks_subject_on_that_day(self):
        """3. Subject day restriction with AVOID prevents subject assignment on that day."""
        constraint = {
            "constraint_type": "SUBJECT_DAY_RESTRICTION",
            "subject_id": str(self.subject_dsa.id),
            "day": "TUESDAY",
            "mode": "AVOID",
        }
        solver_input = dict(self.base_solver_input)
        solver_input["constraints"] = [constraint]

        solver = TimetableSolver()
        res = solver.solve(solver_input)

        self.assertIn(res["status"], [TimetableSolver.STATUS_OPTIMAL, TimetableSolver.STATUS_FEASIBLE])
        for a in res["assignments"]:
            if a["subject_id"] == str(self.subject_dsa.id):
                self.assertNotEqual(a["day"], "TUESDAY", f"DSA scheduled on banned Tuesday: {a}")

    def test_4_division_time_avoid_blocks_matching_slots(self):
        """4. Division time restriction with AVOID prevents division assignment in specified window."""
        constraint = {
            "constraint_type": "DIVISION_TIME_RESTRICTION",
            "division_id": str(self.division.id),
            "day": "WEDNESDAY",
            "start_time": "14:00",
            "end_time": "17:00",
            "mode": "AVOID",
        }
        solver_input = dict(self.base_solver_input)
        solver_input["constraints"] = [constraint]

        solver = TimetableSolver()
        res = solver.solve(solver_input)

        self.assertIn(res["status"], [TimetableSolver.STATUS_OPTIMAL, TimetableSolver.STATUS_FEASIBLE])
        for a in res["assignments"]:
            if a["division_id"] == str(self.division.id) and a["day"] == "WEDNESDAY":
                self.assertFalse(
                    a["start_time"] < "17:00:00" and a["end_time"] > "14:00:00",
                    f"Division scheduled during banned afternoon: {a}",
                )

    def test_5_subject_time_prefer_affects_optimization_objective(self):
        """5. Subject time PREFER creates penalty terms and guides optimization."""
        # 1. Without prefer constraint
        solver_base = TimetableSolver(config=SolverConfig(optimization=OptimizationConfig(enabled=True)))
        res_base = solver_base.solve(dict(self.base_solver_input))
        self.assertIn(res_base["status"], [TimetableSolver.STATUS_OPTIMAL, TimetableSolver.STATUS_FEASIBLE])

        # 2. With prefer constraint on morning slots
        constraint = {
            "constraint_type": "SUBJECT_TIME_PREFERENCE",
            "subject_id": str(self.subject_dsa.id),
            "day": "MONDAY",
            "start_time": "09:00",
            "end_time": "12:00",
            "mode": "PREFER",
        }
        solver_input = dict(self.base_solver_input)
        solver_input["constraints"] = [constraint]

        solver_pref = TimetableSolver(config=SolverConfig(optimization=OptimizationConfig(enabled=True)))
        res_pref = solver_pref.solve(solver_input)

        self.assertIn(res_pref["status"], [TimetableSolver.STATUS_OPTIMAL, TimetableSolver.STATUS_FEASIBLE])
        self.assertIn("objective_value", res_pref)

    def test_6_prefer_constraint_does_not_make_feasible_problem_infeasible(self):
        """6. PREFER constraint does NOT make an otherwise feasible problem infeasible."""
        # Force a preference that cannot fit all sessions (e.g. only 1 slot on 1 day for 3 DSA sessions)
        constraint = {
            "constraint_type": "SUBJECT_TIME_PREFERENCE",
            "subject_id": str(self.subject_dsa.id),
            "day": "MONDAY",
            "start_time": "09:00",
            "end_time": "10:00",  # Only 1 slot available, but DSA needs 3 lectures
            "mode": "PREFER",
        }
        solver_input = dict(self.base_solver_input)
        solver_input["constraints"] = [constraint]

        solver = TimetableSolver(config=SolverConfig(optimization=OptimizationConfig(enabled=True)))
        res = solver.solve(solver_input)

        self.assertIn(res["status"], [TimetableSolver.STATUS_OPTIMAL, TimetableSolver.STATUS_FEASIBLE])
        self.assertEqual(len(res["assignments"]), 5)  # All 5 sessions successfully scheduled

    def test_7_multiple_constraints_work_together(self):
        """7. Multiple hard restrictions and soft preferences work together seamlessly."""
        constraints = [
            {
                "constraint_type": "TEACHER_DAY_RESTRICTION",
                "teacher_id": str(self.teacher_1.id),
                "day": "MONDAY",
                "mode": "AVOID",
            },
            {
                "constraint_type": "SUBJECT_DAY_RESTRICTION",
                "subject_id": str(self.subject_dbms.id),
                "day": "TUESDAY",
                "mode": "AVOID",
            },
            {
                "constraint_type": "SUBJECT_TIME_PREFERENCE",
                "subject_id": str(self.subject_dsa.id),
                "day": "WEDNESDAY",
                "start_time": "09:00",
                "end_time": "12:00",
                "mode": "PREFER",
            },
        ]
        solver_input = dict(self.base_solver_input)
        solver_input["constraints"] = constraints

        solver = TimetableSolver()
        res = solver.solve(solver_input)

        self.assertIn(res["status"], [TimetableSolver.STATUS_OPTIMAL, TimetableSolver.STATUS_FEASIBLE])
        for a in res["assignments"]:
            if a["teacher_id"] == str(self.teacher_1.id):
                self.assertNotEqual(a["day"], "MONDAY")
            if a["subject_id"] == str(self.subject_dbms.id):
                self.assertNotEqual(a["day"], "TUESDAY")

    def test_8_no_constraints_preserves_existing_phase8_behavior(self):
        """8. Omitting constraints preserves existing Phase 8 solver behavior exactly."""
        solver = TimetableSolver()
        res = solver.solve(dict(self.base_solver_input))
        self.assertIn(res["status"], [TimetableSolver.STATUS_OPTIMAL, TimetableSolver.STATUS_FEASIBLE])
        self.assertEqual(len(res["assignments"]), 5)

    def test_9_invalid_or_unvalidated_constraints_rejected_safely(self):
        """9. Unvalidated/malformed constraints are safely rejected without raising exceptions."""
        constraints = [
            {"constraint_type": "INVALID_TYPE", "teacher": "Nobody"},
            {"constraint_type": "TEACHER_DAY_RESTRICTION", "day": "INVALID_DAY"},
        ]
        solver_input = dict(self.base_solver_input)
        solver_input["constraints"] = constraints

        solver = TimetableSolver()
        res = solver.solve(solver_input)
        self.assertIn(res["status"], [TimetableSolver.STATUS_OPTIMAL, TimetableSolver.STATUS_FEASIBLE])
        self.assertEqual(len(res["assignments"]), 5)

    def test_10_existing_published_timetable_remains_unchanged(self):
        """10. Existing PUBLISHED timetable remains unchanged when generating with constraints."""
        from academics.models import TeacherSubject

        # Assign teachers to subjects in DB for TimetableGenerationService
        TeacherSubject.objects.create(teacher=self.teacher_1, subject=self.subject_dsa, priority=1)
        TeacherSubject.objects.create(teacher=self.teacher_2, subject=self.subject_dbms, priority=1)

        # Create pre-existing PUBLISHED timetable v1
        pub_tt = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=1,
            status=Timetable.Status.PUBLISHED,
        )

        constraints = [
            {
                "constraint_type": "TEACHER_DAY_RESTRICTION",
                "teacher": "Amit Patil",
                "day": "MONDAY",
                "mode": "AVOID",
            }
        ]

        generator = TimetableGenerationService(
            semester_id=self.semester.id,
            academic_year="2026-2027",
            constraints=constraints,
        )
        gen_res = generator.generate()

        self.assertIn(gen_res["status"], [TimetableSolver.STATUS_OPTIMAL, TimetableSolver.STATUS_FEASIBLE])
        self.assertEqual(gen_res["version"], 2)

        # Refresh pub_tt to verify it remained PUBLISHED and untouched
        pub_tt.refresh_from_db()
        self.assertEqual(pub_tt.status, Timetable.Status.PUBLISHED)
        self.assertEqual(pub_tt.version, 1)









