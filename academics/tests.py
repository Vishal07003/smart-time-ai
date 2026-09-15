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
