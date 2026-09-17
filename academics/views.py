from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import IsStaffRole
from .models import (
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
    TimetableConflict,
    TimetableSlot,
)
from .permissions import (
    IsStaffOrReadOnlyAcademic,
    IsStaffOrReadOnlyPublishedTimetable,
    IsStaffOrTeacherOwnerAvailability,
    IsStaffOrTeacherOwnerLeave,
)
from .serializers import (
    ClassroomSerializer,
    DepartmentSerializer,
    DivisionSerializer,
    LaboratorySerializer,
    PracticalBatchSerializer,
    ProgramSerializer,
    SemesterSerializer,
    SubjectSerializer,
    TeacherAvailabilitySerializer,
    TeacherLeaveSerializer,
    TeacherSubjectSerializer,
    TimetableConflictSerializer,
    TimetableSerializer,
    TimetableSlotSerializer,
)
from .services.conflict_detection import ConflictDetectionService


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


class TeacherSubjectViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for TeacherSubject model.
    - Restricted strictly to STAFF users.
    - Supports filtering by `?teacher={id}` and `?subject={id}`
    """

    queryset = TeacherSubject.objects.select_related(
        "teacher", "teacher__user", "subject", "subject__program"
    ).all()
    serializer_class = TeacherSubjectSerializer
    permission_classes = [IsAuthenticated, IsStaffRole]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = [
        "teacher__employee_code",
        "teacher__user__first_name",
        "teacher__user__last_name",
        "teacher__user__username",
        "subject__name",
        "subject__code",
    ]
    ordering_fields = [
        "priority",
        "created_at",
        "teacher__employee_code",
        "subject__code",
    ]
    ordering = ["teacher", "priority"]

    def get_queryset(self):
        queryset = super().get_queryset()
        teacher_id = self.request.query_params.get("teacher")
        if teacher_id:
            queryset = queryset.filter(teacher_id=teacher_id)

        subject_id = self.request.query_params.get("subject")
        if subject_id:
            queryset = queryset.filter(subject_id=subject_id)

        return queryset


class TeacherAvailabilityViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for TeacherAvailability model.
    - Staff: Full CRUD on all teacher availabilities.
    - Teacher: Full CRUD on ONLY their own availability.
    - Others: Denied access.
    - Supports filtering by `?teacher={id}`, `?day={day}`, and `?is_available={true|false}`
    """

    queryset = TeacherAvailability.objects.select_related(
        "teacher", "teacher__user", "teacher__department"
    ).all()
    serializer_class = TeacherAvailabilitySerializer
    permission_classes = [IsAuthenticated, IsStaffOrTeacherOwnerAvailability]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = [
        "teacher__employee_code",
        "teacher__user__first_name",
        "teacher__user__last_name",
        "day",
    ]
    ordering_fields = [
        "day",
        "start_time",
        "end_time",
        "created_at",
        "teacher__employee_code",
    ]
    ordering = ["day", "start_time"]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if hasattr(user, "role") and user.role == User.Role.TEACHER:
            return queryset.filter(teacher__user=user)

        teacher_id = self.request.query_params.get("teacher")
        if teacher_id:
            queryset = queryset.filter(teacher_id=teacher_id)

        day = self.request.query_params.get("day")
        if day:
            queryset = queryset.filter(day__iexact=day.strip())

        is_available = self.request.query_params.get("is_available")
        if is_available is not None:
            if is_available.lower() in ("true", "1"):
                queryset = queryset.filter(is_available=True)
            elif is_available.lower() in ("false", "0"):
                queryset = queryset.filter(is_available=False)

        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        if hasattr(user, "role") and user.role == User.Role.TEACHER and hasattr(user, "teacher_profile"):
            serializer.save(teacher=user.teacher_profile)
        else:
            serializer.save()


class TeacherLeaveViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for TeacherLeave model.
    - Staff: Full CRUD on all leave requests, can approve/reject.
    - Teacher: View own leaves, create leave request (status PENDING), edit/delete own leaves.
    - Others: Denied access.
    - Supports filtering by `?teacher={id}`, `?status={PENDING|APPROVED|REJECTED}`
    """

    queryset = TeacherLeave.objects.select_related(
        "teacher", "teacher__user", "teacher__department"
    ).all()
    serializer_class = TeacherLeaveSerializer
    permission_classes = [IsAuthenticated, IsStaffOrTeacherOwnerLeave]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = [
        "teacher__employee_code",
        "teacher__user__first_name",
        "teacher__user__last_name",
        "reason",
        "status",
    ]
    ordering_fields = [
        "start_date",
        "end_date",
        "status",
        "created_at",
        "teacher__employee_code",
    ]
    ordering = ["-start_date", "-created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if hasattr(user, "role") and user.role == User.Role.TEACHER:
            return queryset.filter(teacher__user=user)

        teacher_id = self.request.query_params.get("teacher")
        if teacher_id:
            queryset = queryset.filter(teacher_id=teacher_id)

        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status__iexact=status_param.strip())

        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        if hasattr(user, "role") and user.role == User.Role.TEACHER and hasattr(user, "teacher_profile"):
            serializer.save(teacher=user.teacher_profile, status=TeacherLeave.Status.PENDING)
        else:
            serializer.save()

    @action(
        detail=True,
        methods=["patch"],
        url_path="status",
        url_name="status",
        permission_classes=[IsAuthenticated, IsStaffRole],
    )
    def update_status(self, request, pk=None):
        leave = self.get_object()
        status_val = request.data.get("status")
        if not status_val:
            return Response(
                {"status": "Status field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        status_clean = status_val.strip().upper() if isinstance(status_val, str) else status_val
        if status_clean not in TeacherLeave.Status.values:
            return Response(
                {"status": f"Invalid status '{status_val}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        leave.status = status_clean
        leave.save()
        serializer = self.get_serializer(leave)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ClassroomViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for Classroom model.
    - Staff: Full CRUD
    - Teacher/Student: Read-only
    - Supports filtering by `?building={name}` and `?status={AVAILABLE|UNAVAILABLE|MAINTENANCE}`
    """

    queryset = Classroom.objects.all()
    serializer_class = ClassroomSerializer
    permission_classes = [IsStaffOrReadOnlyAcademic]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["building", "room_number"]
    ordering_fields = [
        "building",
        "room_number",
        "floor",
        "capacity",
        "status",
        "created_at",
    ]
    ordering = ["building", "room_number"]

    def get_queryset(self):
        queryset = super().get_queryset()
        building = self.request.query_params.get("building")
        if building:
            queryset = queryset.filter(building__iexact=building.strip())
        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status__iexact=status_param.strip())
        return queryset


class LaboratoryViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for Laboratory model.
    - Staff: Full CRUD
    - Teacher/Student: Read-only
    - Supports filtering by `?building={name}` and `?status={AVAILABLE|UNAVAILABLE|MAINTENANCE}`
    """

    queryset = Laboratory.objects.all()
    serializer_class = LaboratorySerializer
    permission_classes = [IsStaffOrReadOnlyAcademic]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["building", "lab_number", "name"]
    ordering_fields = [
        "building",
        "lab_number",
        "name",
        "floor",
        "capacity",
        "status",
        "created_at",
    ]
    ordering = ["building", "lab_number"]

    def get_queryset(self):
        queryset = super().get_queryset()
        building = self.request.query_params.get("building")
        if building:
            queryset = queryset.filter(building__iexact=building.strip())
        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status__iexact=status_param.strip())
        return queryset


class TimetableViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for Timetable model.
    - Staff: Full CRUD and publishing/archiving actions.
    - Teacher/Student: Read-only access to PUBLISHED timetables only.
    - Supports filtering by `?semester={id}`, `?academic_year={year}`, `?status={status}`
    """

    queryset = Timetable.objects.select_related(
        "semester", "semester__program", "semester__program__department", "created_by"
    ).all()
    serializer_class = TimetableSerializer
    permission_classes = [IsAuthenticated, IsStaffOrReadOnlyPublishedTimetable]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = [
        "semester__program__name",
        "semester__program__code",
        "academic_year",
        "status",
    ]
    ordering_fields = [
        "academic_year",
        "version",
        "status",
        "created_at",
        "published_at",
    ]
    ordering = ["-academic_year", "semester", "-version"]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if hasattr(user, "role") and user.role != User.Role.STAFF:
            queryset = queryset.filter(status=Timetable.Status.PUBLISHED)

        semester_id = self.request.query_params.get("semester")
        if semester_id:
            queryset = queryset.filter(semester_id=semester_id)

        academic_year = self.request.query_params.get("academic_year")
        if academic_year:
            queryset = queryset.filter(academic_year__iexact=academic_year.strip())

        status_param = self.request.query_params.get("status")
        if status_param and hasattr(user, "role") and user.role == User.Role.STAFF:
            queryset = queryset.filter(status__iexact=status_param.strip())

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_destroy(self, instance):
        if instance.status == Timetable.Status.PUBLISHED:
            raise ValidationError(
                "Cannot delete a PUBLISHED timetable. Please un-publish or archive it first."
            )
        instance.delete()

    @action(
        detail=True,
        methods=["post"],
        url_path="publish",
        url_name="publish",
        permission_classes=[IsAuthenticated, IsStaffRole],
    )
    def publish(self, request, pk=None):
        timetable = self.get_object()
        from django.utils import timezone

        timetable.status = Timetable.Status.PUBLISHED
        timetable.published_at = timezone.now()
        timetable.save()
        serializer = self.get_serializer(timetable)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="archive",
        url_name="archive",
        permission_classes=[IsAuthenticated, IsStaffRole],
    )
    def archive(self, request, pk=None):
        timetable = self.get_object()
        timetable.status = Timetable.Status.ARCHIVED
        timetable.save()
        serializer = self.get_serializer(timetable)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="check-conflicts",
        url_name="check-conflicts",
        permission_classes=[IsAuthenticated, IsStaffRole],
    )
    def check_conflicts(self, request, pk=None):
        timetable = self.get_object()
        service = ConflictDetectionService(timetable)
        conflicts = service.detect_conflicts()
        serializer = TimetableConflictSerializer(conflicts, many=True)
        return Response(
            {
                "message": f"Conflict detection completed. Found {len(conflicts)} conflict(s).",
                "total_conflicts": len(conflicts),
                "conflicts": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="conflicts",
        url_name="conflicts",
        permission_classes=[IsAuthenticated, IsStaffOrReadOnlyPublishedTimetable],
    )
    def conflicts(self, request, pk=None):
        timetable = self.get_object()
        conflicts = TimetableConflict.objects.filter(timetable=timetable).select_related(
            "slot", "conflicting_slot", "resolved_by"
        )
        serializer = TimetableConflictSerializer(conflicts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class TimetableSlotViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for TimetableSlot model.
    - Staff: Full CRUD.
    - Teacher: Read-only access to published timetables (or own scheduled slots).
    - Student: Read-only access to published timetable slots for their division/batch.
    - Supports filtering by `?timetable={id}`, `?division={id}`, `?batch={id}`, `?teacher={id}`, `?day={day}`, `?session_type={type}`
    """

    queryset = TimetableSlot.objects.select_related(
        "timetable",
        "timetable__semester",
        "division",
        "batch",
        "subject",
        "teacher",
        "teacher__user",
        "classroom",
        "laboratory",
    ).all()
    serializer_class = TimetableSlotSerializer
    permission_classes = [IsAuthenticated, IsStaffOrReadOnlyPublishedTimetable]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = [
        "subject__name",
        "subject__code",
        "teacher__employee_code",
        "teacher__user__first_name",
        "teacher__user__last_name",
        "division__name",
        "day",
    ]
    ordering_fields = [
        "day",
        "start_time",
        "end_time",
        "session_type",
        "status",
        "created_at",
    ]
    ordering = ["timetable", "day", "start_time"]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if hasattr(user, "role") and user.role == User.Role.TEACHER:
            queryset = queryset.filter(timetable__status=Timetable.Status.PUBLISHED)
            if hasattr(user, "teacher_profile"):
                queryset = queryset.filter(teacher=user.teacher_profile)
        elif hasattr(user, "role") and user.role == User.Role.STUDENT:
            queryset = queryset.filter(timetable__status=Timetable.Status.PUBLISHED)
            if hasattr(user, "student_profile"):
                if user.student_profile.division_id:
                    if user.student_profile.batch_id:
                        queryset = queryset.filter(
                            division_id=user.student_profile.division_id
                        ).filter(
                            Q(batch_id=user.student_profile.batch_id)
                            | Q(batch__isnull=True)
                        )
                    else:
                        queryset = queryset.filter(
                            division_id=user.student_profile.division_id
                        )

        timetable_id = self.request.query_params.get("timetable")
        if timetable_id:
            queryset = queryset.filter(timetable_id=timetable_id)

        division_id = self.request.query_params.get("division")
        if division_id:
            queryset = queryset.filter(division_id=division_id)

        batch_id = self.request.query_params.get("batch")
        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)

        teacher_id = self.request.query_params.get("teacher")
        if teacher_id and (not hasattr(user, "role") or user.role == User.Role.STAFF):
            queryset = queryset.filter(teacher_id=teacher_id)

        day = self.request.query_params.get("day")
        if day:
            queryset = queryset.filter(day__iexact=day.strip())

        session_type = self.request.query_params.get("session_type")
        if session_type:
            queryset = queryset.filter(session_type__iexact=session_type.strip())

        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status__iexact=status_param.strip())

        return queryset


class TimetableConflictViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing and resolving Timetable Conflicts.
    - Staff: Full access and can resolve/ignore.
    - Teacher/Student: Read-only access to conflicts on PUBLISHED timetables.
    - Supports filtering by `?timetable={id}`, `?conflict_type={type}`, `?status={DETECTED|RESOLVED|IGNORED}`
    """

    queryset = TimetableConflict.objects.select_related(
        "timetable", "slot", "conflicting_slot", "resolved_by"
    ).all()
    serializer_class = TimetableConflictSerializer
    permission_classes = [IsAuthenticated, IsStaffOrReadOnlyPublishedTimetable]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["conflict_type", "severity", "description", "status"]
    ordering_fields = ["severity", "created_at", "status"]
    ordering = ["-severity", "-created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if hasattr(user, "role") and user.role != User.Role.STAFF:
            queryset = queryset.filter(timetable__status=Timetable.Status.PUBLISHED)

        timetable_id = self.request.query_params.get("timetable")
        if timetable_id:
            queryset = queryset.filter(timetable_id=timetable_id)

        conflict_type = self.request.query_params.get("conflict_type")
        if conflict_type:
            queryset = queryset.filter(conflict_type__iexact=conflict_type.strip())

        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status__iexact=status_param.strip())

        return queryset

    @action(
        detail=True,
        methods=["post"],
        url_path="resolve",
        url_name="resolve",
        permission_classes=[IsAuthenticated, IsStaffRole],
    )
    def resolve(self, request, pk=None):
        conflict = self.get_object()
        from django.utils import timezone

        conflict.status = TimetableConflict.Status.RESOLVED
        conflict.resolved_by = request.user
        conflict.resolved_at = timezone.now()
        conflict.save()
        serializer = self.get_serializer(conflict)
        return Response(serializer.data, status=status.HTTP_200_OK)

