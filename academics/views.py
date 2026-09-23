from django.core.exceptions import PermissionDenied as DjangoPermissionDenied, ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import TeacherProfile, User
from accounts.permissions import IsStaffRole
from .models import (
    Classroom,
    Department,
    Division,
    Laboratory,
    Notification,
    PracticalBatch,
    Program,
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
from .permissions import (
    IsStaffOrReadOnlyAcademic,
    IsStaffOrReadOnlyPublishedTimetable,
    IsStaffOrTeacherOwnerAvailability,
    IsStaffOrTeacherOwnerLeave,
)
from .serializers import (
    ClassroomSerializer,
    ConstraintGenerateTimetableRequestSerializer,
    ConstraintParseAndValidateRequestSerializer,
    DepartmentSerializer,
    DivisionSerializer,
    LaboratorySerializer,
    NotificationSerializer,
    PracticalBatchSerializer,
    ProgramSerializer,
    RescheduleConfirmRequestSerializer,
    SemesterSerializer,
    SlotRescheduleSerializer,
    SubjectSerializer,
    TeacherAvailabilitySerializer,
    TeacherLeaveSerializer,
    TeacherSubjectSerializer,
    TeacherSubstitutionCreateSerializer,
    TeacherSubstitutionSerializer,
    TimetableChangeLogSerializer,
    TimetableConflictSerializer,
    TimetableGenerateRequestSerializer,
    TimetableSerializer,
    TimetableSlotSerializer,
)
from .services.conflict_detection import ConflictDetectionService
from .services.constraint_parser import ConstraintParserService, ParsingContext
from .services.constraint_validator import ConstraintValidatorService
from .services.rescheduling_service import ReschedulingSuggestionService
from .services.substitute_service import SubstituteSuggestionService
from .services.timetable_generator import TimetableGenerationService


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
        timetable = serializer.save(created_by=self.request.user)
        from academics.services.timetable_history_service import TimetableHistoryService
        TimetableHistoryService.log_timetable_created(timetable, changed_by=self.request.user)

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

        with transaction.atomic():
            from academics.services.timetable_history_service import TimetableHistoryService

            # 1. Archive any previously PUBLISHED timetables for the same semester and academic year
            prev_published = list(
                Timetable.objects.filter(
                    semester=timetable.semester,
                    academic_year=timetable.academic_year,
                    status=Timetable.Status.PUBLISHED,
                ).exclude(pk=timetable.pk)
            )
            for prev in prev_published:
                prev.status = Timetable.Status.ARCHIVED
                prev.save(update_fields=["status", "updated_at"])
                TimetableHistoryService.log_timetable_archived(prev, changed_by=request.user)

            old_status = timetable.status
            # 2. Mark this timetable as PUBLISHED (preserve published_at if already set)
            timetable.status = Timetable.Status.PUBLISHED
            if not timetable.published_at:
                timetable.published_at = timezone.now()
            timetable.save(update_fields=["status", "published_at", "updated_at"])

            TimetableHistoryService.log_timetable_published(timetable, changed_by=request.user, old_status=old_status)

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
        old_status = timetable.status
        timetable.status = Timetable.Status.ARCHIVED
        timetable.save()

        from academics.services.timetable_history_service import TimetableHistoryService
        TimetableHistoryService.log_timetable_archived(timetable, changed_by=request.user, old_status=old_status)

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
        detail=False,
        methods=["post"],
        url_path="generate",
        url_name="generate",
        permission_classes=[IsAuthenticated, IsStaffRole],
    )
    def generate(self, request):
        serializer = TimetableGenerateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        semester_id = serializer.validated_data["semester"].id
        academic_year = serializer.validated_data["academic_year"]

        generator = TimetableGenerationService(
            semester_id=semester_id,
            academic_year=academic_year,
            created_by=request.user,
        )
        result = generator.generate()
        if result.get("status") in ("FEASIBLE", "OPTIMAL"):
            return Response(result, status=status.HTTP_201_CREATED)
        return Response(result, status=status.HTTP_400_BAD_REQUEST)

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

    @action(
        detail=True,
        methods=["get"],
        url_path="slots",
        url_name="slots",
        permission_classes=[IsAuthenticated, IsStaffOrReadOnlyPublishedTimetable],
    )
    def slots(self, request, pk=None):
        timetable = self.get_object()
        slots = TimetableSlot.objects.filter(timetable=timetable).select_related(
            "timetable",
            "timetable__semester",
            "division",
            "batch",
            "subject",
            "teacher",
            "teacher__user",
            "classroom",
            "laboratory",
        ).order_by("day", "start_time")
        serializer = TimetableSlotSerializer(slots, many=True)
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


def build_parsing_context_from_db(semester=None) -> ParsingContext:
    """Constructs a ParsingContext from active database records to assist entity resolution."""
    teachers_qs = TeacherProfile.objects.filter(
        status=TeacherProfile.Status.ACTIVE,
        user__is_active=True,
    ).select_related("user")
    teachers_data = [
        {
            "id": str(t.id),
            "name": t.user.get_full_name() or t.user.username,
            "employee_code": t.employee_code,
        }
        for t in teachers_qs
    ]

    if semester:
        subjects_qs = Subject.objects.filter(program=semester.program)
        divisions_qs = Division.objects.filter(semester=semester)
    else:
        subjects_qs = Subject.objects.all()
        divisions_qs = Division.objects.all()

    subjects_data = [
        {
            "id": str(s.id),
            "name": s.name,
            "code": s.code,
        }
        for s in subjects_qs
    ]

    divisions_data = [
        {
            "id": str(d.id),
            "name": d.name,
        }
        for d in divisions_qs
    ]

    return ParsingContext(
        teachers=teachers_data,
        subjects=subjects_data,
        divisions=divisions_data,
    )


class ConstraintParseAndValidateView(APIView):
    """
    POST /api/v1/constraints/parse-and-validate/
    Staff-only endpoint to parse natural-language timetable requirements into
    structured constraints and validate/normalize them against actual database entities.
    """

    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request, *args, **kwargs):
        serializer = ConstraintParseAndValidateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        text = serializer.validated_data["text"]
        semester = serializer.validated_data.get("semester")

        # 1. Build context & parse
        context = build_parsing_context_from_db(semester=semester)
        parser = ConstraintParserService()
        parse_res = parser.parse(text, context=context)

        if not parse_res.success or not parse_res.constraint:
            formatted_errors = []
            for err in parse_res.errors:
                if "ambiguous" in err.lower():
                    code = "AMBIGUOUS"
                    field_name = "teacher" if "teacher" in err.lower() else ("subject" if "subject" in err.lower() else "division")
                elif "unknown" in err.lower() or "not found" in err.lower():
                    code = "NOT_FOUND"
                    field_name = "teacher" if "teacher" in err.lower() else ("subject" if "subject" in err.lower() else "division")
                else:
                    code = "PARSER_ERROR"
                    field_name = "text"
                formatted_errors.append({
                    "code": code,
                    "field": field_name,
                    "message": err,
                })
            return Response(
                {
                    "valid": False,
                    "constraint": None,
                    "errors": formatted_errors,
                },
                status=status.HTTP_200_OK,
            )

        # 2. Validate & normalize against DB
        validator = ConstraintValidatorService()
        val_res = validator.validate(parse_res.constraint, semester=semester)

        return Response(val_res.to_dict(), status=status.HTTP_200_OK)


class ConstraintGenerateTimetableView(APIView):
    """
    POST /api/v1/constraints/generate-timetable/
    Staff-only endpoint to parse natural-language constraints, validate them,
    and generate an OR-Tools optimized timetable.
    """

    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request, *args, **kwargs):
        serializer = ConstraintGenerateTimetableRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        text = serializer.validated_data["text"]
        semester = serializer.validated_data["semester"]
        academic_year = serializer.validated_data["academic_year"]

        # 1. Parse natural language
        context = build_parsing_context_from_db(semester=semester)
        parser = ConstraintParserService()
        parse_res = parser.parse(text, context=context)

        if not parse_res.success or not parse_res.constraint:
            formatted_errors = []
            for err in parse_res.errors:
                if "ambiguous" in err.lower():
                    code = "AMBIGUOUS"
                    field_name = "teacher" if "teacher" in err.lower() else ("subject" if "subject" in err.lower() else "division")
                elif "unknown" in err.lower() or "not found" in err.lower():
                    code = "NOT_FOUND"
                    field_name = "teacher" if "teacher" in err.lower() else ("subject" if "subject" in err.lower() else "division")
                else:
                    code = "PARSER_ERROR"
                    field_name = "text"
                formatted_errors.append({
                    "code": code,
                    "field": field_name,
                    "message": err,
                })
            return Response(
                {
                    "status": "INFEASIBLE",
                    "valid": False,
                    "constraint": None,
                    "errors": formatted_errors,
                    "conflicts": [],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Validate & normalize
        validator = ConstraintValidatorService()
        val_res = validator.validate(parse_res.constraint, semester=semester)

        if not val_res.valid or not val_res.constraint:
            return Response(
                {
                    "status": "INFEASIBLE",
                    "valid": False,
                    "constraint": None,
                    "errors": [err.to_dict() for err in val_res.errors],
                    "conflicts": [],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3. Generate Timetable with OR-Tools Solver
        generator = TimetableGenerationService(
            semester_id=semester.id,
            academic_year=academic_year,
            created_by=request.user,
            constraints=[val_res.constraint],
        )
        result = generator.generate()

        if result.get("status") in ("FEASIBLE", "OPTIMAL"):
            return Response(result, status=status.HTTP_201_CREATED)
        return Response(result, status=status.HTTP_400_BAD_REQUEST)


class SubstituteSuggestionsView(APIView):
    """
    GET /api/v1/substitutions/suggestions/?teacher_leave=<UUID>
    Staff-only endpoint to find affected published slots and suggest qualified,
    available substitute teacher candidates.
    """

    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request, *args, **kwargs):
        leave_id = request.query_params.get("teacher_leave")
        if not leave_id:
            return Response(
                {"error": "Query parameter 'teacher_leave' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            leave = TeacherLeave.objects.select_related(
                "teacher", "teacher__user"
            ).get(id=leave_id)
        except (TeacherLeave.DoesNotExist, ValueError):
            return Response(
                {"error": f"Teacher leave with ID '{leave_id}' was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if leave.status != TeacherLeave.Status.APPROVED:
            return Response(
                {"error": "Teacher leave must be in APPROVED status to view substitute suggestions."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        suggestions = SubstituteSuggestionService.get_suggestions_for_leave(leave)
        return Response(suggestions, status=status.HTTP_200_OK)


class TeacherSubstitutionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Teacher Substitutions.
    - Staff: Full access to list and confirm substitutions.
    - Teacher/Student: Denied.
    """

    queryset = (
        TeacherSubstitution.objects.select_related(
            "timetable_slot",
            "timetable_slot__subject",
            "timetable_slot__division",
            "absent_teacher",
            "absent_teacher__user",
            "substitute_teacher",
            "substitute_teacher__user",
            "assigned_by",
        )
        .all()
    )
    serializer_class = TeacherSubstitutionSerializer
    permission_classes = [IsAuthenticated, IsStaffRole]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = [
        "absent_teacher__employee_code",
        "absent_teacher__user__first_name",
        "substitute_teacher__employee_code",
        "substitute_teacher__user__first_name",
        "reason",
        "status",
    ]
    ordering_fields = ["assigned_at", "created_at", "status"]
    ordering = ["-assigned_at"]

    def get_permissions(self):
        if self.action in ["accept", "decline"]:
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsStaffRole()]

    def create(self, request, *args, **kwargs):
        serializer = TeacherSubstitutionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        slot = serializer.validated_data["timetable_slot"]
        substitute_teacher = serializer.validated_data["substitute_teacher"]
        teacher_leave = serializer.validated_data.get("teacher_leave")
        reason = serializer.validated_data.get("reason", "")

        try:
            substitution = SubstituteSuggestionService.confirm_substitution(
                slot_id=slot.id,
                substitute_teacher_id=substitute_teacher.id,
                reason=reason,
                assigned_by=request.user,
                teacher_leave_id=teacher_leave.id if teacher_leave else None,
            )
        except (ValidationError, DjangoValidationError) as e:
            if hasattr(e, "message_dict"):
                return Response(e.message_dict, status=status.HTTP_400_BAD_REQUEST)
            if hasattr(e, "detail"):
                return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
            if hasattr(e, "messages"):
                return Response({"detail": e.messages}, status=status.HTTP_400_BAD_REQUEST)
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        response_serializer = TeacherSubstitutionSerializer(substitution)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="accept")
    def accept(self, request, pk=None):
        """
        Action for the assigned substitute teacher to accept a substitution assignment.
        """
        try:
            substitution = SubstituteSuggestionService.accept_substitution(
                substitution_id=pk,
                user=request.user,
            )
        except DjangoPermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except (ValidationError, DjangoValidationError) as e:
            if hasattr(e, "message_dict"):
                return Response(e.message_dict, status=status.HTTP_400_BAD_REQUEST)
            if hasattr(e, "detail"):
                return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
            if hasattr(e, "messages"):
                return Response({"detail": e.messages}, status=status.HTTP_400_BAD_REQUEST)
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = TeacherSubstitutionSerializer(substitution)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="decline")
    def decline(self, request, pk=None):
        """
        Action for the assigned substitute teacher to decline a substitution assignment.
        """
        try:
            substitution = SubstituteSuggestionService.decline_substitution(
                substitution_id=pk,
                user=request.user,
            )
        except DjangoPermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except (ValidationError, DjangoValidationError) as e:
            if hasattr(e, "message_dict"):
                return Response(e.message_dict, status=status.HTTP_400_BAD_REQUEST)
            if hasattr(e, "detail"):
                return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
            if hasattr(e, "messages"):
                return Response({"detail": e.messages}, status=status.HTTP_400_BAD_REQUEST)
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = TeacherSubstitutionSerializer(substitution)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing and managing user notifications.
    Authenticated users can only access their own notifications.
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["title", "message", "notification_type"]
    ordering_fields = ["created_at", "read_at", "is_read"]
    ordering = ["-created_at"]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Notification.objects.none()
        qs = Notification.objects.filter(recipient=user).select_related("related_substitution")
        is_read_param = self.request.query_params.get("is_read")
        if is_read_param is not None:
            if is_read_param.lower() in ["true", "1"]:
                qs = qs.filter(is_read=True)
            elif is_read_param.lower() in ["false", "0"]:
                qs = qs.filter(is_read=False)
        return qs

    @action(detail=True, methods=["patch", "post"], url_path="read")
    def mark_read(self, request, pk=None):
        """
        Marks a specific notification as read.
        Only the owner (recipient) can mark it read.
        """
        try:
            notification = Notification.objects.get(pk=pk)
        except (Notification.DoesNotExist, ValueError):
            return Response({"detail": "Notification not found."}, status=status.HTTP_404_NOT_FOUND)

        if notification.recipient != request.user:
            return Response(
                {"detail": "You do not have permission to mark this notification as read."},
                status=status.HTTP_403_FORBIDDEN,
            )

        notification.mark_as_read()
        serializer = self.get_serializer(notification)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ReschedulingSuggestionsView(APIView):
    """
    Staff-only endpoint to generate deterministic rescheduling suggestions for an affected published TimetableSlot.
    """

    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request, *args, **kwargs):
        slot_id = request.query_params.get("timetable_slot")
        if not slot_id:
            return Response(
                {"timetable_slot": "Query parameter 'timetable_slot' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            suggestions_data = ReschedulingSuggestionService.get_suggestions_for_slot(slot_id)
            return Response(suggestions_data, status=status.HTTP_200_OK)
        except DjangoValidationError as e:
            if hasattr(e, "message_dict"):
                return Response(e.message_dict, status=status.HTTP_400_BAD_REQUEST)
            if hasattr(e, "messages"):
                return Response({"detail": e.messages}, status=status.HTTP_400_BAD_REQUEST)
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ReschedulingConfirmView(APIView):
    """
    Staff-only endpoint to confirm and persist a slot reschedule safely.
    Re-validates all parameters server-side, creates a new draft timetable version (status: GENERATED),
    and logs a SlotReschedule record without mutating the original published timetable.
    """

    permission_classes = [IsAuthenticated, IsStaffRole]

    def post(self, request, *args, **kwargs):
        serializer = RescheduleConfirmRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        slot = serializer.validated_data["timetable_slot"]
        teacher = serializer.validated_data["teacher"]
        day = serializer.validated_data["day"]
        start_time = serializer.validated_data["start_time"]
        end_time = serializer.validated_data["end_time"]
        classroom = serializer.validated_data.get("classroom")
        laboratory = serializer.validated_data.get("laboratory")
        reason = serializer.validated_data.get("reason", "")

        try:
            result = ReschedulingSuggestionService.confirm_reschedule(
                slot_id=slot.id,
                teacher_id=teacher.id,
                day=day,
                start_time=start_time,
                end_time=end_time,
                classroom_id=classroom.id if classroom else None,
                laboratory_id=laboratory.id if laboratory else None,
                reason=reason,
                user=request.user,
            )
            return Response(result, status=status.HTTP_201_CREATED)
        except DjangoValidationError as e:
            if hasattr(e, "message_dict"):
                return Response(e.message_dict, status=status.HTTP_400_BAD_REQUEST)
            if hasattr(e, "messages"):
                return Response({"detail": e.messages}, status=status.HTTP_400_BAD_REQUEST)
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class TimetableChangeLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Staff-only read-only API for viewing immutable TimetableChangeLog audit records.
    Supports filtering by ?timetable={uuid}, ?timetable_slot={uuid}, ?action={ACTION},
    ?changed_by={uuid}, ?date_from={iso}, ?date_to={iso}.
    """

    queryset = TimetableChangeLog.objects.select_related(
        "timetable", "timetable_slot", "changed_by"
    ).all()
    serializer_class = TimetableChangeLogSerializer
    permission_classes = [IsAuthenticated, IsStaffRole]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = [
        "action",
        "reason",
        "changed_by__username",
        "changed_by__first_name",
        "changed_by__last_name",
    ]
    ordering_fields = ["created_at", "action"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = super().get_queryset()

        timetable_id = self.request.query_params.get("timetable")
        if timetable_id:
            qs = qs.filter(timetable_id=timetable_id)

        slot_id = self.request.query_params.get("timetable_slot")
        if slot_id:
            qs = qs.filter(timetable_slot_id=slot_id)

        action_param = self.request.query_params.get("action")
        if action_param:
            qs = qs.filter(action=action_param.strip().upper())

        changed_by_id = self.request.query_params.get("changed_by")
        if changed_by_id:
            qs = qs.filter(changed_by_id=changed_by_id)

        date_from = self.request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(created_at__gte=date_from)

        date_to = self.request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(created_at__lte=date_to)

        return qs





