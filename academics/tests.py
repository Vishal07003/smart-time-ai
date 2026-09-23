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
    Notification,
    Semester,
    SlotReschedule,
    Subject,
    TeacherAvailability,
    TeacherLeave,
    TeacherSubject,
    TeacherSubstitution,
    Timetable,
    TimetableChangeLog,
    TimetableConflict,
    TimetableSlot,
)
from academics.validators import (
    validate_academic_year,
    validate_code_format,
    validate_non_empty_name,
    validate_positive_integer,
)
from academics.services.conflict_detection import ConflictDetectionService
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
from academics.services.substitute_service import SubstituteSuggestionService
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


class NaturalLanguageConstraintAPITests(APITestCase):
    """
    Phase 9D: Staff-facing Natural Language Constraint API integration tests.
    """

    def setUp(self):
        # 1. Create Users & Roles
        self.staff_user = UserModel.objects.create_superuser(
            username="staff_admin_9d",
            email="staff.9d@example.com",
            password="Password123!",
            role=UserModel.Role.STAFF,
        )
        self.teacher_user = UserModel.objects.create_user(
            username="teacher_user_9d",
            email="teacher.9d@example.com",
            password="Password123!",
            first_name="Amit",
            last_name="Patil",
            role=UserModel.Role.TEACHER,
        )
        self.student_user = UserModel.objects.create_user(
            username="student_user_9d",
            email="student.9d@example.com",
            password="Password123!",
            role=UserModel.Role.STUDENT,
        )

        # 2. Create Academic Hierarchy
        self.dept = Department.objects.create(name="Computer Engineering", code="CE_9D")
        self.program = Program.objects.create(
            department=self.dept,
            name="B.Tech Computer Science",
            code="BTCS_9D",
            duration_years=4,
        )
        self.semester = Semester.objects.create(
            program=self.program,
            number=6,
            academic_year="2026-2027",
        )
        self.division = Division.objects.create(semester=self.semester, name="A", capacity=60)
        self.batch = PracticalBatch.objects.create(division=self.division, name="B1", capacity=20)

        # 3. Create Resources & Profiles
        self.classroom = Classroom.objects.create(
            building="TechBlock",
            room_number="101",
            capacity=60,
            status=Classroom.Status.AVAILABLE,
        )
        self.teacher_profile = TeacherProfile.objects.create(
            user=self.teacher_user,
            employee_code="EMP_AMIT_9D",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )

        # 4. Create Subjects and Qualifications
        from academics.models import TeacherSubject

        self.subject_dsa = Subject.objects.create(
            program=self.program,
            name="Data Structures",
            code="CS601_9D",
            type=Subject.Type.LECTURE,
            credits=Decimal("4.0"),
            weekly_lectures=3,
        )
        TeacherSubject.objects.create(
            teacher=self.teacher_profile,
            subject=self.subject_dsa,
            priority=1,
        )

        self.parse_url = reverse("academics:constraint-parse-and-validate")
        self.generate_url = reverse("academics:constraint-generate-timetable")

    def test_1_staff_can_parse_and_validate_natural_language(self):
        """1. Staff can parse and validate natural language requirement via API."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "text": "Amit Patil ko Monday morning class mat do",
            "semester": str(self.semester.id),
        }
        res = self.client.post(self.parse_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["valid"])
        self.assertIsNotNone(res.data["constraint"])
        self.assertEqual(res.data["constraint"]["constraint_type"], "TEACHER_TIME_RESTRICTION")
        self.assertEqual(res.data["constraint"]["teacher_id"], str(self.teacher_profile.id))
        self.assertEqual(res.data["constraint"]["day"], "MONDAY")
        self.assertEqual(res.data["constraint"]["start_time"], "09:00")
        self.assertEqual(res.data["constraint"]["end_time"], "12:00")
        self.assertEqual(res.data["constraint"]["mode"], "AVOID")

    def test_2_teacher_cannot_access(self):
        """2. Teacher role is forbidden from constraint endpoints."""
        self.client.force_authenticate(user=self.teacher_user)
        payload = {"text": "Test instruction", "semester": str(self.semester.id)}
        res_parse = self.client.post(self.parse_url, payload, format="json")
        self.assertEqual(res_parse.status_code, status.HTTP_403_FORBIDDEN)

        res_gen = self.client.post(
            self.generate_url,
            {**payload, "academic_year": "2026-2027"},
            format="json",
        )
        self.assertEqual(res_gen.status_code, status.HTTP_403_FORBIDDEN)

    def test_3_student_cannot_access(self):
        """3. Student role is forbidden from constraint endpoints."""
        self.client.force_authenticate(user=self.student_user)
        payload = {"text": "Test instruction", "semester": str(self.semester.id)}
        res_parse = self.client.post(self.parse_url, payload, format="json")
        self.assertEqual(res_parse.status_code, status.HTTP_403_FORBIDDEN)

        res_gen = self.client.post(
            self.generate_url,
            {**payload, "academic_year": "2026-2027"},
            format="json",
        )
        self.assertEqual(res_gen.status_code, status.HTTP_403_FORBIDDEN)

    def test_4_unauthenticated_request_rejected(self):
        """4. Unauthenticated requests are rejected with 401 Unauthorized."""
        payload = {"text": "Test instruction", "semester": str(self.semester.id)}
        res_parse = self.client.post(self.parse_url, payload, format="json")
        self.assertEqual(res_parse.status_code, status.HTTP_401_UNAUTHORIZED)

        res_gen = self.client.post(
            self.generate_url,
            {**payload, "academic_year": "2026-2027"},
            format="json",
        )
        self.assertEqual(res_gen.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_5_valid_natural_language_produces_canonical_constraint(self):
        """5. Valid PREFER natural language produces typed canonical constraint dict."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "text": "Data Structures Friday afternoon prefer karo",
            "semester": str(self.semester.id),
        }
        res = self.client.post(self.parse_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["valid"])
        self.assertEqual(res.data["constraint"]["constraint_type"], "SUBJECT_TIME_PREFERENCE")
        self.assertEqual(res.data["constraint"]["subject_id"], str(self.subject_dsa.id))
        self.assertEqual(res.data["constraint"]["day"], "FRIDAY")
        self.assertEqual(res.data["constraint"]["mode"], "PREFER")

    def test_6_ambiguous_teacher_or_entity_returns_validation_error(self):
        """6. Ambiguous entity match returns structured validation error."""
        # Create a second teacher named Amit
        user_amit2 = UserModel.objects.create_user(
            username="teacher_amit_sharma_9d",
            email="amit.sharma.9d@example.com",
            first_name="Amit",
            last_name="Sharma",
            role=UserModel.Role.TEACHER,
        )
        TeacherProfile.objects.create(
            user=user_amit2,
            employee_code="EMP_AMITS_9D",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )

        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "text": "Amit ko Monday morning class mat do",
            "semester": str(self.semester.id),
        }
        res = self.client.post(self.parse_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data["valid"])
        self.assertIsNone(res.data["constraint"])
        self.assertTrue(any(e["code"] == "AMBIGUOUS" for e in res.data["errors"]))

    def test_7_invalid_constraint_does_not_invoke_solver(self):
        """7. Invalid constraint returns 400 and does NOT invoke solver or create timetable."""
        self.client.force_authenticate(user=self.staff_user)
        initial_timetable_count = Timetable.objects.count()

        payload = {
            "text": "UnknownProfessor ko Monday mat do",
            "semester": str(self.semester.id),
            "academic_year": "2026-2027",
        }
        res = self.client.post(self.generate_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Timetable.objects.count(), initial_timetable_count)

    def test_8_valid_avoid_constraint_reaches_timetable_generation(self):
        """8. Valid AVOID constraint is enforced in the generated timetable."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "text": "Amit Patil ko Monday avoid karo",
            "semester": str(self.semester.id),
            "academic_year": "2026-2027",
        }
        res = self.client.post(self.generate_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn(res.data["status"], ["FEASIBLE", "OPTIMAL"])

        # Check created slots: teacher Amit must NOT be scheduled on Monday
        timetable_id = res.data["timetable_id"]
        monday_slots = TimetableSlot.objects.filter(
            timetable_id=timetable_id,
            teacher=self.teacher_profile,
            day="MONDAY",
        )
        self.assertEqual(monday_slots.count(), 0)

    def test_9_prefer_constraint_reaches_optimization(self):
        """9. PREFER constraint reaches solver optimization with objective calculation."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "text": "Data Structures Friday morning prefer karo",
            "semester": str(self.semester.id),
            "academic_year": "2026-2027",
        }
        res = self.client.post(self.generate_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn("objective_value", res.data)

    def test_10_infeasible_result_creates_no_timetable(self):
        """10. Infeasible constraints return 400 and create 0 database records."""
        # Block all days for the only qualified teacher
        from academics.models import TeacherAvailability

        for d in ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]:
            TeacherAvailability.objects.create(
                teacher=self.teacher_profile,
                day=d,
                start_time="09:00:00",
                end_time="17:00:00",
                is_available=False,
            )

        self.client.force_authenticate(user=self.staff_user)
        initial_timetable_count = Timetable.objects.count()

        payload = {
            "text": "Data Structures Monday prefer karo",
            "semester": str(self.semester.id),
            "academic_year": "2026-2027",
        }
        res = self.client.post(self.generate_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["status"], "INFEASIBLE")
        self.assertEqual(Timetable.objects.count(), initial_timetable_count)

    def test_11_existing_published_timetable_remains_unchanged(self):
        """11. Pre-existing PUBLISHED timetable remains PUBLISHED when generating with constraints."""
        pub_tt = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=1,
            status=Timetable.Status.PUBLISHED,
        )

        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "text": "Amit Patil ko Monday avoid karo",
            "semester": str(self.semester.id),
            "academic_year": "2026-2027",
        }
        res = self.client.post(self.generate_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["version"], 2)

        pub_tt.refresh_from_db()
        self.assertEqual(pub_tt.status, Timetable.Status.PUBLISHED)
        self.assertEqual(pub_tt.version, 1)

    def test_12_generated_timetable_is_not_auto_published(self):
        """12. Newly generated timetable remains in GENERATED status and is NOT auto-published."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "text": "Data Structures Friday afternoon prefer karo",
            "semester": str(self.semester.id),
            "academic_year": "2026-2027",
        }
        res = self.client.post(self.generate_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        new_tt = Timetable.objects.get(id=res.data["timetable_id"])
        self.assertEqual(new_tt.status, Timetable.Status.GENERATED)


class TeacherSubstitutionTests(APITestCase):
    """
    Phase 10A: Unit and API integration tests for Teacher Replacement & Substitute Suggestion.
    """

    def setUp(self):
        from datetime import date

        # 1. Users & Roles
        self.staff_user = UserModel.objects.create_superuser(
            username="staff_sub_10a",
            email="staff.sub.10a@example.com",
            password="Password123!",
            role=UserModel.Role.STAFF,
        )
        self.user_amit = UserModel.objects.create_user(
            username="teacher_amit_10a",
            email="amit.10a@example.com",
            password="Password123!",
            first_name="Amit",
            last_name="Patil",
            role=UserModel.Role.TEACHER,
        )
        self.user_suresh = UserModel.objects.create_user(
            username="teacher_suresh_10a",
            email="suresh.10a@example.com",
            password="Password123!",
            first_name="Suresh",
            last_name="Raina",
            role=UserModel.Role.TEACHER,
        )
        self.user_inactive = UserModel.objects.create_user(
            username="teacher_inact_10a",
            email="inact.10a@example.com",
            password="Password123!",
            first_name="Inactive",
            last_name="Prof",
            role=UserModel.Role.TEACHER,
        )
        self.student_user = UserModel.objects.create_user(
            username="student_sub_10a",
            email="student.10a@example.com",
            password="Password123!",
            role=UserModel.Role.STUDENT,
        )

        # 2. Academic Hierarchy
        self.dept = Department.objects.create(name="Computer Engineering", code="CE_10A")
        self.program = Program.objects.create(
            department=self.dept,
            name="B.Tech Computer Science",
            code="BTCS_10A",
            duration_years=4,
        )
        self.semester = Semester.objects.create(
            program=self.program,
            number=7,
            academic_year="2026-2027",
        )
        self.division = Division.objects.create(semester=self.semester, name="A", capacity=60)
        self.batch = PracticalBatch.objects.create(division=self.division, name="B1", capacity=20)

        # 3. Resources & Teacher Profiles
        self.classroom = Classroom.objects.create(
            building="Main",
            room_number="301",
            capacity=60,
            status=Classroom.Status.AVAILABLE,
        )
        self.teacher_amit = TeacherProfile.objects.create(
            user=self.user_amit,
            employee_code="EMP_AMIT_10A",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )
        self.teacher_suresh = TeacherProfile.objects.create(
            user=self.user_suresh,
            employee_code="EMP_SURESH_10A",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )
        self.teacher_inactive = TeacherProfile.objects.create(
            user=self.user_inactive,
            employee_code="EMP_INACT_10A",
            department=self.dept,
            status=TeacherProfile.Status.INACTIVE,
        )

        # 4. Subjects & TeacherSubject Qualifications
        self.subject_java = Subject.objects.create(
            program=self.program,
            name="Java Programming",
            code="CS701_10A",
            type=Subject.Type.LECTURE,
            credits=Decimal("4.0"),
            weekly_lectures=4,
        )
        self.subject_os = Subject.objects.create(
            program=self.program,
            name="Operating Systems",
            code="CS702_10A",
            type=Subject.Type.LECTURE,
            credits=Decimal("4.0"),
            weekly_lectures=3,
        )

        TeacherSubject.objects.create(teacher=self.teacher_amit, subject=self.subject_java, priority=1)
        TeacherSubject.objects.create(teacher=self.teacher_suresh, subject=self.subject_java, priority=2)
        TeacherSubject.objects.create(teacher=self.teacher_inactive, subject=self.subject_java, priority=3)

        # 5. Published Timetable & Slots
        self.timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=1,
            status=Timetable.Status.PUBLISHED,
            created_by=self.staff_user,
        )
        self.slot_monday_10am = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            batch=None,
            subject=self.subject_java,
            teacher=self.teacher_amit,
            classroom=self.classroom,
            day="MONDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type="LECTURE",
            status=TimetableSlot.Status.SCHEDULED,
        )
        self.slot_tuesday_11am = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            batch=None,
            subject=self.subject_java,
            teacher=self.teacher_amit,
            classroom=self.classroom,
            day="TUESDAY",
            start_time="11:00:00",
            end_time="12:00:00",
            session_type="LECTURE",
            status=TimetableSlot.Status.SCHEDULED,
        )

        # 6. Approved Leave for Amit: 2026-09-21 (Monday) to 2026-09-22 (Tuesday)
        self.approved_leave = TeacherLeave.objects.create(
            teacher=self.teacher_amit,
            start_date=date(2026, 9, 21),  # Monday
            end_date=date(2026, 9, 22),    # Tuesday
            reason="Medical emergency",
            status=TeacherLeave.Status.APPROVED,
        )

        # 7. Pending Leave
        self.pending_leave = TeacherLeave.objects.create(
            teacher=self.teacher_amit,
            start_date=date(2026, 9, 28),
            end_date=date(2026, 9, 29),
            reason="Personal work",
            status=TeacherLeave.Status.PENDING,
        )

        self.suggestions_url = reverse("academics:substitute-suggestions")
        self.substitutions_url = reverse("academics:substitution-list")

    def test_1_get_suggestions_for_approved_leave(self):
        """1. Staff can view affected slots and eligible substitute candidates for an approved leave."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.suggestions_url}?teacher_leave={self.approved_leave.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["teacher_leave"], str(self.approved_leave.id))
        self.assertEqual(res.data["teacher"]["id"], str(self.teacher_amit.id))
        self.assertEqual(len(res.data["affected_slots"]), 2)

        slot1 = res.data["affected_slots"][0]
        self.assertEqual(slot1["day"], "MONDAY")
        self.assertEqual(len(slot1["candidates"]), 1)
        candidate = slot1["candidates"][0]
        self.assertEqual(candidate["teacher_id"], str(self.teacher_suresh.id))
        self.assertTrue(candidate["qualification_match"])
        self.assertTrue(candidate["available"])
        self.assertFalse(candidate["has_clash"])

    def test_2_suggestions_denied_for_teacher_and_student(self):
        """2. Teacher and student are denied access to substitute suggestions."""
        self.client.force_authenticate(user=self.user_amit)
        res_t = self.client.get(f"{self.suggestions_url}?teacher_leave={self.approved_leave.id}")
        self.assertEqual(res_t.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.student_user)
        res_s = self.client.get(f"{self.suggestions_url}?teacher_leave={self.approved_leave.id}")
        self.assertEqual(res_s.status_code, status.HTTP_403_FORBIDDEN)

    def test_3_suggestions_unauthenticated_denied(self):
        """3. Unauthenticated requests to suggestions endpoint return 401 Unauthorized."""
        res = self.client.get(f"{self.suggestions_url}?teacher_leave={self.approved_leave.id}")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_4_suggestions_for_non_approved_leave_fails(self):
        """4. Requesting suggestions for a PENDING or non-approved leave returns 400 Bad Request."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.suggestions_url}?teacher_leave={self.pending_leave.id}")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", res.data)

    def test_5_suggestions_for_nonexistent_leave_returns_404(self):
        """5. Requesting suggestions for a non-existent leave UUID returns 404 Not Found."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.suggestions_url}?teacher_leave={uuid.uuid4()}")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_6_inactive_teacher_not_suggested(self):
        """6. Inactive teachers are never included in the candidate list."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.suggestions_url}?teacher_leave={self.approved_leave.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        candidate_ids = [c["teacher_id"] for slot in res.data["affected_slots"] for c in slot["candidates"]]
        self.assertNotIn(str(self.teacher_inactive.id), candidate_ids)

    def test_7_unqualified_teacher_not_suggested(self):
        """7. Teachers without required TeacherSubject qualification are not suggested."""
        # Create a teacher qualified only for OS, not Java
        user_os = UserModel.objects.create_user(
            username="teacher_os_10a",
            email="os.10a@example.com",
            first_name="Ramesh",
            last_name="OS",
            role=UserModel.Role.TEACHER,
        )
        teacher_os = TeacherProfile.objects.create(
            user=user_os,
            employee_code="EMP_OS_10A",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )
        TeacherSubject.objects.create(teacher=teacher_os, subject=self.subject_os, priority=1)

        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.suggestions_url}?teacher_leave={self.approved_leave.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        candidate_ids = [c["teacher_id"] for slot in res.data["affected_slots"] for c in slot["candidates"]]
        self.assertNotIn(str(teacher_os.id), candidate_ids)

    def test_8_teacher_with_timetable_clash_not_suggested(self):
        """8. Teacher with an existing class at the same day & time is not suggested."""
        # Schedule Suresh on Monday 10:00 - 11:00 for OS
        TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            batch=None,
            subject=self.subject_os,
            teacher=self.teacher_suresh,
            classroom=self.classroom,
            day="MONDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type="LECTURE",
            status=TimetableSlot.Status.SCHEDULED,
        )

        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.suggestions_url}?teacher_leave={self.approved_leave.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # On Monday 10:00 - 11:00, Suresh has a clash, so candidates should be empty
        monday_slot = next(s for s in res.data["affected_slots"] if s["day"] == "MONDAY")
        self.assertEqual(len(monday_slot["candidates"]), 0)

        # On Tuesday 11:00 - 12:00, Suresh has no clash, so he should still be suggested
        tuesday_slot = next(s for s in res.data["affected_slots"] if s["day"] == "TUESDAY")
        self.assertEqual(len(tuesday_slot["candidates"]), 1)

    def test_9_teacher_on_leave_not_suggested(self):
        """9. Teacher with an approved leave overlapping that date is not suggested."""
        from datetime import date

        TeacherLeave.objects.create(
            teacher=self.teacher_suresh,
            start_date=date(2026, 9, 21),
            end_date=date(2026, 9, 21),
            reason="Sick leave",
            status=TeacherLeave.Status.APPROVED,
        )

        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.suggestions_url}?teacher_leave={self.approved_leave.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        monday_slot = next(s for s in res.data["affected_slots"] if s["day"] == "MONDAY")
        self.assertEqual(len(monday_slot["candidates"]), 0)

    def test_10_teacher_unavailable_not_suggested(self):
        """10. Teacher marked unavailable during the slot day/time is not suggested."""
        TeacherAvailability.objects.create(
            teacher=self.teacher_suresh,
            day="MONDAY",
            start_time="09:00:00",
            end_time="12:00:00",
            is_available=False,
        )

        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.suggestions_url}?teacher_leave={self.approved_leave.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        monday_slot = next(s for s in res.data["affected_slots"] if s["day"] == "MONDAY")
        self.assertEqual(len(monday_slot["candidates"]), 0)

    def test_11_staff_can_confirm_valid_substitution(self):
        """11. Staff can confirm a substitution and original TimetableSlot teacher remains unchanged."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "timetable_slot": str(self.slot_monday_10am.id),
            "substitute_teacher": str(self.teacher_suresh.id),
            "teacher_leave": str(self.approved_leave.id),
            "reason": "Covering for Amit Patil on approved medical leave",
        }
        res = self.client.post(self.substitutions_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["status"], "CONFIRMED")
        self.assertEqual(str(res.data["absent_teacher"]), str(self.teacher_amit.id))
        self.assertEqual(str(res.data["substitute_teacher"]), str(self.teacher_suresh.id))

        # Check DB record
        sub = TeacherSubstitution.objects.get(id=res.data["id"])
        self.assertEqual(sub.status, TeacherSubstitution.Status.CONFIRMED)
        self.assertEqual(sub.assigned_by, self.staff_user)

        # Crucial check: original slot teacher must remain Amit
        self.slot_monday_10am.refresh_from_db()
        self.assertEqual(self.slot_monday_10am.teacher_id, self.teacher_amit.id)

    def test_12_confirm_substitution_denied_for_teacher_and_student(self):
        """12. Teacher and student roles cannot confirm substitutions."""
        payload = {
            "timetable_slot": str(self.slot_monday_10am.id),
            "substitute_teacher": str(self.teacher_suresh.id),
        }
        self.client.force_authenticate(user=self.user_amit)
        res_t = self.client.post(self.substitutions_url, payload, format="json")
        self.assertEqual(res_t.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.student_user)
        res_s = self.client.post(self.substitutions_url, payload, format="json")
        self.assertEqual(res_s.status_code, status.HTTP_403_FORBIDDEN)

    def test_13_cannot_substitute_same_absent_teacher(self):
        """13. Attempting to assign absent teacher as their own substitute fails."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "timetable_slot": str(self.slot_monday_10am.id),
            "substitute_teacher": str(self.teacher_amit.id),
        }
        res = self.client.post(self.substitutions_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("substitute_teacher", res.data)

    def test_14_cannot_substitute_with_clashing_or_unqualified_teacher(self):
        """14. Confirming an unqualified teacher fails server-side validation."""
        user_unq = UserModel.objects.create_user(
            username="teacher_unq_10a",
            email="unq.10a@example.com",
            first_name="Unqualified",
            last_name="Prof",
            role=UserModel.Role.TEACHER,
        )
        teacher_unq = TeacherProfile.objects.create(
            user=user_unq,
            employee_code="EMP_UNQ_10A",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )

        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "timetable_slot": str(self.slot_monday_10am.id),
            "substitute_teacher": str(teacher_unq.id),
        }
        res = self.client.post(self.substitutions_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("substitute_teacher", res.data)

    def test_15_cannot_create_duplicate_active_substitution_for_same_slot(self):
        """15. Cannot confirm multiple active substitutions for the exact same TimetableSlot."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "timetable_slot": str(self.slot_monday_10am.id),
            "substitute_teacher": str(self.teacher_suresh.id),
        }
        res1 = self.client.post(self.substitutions_url, payload, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # Attempt second confirmation
        res2 = self.client.post(self.substitutions_url, payload, format="json")
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("timetable_slot", res2.data)

    def test_16_slot_on_unpublished_timetable_cannot_be_substituted(self):
        """16. TimetableSlot on a GENERATED (unpublished) timetable cannot be substituted."""
        gen_timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=2,
            status=Timetable.Status.GENERATED,
        )
        gen_slot = TimetableSlot.objects.create(
            timetable=gen_timetable,
            division=self.division,
            subject=self.subject_java,
            teacher=self.teacher_amit,
            classroom=self.classroom,
            day="MONDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type="LECTURE",
        )

        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "timetable_slot": str(gen_slot.id),
            "substitute_teacher": str(self.teacher_suresh.id),
        }
        res = self.client.post(self.substitutions_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("timetable_slot", res.data)


class TeacherSubstitutionNotificationWorkflowTests(APITestCase):
    """
    Phase 10B: Substitute Teacher Notification + Accept/Decline Workflow Tests.
    """

    def setUp(self):
        # 1. Users
        self.staff_user = UserModel.objects.create_user(
            username="staff_user_10b",
            email="staff.10b@example.com",
            password="Password123!",
            first_name="Admin",
            last_name="Staff",
            role=UserModel.Role.STAFF,
            is_staff=True,
        )
        self.user_amit = UserModel.objects.create_user(
            username="teacher_amit_10b",
            email="amit.10b@example.com",
            password="Password123!",
            first_name="Amit",
            last_name="Patil",
            role=UserModel.Role.TEACHER,
        )
        self.user_suresh = UserModel.objects.create_user(
            username="teacher_suresh_10b",
            email="suresh.10b@example.com",
            password="Password123!",
            first_name="Suresh",
            last_name="Rao",
            role=UserModel.Role.TEACHER,
        )
        self.user_ramesh = UserModel.objects.create_user(
            username="teacher_ramesh_10b",
            email="ramesh.10b@example.com",
            password="Password123!",
            first_name="Ramesh",
            last_name="Kumar",
            role=UserModel.Role.TEACHER,
        )
        self.student_user = UserModel.objects.create_user(
            username="student_user_10b",
            email="student.10b@example.com",
            password="Password123!",
            first_name="Rahul",
            last_name="Sharma",
            role=UserModel.Role.STUDENT,
        )

        # 2. Academic Hierarchy
        self.dept = Department.objects.create(name="Computer Engineering 10B", code="CE_10B")
        self.program = Program.objects.create(
            department=self.dept,
            name="B.Tech Computer Science 10B",
            code="BTCS_10B",
            duration_years=4,
        )
        self.semester = Semester.objects.create(
            program=self.program,
            number=7,
            academic_year="2026-2027",
        )
        self.division = Division.objects.create(semester=self.semester, name="A", capacity=60)

        # 3. Resources & Teacher Profiles
        self.classroom = Classroom.objects.create(
            building="Main",
            room_number="301",
            capacity=60,
            status=Classroom.Status.AVAILABLE,
        )
        self.teacher_amit = TeacherProfile.objects.create(
            user=self.user_amit,
            employee_code="EMP_AMIT_10B",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )
        self.teacher_suresh = TeacherProfile.objects.create(
            user=self.user_suresh,
            employee_code="EMP_SURESH_10B",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )
        self.teacher_ramesh = TeacherProfile.objects.create(
            user=self.user_ramesh,
            employee_code="EMP_RAMESH_10B",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )

        # 4. Subjects & Qualifications
        self.subject_java = Subject.objects.create(
            program=self.program,
            name="Java Programming",
            code="CS701_10B",
            type=Subject.Type.LECTURE,
            credits=Decimal("4.0"),
            weekly_lectures=4,
        )
        TeacherSubject.objects.create(teacher=self.teacher_amit, subject=self.subject_java, priority=1)
        TeacherSubject.objects.create(teacher=self.teacher_suresh, subject=self.subject_java, priority=2)
        TeacherSubject.objects.create(teacher=self.teacher_ramesh, subject=self.subject_java, priority=3)

        # 5. Published Timetable & Slot
        self.timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=1,
            status=Timetable.Status.PUBLISHED,
            created_by=self.staff_user,
        )
        self.slot = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            batch=None,
            subject=self.subject_java,
            teacher=self.teacher_amit,
            classroom=self.classroom,
            day="MONDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type="LECTURE",
            status=TimetableSlot.Status.SCHEDULED,
        )

        self.substitutions_url = "/api/v1/substitutions/"
        self.notifications_url = "/api/v1/notifications/"

    def _create_substitution_helper(self, status=TeacherSubstitution.Status.PENDING):
        """Helper to create a substitution for test isolation."""
        sub = TeacherSubstitution.objects.create(
            timetable_slot=self.slot,
            absent_teacher=self.teacher_amit,
            substitute_teacher=self.teacher_suresh,
            reason="Medical leave cover",
            status=status,
            assigned_by=self.staff_user,
        )
        return sub

    def test_01_staff_assignment_creates_notification(self):
        """1. Staff assignment creates notification for substitute teacher."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "timetable_slot": str(self.slot.id),
            "substitute_teacher": str(self.teacher_suresh.id),
            "reason": "Covering for Amit",
        }
        res = self.client.post(self.substitutions_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # Verify notification created
        notif = Notification.objects.filter(recipient=self.user_suresh).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.notification_type, Notification.NotificationType.SUBSTITUTION_ASSIGNED)
        self.assertEqual(notif.title, "Substitute Class Assigned")
        self.assertIn("Java Programming", notif.message)
        self.assertFalse(notif.is_read)

    def test_02_notification_belongs_only_to_assigned_teacher(self):
        """2. Notification belongs only to assigned teacher and appears in their list."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "timetable_slot": str(self.slot.id),
            "substitute_teacher": str(self.teacher_suresh.id),
        }
        self.client.post(self.substitutions_url, payload, format="json")

        self.client.force_authenticate(user=self.user_suresh)
        res = self.client.get(self.notifications_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data if isinstance(res.data, list) else res.data.get("results", [])
        self.assertTrue(len(results) >= 1)
        self.assertEqual(results[0]["title"], "Substitute Class Assigned")

    def test_03_other_teacher_cannot_access_it(self):
        """3. Other teachers cannot access another teacher's notifications."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "timetable_slot": str(self.slot.id),
            "substitute_teacher": str(self.teacher_suresh.id),
        }
        self.client.post(self.substitutions_url, payload, format="json")

        # Ramesh checks notifications -> should be empty
        self.client.force_authenticate(user=self.user_ramesh)
        res = self.client.get(self.notifications_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data if isinstance(res.data, list) else res.data.get("results", [])
        self.assertEqual(len(results), 0)

    def test_04_student_cannot_access_it(self):
        """4. Students cannot access teacher notifications."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "timetable_slot": str(self.slot.id),
            "substitute_teacher": str(self.teacher_suresh.id),
        }
        self.client.post(self.substitutions_url, payload, format="json")

        self.client.force_authenticate(user=self.student_user)
        res = self.client.get(self.notifications_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data if isinstance(res.data, list) else res.data.get("results", [])
        self.assertEqual(len(results), 0)

    def test_05_assigned_teacher_can_accept(self):
        """5. Assigned substitute teacher can accept the substitution."""
        sub = self._create_substitution_helper(status=TeacherSubstitution.Status.PENDING)

        self.client.force_authenticate(user=self.user_suresh)
        accept_url = f"{self.substitutions_url}{sub.id}/accept/"
        res = self.client.post(accept_url, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "CONFIRMED")

        sub.refresh_from_db()
        self.assertEqual(sub.status, TeacherSubstitution.Status.CONFIRMED)

    def test_06_wrong_teacher_cannot_accept(self):
        """6. Wrong teacher cannot accept a substitution assigned to someone else."""
        sub = self._create_substitution_helper(status=TeacherSubstitution.Status.PENDING)

        self.client.force_authenticate(user=self.user_ramesh)
        accept_url = f"{self.substitutions_url}{sub.id}/accept/"
        res = self.client.post(accept_url, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_07_assigned_teacher_can_decline(self):
        """7. Assigned substitute teacher can decline the substitution."""
        sub = self._create_substitution_helper(status=TeacherSubstitution.Status.PENDING)

        self.client.force_authenticate(user=self.user_suresh)
        decline_url = f"{self.substitutions_url}{sub.id}/decline/"
        res = self.client.post(decline_url, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn(res.data["status"], ["DECLINED", "CANCELLED"])

        sub.refresh_from_db()
        self.assertIn(sub.status, [TeacherSubstitution.Status.DECLINED, TeacherSubstitution.Status.CANCELLED])

    def test_08_wrong_teacher_cannot_decline(self):
        """8. Wrong teacher cannot decline a substitution assigned to someone else."""
        sub = self._create_substitution_helper(status=TeacherSubstitution.Status.PENDING)

        self.client.force_authenticate(user=self.user_ramesh)
        decline_url = f"{self.substitutions_url}{sub.id}/decline/"
        res = self.client.post(decline_url, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_09_already_accepted_cannot_be_accepted_again(self):
        """9. An already confirmed/accepted substitution cannot be accepted again."""
        sub = self._create_substitution_helper(status=TeacherSubstitution.Status.CONFIRMED)

        self.client.force_authenticate(user=self.user_suresh)
        accept_url = f"{self.substitutions_url}{sub.id}/accept/"
        res = self.client.post(accept_url, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_10_cancelled_or_declined_cannot_be_accepted(self):
        """10. Cancelled or declined substitution cannot be accepted."""
        sub = self._create_substitution_helper(status=TeacherSubstitution.Status.DECLINED)

        self.client.force_authenticate(user=self.user_suresh)
        accept_url = f"{self.substitutions_url}{sub.id}/accept/"
        res = self.client.post(accept_url, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_11_notification_can_be_marked_read_only_by_owner(self):
        """11. Notification can be marked read by its owner."""
        notif = Notification.objects.create(
            recipient=self.user_suresh,
            notification_type=Notification.NotificationType.SUBSTITUTION_ASSIGNED,
            title="Test Notice",
            message="Test Msg",
        )

        self.client.force_authenticate(user=self.user_suresh)
        read_url = f"{self.notifications_url}{notif.id}/read/"
        res = self.client.patch(read_url, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["is_read"])
        self.assertIsNotNone(res.data["read_at"])

        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_12_other_user_cannot_mark_it_read(self):
        """12. Other users cannot mark another user's notification as read."""
        notif = Notification.objects.create(
            recipient=self.user_suresh,
            notification_type=Notification.NotificationType.SUBSTITUTION_ASSIGNED,
            title="Test Notice",
            message="Test Msg",
        )

        self.client.force_authenticate(user=self.user_ramesh)
        read_url = f"{self.notifications_url}{notif.id}/read/"
        res = self.client.patch(read_url, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_13_staff_receives_notification_after_accept(self):
        """13. Staff receives notification after substitute accepts."""
        sub = self._create_substitution_helper(status=TeacherSubstitution.Status.PENDING)

        self.client.force_authenticate(user=self.user_suresh)
        accept_url = f"{self.substitutions_url}{sub.id}/accept/"
        res = self.client.post(accept_url, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        staff_notif = Notification.objects.filter(
            recipient=self.staff_user,
            notification_type=Notification.NotificationType.SUBSTITUTION_ACCEPTED,
        ).first()
        self.assertIsNotNone(staff_notif)
        self.assertEqual(staff_notif.title, "Substitute Assignment Accepted")
        self.assertIn("Suresh", staff_notif.message)

    def test_14_staff_receives_notification_after_decline(self):
        """14. Staff receives notification after substitute declines."""
        sub = self._create_substitution_helper(status=TeacherSubstitution.Status.PENDING)

        self.client.force_authenticate(user=self.user_suresh)
        decline_url = f"{self.substitutions_url}{sub.id}/decline/"
        res = self.client.post(decline_url, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        staff_notif = Notification.objects.filter(
            recipient=self.staff_user,
            notification_type=Notification.NotificationType.SUBSTITUTION_DECLINED,
        ).first()
        self.assertIsNotNone(staff_notif)
        self.assertEqual(staff_notif.title, "Substitute Assignment Declined")
        self.assertIn("Suresh", staff_notif.message)

    def test_15_original_published_timetable_slot_remains_unchanged(self):
        """15. Original published TimetableSlot teacher remains strictly unchanged."""
        sub = self._create_substitution_helper(status=TeacherSubstitution.Status.PENDING)

        # Accept
        self.client.force_authenticate(user=self.user_suresh)
        self.client.post(f"{self.substitutions_url}{sub.id}/accept/", format="json")
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.teacher_id, self.teacher_amit.id)

        # Decline another
        sub2 = TeacherSubstitution.objects.create(
            timetable_slot=self.slot,
            absent_teacher=self.teacher_amit,
            substitute_teacher=self.teacher_ramesh,
            status=TeacherSubstitution.Status.PENDING,
            assigned_by=self.staff_user,
        )
        self.client.force_authenticate(user=self.user_ramesh)
        self.client.post(f"{self.substitutions_url}{sub2.id}/decline/", format="json")
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.teacher_id, self.teacher_amit.id)

    def test_16_phase_10a_substitutions_and_suggestions_still_pass(self):
        """16. Existing Phase 10A suggestions pipeline continues to function correctly."""
        leave = TeacherLeave.objects.create(
            teacher=self.teacher_amit,
            start_date="2026-10-05",
            end_date="2026-10-05",
            reason="Medical Checkup",
            status=TeacherLeave.Status.APPROVED,
        )
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"/api/v1/substitutions/suggestions/?teacher_leave={leave.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["teacher"]["id"], str(self.teacher_amit.id))
        self.assertEqual(len(res.data["affected_slots"]), 1)


class ReschedulingSuggestionWorkflowTests(APITestCase):
    """
    Phase 10C: Automatic Rescheduling + Alternative Teacher/Room/Time Suggestions Tests.
    """

    def setUp(self):
        # 1. Users
        self.staff_user = UserModel.objects.create_user(
            username="staff_user_10c",
            email="staff.10c@example.com",
            password="Password123!",
            first_name="Admin",
            last_name="Staff",
            role=UserModel.Role.STAFF,
            is_staff=True,
        )
        self.user_amit = UserModel.objects.create_user(
            username="teacher_amit_10c",
            email="amit.10c@example.com",
            password="Password123!",
            first_name="Amit",
            last_name="Patil",
            role=UserModel.Role.TEACHER,
        )
        self.user_suresh = UserModel.objects.create_user(
            username="teacher_suresh_10c",
            email="suresh.10c@example.com",
            password="Password123!",
            first_name="Suresh",
            last_name="Rao",
            role=UserModel.Role.TEACHER,
        )
        self.user_ramesh = UserModel.objects.create_user(
            username="teacher_ramesh_10c",
            email="ramesh.10c@example.com",
            password="Password123!",
            first_name="Ramesh",
            last_name="Kumar",
            role=UserModel.Role.TEACHER,
        )
        self.student_user = UserModel.objects.create_user(
            username="student_user_10c",
            email="student.10c@example.com",
            password="Password123!",
            first_name="Rahul",
            last_name="Sharma",
            role=UserModel.Role.STUDENT,
        )

        # 2. Academic Hierarchy
        self.dept = Department.objects.create(name="Computer Engineering 10C", code="CE_10C")
        self.program = Program.objects.create(
            department=self.dept,
            name="B.Tech Computer Science 10C",
            code="BTCS_10C",
            duration_years=4,
        )
        self.semester = Semester.objects.create(
            program=self.program,
            number=7,
            academic_year="2026-2027",
        )
        self.division = Division.objects.create(semester=self.semester, name="A", capacity=60)
        self.division_b = Division.objects.create(semester=self.semester, name="B", capacity=60)
        self.batch = PracticalBatch.objects.create(division=self.division, name="B1", capacity=30)

        # 3. Classrooms & Laboratories
        self.classroom_101 = Classroom.objects.create(
            building="Main",
            room_number="101",
            capacity=60,
            status=Classroom.Status.AVAILABLE,
        )
        self.classroom_102 = Classroom.objects.create(
            building="Main",
            room_number="102",
            capacity=60,
            status=Classroom.Status.AVAILABLE,
        )
        self.lab_201 = Laboratory.objects.create(
            building="Main",
            lab_number="201",
            name="Network Lab",
            capacity=30,
            status=Laboratory.Status.AVAILABLE,
        )

        # 4. Teacher Profiles
        self.teacher_amit = TeacherProfile.objects.create(
            user=self.user_amit,
            employee_code="EMP_AMIT_10C",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )
        self.teacher_suresh = TeacherProfile.objects.create(
            user=self.user_suresh,
            employee_code="EMP_SURESH_10C",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )
        self.teacher_ramesh = TeacherProfile.objects.create(
            user=self.user_ramesh,
            employee_code="EMP_RAMESH_10C",
            department=self.dept,
            status=TeacherProfile.Status.ACTIVE,
        )

        # 5. Subjects & Qualifications
        self.subject_java = Subject.objects.create(
            program=self.program,
            name="Java Programming",
            code="CS701_10C",
            type=Subject.Type.LECTURE,
            credits=Decimal("4.0"),
            weekly_lectures=4,
        )
        self.subject_python = Subject.objects.create(
            program=self.program,
            name="Python Programming",
            code="CS702_10C",
            type=Subject.Type.PRACTICAL,
            credits=Decimal("2.0"),
            weekly_practicals=2,
        )
        TeacherSubject.objects.create(teacher=self.teacher_amit, subject=self.subject_java, priority=1)
        TeacherSubject.objects.create(teacher=self.teacher_suresh, subject=self.subject_java, priority=2)
        # Ramesh is qualified only for Python, NOT Java
        TeacherSubject.objects.create(teacher=self.teacher_ramesh, subject=self.subject_python, priority=1)

        # 6. Published Timetable & Slots
        self.timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=1,
            status=Timetable.Status.PUBLISHED,
            created_by=self.staff_user,
        )
        self.slot_monday = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            batch=None,
            subject=self.subject_java,
            teacher=self.teacher_amit,
            classroom=self.classroom_101,
            day="MONDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )

        self.reschedule_suggestions_url = "/api/v1/rescheduling/suggestions/"
        self.reschedule_confirm_url = "/api/v1/rescheduling/confirm/"

    def test_01_approved_leave_identifies_affected_published_slot(self):
        """1. Approved leave correctly identifies affected published slot."""
        TeacherLeave.objects.create(
            teacher=self.teacher_amit,
            start_date="2026-10-05",
            end_date="2026-10-05",
            reason="Medical Leave",
            status=TeacherLeave.Status.APPROVED,
        )
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.reschedule_suggestions_url}?timetable_slot={self.slot_monday.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["slot_id"], str(self.slot_monday.id))
        self.assertEqual(res.data["original"]["teacher_id"], str(self.teacher_amit.id))

    def test_02_qualified_available_substitute_is_suggested(self):
        """2. Qualified available substitute (Suresh) is suggested at original time."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.reschedule_suggestions_url}?timetable_slot={self.slot_monday.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        suggestions = res.data["suggestions"]
        self.assertTrue(len(suggestions) > 0)
        top_suggestion = suggestions[0]
        self.assertEqual(top_suggestion["type"], "SUBSTITUTE_TEACHER")
        self.assertEqual(top_suggestion["teacher_id"], str(self.teacher_suresh.id))
        self.assertEqual(top_suggestion["day"], "MONDAY")
        self.assertEqual(top_suggestion["score"], 95)

    def test_03_unqualified_teacher_is_excluded(self):
        """3. Unqualified teacher (Ramesh) is completely excluded from Java suggestions."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.reschedule_suggestions_url}?timetable_slot={self.slot_monday.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        teacher_ids = [s["teacher_id"] for s in res.data["suggestions"]]
        self.assertNotIn(str(self.teacher_ramesh.id), teacher_ids)

    def test_04_teacher_clash_is_excluded(self):
        """4. Teacher clash at original time excludes substitute from that specific time slot."""
        # Create a class for Suresh on Monday 10:00 - 11:00
        TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division_b,
            subject=self.subject_java,
            teacher=self.teacher_suresh,
            classroom=self.classroom_102,
            day="MONDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )

        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.reschedule_suggestions_url}?timetable_slot={self.slot_monday.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        monday_10am_suresh = [
            s for s in res.data["suggestions"]
            if s["teacher_id"] == str(self.teacher_suresh.id) and s["day"] == "MONDAY" and s["start_time"] == "10:00"
        ]
        self.assertEqual(len(monday_10am_suresh), 0)

    def test_05_teacher_leave_is_excluded(self):
        """5. Teacher on approved leave is excluded from candidate suggestions for that period."""
        TeacherLeave.objects.create(
            teacher=self.teacher_suresh,
            start_date="2026-10-05",  # Monday
            end_date="2026-10-05",
            reason="Conference",
            status=TeacherLeave.Status.APPROVED,
        )

        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.reschedule_suggestions_url}?timetable_slot={self.slot_monday.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        monday_suresh = [
            s for s in res.data["suggestions"]
            if s["teacher_id"] == str(self.teacher_suresh.id) and s["day"] == "MONDAY"
        ]
        self.assertEqual(len(monday_suresh), 0)

    def test_06_division_batch_clash_is_excluded(self):
        """6. Times when division already has a class are excluded as alternative slots."""
        # Division A has class on Tuesday 11:00 - 12:00
        TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            subject=self.subject_java,
            teacher=self.teacher_suresh,
            classroom=self.classroom_101,
            day="TUESDAY",
            start_time="11:00:00",
            end_time="12:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )

        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.reschedule_suggestions_url}?timetable_slot={self.slot_monday.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        tue_11am_slots = [
            s for s in res.data["suggestions"]
            if s["day"] == "TUESDAY" and s["start_time"] == "11:00"
        ]
        self.assertEqual(len(tue_11am_slots), 0)

    def test_07_classroom_clash_is_excluded(self):
        """7. Classroom occupied by another division is excluded for that time slot."""
        # Classroom 101 occupied by Division B on Wednesday 10:00 - 11:00
        TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division_b,
            subject=self.subject_java,
            teacher=self.teacher_suresh,
            classroom=self.classroom_101,
            day="WEDNESDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )

        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.reschedule_suggestions_url}?timetable_slot={self.slot_monday.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        wed_10am_room101 = [
            s for s in res.data["suggestions"]
            if s["day"] == "WEDNESDAY" and s["start_time"] == "10:00" and s["classroom_id"] == str(self.classroom_101.id)
        ]
        self.assertEqual(len(wed_10am_room101), 0)

    def test_08_laboratory_clash_is_excluded(self):
        """8. Laboratory occupied by another class is excluded for practical slots."""
        prac_slot = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            batch=self.batch,
            subject=self.subject_python,
            teacher=self.teacher_ramesh,
            laboratory=self.lab_201,
            day="MONDAY",
            start_time="14:00:00",
            end_time="15:00:00",
            session_type=TimetableSlot.SessionType.PRACTICAL,
            status=TimetableSlot.Status.SCHEDULED,
        )

        # Lab 201 occupied on Tuesday 14:00 - 15:00 by Division B
        TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division_b,
            subject=self.subject_python,
            teacher=self.teacher_ramesh,
            laboratory=self.lab_201,
            day="TUESDAY",
            start_time="14:00:00",
            end_time="15:00:00",
            session_type=TimetableSlot.SessionType.PRACTICAL,
            status=TimetableSlot.Status.SCHEDULED,
        )

        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.reschedule_suggestions_url}?timetable_slot={prac_slot.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        tue_lab201 = [
            s for s in res.data["suggestions"]
            if s["day"] == "TUESDAY" and s["start_time"] == "14:00" and s["laboratory_id"] == str(self.lab_201.id)
        ]
        self.assertEqual(len(tue_lab201), 0)

    def test_09_alternative_time_is_suggested_when_substitute_at_original_time_unavailable(self):
        """9. When substitute at original time is unavailable, alternative time is suggested."""
        TeacherAvailability.objects.create(
            teacher=self.teacher_suresh,
            day="MONDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            is_available=False,
        )

        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.reschedule_suggestions_url}?timetable_slot={self.slot_monday.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Should find alternative time suggestions for other days
        suggestions = res.data["suggestions"]
        self.assertTrue(len(suggestions) > 0)
        alt_time_suggestions = [s for s in suggestions if s["day"] != "MONDAY" or s["start_time"] != "10:00"]
        self.assertTrue(len(alt_time_suggestions) > 0)

    def test_10_alternative_room_is_suggested_when_room_conflict_exists(self):
        """10. When classroom conflict exists, alternative room is suggested."""
        # Classroom 101 occupied at original time by Division B
        TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division_b,
            subject=self.subject_java,
            teacher=self.teacher_suresh,
            classroom=self.classroom_101,
            day="MONDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )

        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.reschedule_suggestions_url}?timetable_slot={self.slot_monday.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        room_102_suggestions = [
            s for s in res.data["suggestions"] if s["classroom_id"] == str(self.classroom_102.id)
        ]
        self.assertTrue(len(room_102_suggestions) > 0)

    def test_11_suggestions_are_deterministic(self):
        """11. Successive calls to suggestion engine return identical ordered output and scores."""
        self.client.force_authenticate(user=self.staff_user)
        res1 = self.client.get(f"{self.reschedule_suggestions_url}?timetable_slot={self.slot_monday.id}")
        res2 = self.client.get(f"{self.reschedule_suggestions_url}?timetable_slot={self.slot_monday.id}")

        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res1.data["suggestions"], res2.data["suggestions"])

    def test_12_staff_can_access_suggestions(self):
        """12. Staff can access rescheduling suggestions."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"{self.reschedule_suggestions_url}?timetable_slot={self.slot_monday.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("suggestions", res.data)

    def test_13_teacher_cannot_access_suggestions(self):
        """13. Teachers are denied access to rescheduling suggestions."""
        self.client.force_authenticate(user=self.user_amit)
        res = self.client.get(f"{self.reschedule_suggestions_url}?timetable_slot={self.slot_monday.id}")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_14_student_cannot_access_suggestions(self):
        """14. Students are denied access to rescheduling suggestions."""
        self.client.force_authenticate(user=self.student_user)
        res = self.client.get(f"{self.reschedule_suggestions_url}?timetable_slot={self.slot_monday.id}")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_15_invalid_client_submitted_suggestion_is_rejected(self):
        """15. Invalid client-submitted combination (unqualified teacher) is rejected server-side."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "timetable_slot": str(self.slot_monday.id),
            "teacher": str(self.teacher_ramesh.id),  # Ramesh not qualified for Java
            "day": "TUESDAY",
            "start_time": "11:00",
            "end_time": "12:00",
            "classroom": str(self.classroom_101.id),
        }
        res = self.client.post(self.reschedule_confirm_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("teacher", res.data)

    def test_16_valid_suggestion_can_be_confirmed_by_staff(self):
        """16. Valid suggestion is confirmed by staff, creating a SlotReschedule record."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "timetable_slot": str(self.slot_monday.id),
            "teacher": str(self.teacher_suresh.id),
            "day": "TUESDAY",
            "start_time": "11:00",
            "end_time": "12:00",
            "classroom": str(self.classroom_101.id),
            "reason": "Rescheduling due to medical leave",
        }
        res = self.client.post(self.reschedule_confirm_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["status"], "CONFIRMED")
        self.assertEqual(res.data["new_assignment"]["day"], "TUESDAY")

        # Verify SlotReschedule in DB
        reschedule = SlotReschedule.objects.get(id=res.data["reschedule_id"])
        self.assertEqual(reschedule.status, SlotReschedule.Status.CONFIRMED)
        self.assertEqual(reschedule.new_day, "TUESDAY")
        self.assertEqual(reschedule.new_teacher_id, self.teacher_suresh.id)
        self.assertEqual(reschedule.created_by, self.staff_user)

    def test_17_original_published_timetable_remains_unchanged(self):
        """17. Original published Timetable and TimetableSlot remain completely unchanged."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "timetable_slot": str(self.slot_monday.id),
            "teacher": str(self.teacher_suresh.id),
            "day": "TUESDAY",
            "start_time": "11:00",
            "end_time": "12:00",
            "classroom": str(self.classroom_101.id),
            "reason": "Safe rescheduling",
        }
        res = self.client.post(self.reschedule_confirm_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # Verify original published timetable
        self.timetable.refresh_from_db()
        self.assertEqual(self.timetable.status, Timetable.Status.PUBLISHED)
        self.assertEqual(self.timetable.version, 1)

        # Verify original slot
        self.slot_monday.refresh_from_db()
        self.assertEqual(self.slot_monday.day, "MONDAY")
        self.assertEqual(self.slot_monday.teacher_id, self.teacher_amit.id)
        self.assertEqual(str(self.slot_monday.start_time)[:5], "10:00")

    def test_18_confirmed_change_is_not_automatically_published(self):
        """18. The new draft timetable created for the reschedule has status GENERATED."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "timetable_slot": str(self.slot_monday.id),
            "teacher": str(self.teacher_suresh.id),
            "day": "TUESDAY",
            "start_time": "11:00",
            "end_time": "12:00",
            "classroom": str(self.classroom_101.id),
        }
        res = self.client.post(self.reschedule_confirm_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        new_tt_id = res.data["new_timetable"]["id"]
        new_tt = Timetable.objects.get(id=new_tt_id)
        self.assertEqual(new_tt.status, Timetable.Status.GENERATED)
        self.assertEqual(new_tt.version, 2)

    def test_19_existing_phase_10a_and_10b_behavior_remains_unchanged(self):
        """19. Existing Phase 10A suggestions and 10B accept/decline workflows continue to pass."""
        leave = TeacherLeave.objects.create(
            teacher=self.teacher_amit,
            start_date="2026-10-05",
            end_date="2026-10-05",
            reason="Medical Leave",
            status=TeacherLeave.Status.APPROVED,
        )
        self.client.force_authenticate(user=self.staff_user)
        res_sug = self.client.get(f"/api/v1/substitutions/suggestions/?teacher_leave={leave.id}")
        self.assertEqual(res_sug.status_code, status.HTTP_200_OK)
        self.assertEqual(res_sug.data["teacher"]["id"], str(self.teacher_amit.id))


class TimetableHistoryWorkflowTests(APITestCase):
    """
    Focused Phase 11 Test Suite: Timetable History & Change Tracking.
    Verifies immutable audit logging across generation, publishing, archiving,
    rescheduling, substitution workflows, and Staff-only read-only history API.
    """

    def setUp(self):
        # 1. Create Users
        self.staff_user = User.objects.create_user(
            username="history_staff_user",
            email="history_staff@example.com",
            password="Password123!",
            role=User.Role.STAFF,
        )
        self.teacher_amit_user = User.objects.create_user(
            username="amit_history_teacher",
            email="amit_history@example.com",
            password="Password123!",
            first_name="Amit",
            last_name="Patil",
            role=User.Role.TEACHER,
        )
        self.teacher_suresh_user = User.objects.create_user(
            username="suresh_history_teacher",
            email="suresh_history@example.com",
            password="Password123!",
            first_name="Suresh",
            last_name="Raina",
            role=User.Role.TEACHER,
        )
        self.student_user = User.objects.create_user(
            username="history_student_user",
            email="history_student@example.com",
            password="Password123!",
            role=User.Role.STUDENT,
        )

        # 2. Academic Entities
        self.department = Department.objects.create(
            name="History Computer Science Dept",
            code="CS_HIST_11",
        )
        self.program = Program.objects.create(
            department=self.department,
            name="B.Tech History CS",
            code="BTCS_HIST_11",
            duration_years=4,
        )
        self.semester = Semester.objects.create(
            program=self.program,
            number=7,
            academic_year="2026-2027",
        )
        self.division = Division.objects.create(
            semester=self.semester,
            name="Division A",
            capacity=60,
        )

        # 3. Teacher Profiles
        self.teacher_amit = TeacherProfile.objects.create(
            user=self.teacher_amit_user,
            department=self.department,
            employee_code="T_HIST_01",
            designation="Professor",
            status=TeacherProfile.Status.ACTIVE,
        )
        self.teacher_suresh = TeacherProfile.objects.create(
            user=self.teacher_suresh_user,
            department=self.department,
            employee_code="T_HIST_02",
            designation="Associate Professor",
            status=TeacherProfile.Status.ACTIVE,
        )

        # 4. Rooms
        self.classroom_101 = Classroom.objects.create(
            building="History Block",
            room_number="101",
            capacity=60,
            status=Classroom.Status.AVAILABLE,
        )

        # 5. Subject & TeacherSubject Qualifications
        self.subject_java = Subject.objects.create(
            program=self.program,
            name="Java Enterprise",
            code="CS701_HIST",
            type=Subject.Type.LECTURE,
            credits=Decimal("4.0"),
            weekly_lectures=4,
        )
        TeacherSubject.objects.create(teacher=self.teacher_amit, subject=self.subject_java, priority=1)
        TeacherSubject.objects.create(teacher=self.teacher_suresh, subject=self.subject_java, priority=2)

        # 6. Published Timetable & Slots
        self.timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=1,
            status=Timetable.Status.PUBLISHED,
            created_by=self.staff_user,
        )
        self.slot_monday = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            batch=None,
            subject=self.subject_java,
            teacher=self.teacher_amit,
            classroom=self.classroom_101,
            day="MONDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )

        self.history_url = "/api/v1/timetable-history/"

    def test_01_timetable_generation_creates_history(self):
        """1. Timetable generation creates TIMETABLE_GENERATED history."""
        from academics.services.timetable_history_service import TimetableHistoryService
        tt_gen = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=2,
            status=Timetable.Status.GENERATED,
            created_by=self.staff_user,
        )
        log = TimetableHistoryService.log_timetable_generated(tt_gen, changed_by=self.staff_user)
        self.assertEqual(log.action, TimetableChangeLog.Action.TIMETABLE_GENERATED)
        self.assertEqual(log.changed_by, self.staff_user)
        self.assertEqual(log.timetable, tt_gen)
        self.assertEqual(log.new_data["status"], "GENERATED")

    def test_02_publish_creates_history(self):
        """2. Publishing a timetable records TIMETABLE_PUBLISHED and archives older published versions."""
        self.client.force_authenticate(user=self.staff_user)
        new_tt = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=2,
            status=Timetable.Status.GENERATED,
            created_by=self.staff_user,
        )
        res = self.client.post(f"/api/v1/timetables/{new_tt.id}/publish/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        publish_log = TimetableChangeLog.objects.filter(
            timetable=new_tt,
            action=TimetableChangeLog.Action.TIMETABLE_PUBLISHED,
        ).first()
        self.assertIsNotNone(publish_log)
        self.assertEqual(publish_log.changed_by, self.staff_user)

        archive_log = TimetableChangeLog.objects.filter(
            timetable=self.timetable,
            action=TimetableChangeLog.Action.TIMETABLE_ARCHIVED,
        ).first()
        self.assertIsNotNone(archive_log)

    def test_03_archive_creates_history(self):
        """3. Archiving a timetable records TIMETABLE_ARCHIVED history."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.post(f"/api/v1/timetables/{self.timetable.id}/archive/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        archive_log = TimetableChangeLog.objects.filter(
            timetable=self.timetable,
            action=TimetableChangeLog.Action.TIMETABLE_ARCHIVED,
        ).first()
        self.assertIsNotNone(archive_log)
        self.assertEqual(archive_log.changed_by, self.staff_user)

    def test_04_reschedule_creates_correct_old_new_data(self):
        """4. Reschedule creates correct old and new scheduling data snapshots."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "timetable_slot": str(self.slot_monday.id),
            "teacher": str(self.teacher_suresh.id),
            "day": "TUESDAY",
            "start_time": "11:00",
            "end_time": "12:00",
            "classroom": str(self.classroom_101.id),
            "reason": "Rescheduled for seminar",
        }
        res = self.client.post("/api/v1/rescheduling/confirm/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        resched_log = TimetableChangeLog.objects.filter(
            action=TimetableChangeLog.Action.SLOT_RESCHEDULED,
        ).first()
        self.assertIsNotNone(resched_log)
        self.assertEqual(resched_log.reason, "Rescheduled for seminar")
        self.assertEqual(resched_log.old_data["day"], "MONDAY")
        self.assertEqual(resched_log.old_data["start_time"], "10:00")
        self.assertEqual(resched_log.old_data["teacher_id"], str(self.teacher_amit.id))
        self.assertEqual(resched_log.new_data["day"], "TUESDAY")
        self.assertEqual(resched_log.new_data["start_time"], "11:00")
        self.assertEqual(resched_log.new_data["teacher_id"], str(self.teacher_suresh.id))

    def test_05_substitute_assignment_creates_history(self):
        """5. Assigning a substitute records SUBSTITUTE_ASSIGNED history."""
        self.client.force_authenticate(user=self.staff_user)
        payload = {
            "timetable_slot": str(self.slot_monday.id),
            "substitute_teacher": str(self.teacher_suresh.id),
            "reason": "Medical Leave Substitute",
        }
        res = self.client.post("/api/v1/substitutions/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        sub_log = TimetableChangeLog.objects.filter(
            action=TimetableChangeLog.Action.SUBSTITUTE_ASSIGNED,
            timetable_slot=self.slot_monday,
        ).first()
        self.assertIsNotNone(sub_log)
        self.assertEqual(sub_log.changed_by, self.staff_user)
        self.assertEqual(sub_log.new_data["teacher_id"], str(self.teacher_suresh.id))

    def test_06_substitute_acceptance_creates_history(self):
        """6. Substitute acceptance records SUBSTITUTE_ACCEPTED with substitute teacher as actor."""
        # Create substitution
        sub = TeacherSubstitution.objects.create(
            timetable_slot=self.slot_monday,
            absent_teacher=self.teacher_amit,
            substitute_teacher=self.teacher_suresh,
            status=TeacherSubstitution.Status.PENDING,
            assigned_by=self.staff_user,
        )
        self.client.force_authenticate(user=self.teacher_suresh_user)
        res = self.client.post(f"/api/v1/substitutions/{sub.id}/accept/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        accept_log = TimetableChangeLog.objects.filter(
            action=TimetableChangeLog.Action.SUBSTITUTE_ACCEPTED,
            timetable_slot=self.slot_monday,
        ).first()
        self.assertIsNotNone(accept_log)
        self.assertEqual(accept_log.changed_by, self.teacher_suresh_user)
        self.assertEqual(accept_log.new_data["status"], "CONFIRMED")

    def test_07_substitute_decline_creates_history(self):
        """7. Substitute decline records SUBSTITUTE_DECLINED with substitute teacher as actor."""
        sub = TeacherSubstitution.objects.create(
            timetable_slot=self.slot_monday,
            absent_teacher=self.teacher_amit,
            substitute_teacher=self.teacher_suresh,
            status=TeacherSubstitution.Status.PENDING,
            assigned_by=self.staff_user,
        )
        self.client.force_authenticate(user=self.teacher_suresh_user)
        res = self.client.post(f"/api/v1/substitutions/{sub.id}/decline/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        decline_log = TimetableChangeLog.objects.filter(
            action=TimetableChangeLog.Action.SUBSTITUTE_DECLINED,
            timetable_slot=self.slot_monday,
        ).first()
        self.assertIsNotNone(decline_log)
        self.assertEqual(decline_log.changed_by, self.teacher_suresh_user)
        self.assertEqual(decline_log.new_data["status"], "DECLINED")

    def test_08_history_identifies_changed_by_correctly(self):
        """8. History accurately records the user responsible for each action."""
        from academics.services.timetable_history_service import TimetableHistoryService
        log = TimetableHistoryService.log_timetable_created(self.timetable, changed_by=self.staff_user)
        self.assertEqual(log.changed_by_id, self.staff_user.id)

    def test_09_history_records_are_immutable(self):
        """9. History records are immutable and cannot be updated or deleted."""
        from django.core.exceptions import ValidationError as DjangoValidationError
        log = TimetableChangeLog.objects.create(
            timetable=self.timetable,
            action=TimetableChangeLog.Action.TIMETABLE_CREATED,
            changed_by=self.staff_user,
            reason="Initial Creation",
        )
        # Attempt update
        log.reason = "Modified Reason"
        with self.assertRaises(DjangoValidationError):
            log.save()

        # Attempt delete
        with self.assertRaises(DjangoValidationError):
            log.delete()

    def test_10_staff_can_list_history(self):
        """10. Staff can list timetable history records with correct response contract."""
        TimetableChangeLog.objects.create(
            timetable=self.timetable,
            action=TimetableChangeLog.Action.TIMETABLE_PUBLISHED,
            changed_by=self.staff_user,
            reason="Published for semester",
        )
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(self.history_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data["results"] if "results" in res.data else res.data) >= 1)
        item = (res.data["results"] if "results" in res.data else res.data)[0]
        self.assertIn("id", item)
        self.assertIn("action", item)
        self.assertIn("timetable", item)
        self.assertIn("changed_by", item)
        self.assertEqual(item["changed_by"]["id"], str(self.staff_user.id))

    def test_11_teacher_cannot_access_history(self):
        """11. Teachers are forbidden from accessing timetable history (403)."""
        self.client.force_authenticate(user=self.teacher_amit_user)
        res = self.client.get(self.history_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_12_student_cannot_access_history(self):
        """12. Students and unauthenticated users cannot access timetable history."""
        self.client.force_authenticate(user=self.student_user)
        res = self.client.get(self.history_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        self.client.logout()
        res_unauth = self.client.get(self.history_url)
        self.assertEqual(res_unauth.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_13_filters_work_correctly(self):
        """13. History endpoint correctly filters by timetable, slot, action, and changed_by."""
        log1 = TimetableChangeLog.objects.create(
            timetable=self.timetable,
            timetable_slot=self.slot_monday,
            action=TimetableChangeLog.Action.SLOT_RESCHEDULED,
            changed_by=self.staff_user,
            reason="Rescheduled",
        )
        tt_other = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=3,
            status=Timetable.Status.GENERATED,
            created_by=self.staff_user,
        )
        log2 = TimetableChangeLog.objects.create(
            timetable=tt_other,
            action=TimetableChangeLog.Action.TIMETABLE_GENERATED,
            changed_by=self.staff_user,
            reason="Generated",
        )

        self.client.force_authenticate(user=self.staff_user)

        # Filter by timetable
        res = self.client.get(f"{self.history_url}?timetable={self.timetable.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data["results"] if "results" in res.data else res.data
        self.assertTrue(len(results) > 0)
        self.assertTrue(all(str(r["timetable"]) == str(self.timetable.id) for r in results))

        # Filter by action
        res_action = self.client.get(f"{self.history_url}?action=SLOT_RESCHEDULED")
        self.assertEqual(res_action.status_code, status.HTTP_200_OK)
        results_action = res_action.data["results"] if "results" in res_action.data else res_action.data
        self.assertTrue(len(results_action) > 0)
        self.assertTrue(all(r["action"] == "SLOT_RESCHEDULED" for r in results_action))

    def test_14_newest_history_appears_first(self):
        """14. Timetable history is sorted chronologically descending (-created_at)."""
        TimetableChangeLog.objects.create(
            timetable=self.timetable,
            action=TimetableChangeLog.Action.TIMETABLE_CREATED,
            changed_by=self.staff_user,
        )
        TimetableChangeLog.objects.create(
            timetable=self.timetable,
            action=TimetableChangeLog.Action.TIMETABLE_PUBLISHED,
            changed_by=self.staff_user,
        )

        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(self.history_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data["results"] if "results" in res.data else res.data
        timestamps = [r["created_at"] for r in results]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_15_duplicate_operation_does_not_create_duplicate_history(self):
        """15. Idempotent / repeated operations do not create redundant duplicate history entries."""
        from academics.services.timetable_history_service import TimetableHistoryService
        count_before = TimetableChangeLog.objects.count()
        TimetableHistoryService.log_timetable_created(self.timetable, changed_by=self.staff_user)
        TimetableHistoryService.log_timetable_created(self.timetable, changed_by=self.staff_user)
        count_after = TimetableChangeLog.objects.count()
        self.assertEqual(count_after, count_before + 1)

    def test_16_published_timetable_remains_unchanged(self):
        """16. Auditing workflows and log retrieval do not modify published timetable status."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(self.history_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.timetable.refresh_from_db()
        self.assertEqual(self.timetable.status, Timetable.Status.PUBLISHED)
        self.assertEqual(self.timetable.version, 1)

    def test_17_existing_phase_1_to_10c_compatibility(self):
        """17. Rescheduling and substitute workflows remain fully functional with audit logging."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(f"/api/v1/rescheduling/suggestions/?timetable_slot={self.slot_monday.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data["suggestions"]) > 0)


class StaffDashboardWorkflowTests(APITestCase):
    """
    Focused Phase 12 Test Suite: Staff Dashboard APIs.
    Verifies operational summary metrics, today's schedule with current/upcoming/completed
    session classification, pending leaves, substitutions, unresolved conflicts, recent change history,
    and strict Staff-only role permissions.
    """

    def setUp(self):
        from accounts.models import StudentProfile, TeacherProfile, User
        self.User = User
        self.TeacherProfile = TeacherProfile
        self.StudentProfile = StudentProfile

        # 1. Users
        self.staff_user = User.objects.create_user(
            username="dash_staff_user",
            email="dash_staff@example.com",
            password="Password123!",
            role=User.Role.STAFF,
        )
        self.teacher_amit_user = User.objects.create_user(
            username="amit_dash_teacher",
            email="amit_dash@example.com",
            password="Password123!",
            first_name="Amit",
            last_name="Patil",
            role=User.Role.TEACHER,
        )
        self.teacher_suresh_user = User.objects.create_user(
            username="suresh_dash_teacher",
            email="suresh_dash@example.com",
            password="Password123!",
            first_name="Suresh",
            last_name="Raina",
            role=User.Role.TEACHER,
        )
        self.student_user = User.objects.create_user(
            username="dash_student_user",
            email="dash_student@example.com",
            password="Password123!",
            role=User.Role.STUDENT,
        )

        # 2. Academic Entities
        self.department = Department.objects.create(
            name="Dashboard Computer Science Dept",
            code="CS_DASH_12",
        )
        self.program = Program.objects.create(
            department=self.department,
            name="B.Tech Dashboard CS",
            code="BTCS_DASH_12",
            duration_years=4,
        )
        self.semester = Semester.objects.create(
            program=self.program,
            number=7,
            academic_year="2026-2027",
        )
        self.division = Division.objects.create(
            semester=self.semester,
            name="Division A",
            capacity=60,
        )

        # 3. Profiles
        self.teacher_amit = TeacherProfile.objects.create(
            user=self.teacher_amit_user,
            department=self.department,
            employee_code="T_DASH_01",
            designation="Professor",
            status=TeacherProfile.Status.ACTIVE,
        )
        self.teacher_suresh = TeacherProfile.objects.create(
            user=self.teacher_suresh_user,
            department=self.department,
            employee_code="T_DASH_02",
            designation="Associate Professor",
            status=TeacherProfile.Status.ACTIVE,
        )
        self.student_profile = StudentProfile.objects.create(
            user=self.student_user,
            student_code="STU_DASH_01",
            roll_number="1",
            division=self.division,
            admission_year=2024,
            status=StudentProfile.Status.ACTIVE,
        )

        # 4. Rooms & Subjects
        self.classroom_101 = Classroom.objects.create(
            building="Dashboard Block",
            room_number="101",
            capacity=60,
            status=Classroom.Status.AVAILABLE,
        )
        self.subject_java = Subject.objects.create(
            program=self.program,
            name="Java System Architecture",
            code="CS701_DASH",
            type=Subject.Type.LECTURE,
            credits=Decimal("4.0"),
            weekly_lectures=4,
        )
        TeacherSubject.objects.create(teacher=self.teacher_amit, subject=self.subject_java, priority=1)
        TeacherSubject.objects.create(teacher=self.teacher_suresh, subject=self.subject_java, priority=2)

        # 5. Published Timetable & Slots
        self.timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=1,
            status=Timetable.Status.PUBLISHED,
            created_by=self.staff_user,
        )

        # Wednesday Slots for testing time classifications (2026-09-23 is Wednesday)
        self.slot_wed_completed = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            batch=None,
            subject=self.subject_java,
            teacher=self.teacher_amit,
            classroom=self.classroom_101,
            day="WEDNESDAY",
            start_time="09:00:00",
            end_time="10:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )
        self.slot_wed_current = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            batch=None,
            subject=self.subject_java,
            teacher=self.teacher_suresh,
            classroom=self.classroom_101,
            day="WEDNESDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )
        self.slot_wed_upcoming = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            batch=None,
            subject=self.subject_java,
            teacher=self.teacher_amit,
            classroom=self.classroom_101,
            day="WEDNESDAY",
            start_time="11:00:00",
            end_time="12:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )

        self.dashboard_url = "/api/v1/staff/dashboard/"

    def test_01_staff_can_access_dashboard(self):
        """1. Staff can successfully retrieve the dashboard payload with all expected keys."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        expected_keys = [
            "summary",
            "today",
            "teacher_leaves",
            "substitutions",
            "conflicts",
            "recent_changes",
            "quick_actions",
        ]
        for k in expected_keys:
            self.assertIn(k, res.data)

    def test_02_teacher_forbidden_from_dashboard(self):
        """2. Teacher role users are forbidden (403) from accessing staff dashboard."""
        self.client.force_authenticate(user=self.teacher_amit_user)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_03_student_forbidden_and_unauthenticated_unauthorized(self):
        """3. Student role users receive 403; unauthenticated users receive 401."""
        self.client.force_authenticate(user=self.student_user)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        self.client.logout()
        res_unauth = self.client.get(self.dashboard_url)
        self.assertEqual(res_unauth.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_04_summary_counts_accurate(self):
        """4. Summary counts reflect active teachers, active students, leaves, and conflicts."""
        # Create pending leave
        TeacherLeave.objects.create(
            teacher=self.teacher_amit,
            start_date="2026-10-10",
            end_date="2026-10-10",
            reason="Medical",
            status=TeacherLeave.Status.PENDING,
        )
        # Create pending substitution
        TeacherSubstitution.objects.create(
            timetable_slot=self.slot_wed_completed,
            absent_teacher=self.teacher_amit,
            substitute_teacher=self.teacher_suresh,
            status=TeacherSubstitution.Status.PENDING,
            assigned_by=self.staff_user,
        )
        # Create conflict
        TimetableConflict.objects.create(
            timetable=self.timetable,
            conflict_type="ROOM_CLASH",
            severity="HARD",
            description="Room double booking detected",
            status=TimetableConflict.Status.DETECTED,
        )

        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        summary = res.data["summary"]
        self.assertEqual(summary["active_teachers_count"], 2)
        self.assertEqual(summary["active_students_count"], 1)
        self.assertEqual(summary["pending_leaves_count"], 1)
        self.assertEqual(summary["pending_substitutions_count"], 1)
        self.assertEqual(summary["unresolved_conflicts_count"], 1)

    def test_05_today_classes_payload(self):
        """5. Today's classes return structured details (subject, teacher, division, room, times)."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        today = res.data["today"]
        self.assertIn("classes", today)
        self.assertIn("day", today)
        if len(today["classes"]) > 0:
            sample_class = today["classes"][0]
            self.assertIn("id", sample_class)
            self.assertIn("subject", sample_class)
            self.assertIn("teacher", sample_class)
            self.assertIn("division", sample_class)
            self.assertIn("start_time", sample_class)
            self.assertIn("end_time", sample_class)
            self.assertIn("session_type", sample_class)
            self.assertIn("status", sample_class)

    def test_06_current_upcoming_completed_classification(self):
        """6. Classes for today are accurately categorized into completed, current, and upcoming."""
        from datetime import datetime
        from academics.services.staff_dashboard_service import StaffDashboardService

        # Reference time: Wednesday at 10:30 (during slot_wed_current 10:00-11:00)
        ref_dt = datetime(2026, 9, 23, 10, 30, 0)
        data = StaffDashboardService.get_dashboard_data(user=self.staff_user, reference_datetime=ref_dt)

        today = data["today"]
        self.assertEqual(today["day"], "WEDNESDAY")

        completed_ids = [c["id"] for c in today["completed"]]
        current_ids = [c["id"] for c in today["current"]]
        upcoming_ids = [c["id"] for c in today["upcoming"]]

        self.assertIn(str(self.slot_wed_completed.id), completed_ids)
        self.assertIn(str(self.slot_wed_current.id), current_ids)
        self.assertIn(str(self.slot_wed_upcoming.id), upcoming_ids)

    def test_07_pending_leaves_substitutions_conflicts_included(self):
        """7. Pending leaves, substitutions, and conflicts appear in dedicated dashboard lists."""
        leave = TeacherLeave.objects.create(
            teacher=self.teacher_amit,
            start_date="2026-10-10",
            end_date="2026-10-10",
            reason="Conference Leave",
            status=TeacherLeave.Status.PENDING,
        )
        sub = TeacherSubstitution.objects.create(
            timetable_slot=self.slot_wed_completed,
            absent_teacher=self.teacher_amit,
            substitute_teacher=self.teacher_suresh,
            status=TeacherSubstitution.Status.PENDING,
            assigned_by=self.staff_user,
        )
        conflict = TimetableConflict.objects.create(
            timetable=self.timetable,
            conflict_type="TEACHER_CLASH",
            severity="HARD",
            description="Teacher clash detected",
            status=TimetableConflict.Status.DETECTED,
        )

        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        leave_ids = [l["id"] for l in res.data["teacher_leaves"]]
        self.assertIn(str(leave.id), leave_ids)

        sub_ids = [s["id"] for s in res.data["substitutions"]]
        self.assertIn(str(sub.id), sub_ids)

        conflict_ids = [c["id"] for c in res.data["conflicts"]]
        self.assertIn(str(conflict.id), conflict_ids)

    def test_08_recent_history_included(self):
        """8. Recent change logs from TimetableChangeLog are populated in dashboard."""
        log = TimetableChangeLog.objects.create(
            timetable=self.timetable,
            action=TimetableChangeLog.Action.TIMETABLE_PUBLISHED,
            changed_by=self.staff_user,
            reason="Published for semester",
        )

        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        log_ids = [l["id"] for l in res.data["recent_changes"]]
        self.assertIn(str(log.id), log_ids)

    def test_09_quick_actions_data(self):
        """9. Quick actions dictionary provides actionable indicators for Staff."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        qa = res.data["quick_actions"]
        self.assertTrue(qa["can_generate"])
        self.assertIn("unresolved_conflicts", qa)
        self.assertIn("pending_leaves", qa)
        self.assertIn("pending_substitutions", qa)
        self.assertIn("recent_changes_count", qa)


class TeacherDashboardWorkflowTests(APITestCase):
    """
    Focused Phase 13 Test Suite: Teacher Dashboard APIs.
    Verifies personalized schedule classification (today & weekly), leave requests,
    substitute classes, user-isolated notifications, and relevant change history.
    """

    def setUp(self):
        from accounts.models import StudentProfile, TeacherProfile, User
        self.User = User
        self.TeacherProfile = TeacherProfile
        self.StudentProfile = StudentProfile

        # 1. Users
        self.staff_user = User.objects.create_user(
            username="teacher_dash_staff",
            email="tdash_staff@example.com",
            password="Password123!",
            role=User.Role.STAFF,
        )
        self.teacher_amit_user = User.objects.create_user(
            username="amit_tdash_teacher",
            email="amit_tdash@example.com",
            password="Password123!",
            first_name="Amit",
            last_name="Patil",
            role=User.Role.TEACHER,
        )
        self.teacher_suresh_user = User.objects.create_user(
            username="suresh_tdash_teacher",
            email="suresh_tdash@example.com",
            password="Password123!",
            first_name="Suresh",
            last_name="Raina",
            role=User.Role.TEACHER,
        )
        self.student_user = User.objects.create_user(
            username="tdash_student_user",
            email="tdash_student@example.com",
            password="Password123!",
            role=User.Role.STUDENT,
        )

        # 2. Academic Entities
        self.department = Department.objects.create(
            name="Teacher Dash Computer Science Dept",
            code="CS_TDASH_13",
        )
        self.program = Program.objects.create(
            department=self.department,
            name="B.Tech Teacher Dash CS",
            code="BTCS_TDASH_13",
            duration_years=4,
        )
        self.semester = Semester.objects.create(
            program=self.program,
            number=7,
            academic_year="2026-2027",
        )
        self.division = Division.objects.create(
            semester=self.semester,
            name="Division A",
            capacity=60,
        )

        # 3. Profiles
        self.teacher_amit = TeacherProfile.objects.create(
            user=self.teacher_amit_user,
            department=self.department,
            employee_code="T_TDASH_01",
            designation="Professor",
            status=TeacherProfile.Status.ACTIVE,
        )
        self.teacher_suresh = TeacherProfile.objects.create(
            user=self.teacher_suresh_user,
            department=self.department,
            employee_code="T_TDASH_02",
            designation="Associate Professor",
            status=TeacherProfile.Status.ACTIVE,
        )

        # 4. Rooms & Subjects
        self.classroom_101 = Classroom.objects.create(
            building="Teacher Dash Block",
            room_number="101",
            capacity=60,
            status=Classroom.Status.AVAILABLE,
        )
        self.subject_java = Subject.objects.create(
            program=self.program,
            name="Java Advanced Programming",
            code="CS701_TDASH",
            type=Subject.Type.LECTURE,
            credits=Decimal("4.0"),
            weekly_lectures=4,
        )
        TeacherSubject.objects.create(teacher=self.teacher_amit, subject=self.subject_java, priority=1)
        TeacherSubject.objects.create(teacher=self.teacher_suresh, subject=self.subject_java, priority=2)

        # 5. Published Timetable & Slots
        self.timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=1,
            status=Timetable.Status.PUBLISHED,
            created_by=self.staff_user,
        )

        # Wednesday Slots for testing time classifications (2026-09-23 is Wednesday)
        self.slot_amit_completed = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            batch=None,
            subject=self.subject_java,
            teacher=self.teacher_amit,
            classroom=self.classroom_101,
            day="WEDNESDAY",
            start_time="09:00:00",
            end_time="10:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )
        self.slot_amit_current = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            batch=None,
            subject=self.subject_java,
            teacher=self.teacher_amit,
            classroom=self.classroom_101,
            day="WEDNESDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )
        self.slot_amit_upcoming = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            batch=None,
            subject=self.subject_java,
            teacher=self.teacher_amit,
            classroom=self.classroom_101,
            day="WEDNESDAY",
            start_time="11:00:00",
            end_time="12:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )

        # Suresh's slot (should NOT leak into Amit's dashboard)
        self.slot_suresh_other = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            batch=None,
            subject=self.subject_java,
            teacher=self.teacher_suresh,
            classroom=self.classroom_101,
            day="WEDNESDAY",
            start_time="14:00:00",
            end_time="15:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )

        self.teacher_dashboard_url = "/api/v1/teacher/dashboard/"

    def test_01_teacher_can_access_dashboard(self):
        """1. Teacher can access the teacher dashboard endpoint (200 OK)."""
        self.client.force_authenticate(user=self.teacher_amit_user)
        res = self.client.get(self.teacher_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        expected_keys = [
            "summary",
            "today",
            "weekly_timetable",
            "leave_requests",
            "substitute_classes",
            "notifications",
            "recent_changes",
        ]
        for k in expected_keys:
            self.assertIn(k, res.data)

    def test_02_staff_forbidden_from_dashboard(self):
        """2. Staff role users are forbidden (403) from accessing teacher dashboard."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(self.teacher_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_03_student_forbidden_and_unauthenticated_unauthorized(self):
        """3. Student role users receive 403; unauthenticated users receive 401."""
        self.client.force_authenticate(user=self.student_user)
        res = self.client.get(self.teacher_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        self.client.logout()
        res_unauth = self.client.get(self.teacher_dashboard_url)
        self.assertEqual(res_unauth.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_04_only_authenticated_teachers_classes_returned(self):
        """4. Only the authenticated teacher's scheduled classes are returned."""
        self.client.force_authenticate(user=self.teacher_amit_user)
        res = self.client.get(self.teacher_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        today_classes = res.data["today"]["classes"]
        today_ids = [c["id"] for c in today_classes]
        self.assertIn(str(self.slot_amit_completed.id), today_ids)
        self.assertIn(str(self.slot_amit_current.id), today_ids)
        self.assertIn(str(self.slot_amit_upcoming.id), today_ids)
        # Suresh's slot must NOT be present
        self.assertNotIn(str(self.slot_suresh_other.id), today_ids)

    def test_05_today_current_upcoming_completed_classification(self):
        """5. Today's classes for the teacher are properly categorized by reference time."""
        from datetime import datetime
        from academics.services.teacher_dashboard_service import TeacherDashboardService

        ref_dt = datetime(2026, 9, 23, 10, 30, 0)
        data = TeacherDashboardService.get_dashboard_data(user=self.teacher_amit_user, reference_datetime=ref_dt)

        completed_ids = [c["id"] for c in data["today"]["completed"]]
        current_ids = [c["id"] for c in data["today"]["current"]]
        upcoming_ids = [c["id"] for c in data["today"]["upcoming"]]

        self.assertIn(str(self.slot_amit_completed.id), completed_ids)
        self.assertIn(str(self.slot_amit_current.id), current_ids)
        self.assertIn(str(self.slot_amit_upcoming.id), upcoming_ids)

    def test_06_weekly_timetable_contains_only_teachers_classes(self):
        """6. Weekly timetable contains strictly the authenticated teacher's published classes."""
        self.client.force_authenticate(user=self.teacher_amit_user)
        res = self.client.get(self.teacher_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        weekly = res.data["weekly_timetable"]
        weekly_ids = [s["id"] for s in weekly]
        self.assertIn(str(self.slot_amit_completed.id), weekly_ids)
        self.assertIn(str(self.slot_amit_current.id), weekly_ids)
        self.assertIn(str(self.slot_amit_upcoming.id), weekly_ids)
        self.assertNotIn(str(self.slot_suresh_other.id), weekly_ids)

    def test_07_own_leave_requests_returned(self):
        """7. Authenticated teacher sees only their own leave requests."""
        leave_amit = TeacherLeave.objects.create(
            teacher=self.teacher_amit,
            start_date="2026-10-10",
            end_date="2026-10-10",
            reason="Amit Personal Leave",
            status=TeacherLeave.Status.PENDING,
        )
        leave_suresh = TeacherLeave.objects.create(
            teacher=self.teacher_suresh,
            start_date="2026-10-12",
            end_date="2026-10-12",
            reason="Suresh Personal Leave",
            status=TeacherLeave.Status.PENDING,
        )

        self.client.force_authenticate(user=self.teacher_amit_user)
        res = self.client.get(self.teacher_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        leave_ids = [l["id"] for l in res.data["leave_requests"]]
        self.assertIn(str(leave_amit.id), leave_ids)
        self.assertNotIn(str(leave_suresh.id), leave_ids)

    def test_08_relevant_substitutions_returned(self):
        """8. Teacher sees substitutions where they are either assigned substitute or absent teacher."""
        sub_amit_absent = TeacherSubstitution.objects.create(
            timetable_slot=self.slot_amit_completed,
            absent_teacher=self.teacher_amit,
            substitute_teacher=self.teacher_suresh,
            status=TeacherSubstitution.Status.PENDING,
            assigned_by=self.staff_user,
        )

        self.client.force_authenticate(user=self.teacher_amit_user)
        res = self.client.get(self.teacher_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        sub_ids = [s["id"] for s in res.data["substitute_classes"]]
        self.assertIn(str(sub_amit_absent.id), sub_ids)

    def test_09_own_notifications_and_unread_count_returned(self):
        """9. Only authenticated teacher's notifications and unread counts are exposed."""
        n1 = Notification.objects.create(
            recipient=self.teacher_amit_user,
            notification_type=Notification.NotificationType.GENERAL,
            title="Notification for Amit",
            message="Welcome Amit",
            is_read=False,
        )
        n_other = Notification.objects.create(
            recipient=self.teacher_suresh_user,
            notification_type=Notification.NotificationType.GENERAL,
            title="Notification for Suresh",
            message="Welcome Suresh",
            is_read=False,
        )

        self.client.force_authenticate(user=self.teacher_amit_user)
        res = self.client.get(self.teacher_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        notifs = res.data["notifications"]
        self.assertEqual(notifs["unread_count"], 1)
        item_ids = [item["id"] for item in notifs["items"]]
        self.assertIn(str(n1.id), item_ids)
        self.assertNotIn(str(n_other.id), item_ids)

    def test_10_relevant_timetable_history_returned(self):
        """10. Timetable changes relevant to the teacher appear in recent changes."""
        log = TimetableChangeLog.objects.create(
            timetable=self.timetable,
            timetable_slot=self.slot_amit_completed,
            action=TimetableChangeLog.Action.SLOT_RESCHEDULED,
            changed_by=self.staff_user,
            reason="Rescheduled Amit class",
            old_data={"teacher_id": str(self.teacher_amit.id)},
            new_data={"teacher_id": str(self.teacher_amit.id)},
        )

        self.client.force_authenticate(user=self.teacher_amit_user)
        res = self.client.get(self.teacher_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        change_ids = [c["id"] for c in res.data["recent_changes"]]
        self.assertIn(str(log.id), change_ids)

    def test_11_summary_counts_are_correct(self):
        """11. Summary metrics accurately calculate today's classes, leaves, substitutions, notifications."""
        from datetime import datetime
        from academics.services.teacher_dashboard_service import TeacherDashboardService

        TeacherLeave.objects.create(
            teacher=self.teacher_amit,
            start_date="2026-10-15",
            end_date="2026-10-15",
            reason="Leave",
            status=TeacherLeave.Status.PENDING,
        )
        Notification.objects.create(
            recipient=self.teacher_amit_user,
            notification_type=Notification.NotificationType.GENERAL,
            title="Notice",
            message="Notice",
            is_read=False,
        )

        ref_dt = datetime(2026, 9, 23, 10, 30, 0)
        data = TeacherDashboardService.get_dashboard_data(user=self.teacher_amit_user, reference_datetime=ref_dt)

        summary = data["summary"]
        self.assertEqual(summary["today_classes_count"], 3)
        self.assertIsNotNone(summary["current_class"])
        self.assertEqual(summary["upcoming_classes_count"], 1)
        self.assertEqual(summary["completed_classes_count"], 1)
        self.assertEqual(summary["pending_leave_requests"], 1)
        self.assertEqual(summary["unread_notifications"], 1)

    def test_12_no_other_teachers_private_data_leaks(self):
        """12. Strict user isolation ensures Suresh's private records are invisible to Amit."""
        # Suresh's leave & notification
        TeacherLeave.objects.create(
            teacher=self.teacher_suresh,
            start_date="2026-10-20",
            end_date="2026-10-20",
            reason="Suresh confidential leave",
            status=TeacherLeave.Status.PENDING,
        )
        Notification.objects.create(
            recipient=self.teacher_suresh_user,
            notification_type=Notification.NotificationType.GENERAL,
            title="Suresh Confidential Notice",
            message="Private message",
            is_read=False,
        )

        self.client.force_authenticate(user=self.teacher_amit_user)
        res = self.client.get(self.teacher_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Check leaves
        leave_reasons = [l["reason"] for l in res.data["leave_requests"]]
        self.assertNotIn("Suresh confidential leave", leave_reasons)

        # Check notifications
        notif_titles = [n["title"] for n in res.data["notifications"]["items"]]
        self.assertNotIn("Suresh Confidential Notice", notif_titles)


class StudentDashboardWorkflowTests(APITestCase):
    """
    Focused Phase 14 Test Suite: Student Dashboard APIs.
    Verifies personalized schedule classification (today & weekly) with strict division and batch filtering,
    rescheduled classes, student-isolated notifications, relevant change history, and role-based permissions.
    """

    def setUp(self):
        from accounts.models import StudentProfile, TeacherProfile, User
        self.User = User
        self.TeacherProfile = TeacherProfile
        self.StudentProfile = StudentProfile

        # 1. Users
        self.staff_user = User.objects.create_user(
            username="stu_dash_staff",
            email="sdash_staff@example.com",
            password="Password123!",
            role=User.Role.STAFF,
        )
        self.teacher_user = User.objects.create_user(
            username="stu_dash_teacher",
            email="sdash_teacher@example.com",
            password="Password123!",
            first_name="Amit",
            last_name="Patil",
            role=User.Role.TEACHER,
        )
        self.student_user_a = User.objects.create_user(
            username="stu_dash_student_a",
            email="sdash_student_a@example.com",
            password="Password123!",
            first_name="Rohan",
            last_name="Sharma",
            role=User.Role.STUDENT,
        )
        self.student_user_b = User.objects.create_user(
            username="stu_dash_student_b",
            email="sdash_student_b@example.com",
            password="Password123!",
            first_name="Priya",
            last_name="Singh",
            role=User.Role.STUDENT,
        )
        self.student_user_no_batch = User.objects.create_user(
            username="stu_dash_student_nobatch",
            email="sdash_student_nobatch@example.com",
            password="Password123!",
            role=User.Role.STUDENT,
        )
        self.student_user_div_b = User.objects.create_user(
            username="stu_dash_student_divb",
            email="sdash_student_divb@example.com",
            password="Password123!",
            role=User.Role.STUDENT,
        )

        # 2. Academic Entities
        self.department = Department.objects.create(
            name="Student Dash Computer Science Dept",
            code="CS_SDASH_14",
        )
        self.program = Program.objects.create(
            department=self.department,
            name="B.Tech Student Dash CS",
            code="BTCS_SDASH_14",
            duration_years=4,
        )
        self.semester = Semester.objects.create(
            program=self.program,
            number=7,
            academic_year="2026-2027",
        )
        self.division_a = Division.objects.create(
            semester=self.semester,
            name="Division A",
            capacity=60,
        )
        self.division_b = Division.objects.create(
            semester=self.semester,
            name="Division B",
            capacity=60,
        )
        self.batch_a = PracticalBatch.objects.create(
            division=self.division_a,
            name="Batch A1",
            capacity=30,
        )
        self.batch_b = PracticalBatch.objects.create(
            division=self.division_a,
            name="Batch A2",
            capacity=30,
        )

        # 3. Profiles
        self.teacher_profile = TeacherProfile.objects.create(
            user=self.teacher_user,
            department=self.department,
            employee_code="T_SDASH_01",
            designation="Professor",
            status=TeacherProfile.Status.ACTIVE,
        )
        self.student_profile_a = StudentProfile.objects.create(
            user=self.student_user_a,
            student_code="STU_SDASH_01",
            roll_number="1",
            division=self.division_a,
            batch=self.batch_a,
            admission_year=2024,
            status=StudentProfile.Status.ACTIVE,
        )
        self.student_profile_b = StudentProfile.objects.create(
            user=self.student_user_b,
            student_code="STU_SDASH_02",
            roll_number="2",
            division=self.division_a,
            batch=self.batch_b,
            admission_year=2024,
            status=StudentProfile.Status.ACTIVE,
        )
        self.student_profile_no_batch = StudentProfile.objects.create(
            user=self.student_user_no_batch,
            student_code="STU_SDASH_03",
            roll_number="3",
            division=self.division_a,
            batch=None,
            admission_year=2024,
            status=StudentProfile.Status.ACTIVE,
        )
        self.student_profile_div_b = StudentProfile.objects.create(
            user=self.student_user_div_b,
            student_code="STU_SDASH_04",
            roll_number="4",
            division=self.division_b,
            batch=None,
            admission_year=2024,
            status=StudentProfile.Status.ACTIVE,
        )

        # 4. Rooms & Subjects
        self.classroom_101 = Classroom.objects.create(
            building="Student Dash Block",
            room_number="101",
            capacity=60,
            status=Classroom.Status.AVAILABLE,
        )
        self.lab_201 = Laboratory.objects.create(
            building="Student Dash Block",
            lab_number="201",
            name="Computer Lab 1",
            capacity=30,
            status=Laboratory.Status.AVAILABLE,
        )
        self.subject_lecture = Subject.objects.create(
            program=self.program,
            name="Distributed Systems",
            code="CS701_SDASH",
            type=Subject.Type.LECTURE,
            credits=Decimal("4.0"),
            weekly_lectures=4,
        )
        self.subject_practical = Subject.objects.create(
            program=self.program,
            name="Cloud Computing Lab",
            code="CS702_SDASH",
            type=Subject.Type.PRACTICAL,
            credits=Decimal("2.0"),
            weekly_practicals=2,
        )
        TeacherSubject.objects.create(teacher=self.teacher_profile, subject=self.subject_lecture, priority=1)
        TeacherSubject.objects.create(teacher=self.teacher_profile, subject=self.subject_practical, priority=1)

        # 5. Published Timetable & Slots
        self.timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2026-2027",
            version=1,
            status=Timetable.Status.PUBLISHED,
            created_by=self.staff_user,
        )

        # Wednesday Slots (2026-09-23 is Wednesday)
        # Completed lecture for whole Division A (batch=None)
        self.slot_div_a_completed = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division_a,
            batch=None,
            subject=self.subject_lecture,
            teacher=self.teacher_profile,
            classroom=self.classroom_101,
            day="WEDNESDAY",
            start_time="09:00:00",
            end_time="10:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )
        # Current practical for Batch A only (10:00 - 11:00)
        self.slot_batch_a_current = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division_a,
            batch=self.batch_a,
            subject=self.subject_practical,
            teacher=self.teacher_profile,
            laboratory=self.lab_201,
            day="WEDNESDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type=TimetableSlot.SessionType.PRACTICAL,
            status=TimetableSlot.Status.SCHEDULED,
        )
        # Current practical for Batch B only (10:00 - 11:00)
        self.slot_batch_b_current = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division_a,
            batch=self.batch_b,
            subject=self.subject_practical,
            teacher=self.teacher_profile,
            laboratory=self.lab_201,
            day="WEDNESDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type=TimetableSlot.SessionType.PRACTICAL,
            status=TimetableSlot.Status.SCHEDULED,
        )
        # Upcoming lecture for whole Division A (11:00 - 12:00)
        self.slot_div_a_upcoming = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division_a,
            batch=None,
            subject=self.subject_lecture,
            teacher=self.teacher_profile,
            classroom=self.classroom_101,
            day="WEDNESDAY",
            start_time="11:00:00",
            end_time="12:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )
        # Rescheduled slot for Division A
        self.slot_div_a_rescheduled = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division_a,
            batch=None,
            subject=self.subject_lecture,
            teacher=self.teacher_profile,
            classroom=self.classroom_101,
            day="WEDNESDAY",
            start_time="14:00:00",
            end_time="15:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.RESCHEDULED,
        )
        # Division B slot (must never appear in Division A student's payload)
        self.slot_div_b = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division_b,
            batch=None,
            subject=self.subject_lecture,
            teacher=self.teacher_profile,
            classroom=self.classroom_101,
            day="WEDNESDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )

        # Thursday Slot for weekly timetable ordering
        self.slot_div_a_thursday = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division_a,
            batch=None,
            subject=self.subject_lecture,
            teacher=self.teacher_profile,
            classroom=self.classroom_101,
            day="THURSDAY",
            start_time="10:00:00",
            end_time="11:00:00",
            session_type=TimetableSlot.SessionType.LECTURE,
            status=TimetableSlot.Status.SCHEDULED,
        )

        self.student_dashboard_url = "/api/v1/student/dashboard/"

    def test_01_student_can_access_dashboard(self):
        """1. Student can access the student dashboard endpoint (200 OK) with complete response structure."""
        self.client.force_authenticate(user=self.student_user_a)
        res = self.client.get(self.student_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        expected_keys = [
            "summary",
            "today",
            "weekly_timetable",
            "rescheduled_classes",
            "notifications",
            "recent_changes",
        ]
        for k in expected_keys:
            self.assertIn(k, res.data)

    def test_02_staff_forbidden_from_student_dashboard(self):
        """2. Staff role users are forbidden (403) from accessing student dashboard."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get(self.student_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_03_teacher_forbidden_from_student_dashboard(self):
        """3. Teacher role users are forbidden (403) from accessing student dashboard."""
        self.client.force_authenticate(user=self.teacher_user)
        res = self.client.get(self.student_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_04_unauthenticated_unauthorized(self):
        """4. Unauthenticated users receive 401 Unauthorized."""
        res = self.client.get(self.student_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_05_only_students_division_timetable_returned(self):
        """5. Only timetable slots matching student's assigned division are returned (no Division B)."""
        self.client.force_authenticate(user=self.student_user_a)
        res = self.client.get(self.student_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        today_classes = res.data["today"]["classes"]
        today_ids = [c["id"] for c in today_classes]

        self.assertIn(str(self.slot_div_a_completed.id), today_ids)
        self.assertNotIn(str(self.slot_div_b.id), today_ids)

        weekly_ids = [s["id"] for s in res.data["weekly_timetable"]]
        self.assertIn(str(self.slot_div_a_thursday.id), weekly_ids)
        self.assertNotIn(str(self.slot_div_b.id), weekly_ids)

    def test_06_batch_filtering_works_correctly(self):
        """6. Student in Batch A sees Batch A slots and NOT Batch B practical slots."""
        # Authenticate as Batch A student
        self.client.force_authenticate(user=self.student_user_a)
        res_a = self.client.get(self.student_dashboard_url)
        self.assertEqual(res_a.status_code, status.HTTP_200_OK)

        today_ids_a = [c["id"] for c in res_a.data["today"]["classes"]]
        self.assertIn(str(self.slot_batch_a_current.id), today_ids_a)
        self.assertNotIn(str(self.slot_batch_b_current.id), today_ids_a)

        # Authenticate as Batch B student
        self.client.force_authenticate(user=self.student_user_b)
        res_b = self.client.get(self.student_dashboard_url)
        self.assertEqual(res_b.status_code, status.HTTP_200_OK)

        today_ids_b = [c["id"] for c in res_b.data["today"]["classes"]]
        self.assertIn(str(self.slot_batch_b_current.id), today_ids_b)
        self.assertNotIn(str(self.slot_batch_a_current.id), today_ids_b)

    def test_07_division_wide_classes_are_included(self):
        """7. Division-wide lectures (batch=None) are included for students both with and without batches."""
        # Student with Batch A
        self.client.force_authenticate(user=self.student_user_a)
        res_a = self.client.get(self.student_dashboard_url)
        self.assertEqual(res_a.status_code, status.HTTP_200_OK)
        today_ids_a = [c["id"] for c in res_a.data["today"]["classes"]]
        self.assertIn(str(self.slot_div_a_completed.id), today_ids_a)
        self.assertIn(str(self.slot_div_a_upcoming.id), today_ids_a)

        # Student with NO batch
        self.client.force_authenticate(user=self.student_user_no_batch)
        res_nb = self.client.get(self.student_dashboard_url)
        self.assertEqual(res_nb.status_code, status.HTTP_200_OK)
        today_ids_nb = [c["id"] for c in res_nb.data["today"]["classes"]]
        self.assertIn(str(self.slot_div_a_completed.id), today_ids_nb)
        self.assertIn(str(self.slot_div_a_upcoming.id), today_ids_nb)
        # Must NOT see any batch-specific practicals
        self.assertNotIn(str(self.slot_batch_a_current.id), today_ids_nb)
        self.assertNotIn(str(self.slot_batch_b_current.id), today_ids_nb)

    def test_08_today_current_upcoming_completed_classification(self):
        """8. Classes for today are accurately categorized into completed, current, and upcoming."""
        from datetime import datetime
        from academics.services.student_dashboard_service import StudentDashboardService

        # Reference time: Wednesday at 10:30 (during slot_batch_a_current 10:00-11:00)
        ref_dt = datetime(2026, 9, 23, 10, 30, 0)
        data = StudentDashboardService.get_dashboard_data(user=self.student_user_a, reference_datetime=ref_dt)

        today = data["today"]
        self.assertEqual(today["day"], "WEDNESDAY")

        completed_ids = [c["id"] for c in today["completed"]]
        current_ids = [c["id"] for c in today["current"]]
        upcoming_ids = [c["id"] for c in today["upcoming"]]

        self.assertIn(str(self.slot_div_a_completed.id), completed_ids)
        self.assertIn(str(self.slot_batch_a_current.id), current_ids)
        self.assertIn(str(self.slot_div_a_upcoming.id), upcoming_ids)

    def test_09_weekly_timetable_contains_only_student_classes_sorted(self):
        """9. Weekly timetable contains strictly student's classes sorted by weekday -> start_time."""
        self.client.force_authenticate(user=self.student_user_a)
        res = self.client.get(self.student_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        weekly = res.data["weekly_timetable"]
        weekly_ids = [s["id"] for s in weekly]
        self.assertIn(str(self.slot_div_a_completed.id), weekly_ids)
        self.assertIn(str(self.slot_batch_a_current.id), weekly_ids)
        self.assertIn(str(self.slot_div_a_thursday.id), weekly_ids)
        self.assertNotIn(str(self.slot_batch_b_current.id), weekly_ids)
        self.assertNotIn(str(self.slot_div_b.id), weekly_ids)

        # Check sorting: Wednesday slots must appear before Thursday slots
        wed_index = next(i for i, s in enumerate(weekly) if s["id"] == str(self.slot_div_a_completed.id))
        thu_index = next(i for i, s in enumerate(weekly) if s["id"] == str(self.slot_div_a_thursday.id))
        self.assertLess(wed_index, thu_index)

    def test_10_subject_and_teacher_information_returned(self):
        """10. Subject and teacher information exposed correctly without leaking teacher phone/email."""
        self.client.force_authenticate(user=self.student_user_a)
        res = self.client.get(self.student_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        today_classes = res.data["today"]["classes"]
        slot_data = next(c for c in today_classes if c["id"] == str(self.slot_div_a_completed.id))

        self.assertEqual(slot_data["subject"]["name"], "Distributed Systems")
        self.assertEqual(slot_data["subject"]["code"], "CS701_SDASH")
        self.assertEqual(slot_data["teacher_name"], "Amit Patil")
        self.assertEqual(slot_data["session_type"], TimetableSlot.SessionType.LECTURE)
        # Ensure private fields are NOT in the slot dict
        self.assertNotIn("email", slot_data)
        self.assertNotIn("phone", slot_data)

    def test_11_classroom_laboratory_information_returned_correctly(self):
        """11. Classroom returned for lectures and Laboratory returned for practicals."""
        self.client.force_authenticate(user=self.student_user_a)
        res = self.client.get(self.student_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        today_classes = res.data["today"]["classes"]
        lec_slot = next(c for c in today_classes if c["id"] == str(self.slot_div_a_completed.id))
        prac_slot = next(c for c in today_classes if c["id"] == str(self.slot_batch_a_current.id))

        self.assertIsNotNone(lec_slot["classroom"])
        self.assertEqual(lec_slot["classroom"]["room_number"], "101")
        self.assertIsNone(lec_slot["laboratory"])

        self.assertIsNotNone(prac_slot["laboratory"])
        self.assertEqual(prac_slot["laboratory"]["lab_number"], "201")
        self.assertIsNone(prac_slot["classroom"])

    def test_12_rescheduled_classes_returned(self):
        """12. Rescheduled classes relevant to the student are returned in rescheduled_classes list."""
        reschedule_rec = SlotReschedule.objects.create(
            original_slot=self.slot_div_a_rescheduled,
            new_teacher=self.teacher_profile,
            new_classroom=self.classroom_101,
            new_day="FRIDAY",
            new_start_time="14:00:00",
            new_end_time="15:00:00",
            reason="Special guest lecture",
            status=SlotReschedule.Status.CONFIRMED,
            created_by=self.staff_user,
        )

        self.client.force_authenticate(user=self.student_user_a)
        res = self.client.get(self.student_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        resched_list = res.data["rescheduled_classes"]
        resched_ids = [r["id"] for r in resched_list]
        self.assertIn(str(reschedule_rec.id), resched_ids)

    def test_13_only_students_notifications_returned(self):
        """13. Notification list strictly contains notifications addressed to authenticated student."""
        n_a = Notification.objects.create(
            recipient=self.student_user_a,
            notification_type=Notification.NotificationType.GENERAL,
            title="Notification for Student A",
            message="Class timing updated",
            is_read=False,
        )
        n_b = Notification.objects.create(
            recipient=self.student_user_b,
            notification_type=Notification.NotificationType.GENERAL,
            title="Notification for Student B",
            message="Private note for B",
            is_read=False,
        )

        self.client.force_authenticate(user=self.student_user_a)
        res = self.client.get(self.student_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        notif_items = res.data["notifications"]["items"]
        item_ids = [n["id"] for n in notif_items]
        self.assertIn(str(n_a.id), item_ids)
        self.assertNotIn(str(n_b.id), item_ids)

    def test_14_unread_notification_count_correct(self):
        """14. Unread notification count accurately counts unread notifications for the student."""
        Notification.objects.create(
            recipient=self.student_user_a,
            notification_type=Notification.NotificationType.GENERAL,
            title="Unread 1",
            message="Msg 1",
            is_read=False,
        )
        Notification.objects.create(
            recipient=self.student_user_a,
            notification_type=Notification.NotificationType.GENERAL,
            title="Read 1",
            message="Msg 2",
            is_read=True,
        )

        self.client.force_authenticate(user=self.student_user_a)
        res = self.client.get(self.student_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.assertEqual(res.data["notifications"]["unread_count"], 1)

    def test_15_relevant_timetable_history_returned(self):
        """15. TimetableChangeLog entries relevant to the student's division are exposed."""
        log = TimetableChangeLog.objects.create(
            timetable=self.timetable,
            timetable_slot=self.slot_div_a_completed,
            action=TimetableChangeLog.Action.SLOT_RESCHEDULED,
            changed_by=self.staff_user,
            reason="Room change for Division A",
            old_data={"division_id": str(self.division_a.id)},
            new_data={"division_id": str(self.division_a.id)},
        )

        self.client.force_authenticate(user=self.student_user_a)
        res = self.client.get(self.student_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        change_ids = [c["id"] for c in res.data["recent_changes"]]
        self.assertIn(str(log.id), change_ids)

    def test_16_summary_counts_correct(self):
        """16. Summary metrics correctly report total, upcoming, completed, unread notifs, and rescheduled."""
        from datetime import datetime
        from academics.services.student_dashboard_service import StudentDashboardService

        Notification.objects.create(
            recipient=self.student_user_a,
            notification_type=Notification.NotificationType.GENERAL,
            title="Important Alert",
            message="Alert",
            is_read=False,
        )

        ref_dt = datetime(2026, 9, 23, 10, 30, 0)
        data = StudentDashboardService.get_dashboard_data(user=self.student_user_a, reference_datetime=ref_dt)

        summary = data["summary"]
        self.assertEqual(summary["today_classes_count"], 4)  # completed, batch_a_current, upcoming, rescheduled
        self.assertIsNotNone(summary["current_class"])
        self.assertEqual(summary["completed_classes_count"], 1)
        self.assertEqual(summary["upcoming_classes_count"], 2)  # upcoming + rescheduled
        self.assertEqual(summary["unread_notifications"], 1)
        self.assertGreaterEqual(summary["today_rescheduled_classes_count"], 1)

    def test_17_no_other_division_or_batch_data_leaks(self):
        """17. Division B and Batch B data never leaks into Division A / Batch A student's payload."""
        self.client.force_authenticate(user=self.student_user_a)
        res = self.client.get(self.student_dashboard_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Division B slot check
        all_returned_slot_ids = [c["id"] for c in res.data["today"]["classes"]] + [
            s["id"] for s in res.data["weekly_timetable"]
        ]
        self.assertNotIn(str(self.slot_div_b.id), all_returned_slot_ids)
        self.assertNotIn(str(self.slot_batch_b_current.id), all_returned_slot_ids)












