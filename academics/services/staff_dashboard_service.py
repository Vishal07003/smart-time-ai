"""
Staff Dashboard Service for SMART-TIME AI (Phase 12).

Aggregates operational metrics, today's schedule classification, pending leaves,
pending substitutions, unresolved conflicts, and recent change history for Staff users.
"""

from datetime import datetime, time
from typing import Any, Dict, List, Optional
import uuid

from django.db.models import Count, Q
from django.utils import timezone

from academics.models import (
    Classroom,
    Laboratory,
    Semester,
    Subject,
    TeacherLeave,
    TeacherSubstitution,
    Timetable,
    TimetableChangeLog,
    TimetableConflict,
    TimetableSlot,
)
from accounts.models import StudentProfile, TeacherProfile, User


class StaffDashboardService:
    """
    Business service to aggregate and construct the Staff Dashboard dataset.
    Optimized with select_related / prefetch_related to avoid N+1 query overhead.
    """

    @classmethod
    def get_dashboard_data(
        cls,
        user: User,
        reference_datetime: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Generates the comprehensive staff dashboard payload.
        Allows passing reference_datetime for deterministic test evaluation.
        """
        now = reference_datetime or timezone.localtime(timezone.now())
        current_day_name = now.strftime("%A").upper()
        current_time = now.time()

        # 1. SUMMARY METRICS
        active_teachers_count = TeacherProfile.objects.filter(
            status=TeacherProfile.Status.ACTIVE,
            user__is_active=True,
        ).count()

        active_students_count = StudentProfile.objects.filter(
            status=StudentProfile.Status.ACTIVE,
            user__is_active=True,
        ).count()

        today_slots_qs = (
            TimetableSlot.objects.filter(
                timetable__status=Timetable.Status.PUBLISHED,
                day=current_day_name,
            )
            .exclude(status=TimetableSlot.Status.CANCELLED)
            .select_related(
                "timetable",
                "timetable__semester",
                "subject",
                "teacher",
                "teacher__user",
                "division",
                "batch",
                "classroom",
                "laboratory",
            )
            .order_by("start_time", "division__name")
        )

        today_classes_count = today_slots_qs.count()

        unresolved_conflicts_count = TimetableConflict.objects.filter(
            status=TimetableConflict.Status.DETECTED,
        ).count()

        pending_leaves_count = TeacherLeave.objects.filter(
            status=TeacherLeave.Status.PENDING,
        ).count()

        pending_substitutions_count = TeacherSubstitution.objects.filter(
            status=TeacherSubstitution.Status.PENDING,
        ).count()

        summary_data = {
            "active_teachers_count": active_teachers_count,
            "active_students_count": active_students_count,
            "today_classes_count": today_classes_count,
            "unresolved_conflicts_count": unresolved_conflicts_count,
            "unresolved_timetable_conflicts_count": unresolved_conflicts_count,
            "pending_leaves_count": pending_leaves_count,
            "pending_teacher_leaves_count": pending_leaves_count,
            "pending_substitutions_count": pending_substitutions_count,
        }

        # 2. TODAY'S CLASSES & CLASSIFICATION (current, upcoming, completed)
        all_today_classes: List[Dict[str, Any]] = []
        current_classes: List[Dict[str, Any]] = []
        upcoming_classes: List[Dict[str, Any]] = []
        completed_classes: List[Dict[str, Any]] = []

        for slot in today_slots_qs:
            teacher_dict = None
            if slot.teacher and slot.teacher.user:
                teacher_dict = {
                    "id": str(slot.teacher.id),
                    "name": slot.teacher.user.get_full_name() or slot.teacher.user.username,
                    "employee_code": slot.teacher.employee_code,
                }

            subject_dict = None
            if slot.subject:
                subject_dict = {
                    "id": str(slot.subject.id),
                    "name": slot.subject.name,
                    "code": slot.subject.code,
                }

            division_dict = None
            if slot.division:
                division_dict = {
                    "id": str(slot.division.id),
                    "name": slot.division.name,
                }

            batch_dict = None
            if slot.batch:
                batch_dict = {
                    "id": str(slot.batch.id),
                    "name": slot.batch.name,
                }

            classroom_dict = None
            if slot.classroom:
                classroom_dict = {
                    "id": str(slot.classroom.id),
                    "name": f"{slot.classroom.building}-{slot.classroom.room_number}",
                    "building": slot.classroom.building,
                    "room_number": slot.classroom.room_number,
                }

            laboratory_dict = None
            if slot.laboratory:
                laboratory_dict = {
                    "id": str(slot.laboratory.id),
                    "name": f"{slot.laboratory.building}-{slot.laboratory.lab_number}",
                    "building": slot.laboratory.building,
                    "lab_number": slot.laboratory.lab_number,
                }

            slot_repr = {
                "id": str(slot.id),
                "timetable_id": str(slot.timetable_id),
                "subject": subject_dict,
                "teacher": teacher_dict,
                "division": division_dict,
                "batch": batch_dict,
                "classroom": classroom_dict,
                "laboratory": laboratory_dict,
                "day": slot.day,
                "start_time": str(slot.start_time)[:5],
                "end_time": str(slot.end_time)[:5],
                "session_type": slot.session_type,
                "status": slot.status,
            }

            all_today_classes.append(slot_repr)

            # Classify by start and end time
            slot_start = slot.start_time
            slot_end = slot.end_time

            if slot_end <= current_time:
                completed_classes.append(slot_repr)
            elif slot_start <= current_time < slot_end:
                current_classes.append(slot_repr)
            else:
                upcoming_classes.append(slot_repr)

        today_data = {
            "day": current_day_name,
            "date": now.strftime("%Y-%m-%d"),
            "current_time": current_time.strftime("%H:%M"),
            "classes": all_today_classes,
            "current": current_classes,
            "upcoming": upcoming_classes,
            "completed": completed_classes,
        }

        # 3. PENDING TEACHER LEAVES
        pending_leaves_qs = (
            TeacherLeave.objects.filter(
                status=TeacherLeave.Status.PENDING,
            )
            .select_related("teacher", "teacher__user", "teacher__department")
            .order_by("-created_at")[:15]
        )
        teacher_leaves_data = [
            {
                "id": str(l.id),
                "teacher": {
                    "id": str(l.teacher.id),
                    "name": l.teacher.user.get_full_name() or l.teacher.user.username,
                    "employee_code": l.teacher.employee_code,
                    "department": l.teacher.department.name if l.teacher.department else None,
                },
                "start_date": str(l.start_date),
                "end_date": str(l.end_date),
                "reason": l.reason,
                "status": l.status,
                "created_at": l.created_at.isoformat(),
            }
            for l in pending_leaves_qs
        ]

        # 4. PENDING SUBSTITUTIONS
        pending_subs_qs = (
            TeacherSubstitution.objects.filter(
                status=TeacherSubstitution.Status.PENDING,
            )
            .select_related(
                "timetable_slot",
                "timetable_slot__subject",
                "timetable_slot__division",
                "absent_teacher",
                "absent_teacher__user",
                "substitute_teacher",
                "substitute_teacher__user",
                "assigned_by",
            )
            .order_by("-assigned_at")[:15]
        )
        substitutions_data = []
        for sub in pending_subs_qs:
            slot_info = None
            if sub.timetable_slot:
                slot_info = {
                    "id": str(sub.timetable_slot_id),
                    "day": sub.timetable_slot.day,
                    "start_time": str(sub.timetable_slot.start_time)[:5],
                    "end_time": str(sub.timetable_slot.end_time)[:5],
                    "subject": sub.timetable_slot.subject.name if sub.timetable_slot.subject else None,
                    "division": sub.timetable_slot.division.name if sub.timetable_slot.division else None,
                }

            substitutions_data.append(
                {
                    "id": str(sub.id),
                    "timetable_slot": slot_info,
                    "absent_teacher": {
                        "id": str(sub.absent_teacher_id),
                        "name": sub.absent_teacher.user.get_full_name() or sub.absent_teacher.user.username,
                        "employee_code": sub.absent_teacher.employee_code,
                    } if sub.absent_teacher and sub.absent_teacher.user else None,
                    "substitute_teacher": {
                        "id": str(sub.substitute_teacher_id),
                        "name": sub.substitute_teacher.user.get_full_name() or sub.substitute_teacher.user.username,
                        "employee_code": sub.substitute_teacher.employee_code,
                    } if sub.substitute_teacher and sub.substitute_teacher.user else None,
                    "reason": sub.reason,
                    "status": sub.status,
                    "assigned_by": {
                        "id": str(sub.assigned_by_id),
                        "name": sub.assigned_by.get_full_name() or sub.assigned_by.username,
                    } if sub.assigned_by else None,
                    "assigned_at": sub.assigned_at.isoformat() if sub.assigned_at else None,
                }
            )

        # 5. UNRESOLVED CONFLICTS
        conflicts_qs = (
            TimetableConflict.objects.filter(
                status=TimetableConflict.Status.DETECTED,
            )
            .select_related("timetable", "slot", "conflicting_slot")
            .order_by("-created_at")[:15]
        )
        conflicts_data = [
            {
                "id": str(c.id),
                "timetable_id": str(c.timetable_id),
                "conflict_type": c.conflict_type,
                "severity": c.severity,
                "description": c.description,
                "status": c.status,
                "slot_id": str(c.slot_id) if c.slot_id else None,
                "conflicting_slot_id": str(c.conflicting_slot_id) if c.conflicting_slot_id else None,
                "created_at": c.created_at.isoformat(),
            }
            for c in conflicts_qs
        ]

        # 6. RECENT TIMETABLE CHANGES
        recent_changes_qs = (
            TimetableChangeLog.objects.select_related(
                "timetable",
                "timetable_slot",
                "changed_by",
            )
            .order_by("-created_at")[:15]
        )
        recent_changes_data = [
            {
                "id": str(log.id),
                "action": log.action,
                "timetable": {
                    "id": str(log.timetable_id),
                    "version": log.timetable.version,
                    "academic_year": log.timetable.academic_year,
                    "status": log.timetable.status,
                } if log.timetable else None,
                "slot_id": str(log.timetable_slot_id) if log.timetable_slot_id else None,
                "changed_by": {
                    "id": str(log.changed_by_id),
                    "name": log.changed_by.get_full_name() or log.changed_by.username,
                } if log.changed_by else None,
                "reason": log.reason,
                "old_data": log.old_data,
                "new_data": log.new_data,
                "created_at": log.created_at.isoformat(),
            }
            for log in recent_changes_qs
        ]

        # 7. QUICK ACTION METRICS
        quick_actions_data = {
            "can_generate": True,
            "unresolved_conflicts": unresolved_conflicts_count,
            "pending_leaves": pending_leaves_count,
            "pending_substitutions": pending_substitutions_count,
            "recent_changes_count": len(recent_changes_data),
        }

        return {
            "summary": summary_data,
            "today": today_data,
            "teacher_leaves": teacher_leaves_data,
            "substitutions": substitutions_data,
            "conflicts": conflicts_data,
            "recent_changes": recent_changes_data,
            "quick_actions": quick_actions_data,
        }
