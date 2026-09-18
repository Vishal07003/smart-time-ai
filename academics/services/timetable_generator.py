"""
Timetable Generation Service for SMART-TIME-AI (Phase 7).
Orchestrates database extraction, session expansion, CP-SAT solver execution,
and atomic timetable persistence with conflict checking.
"""

from typing import Any, Dict, List, Optional
from django.db import models, transaction
from django.db.models import Max

from academics.models import (
    Classroom,
    Division,
    Laboratory,
    PracticalBatch,
    Semester,
    Subject,
    TeacherAvailability,
    TeacherLeave,
    TeacherSubject,
    Timetable,
    TimetableConflict,
    TimetableSlot,
)
from academics.services.conflict_detection import ConflictDetectionService
from academics.services.timetable_solver import SolverConfig, TimetableSolver


class TimetableGenerationService:
    """
    Orchestration service to generate complete, constraint-compliant academic timetables.
    """

    def __init__(
        self,
        semester_id: Any,
        academic_year: str,
        created_by: Any = None,
        config: Optional[SolverConfig] = None,
    ):
        self.semester_id = semester_id
        self.academic_year = str(academic_year).strip()
        self.created_by = created_by
        self.config = config or SolverConfig()

    def generate(self) -> Dict[str, Any]:
        """
        Loads academic data, expands required sessions, executes constraint solver,
        and saves generated timetable and slots atomically.
        """
        # 1. Load and validate Semester
        try:
            semester = Semester.objects.select_related("program").get(id=self.semester_id)
        except Semester.DoesNotExist:
            return {
                "status": TimetableSolver.STATUS_INFEASIBLE,
                "errors": [f"Semester with ID '{self.semester_id}' does not exist."],
                "conflicts": [],
            }

        # 2. Load Divisions and Batches
        divisions = list(
            Division.objects.filter(semester=semester).prefetch_related("batches")
        )
        if not divisions:
            return {
                "status": TimetableSolver.STATUS_INFEASIBLE,
                "errors": [f"No class divisions found for semester '{semester}'."],
                "conflicts": [],
            }

        # 3. Load Subjects for Semester Program
        subjects = list(Subject.objects.filter(program=semester.program))
        if not subjects:
            return {
                "status": TimetableSolver.STATUS_INFEASIBLE,
                "errors": [f"No subjects found for program '{semester.program}'."],
                "conflicts": [],
            }

        subject_ids = [s.id for s in subjects]

        # 4. Load Qualified Teachers from TeacherSubject
        teacher_subject_qs = TeacherSubject.objects.filter(
            subject_id__in=subject_ids
        ).select_related("teacher", "teacher__user", "subject")

        qualified_teachers_by_subject: Dict[str, List[Any]] = {
            str(s.id): [] for s in subjects
        }
        all_assigned_teachers_dict: Dict[str, Any] = {}
        teacher_qualified_subjects: Dict[str, List[str]] = {}

        for ts in teacher_subject_qs:
            subj_id_str = str(ts.subject_id)
            teacher_id_str = str(ts.teacher_id)
            qualified_teachers_by_subject.setdefault(subj_id_str, []).append(ts.teacher)
            all_assigned_teachers_dict[teacher_id_str] = ts.teacher
            teacher_qualified_subjects.setdefault(teacher_id_str, []).append(subj_id_str)

        # 5. Session Expansion
        # For every division and subject, expand weekly_lectures and weekly_practicals
        sessions_to_schedule: List[Dict[str, Any]] = []
        errors: List[str] = []
        conflicts: List[str] = []

        for div in divisions:
            batches = list(div.batches.all())
            for subj in subjects:
                weekly_lectures = subj.weekly_lectures or 0
                weekly_practicals = subj.weekly_practicals or 0

                # Validate qualified teacher exists if session count > 0
                if (weekly_lectures > 0 or weekly_practicals > 0) and not qualified_teachers_by_subject.get(str(subj.id)):
                    err_msg = (
                        f"No qualified teacher assigned via TeacherSubject for subject "
                        f"'{subj.code}' ({subj.name})."
                    )
                    errors.append(err_msg)
                    conflicts.append(f"MISSING_TEACHER: {err_msg}")

                # Expand Lectures (1 requirement per weekly lecture per division)
                for i in range(1, weekly_lectures + 1):
                    sessions_to_schedule.append(
                        {
                            "id": f"lec_{div.id}_{subj.id}_{i}",
                            "subject_id": str(subj.id),
                            "division_id": str(div.id),
                            "batch_id": None,
                            "session_type": "LECTURE",
                            "duration_slots": 1,
                        }
                    )

                # Expand Practicals (1 requirement per weekly practical per batch, or per division if no batches)
                if weekly_practicals > 0:
                    if batches:
                        for batch in batches:
                            for j in range(1, weekly_practicals + 1):
                                sessions_to_schedule.append(
                                    {
                                        "id": f"prac_{batch.id}_{subj.id}_{j}",
                                        "subject_id": str(subj.id),
                                        "division_id": str(div.id),
                                        "batch_id": str(batch.id),
                                        "session_type": "PRACTICAL",
                                        "duration_slots": 1,
                                    }
                                )
                    else:
                        for j in range(1, weekly_practicals + 1):
                            sessions_to_schedule.append(
                                {
                                    "id": f"prac_{div.id}_{subj.id}_{j}",
                                    "subject_id": str(subj.id),
                                    "division_id": str(div.id),
                                    "batch_id": None,
                                    "session_type": "PRACTICAL",
                                    "duration_slots": 1,
                                }
                            )

        if errors:
            return {
                "status": TimetableSolver.STATUS_INFEASIBLE,
                "errors": errors,
                "conflicts": conflicts,
            }

        if not sessions_to_schedule:
            return {
                "status": TimetableSolver.STATUS_INFEASIBLE,
                "errors": ["No academic sessions required to schedule (all subjects have 0 lectures and practicals)."],
                "conflicts": [],
            }

        # 6. Load Teachers with Availabilities and Approved Leaves
        teachers_data: List[Dict[str, Any]] = []
        for t_id, t_profile in all_assigned_teachers_dict.items():
            availabilities = list(
                TeacherAvailability.objects.filter(teacher=t_profile, is_available=False)
            )
            leaves = list(
                TeacherLeave.objects.filter(teacher=t_profile, status=TeacherLeave.Status.APPROVED)
            )

            # Map leave days if any
            leave_days_set = set()
            for l in leaves:
                # If start_date == end_date or covers specific days, can capture day of week
                # Day names from date:
                # l.start_date.strftime("%A").upper()
                pass

            teachers_data.append(
                {
                    "id": t_id,
                    "name": t_profile.user.get_full_name() or t_profile.user.username,
                    "employee_code": t_profile.employee_code,
                    "qualified_subject_ids": teacher_qualified_subjects.get(t_id, []),
                    "unavailable_slots": [
                        {
                            "day": a.day,
                            "start_time": str(a.start_time),
                            "end_time": str(a.end_time),
                        }
                        for a in availabilities
                    ],
                    "leave_days": list(leave_days_set),
                }
            )

        # 7. Load Rooms (Classrooms & Laboratories)
        rooms_data: List[Dict[str, Any]] = []
        classrooms = Classroom.objects.filter(status=Classroom.Status.AVAILABLE)
        for cr in classrooms:
            rooms_data.append(
                {
                    "id": str(cr.id),
                    "name": f"{cr.building}-{cr.room_number}",
                    "room_type": "CLASSROOM",
                    "capacity": cr.capacity,
                    "status": cr.status,
                }
            )

        laboratories = Laboratory.objects.filter(status=Laboratory.Status.AVAILABLE)
        for lab in laboratories:
            rooms_data.append(
                {
                    "id": str(lab.id),
                    "name": f"{lab.building}-{lab.lab_number} ({lab.name})",
                    "room_type": "LABORATORY",
                    "capacity": lab.capacity,
                    "status": lab.status,
                }
            )

        divisions_data = [
            {
                "id": str(d.id),
                "name": d.name,
                "batch_ids": [str(b.id) for b in d.batches.all()],
            }
            for d in divisions
        ]

        # 8. Build Solver Input & Execute Solver
        solver_input = {
            "divisions": divisions_data,
            "teachers": teachers_data,
            "rooms": rooms_data,
            "sessions_to_schedule": sessions_to_schedule,
        }

        solver = TimetableSolver(config=self.config)
        solver_result = solver.solve(solver_input)

        if solver_result.get("status") != TimetableSolver.STATUS_FEASIBLE:
            return {
                "status": solver_result.get("status", TimetableSolver.STATUS_INFEASIBLE),
                "errors": solver_result.get("errors", ["Timetable generation is infeasible."]),
                "conflicts": solver_result.get("conflicts", []),
            }

        # 9. Atomic Database Persistence (Timetable + TimetableSlots + Conflict Detection)
        with transaction.atomic():
            # Determine next version
            max_version = (
                Timetable.objects.filter(
                    semester=semester,
                    academic_year=self.academic_year,
                ).aggregate(Max("version"))["version__max"]
                or 0
            )
            new_version = max_version + 1

            timetable = Timetable.objects.create(
                semester=semester,
                academic_year=self.academic_year,
                version=new_version,
                status=Timetable.Status.GENERATED,
                created_by=self.created_by,
            )

            slots_to_create = []
            for a in solver_result.get("assignments", []):
                slots_to_create.append(
                    TimetableSlot(
                        timetable=timetable,
                        division_id=a["division_id"],
                        batch_id=a.get("batch_id"),
                        subject_id=a["subject_id"],
                        teacher_id=a["teacher_id"],
                        classroom_id=a.get("classroom_id"),
                        laboratory_id=a.get("laboratory_id"),
                        day=a["day"],
                        start_time=a["start_time"],
                        end_time=a["end_time"],
                        session_type=a["session_type"],
                        status=TimetableSlot.Status.SCHEDULED,
                    )
                )

            if slots_to_create:
                TimetableSlot.objects.bulk_create(slots_to_create)

            # Run Phase 5 conflict detection
            conflict_service = ConflictDetectionService(timetable)
            detected_conflicts = conflict_service.detect_conflicts()
            serialized_conflicts = [
                {
                    "id": str(c.id),
                    "conflict_type": c.conflict_type,
                    "severity": c.severity,
                    "description": c.description,
                    "status": c.status,
                }
                for c in detected_conflicts
            ]

            return {
                "status": TimetableSolver.STATUS_FEASIBLE,
                "timetable_id": str(timetable.id),
                "version": timetable.version,
                "total_slots": len(slots_to_create),
                "conflicts": serialized_conflicts,
                "errors": [],
            }
