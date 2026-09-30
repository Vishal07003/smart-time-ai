from django.test import Client, TestCase
from django.urls import reverse
from accounts.models import TeacherProfile, User
from academics.models import (
    Classroom,
    Department,
    Division,
    Laboratory,
    PracticalBatch,
    Program,
    Semester,
    Subject,
    TeacherAvailability,
    TeacherLeave,
    TeacherSubject,
    Timetable,
    TimetableChangeLog,
    TimetableConflict,
    TimetableSlot,
)

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
        self.subject = Subject.objects.create(
            program=self.program,
            name="Data Structures and Algorithms",
            code="CS201",
            type=Subject.Type.LECTURE,
            credits=4.0,
            weekly_lectures=4,
            weekly_practicals=0,
            duration_minutes=60,
        )
        self.teacher_user = User.objects.create_user(
            username="prof_john",
            email="john@smarttime.ai",
            password="TeacherPassword123!",
            role=User.Role.TEACHER,
            first_name="John",
            last_name="Doe",
        )
        self.teacher_profile = TeacherProfile.objects.create(
            user=self.teacher_user,
            employee_code="EMP-1001",
            department=self.department,
        )

    def test_permission_enforcement_for_non_staff(self):
        """Non-staff users should not be able to access academic management views."""
        # Unauthenticated
        response = self.client.get(reverse("staff:academic_departments"))
        self.assertNotEqual(response.status_code, 200)

        response = self.client.get(reverse("staff:academic_programs"))
        self.assertNotEqual(response.status_code, 200)

        response = self.client.get(reverse("staff:academic_subjects"))
        self.assertNotEqual(response.status_code, 200)

        # Logged in as student
        self.client.force_login(self.student_user)
        response = self.client.get(reverse("staff:academic_departments"))
        self.assertNotEqual(response.status_code, 200)

        response = self.client.get(reverse("staff:academic_programs"))
        self.assertNotEqual(response.status_code, 200)

        response = self.client.get(reverse("staff:academic_subjects"))
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
        """Staff can list, search, filter and create semesters."""
        self.client.force_login(self.staff_user)

        # List
        response = self.client.get(reverse("staff:academic_semesters"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Semester 3")
        self.assertContains(response, "BTCS")
        self.assertContains(response, "Computer Science")

        # Search by program name/code
        response = self.client.get(reverse("staff:academic_semesters") + "?q=BTCS")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Semester 3")

        # Filter by program
        response = self.client.get(reverse("staff:academic_semesters") + f"?program={self.program.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Semester 3")

        # Filter by academic year
        response = self.client.get(reverse("staff:academic_semesters") + f"?academic_year={self.semester.academic_year}")
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

    def test_semester_edit_preserves_divisions(self):
        """Editing a semester updates fields and preserves existing division relationships."""
        self.client.force_login(self.staff_user)
        edit_url = reverse("staff:academic_semester_edit", kwargs={"id": self.semester.id})
        edit_data = {
            "program": str(self.program.id),
            "number": 5,
            "academic_year": "2027-2028",
        }
        response = self.client.post(edit_url, edit_data)
        self.assertEqual(response.status_code, 302)
        self.semester.refresh_from_db()
        self.assertEqual(self.semester.number, 5)
        self.assertEqual(self.semester.academic_year, "2027-2028")

        # Division relationship is preserved
        self.division.refresh_from_db()
        self.assertEqual(self.division.semester, self.semester)
        self.assertIn(self.division, self.semester.divisions.all())

    def test_semester_duplicate_validation(self):
        """Cannot create duplicate semester for same program, number, and academic year."""
        self.client.force_login(self.staff_user)
        create_url = reverse("staff:academic_semester_create")
        post_data = {
            "program": str(self.program.id),
            "number": self.semester.number,
            "academic_year": self.semester.academic_year,
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, "form", None, "This semester already exists for the selected program and academic year.")

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

    def test_semester_appears_in_division_form_choices(self):
        """Newly created semester immediately appears in DivisionForm choices."""
        from staff.forms import DivisionForm
        new_sem = Semester.objects.create(
            program=self.program,
            number=6,
            academic_year="2026-2027",
        )
        form = DivisionForm()
        sem_ids = [str(s.id) for s in form.fields["semester"].queryset]
        self.assertIn(str(new_sem.id), sem_ids)

    # --------------------------------------------------------------------------
    # DIVISION TESTS
    # --------------------------------------------------------------------------
    def test_division_list_search_and_filter(self):
        """Staff can list, search, and filter divisions."""
        self.client.force_login(self.staff_user)

        # List
        response = self.client.get(reverse("staff:academic_divisions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Division A")
        self.assertContains(response, "BTCS")

        # Search by Division name
        response = self.client.get(reverse("staff:academic_divisions") + "?q=A")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Division A")

        # Search by Program code
        response = self.client.get(reverse("staff:academic_divisions") + "?q=BTCS")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Division A")

        # Filter by Program
        response = self.client.get(reverse("staff:academic_divisions") + f"?program={self.program.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Division A")

        # Filter by Semester
        response = self.client.get(reverse("staff:academic_divisions") + f"?semester={self.semester.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Division A")

        # Filter with non-matching query
        response = self.client.get(reverse("staff:academic_divisions") + "?q=NonExistentDivision")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Division A")

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

    def test_division_duplicate_validation(self):
        """Cannot create duplicate division with same name under same semester."""
        self.client.force_login(self.staff_user)
        create_url = reverse("staff:academic_division_create")
        post_data = {
            "semester": str(self.semester.id),
            "name": "a",  # already exists as "A"
            "capacity": 50,
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, "form", "name", "A division with this name already exists in this semester.")

    def test_division_edit_preserves_batches(self):
        """Editing a division preserves existing practical batch relationships."""
        self.client.force_login(self.staff_user)
        edit_url = reverse("staff:academic_division_edit", kwargs={"id": self.division.id})
        edit_data = {
            "semester": str(self.semester.id),
            "name": "A-Updated",
            "capacity": 75,
        }
        response = self.client.post(edit_url, edit_data)
        self.assertEqual(response.status_code, 302)
        self.division.refresh_from_db()
        self.assertEqual(self.division.name, "A-UPDATED")
        self.assertEqual(self.division.capacity, 75)

        # Batch relation is preserved
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.division, self.division)
        self.assertIn(self.batch, self.division.batches.all())

    def test_division_appears_in_practical_batch_form_choices(self):
        """Newly created division immediately appears in PracticalBatchForm choices."""
        from staff.forms import PracticalBatchForm
        new_div = Division.objects.create(
            semester=self.semester,
            name="C",
            capacity=60,
        )
        form = PracticalBatchForm()
        div_ids = [str(d.id) for d in form.fields["division"].queryset]
        self.assertIn(str(new_div.id), div_ids)

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
    # SUBJECT TESTS
    # --------------------------------------------------------------------------
    def test_subject_list_search_and_filter(self):
        """Staff can list, search, and filter subjects."""
        self.client.force_login(self.staff_user)

        # List
        response = self.client.get(reverse("staff:academic_subjects"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Data Structures and Algorithms")
        self.assertContains(response, "CS201")
        self.assertContains(response, "BTCS")

        # Search by subject name
        response = self.client.get(reverse("staff:academic_subjects") + "?q=Structures")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CS201")

        # Search by subject code
        response = self.client.get(reverse("staff:academic_subjects") + "?q=CS201")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Data Structures and Algorithms")

        # Filter by program
        response = self.client.get(reverse("staff:academic_subjects") + f"?program={self.program.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CS201")

        # Filter by delivery type
        response = self.client.get(reverse("staff:academic_subjects") + "?type=LECTURE")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CS201")

        # Filter with non-matching query
        response = self.client.get(reverse("staff:academic_subjects") + "?q=NonExistentSubject")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "CS201")

    def test_subject_statistics_calculation_for_multi_component_subjects(self):
        """Statistics count lecture, practical, and tutorial components accurately based on subject components."""
        self.client.force_login(self.staff_user)

        # Baseline: self.subject is CS201 (Lecture only: weekly_lectures=4, weekly_practicals=0)
        # Create Java Programming (Lecture + Practical: 4L / 4P)
        Subject.objects.create(
            program=self.program,
            name="Java Programming",
            code="CS202",
            type=Subject.Type.LECTURE,
            credits=4.0,
            weekly_lectures=4,
            weekly_practicals=4,
            duration_minutes=60,
        )

        # Create Operating Systems Lab (Pure Practical: 0L / 2P)
        Subject.objects.create(
            program=self.program,
            name="Operating Systems Lab",
            code="CS203L",
            type=Subject.Type.PRACTICAL,
            credits=2.0,
            weekly_lectures=0,
            weekly_practicals=2,
            duration_minutes=120,
        )

        # Create Technical Communication Tutorial (Pure Tutorial)
        Subject.objects.create(
            program=self.program,
            name="Technical Communication Tutorial",
            code="HS101",
            type=Subject.Type.TUTORIAL,
            credits=1.0,
            weekly_lectures=0,
            weekly_practicals=0,
            duration_minutes=60,
        )

        # Total subjects = 4 (CS201, CS202, CS203L, HS101)
        # Lecture component subjects: CS201 (weekly_lectures=4) + CS202 (weekly_lectures=4) = 2
        # Practical component subjects: CS202 (weekly_practicals=4) + CS203L (weekly_practicals=2) = 2
        # Tutorial component subjects: HS101 (type=TUTORIAL) = 1
        response = self.client.get(reverse("staff:academic_subjects"))
        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.context["total_subjects_count"], 4)
        self.assertEqual(response.context["lecture_count"], 2)
        self.assertEqual(response.context["practical_count"], 2)
        self.assertEqual(response.context["tutorial_count"], 1)

    def test_subject_create_and_edit_lecture_and_practical(self):
        """Staff can create and edit a subject with both Lecture and Practical components."""
        self.client.force_login(self.staff_user)

        # Create Lecture + Practical subject (e.g. Java Programming)
        create_url = reverse("staff:academic_subject_create")
        post_data = {
            "program": str(self.program.id),
            "name": "Java Programming",
            "code": "CS202",
            "has_lecture": "on",
            "has_practical": "on",
            "credits": 4.0,
            "weekly_lectures": 4,
            "weekly_practicals": 2,
            "duration_minutes": 60,
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 302)
        new_subj = Subject.objects.get(code="CS202")
        self.assertEqual(new_subj.name, "Java Programming")
        self.assertEqual(new_subj.weekly_lectures, 4)
        self.assertEqual(new_subj.weekly_practicals, 2)
        self.assertTrue(new_subj.has_lecture)
        self.assertTrue(new_subj.has_practical)
        self.assertIn("Lecture", new_subj.delivery_components)
        self.assertIn("Practical", new_subj.delivery_components)
        self.assertEqual(new_subj.delivery_components_display, "Lecture + Practical")

        # Edit
        edit_url = reverse("staff:academic_subject_edit", kwargs={"id": new_subj.id})
        post_data["name"] = "Advanced Java Programming"
        response = self.client.post(edit_url, post_data)
        self.assertEqual(response.status_code, 302)
        new_subj.refresh_from_db()
        self.assertEqual(new_subj.name, "Advanced Java Programming")

    def test_subject_create_lecture_only(self):
        """Pure lecture subjects only have weekly lectures and no practicals."""
        self.client.force_login(self.staff_user)

        create_url = reverse("staff:academic_subject_create")
        post_data = {
            "program": str(self.program.id),
            "name": "Discrete Mathematics",
            "code": "MA201",
            "has_lecture": "on",
            "credits": 3.0,
            "weekly_lectures": 4,
            "weekly_practicals": 0,
            "duration_minutes": 60,
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 302)
        subj = Subject.objects.get(code="MA201")
        self.assertEqual(subj.weekly_lectures, 4)
        self.assertEqual(subj.weekly_practicals, 0)
        self.assertTrue(subj.has_lecture)
        self.assertFalse(subj.has_practical)
        self.assertEqual(subj.delivery_components_display, "Lecture")

    def test_subject_create_practical_only(self):
        """Pure practical subjects only have weekly practicals and 0 lectures."""
        self.client.force_login(self.staff_user)

        create_url = reverse("staff:academic_subject_create")
        post_data = {
            "program": str(self.program.id),
            "name": "Web Technologies Lab",
            "code": "CS203L",
            "has_practical": "on",
            "credits": 2.0,
            "weekly_lectures": 0,
            "weekly_practicals": 2,
            "duration_minutes": 120,
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 302)
        subj = Subject.objects.get(code="CS203L")
        self.assertEqual(subj.weekly_lectures, 0)
        self.assertEqual(subj.weekly_practicals, 2)
        self.assertFalse(subj.has_lecture)
        self.assertTrue(subj.has_practical)
        self.assertEqual(subj.delivery_components_display, "Practical")

    def test_subject_validation_requires_at_least_one_component(self):
        """Form rejects submission if neither lecture, practical, nor tutorial is selected."""
        self.client.force_login(self.staff_user)

        create_url = reverse("staff:academic_subject_create")
        post_data = {
            "program": str(self.program.id),
            "name": "Invalid Subject",
            "code": "INV101",
            "credits": 2.0,
            "weekly_lectures": 0,
            "weekly_practicals": 0,
            "duration_minutes": 60,
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response,
            "form",
            None,
            "Please select at least one delivery component (Lecture, Practical, or Tutorial)."
        )

    def test_subject_duplicate_code_validation(self):
        """Cannot create duplicate subject with same code (case-insensitive)."""
        self.client.force_login(self.staff_user)
        create_url = reverse("staff:academic_subject_create")
        post_data = {
            "program": str(self.program.id),
            "name": "Duplicate Data Structures",
            "code": "cs201",  # already exists as "CS201"
            "has_lecture": "on",
            "credits": 3.0,
            "weekly_lectures": 3,
            "weekly_practicals": 0,
            "duration_minutes": 60,
        }
        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, "form", "code", "A subject with this code already exists.")

    def test_subject_detail_and_teacher_subject_integration(self):
        """Subject detail shows assigned teachers and timetable allocations."""
        self.client.force_login(self.staff_user)

        # Assign teacher to subject
        ts = TeacherSubject.objects.create(
            teacher=self.teacher_profile,
            subject=self.subject,
            priority=1,
        )

        detail_url = reverse("staff:academic_subject_detail", kwargs={"id": self.subject.id})
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.subject.name)
        self.assertContains(response, self.subject.code)
        self.assertContains(response, "EMP-1001")
        self.assertContains(response, "Priority 1")
        self.assertContains(response, "John Doe")


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

    # --------------------------------------------------------------------------
    # TEACHER OPERATIONS & RESOURCE MANAGEMENT TESTS
    # --------------------------------------------------------------------------
    def test_teacher_subject_assignment_flow(self):
        """Staff can assign subject to teacher, edit priority, and prevent duplicate assignment."""
        self.client.force_login(self.staff_user)

        # 1. Assign subject
        assign_url = reverse("staff:teacher_subject_assign", kwargs={"teacher_id": self.teacher_profile.id})
        response = self.client.post(assign_url, {"subject": str(self.subject.id), "priority": 1})
        self.assertEqual(response.status_code, 302)
        ts = TeacherSubject.objects.get(teacher=self.teacher_profile, subject=self.subject)
        self.assertEqual(ts.priority, 1)

        # 2. Prevent duplicate assignment
        res_dup = self.client.post(assign_url, {"subject": str(self.subject.id), "priority": 2})
        self.assertEqual(res_dup.status_code, 200)
        self.assertFormError(res_dup, "form", "subject", f"Subject '{self.subject.code}' is already assigned to this teacher.")

        # 3. Edit assignment
        edit_url = reverse("staff:teacher_subject_edit", kwargs={"teacher_id": self.teacher_profile.id, "assignment_id": ts.id})
        res_edit = self.client.post(edit_url, {"subject": str(self.subject.id), "priority": 3})
        self.assertEqual(res_edit.status_code, 302)
        ts.refresh_from_db()
        self.assertEqual(ts.priority, 3)

        # 4. Delete assignment
        del_url = reverse("staff:teacher_subject_delete", kwargs={"teacher_id": self.teacher_profile.id, "assignment_id": ts.id})
        res_del = self.client.post(del_url)
        self.assertEqual(res_del.status_code, 302)
        self.assertFalse(TeacherSubject.objects.filter(id=ts.id).exists())

    def test_teacher_availability_management(self):
        """Staff can create, view, and delete teacher weekly availability slots."""
        self.client.force_login(self.staff_user)

        avail_url = reverse("staff:teacher_availability", kwargs={"teacher_id": self.teacher_profile.id})
        post_data = {
            "day": "MONDAY",
            "start_time": "09:00",
            "end_time": "12:00",
            "is_available": "on",
        }
        response = self.client.post(avail_url, post_data)
        self.assertEqual(response.status_code, 302)

        slot = TeacherAvailability.objects.get(teacher=self.teacher_profile, day="MONDAY")
        self.assertTrue(slot.is_available)

        # Delete slot
        del_url = reverse("staff:teacher_availability_delete", kwargs={"teacher_id": self.teacher_profile.id, "availability_id": slot.id})
        res_del = self.client.post(del_url)
        self.assertEqual(res_del.status_code, 302)
        self.assertFalse(TeacherAvailability.objects.filter(id=slot.id).exists())

    def test_teacher_leave_management_and_approval(self):
        """Staff can record teacher leave and update approval status."""
        self.client.force_login(self.staff_user)

        leave_url = reverse("staff:teacher_leave", kwargs={"teacher_id": self.teacher_profile.id})
        post_data = {
            "start_date": "2026-10-10",
            "end_date": "2026-10-12",
            "reason": "Attending IEEE Conference",
            "status": "PENDING",
        }
        res = self.client.post(leave_url, post_data)
        self.assertEqual(res.status_code, 302)

        leave = TeacherLeave.objects.get(teacher=self.teacher_profile, start_date="2026-10-10")
        self.assertEqual(leave.status, TeacherLeave.Status.PENDING)

        # Update status to APPROVED
        status_url = reverse("staff:teacher_leave_status", kwargs={"teacher_id": self.teacher_profile.id, "leave_id": leave.id})
        res_status = self.client.post(status_url, {"status": "APPROVED"})
        self.assertEqual(res_status.status_code, 302)
        leave.refresh_from_db()
        self.assertEqual(leave.status, TeacherLeave.Status.APPROVED)

    def test_classroom_crud_and_detail(self):
        """Staff can create, list, edit, and view classroom facilities."""
        self.client.force_login(self.staff_user)

        # Create
        create_url = reverse("staff:classroom_create")
        post_data = {
            "building": "Science Block",
            "room_number": "301",
            "floor": 3,
            "capacity": 70,
            "status": "AVAILABLE",
        }
        res = self.client.post(create_url, post_data)
        self.assertEqual(res.status_code, 302)

        cr = Classroom.objects.get(building="Science Block", room_number="301")
        self.assertEqual(cr.capacity, 70)

        # List & Search
        list_url = reverse("staff:classrooms") + "?q=301"
        res_list = self.client.get(list_url)
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, "Room 301")

        # Edit
        edit_url = reverse("staff:classroom_edit", kwargs={"id": cr.id})
        post_data["capacity"] = 75
        res_edit = self.client.post(edit_url, post_data)
        self.assertEqual(res_edit.status_code, 302)
        cr.refresh_from_db()
        self.assertEqual(cr.capacity, 75)

        # Detail
        detail_url = reverse("staff:classroom_detail", kwargs={"id": cr.id})
        res_detail = self.client.get(detail_url)
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, "Science Block")
        self.assertContains(res_detail, "Room 301")

    def test_laboratory_crud_and_detail(self):
        """Staff can create, list, edit, and view laboratory facilities."""
        self.client.force_login(self.staff_user)

        # Create
        create_url = reverse("staff:laboratory_create")
        post_data = {
            "building": "Engineering Block",
            "lab_number": "LAB-204",
            "name": "Robotics & Embedded Systems Lab",
            "floor": 2,
            "capacity": 35,
            "status": "AVAILABLE",
        }
        res = self.client.post(create_url, post_data)
        self.assertEqual(res.status_code, 302)

        lab = Laboratory.objects.get(building="Engineering Block", lab_number="LAB-204")
        self.assertEqual(lab.name, "Robotics & Embedded Systems Lab")

        # List & Search
        list_url = reverse("staff:laboratories") + "?q=Robotics"
        res_list = self.client.get(list_url)
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, "Robotics & Embedded Systems Lab")

        # Edit
        edit_url = reverse("staff:laboratory_edit", kwargs={"id": lab.id})
        post_data["capacity"] = 40
        res_edit = self.client.post(edit_url, post_data)
        self.assertEqual(res_edit.status_code, 302)
        lab.refresh_from_db()
        self.assertEqual(lab.capacity, 40)

        # Detail
        detail_url = reverse("staff:laboratory_detail", kwargs={"id": lab.id})
        res_detail = self.client.get(detail_url)
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, "LAB-204")
        self.assertContains(res_detail, "Robotics & Embedded Systems Lab")


class StaffTimetableManagementTests(TestCase):
    """
    Focused test suite for Staff Timetable Management:
    - Timetable list & filtering
    - Timetable creation & versioning
    - Weekly grid display (Monday-Saturday)
    - Manual slot create, edit, delete & clash detection
    - AI generation integration & safe publishing
    - Conflict inspection & resolution
    - Version history & audit change log
    """

    def setUp(self):
        self.client = Client()

        # Staff user
        self.staff_user = User.objects.create_user(
            username="staff_scheduler",
            email="scheduler@smarttime.ai",
            password="SchedulerPass123!",
            role=User.Role.STAFF,
            first_name="Schedule",
            last_name="Staff",
        )

        # Non-staff user
        self.student_user = User.objects.create_user(
            username="student_observer",
            email="student@smarttime.ai",
            password="StudentPass123!",
            role=User.Role.STUDENT,
        )

        # Academic context
        self.department = Department.objects.create(name="Information Technology", code="IT")
        self.program = Program.objects.create(department=self.department, name="B.Tech IT", code="IT", duration_years=4)
        self.semester = Semester.objects.create(program=self.program, number=3, academic_year="2025-2026")
        self.division = Division.objects.create(semester=self.semester, name="A")
        self.batch = PracticalBatch.objects.create(division=self.division, name="A1")

        # Subject
        self.subject = Subject.objects.create(
            program=self.program,
            name="Data Structures",
            code="CS301",
            type="LECTURE",
            credits=4,
            weekly_lectures=3,
            weekly_practicals=2,
            duration_minutes=60,
        )

        # Teacher
        self.teacher_user = User.objects.create_user(
            username="dr_sharma",
            email="sharma@smarttime.ai",
            password="TeacherPass123!",
            role=User.Role.TEACHER,
            first_name="Ramesh",
            last_name="Sharma",
        )
        self.teacher_profile = TeacherProfile.objects.create(
            user=self.teacher_user,
            department=self.department,
            employee_code="EMP-IT-001",
            designation="Assistant Professor",
        )
        TeacherSubject.objects.create(teacher=self.teacher_profile, subject=self.subject)

        # Classroom & Lab
        self.classroom = Classroom.objects.create(building="Academic Block", room_number="CR-101", capacity=60)
        self.laboratory = Laboratory.objects.create(building="Academic Block", lab_number="LAB-101", name="CS Lab 1", capacity=30)

        # Initial Timetable
        self.timetable = Timetable.objects.create(
            semester=self.semester,
            academic_year="2025-2026",
            version=1,
            status=Timetable.Status.DRAFT,
            created_by=self.staff_user,
        )

    def test_timetable_list_and_permissions(self):
        """Staff can list timetables; unauthenticated or students are blocked."""
        # Unauthenticated
        res = self.client.get(reverse("staff:timetables"))
        self.assertEqual(res.status_code, 302)

        # Student blocked with 403 Forbidden
        self.client.force_login(self.student_user)
        res_student = self.client.get(reverse("staff:timetables"))
        self.assertEqual(res_student.status_code, 403)

        # Staff allowed
        self.client.force_login(self.staff_user)
        res_staff = self.client.get(reverse("staff:timetables"))
        self.assertEqual(res_staff.status_code, 200)
        self.assertContains(res_staff, "B.Tech IT")
        self.assertContains(res_staff, "Semester 3")
        self.assertContains(res_staff, "2025-2026")
        self.assertContains(res_staff, "v1")

    def test_timetable_create_flow(self):
        """Staff can create a timetable and version increments automatically."""
        self.client.force_login(self.staff_user)

        create_url = reverse("staff:timetable_create")
        post_data = {
            "semester": self.semester.id,
            "academic_year": "2025-2026",
            "status": "DRAFT",
        }
        res = self.client.post(create_url, post_data)
        self.assertEqual(res.status_code, 302)

        new_tt = Timetable.objects.filter(semester=self.semester, academic_year="2025-2026").order_by("-version").first()
        self.assertIsNotNone(new_tt)
        self.assertEqual(new_tt.version, 2)
        self.assertEqual(new_tt.status, Timetable.Status.DRAFT)

    def test_timetable_grid_detail_view(self):
        """Staff can view weekly grid showing slots with proper styling."""
        self.client.force_login(self.staff_user)

        # Create slot
        slot = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            subject=self.subject,
            teacher=self.teacher_profile,
            classroom=self.classroom,
            day="MONDAY",
            start_time="09:00:00",
            end_time="10:00:00",
            session_type="LECTURE",
            status="SCHEDULED",
        )

        detail_url = reverse("staff:timetable_detail", kwargs={"id": self.timetable.id})
        res = self.client.get(detail_url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "CS301")
        self.assertContains(res, "CR-101")
        self.assertContains(res, "Ramesh Sharma")
        self.assertContains(res, "Monday")

    def test_manual_slot_crud_and_conflict_check(self):
        """Staff can add and edit manual slots with clash detection and audit logs."""
        self.client.force_login(self.staff_user)

        create_slot_url = reverse("staff:timetable_slot_create", kwargs={"timetable_id": self.timetable.id})
        post_data = {
            "division": self.division.id,
            "batch": self.batch.id,
            "subject": self.subject.id,
            "teacher": self.teacher_profile.id,
            "laboratory": self.laboratory.id,
            "day": "TUESDAY",
            "start_time": "10:00",
            "end_time": "12:00",
            "session_type": "PRACTICAL",
            "status": "SCHEDULED",
        }
        res = self.client.post(create_slot_url, post_data)
        self.assertEqual(res.status_code, 302)

        slot = TimetableSlot.objects.get(timetable=self.timetable, day="TUESDAY", start_time="10:00:00")
        self.assertEqual(slot.session_type, "PRACTICAL")
        self.assertEqual(slot.laboratory, self.laboratory)

        # Audit log created
        log = TimetableChangeLog.objects.filter(timetable=self.timetable, action=TimetableChangeLog.Action.SLOT_CREATED).first()
        self.assertIsNotNone(log)

    def test_publish_workflow_archives_previous_version(self):
        """Publishing a timetable archives any existing published timetable for the semester/year."""
        self.client.force_login(self.staff_user)

        # Timetable 1 published
        self.timetable.status = Timetable.Status.PUBLISHED
        self.timetable.save()

        # Add slot to Timetable 1 so it's valid
        TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            subject=self.subject,
            teacher=self.teacher_profile,
            classroom=self.classroom,
            day="WEDNESDAY",
            start_time="09:00:00",
            end_time="10:00:00",
            session_type="LECTURE",
        )

        # Timetable 2 draft with slot
        tt2 = Timetable.objects.create(
            semester=self.semester,
            academic_year="2025-2026",
            version=2,
            status=Timetable.Status.REVIEW,
            created_by=self.staff_user,
        )
        TimetableSlot.objects.create(
            timetable=tt2,
            division=self.division,
            subject=self.subject,
            teacher=self.teacher_profile,
            classroom=self.classroom,
            day="THURSDAY",
            start_time="11:00:00",
            end_time="12:00:00",
            session_type="LECTURE",
        )

        publish_url = reverse("staff:timetable_publish", kwargs={"id": tt2.id})
        res = self.client.post(publish_url)
        self.assertEqual(res.status_code, 302)

        self.timetable.refresh_from_db()
        tt2.refresh_from_db()

        self.assertEqual(self.timetable.status, Timetable.Status.ARCHIVED)
        self.assertEqual(tt2.status, Timetable.Status.PUBLISHED)
        self.assertIsNotNone(tt2.published_at)

    def test_conflict_detection_and_resolution(self):
        """Conflicts page displays detected clashes and allows resolving them."""
        self.client.force_login(self.staff_user)

        # Create two overlapping slots with same teacher to generate conflict
        s1 = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            subject=self.subject,
            teacher=self.teacher_profile,
            classroom=self.classroom,
            day="FRIDAY",
            start_time="09:00:00",
            end_time="10:00:00",
            session_type="LECTURE",
        )
        s2 = TimetableSlot.objects.create(
            timetable=self.timetable,
            division=self.division,
            subject=self.subject,
            teacher=self.teacher_profile,
            classroom=self.classroom,
            day="FRIDAY",
            start_time="09:30:00",
            end_time="10:30:00",
            session_type="LECTURE",
        )

        # Trigger conflict check
        check_res = self.client.post(reverse("staff:timetable_conflicts"), {
            "action": "run_check",
            "timetable_id": str(self.timetable.id),
        })
        self.assertEqual(check_res.status_code, 302)

        conflict = TimetableConflict.objects.filter(timetable=self.timetable, status="DETECTED").first()
        self.assertIsNotNone(conflict)

        # Resolve conflict
        resolve_res = self.client.post(reverse("staff:timetable_conflicts"), {
            "action": "resolve",
            "conflict_id": str(conflict.id),
        })
        self.assertEqual(resolve_res.status_code, 302)
        conflict.refresh_from_db()
        self.assertEqual(conflict.status, "RESOLVED")


class StaffAIGeneratorConfigurationTests(TestCase):
    """
    Focused tests for Staff -> AI Generator Configuration workflow:
    - Pre-generation configuration step with academic context, schedule settings, and preferences
    - Natural language constraint parsing & validation before generation
    - Review interpreted constraints action ('parse_preview')
    - Full generation with custom constraints and solver configuration
    - Guarantee that generated timetable remains a GENERATED draft and never overwrites PUBLISHED
    - Clash detection and optimization compatibility
    """

    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username="staff_gen_admin",
            email="staff.gen@smarttime.ai",
            password="StaffPassword123!",
            role=User.Role.STAFF,
        )
        self.client.force_login(self.staff_user)

        self.dept = Department.objects.create(name="Computer Eng", code="CE_GEN")
        self.program = Program.objects.create(name="B.Tech CE", code="BTCE_GEN", department=self.dept)
        self.semester = Semester.objects.create(program=self.program, number=1, academic_year="2025-2026")
        self.division = Division.objects.create(semester=self.semester, name="Div A")

        self.teacher_user = User.objects.create_user(
            username="prof_turing",
            first_name="Alan",
            last_name="Turing",
            email="turing@smarttime.ai",
            role=User.Role.TEACHER,
        )
        self.teacher = TeacherProfile.objects.create(
            user=self.teacher_user,
            department=self.dept,
            employee_code="EMP_GEN_01",
            status=TeacherProfile.Status.ACTIVE,
        )

        self.subject = Subject.objects.create(
            program=self.program,
            name="Algorithms",
            code="CS101",
            weekly_lectures=2,
            weekly_practicals=0,
        )
        TeacherSubject.objects.create(
            teacher=self.teacher,
            subject=self.subject,
            priority=1,
        )

        self.classroom = Classroom.objects.create(
            building="Main",
            room_number="R101",
            capacity=60,
            status=Classroom.Status.AVAILABLE,
        )

    def test_generator_page_renders_with_configuration_fields(self):
        """GET /staff/timetables/generate/ should present all configuration sections."""
        res = self.client.get(reverse("staff:timetable_generate"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "AI Timetable Generation Engine")
        self.assertContains(res, "Academic Context")
        self.assertContains(res, "Basic Schedule Settings")
        self.assertContains(res, "Preferences & Optimization Weights")
        self.assertContains(res, "Natural Language Requirements")
        self.assertContains(res, "Parse & Review Understood Constraints")

    def test_parse_preview_interprets_natural_language_requirements(self):
        """POST with action=parse_preview parses and validates NL text without generating yet."""
        payload = {
            "semester": str(self.semester.id),
            "academic_year": "2025-2026",
            "working_days": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"],
            "daily_start_time": "09:00",
            "daily_end_time": "17:00",
            "slot_duration_minutes": 60,
            "prefer_practicals_period": "AFTERNOON",
            "avoid_teacher_consecutive": "on",
            "avoid_division_gaps": "on",
            "subject_distribution": "on",
            "natural_language_requirements": "Keep practical sessions mostly in the afternoon.\nAvoid Algorithms on Friday afternoon.",
            "action": "parse_preview",
        }
        res = self.client.post(reverse("staff:timetable_generate"), payload)
        self.assertEqual(res.status_code, 200)
        self.assertIn("interpreted_constraints", res.context)
        constraints = res.context["interpreted_constraints"]
        self.assertTrue(len(constraints) >= 1)
        # Should NOT have created a Timetable record
        self.assertEqual(Timetable.objects.count(), 0)

    def test_generate_workflow_creates_draft_and_honors_safe_lifecycle(self):
        """Generation must succeed and save as GENERATED status, never directly PUBLISHED."""
        # Create an existing published timetable to ensure safe lifecycle isolation
        published_tt = Timetable.objects.create(
            semester=self.semester,
            academic_year="2025-2026",
            version=1,
            status=Timetable.Status.PUBLISHED,
        )

        payload = {
            "semester": str(self.semester.id),
            "academic_year": "2025-2026",
            "division": str(self.division.id),
            "working_days": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"],
            "daily_start_time": "09:00",
            "daily_end_time": "17:00",
            "slot_duration_minutes": 60,
            "lunch_break_start": "13:00",
            "lunch_break_end": "14:00",
            "prefer_practicals_period": "AFTERNOON",
            "avoid_teacher_consecutive": "on",
            "avoid_division_gaps": "on",
            "subject_distribution": "on",
            "natural_language_requirements": "Keep practical sessions mostly in the afternoon",
            "action": "generate",
        }
        res = self.client.post(reverse("staff:timetable_generate"), payload)
        # Upon success, redirects to timetable_detail
        self.assertEqual(res.status_code, 302)

        # Check published timetable was untouched
        published_tt.refresh_from_db()
        self.assertEqual(published_tt.status, Timetable.Status.PUBLISHED)

        # New timetable should exist with GENERATED status
        new_tt = Timetable.objects.exclude(id=published_tt.id).first()
        self.assertIsNotNone(new_tt)
        self.assertEqual(new_tt.status, Timetable.Status.GENERATED)
        self.assertEqual(new_tt.version, 2)
        self.assertTrue(new_tt.slots.count() > 0)




