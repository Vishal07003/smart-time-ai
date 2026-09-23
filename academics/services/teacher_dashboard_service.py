"""
Teacher Dashboard Service for SMART-TIME AI (Phase 13).

Aggregates operational metrics, today's schedule classification, weekly timetable,
leave requests, substitute assignments, notifications, and relevant change history
strictly for the authenticated Teacher.
"""

from datetime import datetime, time
from typing import Any, Dict, List, Optional
import uuid

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from academics.models import (
    Classroom,
    Laboratory,
    Notification,
    Semester,
    Subject,
    TeacherLeave,
    TeacherSubstitution,
    Timetable,
    TimetableChangeLog,
    TimetableSlot,
)
from accounts.models import TeacherProfile, User


class TeacherDashboardService:
    """
    Business service to aggregate and construct the Teacher Dashboard dataset.
    Ensures strict tenant/user isolation: only data belonging or assigned to the
    authenticated teacher is returned.
    """

    DAYS_ORDER = [
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
    ]

    @classmethod
    def format_slot(cls, slot: TimetableSlot) -> Dict[str, Any]:
        """
        Formats a TimetableSlot instance into a structured dictionary.
        """
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

        timetable_dict = None
        if slot.timetable:
            timetable_dict = {
                "id": str(slot.timetable.id),
                "academic_year": slot.timetable.academic_year,
                "version": slot.timetable.version,
                "status": slot.timetable.status,
            }

        return {
            "id": str(slot.id),
            "day": slot.day,
            "start_time": str(slot.start_time)[:5],
            "end_time": str(slot.end_time)[:5],
            "session_type": slot.session_type,
            "status": slot.status,
            "subject": subject_dict,
            "division": division_dict,
            "batch": batch_dict,
            "classroom": classroom_dict,
            "laboratory": laboratory_dict,
            "timetable": timetable_dict,
        }

    @classmethod
    def get_dashboard_data(
        cls,
        user: User,
        reference_datetime: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Generates the comprehensive teacher dashboard payload for the authenticated teacher.
        Allows passing reference_datetime for deterministic test evaluation.
        """
        if not hasattr(user, "teacher_profile") or not user.teacher_profile:
            raise ValidationError({"detail": "Teacher profile does not exist for this user."})

        teacher = user.teacher_profile
        now = reference_datetime or timezone.localtime(timezone.now())
        current_day_name = now.strftime("%A").upper()
        current_time = now.time()

        # 1. TODAY'S CLASSES FOR AUTHENTICATED TEACHER
        today_slots_qs = (
            TimetableSlot.objects.filter(
                timetable__status=Timetable.Status.PUBLISHED,
                teacher=teacher,
                day=current_day_name,
            )
            .exclude(status=TimetableSlot.Status.CANCELLED)
            .select_related(
                "timetable",
                "timetable__semester",
                "subject",
                "division",
                "batch",
                "classroom",
                "laboratory",
            )
            .order_by("start_time")
        )

        all_today_classes: List[Dict[str, Any]] = []
        current_classes: List[Dict[str, Any]] = []
        upcoming_classes: List[Dict[str, Any]] = []
        completed_classes: List[Dict[str, Any]] = []

        for slot in today_slots_qs:
            slot_repr = cls.format_slot(slot)
            all_today_classes.append(slot_repr)

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

        # 2. WEEKLY TIMETABLE FOR AUTHENTICATED TEACHER
        weekly_slots_qs = (
            TimetableSlot.objects.filter(
                timetable__status=Timetable.Status.PUBLISHED,
                teacher=teacher,
            )
            .exclude(status=TimetableSlot.Status.CANCELLED)
            .select_related(
                "timetable",
                "timetable__semester",
                "subject",
                "division",
                "batch",
                "classroom",
                "laboratory",
            )
        )
        day_index_map = {d: i for i, d in enumerate(cls.DAYS_ORDER)}
        weekly_slots_list = [cls.format_slot(s) for s in weekly_slots_qs]
        weekly_slots_list.sort(
            key=lambda s: (day_index_map.get(s["day"], 99), s["start_time"])
        )

        # 3. MY LEAVE REQUESTS
        my_leaves_qs = (
            TeacherLeave.objects.filter(teacher=teacher)
            .order_by("-created_at")[:15]
        )
        leave_requests_data = [
            {
                "id": str(l.id),
                "start_date": str(l.start_date),
                "end_date": str(l.end_date),
                "reason": l.reason,
                "status": l.status,
                "created_at": l.created_at.isoformat(),
            }
            for l in my_leaves_qs
        ]
        pending_leave_requests_count = TeacherLeave.objects.filter(
            teacher=teacher,
            status=TeacherLeave.Status.PENDING,
        ).count()

        # 4. SUBSTITUTE CLASSES (Where teacher is assigned substitute or absent)
        substitutions_qs = (
            TeacherSubstitution.objects.filter(
                Q(substitute_teacher=teacher) | Q(absent_teacher=teacher),
            )
            .select_related(
                "timetable_slot",
                "timetable_slot__subject",
                "timetable_slot__division",
                "timetable_slot__batch",
                "timetable_slot__classroom",
                "timetable_slot__laboratory",
                "absent_teacher",
                "absent_teacher__user",
                "substitute_teacher",
                "substitute_teacher__user",
                "assigned_by",
            )
            .order_by("-assigned_at")[:20]
        )
        substitute_classes_data = []
        for sub in substitutions_qs:
            slot = sub.timetable_slot
            slot_info = None
            if slot:
                room_str = None
                if slot.classroom:
                    room_str = f"{slot.classroom.building}-{slot.classroom.room_number}"
                elif slot.laboratory:
                    room_str = f"{slot.laboratory.building}-{slot.laboratory.lab_number}"

                slot_info = {
                    "id": str(slot.id),
                    "day": slot.day,
                    "start_time": str(slot.start_time)[:5],
                    "end_time": str(slot.end_time)[:5],
                    "subject": slot.subject.name if slot.subject else None,
                    "division": slot.division.name if slot.division else None,
                    "batch": slot.batch.name if slot.batch else None,
                    "room": room_str,
                }

            substitute_classes_data.append(
                {
                    "id": str(sub.id),
                    "role": "SUBSTITUTE" if sub.substitute_teacher_id == teacher.id else "ABSENT",
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
                    "assigned_at": sub.assigned_at.isoformat() if sub.assigned_at else None,
                }
            )
        pending_substitute_classes_count = TeacherSubstitution.objects.filter(
            Q(substitute_teacher=teacher) | Q(absent_teacher=teacher),
            status=TeacherSubstitution.Status.PENDING,
        ).count()

        # 5. NOTIFICATIONS (Strictly for authenticated user)
        notifications_qs = (
            Notification.objects.filter(recipient=user)
            .order_by("-created_at")[:15]
        )
        unread_notifications_count = Notification.objects.filter(
            recipient=user,
            is_read=False,
        ).count()
        notifications_items = [
            {
                "id": str(n.id),
                "title": n.title,
                "message": n.message,
                "notification_type": n.notification_type,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat(),
                "read_at": n.read_at.isoformat() if n.read_at else None,
            }
            for n in notifications_qs
        ]
        notifications_data = {
            "unread_count": unread_notifications_count,
            "items": notifications_items,
        }

        # 6. RECENT SCHEDULE CHANGES (Relevant to this teacher)
        teacher_id_str = str(teacher.id)
        recent_changes_qs = (
            TimetableChangeLog.objects.filter(
                Q(timetable_slot__teacher=teacher)
                | Q(changed_by=user)
                | Q(new_data__teacher_id=teacher_id_str)
                | Q(old_data__teacher_id=teacher_id_str)
            )
            .select_related("timetable", "timetable_slot", "changed_by")
            .order_by("-created_at")[:15]
        )
        recent_changes_data = [
            {
                "id": str(log.id),
                "action": log.action,
                "timetable_id": str(log.timetable_id),
                "slot_id": str(log.timetable_slot_id) if log.timetable_slot_id else None,
                "subject": (
                    log.new_data.get("subject")
                    or (log.old_data.get("subject") if log.old_data else None)
                ) if log.new_data else (log.old_data.get("subject") if log.old_data else None),
                "reason": log.reason,
                "old_data": log.old_data,
                "new_data": log.new_data,
                "created_at": log.created_at.isoformat(),
            }
            for log in recent_changes_qs
        ]

        # 7. SUMMARY
        summary_data = {
            "today_classes_count": len(all_today_classes),
            "current_class": current_classes[0] if current_classes else None,
            "upcoming_classes_count": len(upcoming_classes),
            "completed_classes_count": len(completed_classes),
            "pending_leave_requests": pending_leave_requests_count,
            "pending_substitute_classes": pending_substitute_classes_count,
            "unread_notifications": unread_notifications_count,
        }

        return {
            "summary": summary_data,
            "today": today_data,
            "weekly_timetable": weekly_slots_list,
            "leave_requests": leave_requests_data,
            "substitute_classes": substitute_classes_data,
            "notifications": notifications_data,
            "recent_changes": recent_changes_data,
        }
