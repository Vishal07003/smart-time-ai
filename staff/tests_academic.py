from django.test import Client, TestCase
from django.urls import reverse
from accounts.models import User
from academics.models import Department, Program, Semester, Division, PracticalBatch

class StaffAcademicManagementTests(TestCase):
    """
    Focused tests for Staff Academic Management:
    - /staff/academic/departments/
    - /staff/academic/programs/
    - /staff/academic/semesters/
    - /staff/academic/divisions/
    - /staff/academic/batches/
    Ensuring hierarchy: Department -> Program -> Semester -> Division -> PracticalBatch
    List, search, create, edit, duplicate validation, and permissions.
    """

    def setUp(self):
        self.client = Client()

        # Users
        self.staff_user = User.objects.create_user(
            username="staff_academic_admin",
            email="staff.academic@smarttime.ai",
            password="StaffPassword123!",
            role=User.Role.STAFF,
            first_name="Academic",
            last_name="Staff",
        )
        self.student_user = User.objects.create_user(
            username="student_academic_user",
            email="student.academic@smarttime.ai",
            password="StudentPassword123!",
            role=User.Role.STUDENT,
        )

        # Baseline Department & Academic Records
        self.department = Department.objects.create(
            name="Computer Engineering",
            code="CE",
        )
        self.program = Program.objects.create(
            department=self.department,
            name="B.Tech Computer Science",
            code="BTCS",
            duration_years=4,
        )
        self.semester = Semester.objects.create(
            program=self.program,
            number=3,
            academic_year="2026-2027",
        )
        self.division = Division.objects.create(
            semester=self.semester,
            name="A",
            capacity=60,
        )
        self.batch = PracticalBatch.objects.create(
            division=self.division,
            name="P1",
            capacity=30,
        )

    def test_permission_enforcement_for_non_staff(self):
        """Non-staff users should not be able to access academic management views."""
        # Unauthenticated
        response = self.client.get(reverse("staff:academic_departments"))
        self.assertNotEqual(response.status_code, 200)

        response = self.client.get(reverse("staff:academic_programs"))
        self.assertNotEqual(response.status_code, 200)

        # Logged in as student
        self.client.force_login(self.student_user)
        response = self.client.get(reverse("staff:academic_departments"))
        self.assertNotEqual(response.status_code, 200)

        response = self.client.get(reverse("staff:academic_programs"))
        self.assertNotEqual(response.status_code, 200)

    # --------------------------------------------------------------------------
    # DEPARTMENT TESTS
    # --------------------------------------------------------------------------
    def test_department_list_and_search(self):
        """Staff can list and search departments."""
        self.client.force_login(self.staff_user)

        # List
        response = self.client.get(reverse("staff:academic_departments"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CE")
        self.assertContains(response, "Computer Engineering")

        # Search matching
        response = self.client.get(reverse("staff:academic_departments") + "?q=Computer")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CE")

        # Search non-matching
        response = self.client.get(reverse("staff:academic_departments") + "?q=Mechanical")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Computer Engineering")

    def test_department_create_and_edit(self):
        """Staff can create and edit an academic department."""
        self.client.force_login(self.staff_user)

        # Create
        create_url = reverse("staff:academic_department_create")
        post_data = {
            "name": "Mechanical Engineering",
            "code": "MECH",
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 302)
        new_dept = Department.objects.get(code="MECH")
        self.assertEqual(new_dept.name, "Mechanical Engineering")

        # Edit
        edit_url = reverse("staff:academic_department_edit", kwargs={"id": new_dept.id})
        edit_data = {
            "name": "Mechanical & Aerospace Engineering",
            "code": "MECH",
        }
        response = self.client.post(edit_url, edit_data)
        self.assertEqual(response.status_code, 302)
        new_dept.refresh_from_db()
        self.assertEqual(new_dept.name, "Mechanical & Aerospace Engineering")

    def test_department_duplicate_validation(self):
        """Cannot create a department with duplicate code (case-insensitive)."""
        self.client.force_login(self.staff_user)
        create_url = reverse("staff:academic_department_create")
        post_data = {
            "name": "Civil Engineering",
            "code": "ce",  # already exists as CE
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, "form", "code", "A department with this code already exists.")

    def test_department_available_in_program_form(self):
        """Created department must be selectable in the ProgramForm."""
        from staff.forms import ProgramForm
        new_dept = Department.objects.create(name="Electrical Engineering", code="EE")
        form = ProgramForm()
        dept_ids = [str(d.id) for d in form.fields["department"].queryset]
        self.assertIn(str(new_dept.id), dept_ids)

    # --------------------------------------------------------------------------
    # PROGRAM TESTS
    # --------------------------------------------------------------------------
    def test_program_list_and_search(self):
        """Staff can list and search programs."""
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("staff:academic_programs"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "BTCS")
        self.assertContains(response, "B.Tech Computer Science")

        # Search query
        response = self.client.get(reverse("staff:academic_programs") + "?q=Computer")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "BTCS")

        response = self.client.get(reverse("staff:academic_programs") + "?q=NonExistent")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "BTCS")

        # Department filter
        response = self.client.get(reverse("staff:academic_programs") + f"?department={self.department.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "BTCS")

    def test_program_create_and_edit(self):
        """Staff can create and edit a program."""
        self.client.force_login(self.staff_user)

        # Create
        create_url = reverse("staff:academic_program_create")
        post_data = {
            "department": str(self.department.id),
            "name": "B.Tech Information Technology",
            "code": "BTIT",
            "duration_years": 4,
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 302)
        new_prog = Program.objects.get(code="BTIT")
        self.assertEqual(new_prog.name, "B.Tech Information Technology")
        self.assertEqual(new_prog.department, self.department)

        # Edit
        edit_url = reverse("staff:academic_program_edit", kwargs={"id": new_prog.id})
        edit_data = {
            "department": str(self.department.id),
            "name": "B.Tech IT - Revised",
            "code": "BTIT",
            "duration_years": 4,
        }
        response = self.client.post(edit_url, edit_data)
        self.assertEqual(response.status_code, 302)
        new_prog.refresh_from_db()
        self.assertEqual(new_prog.name, "B.Tech IT - Revised")

    def test_program_duplicate_code_validation(self):
        """Cannot create or edit program with duplicate code (case-insensitive)."""
        self.client.force_login(self.staff_user)
        create_url = reverse("staff:academic_program_create")
        post_data = {
            "department": str(self.department.id),
            "name": "Duplicate Computer Science",
            "code": "btcs",  # already exists as BTCS
            "duration_years": 4,
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, "form", "code", "A program with this code already exists.")

    def test_program_appears_in_semester_selection(self):
        """Newly created program appears in SemesterForm choices."""
        from staff.forms import SemesterForm
        new_prog = Program.objects.create(
            department=self.department,
            name="M.Tech AI & Data Science",
            code="MTAI",
            duration_years=2,
        )
        form = SemesterForm()
        program_ids = [str(p.id) for p in form.fields["program"].queryset]
        self.assertIn(str(new_prog.id), program_ids)

    def test_program_department_relationship_preserves_semesters(self):
        """Editing a program preserves its related semesters."""
        self.client.force_login(self.staff_user)
        # Create second department
        new_dept = Department.objects.create(name="School of Computing", code="SOC")
        edit_url = reverse("staff:academic_program_edit", kwargs={"id": self.program.id})
        edit_data = {
            "department": str(new_dept.id),
            "name": "B.Tech Computer Science and Engineering",
            "code": "BTCS",
            "duration_years": 4,
        }
        response = self.client.post(edit_url, edit_data)
        self.assertEqual(response.status_code, 302)
        self.program.refresh_from_db()
        self.assertEqual(self.program.department, new_dept)
        # Verify related semester still belongs to this program
        self.assertEqual(self.semester.program, self.program)


    # --------------------------------------------------------------------------
    # SEMESTER TESTS
    # --------------------------------------------------------------------------
    def test_semester_list_search_and_create(self):
        """Staff can list, filter and create semesters."""
        self.client.force_login(self.staff_user)

        # List
        response = self.client.get(reverse("staff:academic_semesters"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Semester 3")

        # Create semester
        create_url = reverse("staff:academic_semester_create")
        post_data = {
            "program": str(self.program.id),
            "number": 4,
            "academic_year": "2026-2027",
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Semester.objects.filter(program=self.program, number=4, academic_year="2026-2027").exists())

    def test_semester_validation_bounds(self):
        """Semester number cannot exceed program duration * 2."""
        self.client.force_login(self.staff_user)
        create_url = reverse("staff:academic_semester_create")
        post_data = {
            "program": str(self.program.id),
            "number": 9,
            "academic_year": "2026-2027",
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, "form", "number", "Semester number (9) cannot exceed maximum program semesters (8).")

    # --------------------------------------------------------------------------
    # DIVISION TESTS
    # --------------------------------------------------------------------------
    def test_division_create_and_edit(self):
        """Staff can create and edit divisions under a semester."""
        self.client.force_login(self.staff_user)

        # Create
        create_url = reverse("staff:academic_division_create")
        post_data = {
            "semester": str(self.semester.id),
            "name": "B",
            "capacity": 65,
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Division.objects.filter(semester=self.semester, name="B").exists())

        # Edit
        div_b = Division.objects.get(semester=self.semester, name="B")
        edit_url = reverse("staff:academic_division_edit", kwargs={"id": div_b.id})
        post_data["capacity"] = 70
        response = self.client.post(edit_url, post_data)
        self.assertEqual(response.status_code, 302)
        div_b.refresh_from_db()
        self.assertEqual(div_b.capacity, 70)

    # --------------------------------------------------------------------------
    # BATCH TESTS
    # --------------------------------------------------------------------------
    def test_batch_create_and_edit(self):
        """Staff can create and edit practical batches under a division."""
        self.client.force_login(self.staff_user)

        # Create
        create_url = reverse("staff:academic_batch_create")
        post_data = {
            "division": str(self.division.id),
            "name": "P2",
            "capacity": 30,
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PracticalBatch.objects.filter(division=self.division, name="P2").exists())

        # Edit
        batch_p2 = PracticalBatch.objects.get(division=self.division, name="P2")
        edit_url = reverse("staff:academic_batch_edit", kwargs={"id": batch_p2.id})
        post_data["capacity"] = 25
        response = self.client.post(edit_url, post_data)
        self.assertEqual(response.status_code, 302)
        batch_p2.refresh_from_db()
        self.assertEqual(batch_p2.capacity, 25)

    def test_hierarchy_relations(self):
        """Verify navigation and relation cascade."""
        self.assertEqual(self.batch.division, self.division)
        self.assertEqual(self.division.semester, self.semester)
        self.assertEqual(self.semester.program, self.program)
        self.assertEqual(self.program.department, self.department)

    # --------------------------------------------------------------------------
    # GUIDED ACADEMIC STRUCTURE WIZARD TESTS
    # --------------------------------------------------------------------------
    def test_academic_structure_wizard_permissions(self):
        """Non-staff users cannot access wizard view or hierarchy API."""
        # Unauthenticated
        url = reverse("staff:academic_structure_create")
        api_url = reverse("staff:api_academic_hierarchy")
        res = self.client.get(url)
        self.assertNotEqual(res.status_code, 200)

        # Student user
        self.client.force_login(self.student_user)
        self.assertNotEqual(self.client.get(url).status_code, 200)
        self.assertNotEqual(self.client.get(api_url).status_code, 200)

    def test_academic_structure_wizard_get_and_api(self):
        """Staff can load wizard GET page and query hierarchy JSON API."""
        self.client.force_login(self.staff_user)

        res = self.client.get(reverse("staff:academic_structure_create"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Create Academic Structure")

        api_res = self.client.get(reverse("staff:api_academic_hierarchy"))
        self.assertEqual(api_res.status_code, 200)
        data = api_res.json()
        self.assertIn("departments", data)
        self.assertTrue(any(d["code"] == "CE" for d in data["departments"]))

    def test_academic_structure_wizard_full_flow_with_batch(self):
        """Staff can create a complete academic hierarchy in one flow."""
        self.client.force_login(self.staff_user)
        url = reverse("staff:academic_structure_create")

        payload = {
            "dept_mode": "new",
            "dept_data": {"name": "Electrical & Electronics Engineering", "code": "EEE"},
            "prog_mode": "new",
            "prog_data": {"name": "B.Tech Electrical Engineering", "code": "BTEEE", "duration_years": 4},
            "sem_mode": "new",
            "sem_data": {"number": 1, "academic_year": "2026-2027"},
            "div_mode": "new",
            "div_data": {"name": "A", "capacity": 60},
            "batch_create": True,
            "batch_data": {"name": "P1", "capacity": 30},
        }

        res = self.client.post(url, data=payload, content_type="application/json")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))

        # Verify DB records and relationships
        dept = Department.objects.get(code="EEE")
        prog = Program.objects.get(code="BTEEE", department=dept)
        sem = Semester.objects.get(program=prog, number=1, academic_year="2026-2027")
        div = Division.objects.get(semester=sem, name="A")
        batch = PracticalBatch.objects.get(division=div, name="P1")

        self.assertEqual(batch.division, div)
        self.assertEqual(div.semester, sem)
        self.assertEqual(sem.program, prog)
        self.assertEqual(prog.department, dept)

    def test_academic_structure_wizard_existing_parent_optional_batch(self):
        """Staff can link existing Department/Program and skip optional Practical Batch."""
        self.client.force_login(self.staff_user)
        url = reverse("staff:academic_structure_create")

        payload = {
            "dept_mode": "select",
            "dept_id": str(self.department.id),
            "prog_mode": "select",
            "prog_id": str(self.program.id),
            "sem_mode": "new",
            "sem_data": {"number": 5, "academic_year": "2026-2027"},
            "div_mode": "new",
            "div_data": {"name": "C", "capacity": 60},
            "batch_create": False,
        }

        res = self.client.post(url, data=payload, content_type="application/json")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))

        # Verify records
        sem = Semester.objects.get(program=self.program, number=5, academic_year="2026-2027")
        div = Division.objects.get(semester=sem, name="C")
        self.assertFalse(PracticalBatch.objects.filter(division=div).exists())

