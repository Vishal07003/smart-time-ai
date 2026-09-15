from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter

from .models import (
    Department,
    Division,
    PracticalBatch,
    Program,
    Semester,
    Subject,
)
from .permissions import IsStaffOrReadOnlyAcademic
from .serializers import (
    DepartmentSerializer,
    DivisionSerializer,
    PracticalBatchSerializer,
    ProgramSerializer,
    SemesterSerializer,
    SubjectSerializer,
)


class DepartmentViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for Department model.
    - Staff: Full CRUD
    - Teacher/Student: Read-only
    """

    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [IsStaffOrReadOnlyAcademic]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name", "code"]
    ordering_fields = ["name", "code", "created_at"]
    ordering = ["name"]


class ProgramViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for Program model.
    - Supports filtering by `?department={id}`
    """

    queryset = Program.objects.select_related("department").all()
    serializer_class = ProgramSerializer
    permission_classes = [IsStaffOrReadOnlyAcademic]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name", "code", "department__name", "department__code"]
    ordering_fields = ["name", "code", "duration_years", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        department_id = self.request.query_params.get("department")
        if department_id:
            queryset = queryset.filter(department_id=department_id)
        return queryset


class SemesterViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for Semester model.
    - Supports filtering by `?program={id}`
    """

    queryset = Semester.objects.select_related("program", "program__department").all()
    serializer_class = SemesterSerializer
    permission_classes = [IsStaffOrReadOnlyAcademic]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["program__name", "program__code", "academic_year"]
    ordering_fields = ["academic_year", "number", "created_at"]
    ordering = ["academic_year", "number"]

    def get_queryset(self):
        queryset = super().get_queryset()
        program_id = self.request.query_params.get("program")
        if program_id:
            queryset = queryset.filter(program_id=program_id)
        academic_year = self.request.query_params.get("academic_year")
        if academic_year:
            queryset = queryset.filter(academic_year__iexact=academic_year.strip())
        return queryset


class DivisionViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for Division model.
    - Supports filtering by `?semester={id}`
    """

    queryset = Division.objects.select_related(
        "semester", "semester__program", "semester__program__department"
    ).all()
    serializer_class = DivisionSerializer
    permission_classes = [IsStaffOrReadOnlyAcademic]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name", "semester__program__name", "semester__program__code"]
    ordering_fields = ["name", "capacity", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        semester_id = self.request.query_params.get("semester")
        if semester_id:
            queryset = queryset.filter(semester_id=semester_id)
        return queryset


class PracticalBatchViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for PracticalBatch model.
    - Supports filtering by `?division={id}`
    """

    queryset = PracticalBatch.objects.select_related(
        "division", "division__semester"
    ).all()
    serializer_class = PracticalBatchSerializer
    permission_classes = [IsStaffOrReadOnlyAcademic]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name", "division__name"]
    ordering_fields = ["name", "capacity", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        division_id = self.request.query_params.get("division")
        if division_id:
            queryset = queryset.filter(division_id=division_id)
        return queryset


class SubjectViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for Subject model.
    - Supports filtering by `?program={id}` and `?type={LECTURE|PRACTICAL|TUTORIAL}`
    """

    queryset = Subject.objects.select_related("program", "program__department").all()
    serializer_class = SubjectSerializer
    permission_classes = [IsStaffOrReadOnlyAcademic]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name", "code", "program__name", "program__code"]
    ordering_fields = ["code", "name", "credits", "type", "created_at"]
    ordering = ["code"]

    def get_queryset(self):
        queryset = super().get_queryset()
        program_id = self.request.query_params.get("program")
        if program_id:
            queryset = queryset.filter(program_id=program_id)

        subject_type = self.request.query_params.get("type")
        if subject_type:
            queryset = queryset.filter(type__iexact=subject_type.strip())

        return queryset
