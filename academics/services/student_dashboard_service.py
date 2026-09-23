"""
Student Dashboard Service for SMART-TIME AI (Phase 14).

Aggregates operational metrics, today's schedule classification, weekly timetable,
rescheduled classes, personal notifications, and relevant change history
strictly for the authenticated Student based on their assigned Division and Batch.
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
    PracticalBatch,
    Semester,
    SlotReschedule,
    Subject,
    Timetable,
    TimetableChangeLog,
    TimetableSlot,
)
from accounts.models import StudentProfile, User


class StudentDashboardService:
    """
    Business service to aggregate and construct the Student Dashboard dataset.
    Ensures strict tenant/user isolation: only data matching the student's assigned
    division and batch is returned.
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
        Formats a TimetableSlot instance into a clean, student-facing structured dictionary.
        Does not expose private teacher fields (e.g. phone, email).
        """
        subject_dict = None
        if slot.subject:
            subject_dict = {
                "id": str(slot.subject.id),
                "name": slot.subject.name,
                "code": slot.subject.code,
            }

        teacher_name = None
        if slot.teacher and slot.teacher.user:
            teacher_name = slot.teacher.user.get_full_name() or slot.teacher.user.username

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
            "teacher_name": teacher_name,
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
        Generates the comprehensive student dashboard payload for the authenticated student.
        Allows passing reference_datetime for deterministic test evaluation.
        """
        if not hasattr(user, "student_profile") or not user.student_profile:
            raise ValidationError({"detail": "Student profile does not exist for this user."})

        student = user.student_profile
        division = student.division
        batch = student.batch

        now = reference_datetime or timezone.localtime(timezone.now())
        current_day_name = now.strftime("%A").upper()
        current_time = now.time()

        # Batch filter condition
        if batch:
            batch_filter = Q(batch=batch) | Q(batch__isnull=True)
        else:
            batch_filter = Q(batch__isnull=True)

        # 1. TODAY'S CLASSES FOR AUTHENTICATED STUDENT'S DIVISION & BATCH
        today_slots_qs = (
            TimetableSlot.objects.filter(
                timetable__status=Timetable.Status.PUBLISHED,
                division=division,
                day=current_day_name,
            )
            .filter(batch_filter)
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
            .order_by("start_time")
        )

        all_today_classes: List[Dict[str, Any]] = []
        current_classes: List[Dict[str, Any]] = []
        upcoming_classes: List[Dict[str, Any]] = []
        completed_classes: List[Dict[str, Any]] = []
        today_rescheduled_count = 0

        for slot in today_slots_qs:
            slot_repr = cls.format_slot(slot)
            all_today_classes.append(slot_repr)

            if slot.status == TimetableSlot.Status.RESCHEDULED:
                today_rescheduled_count += 1

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

        # 2. WEEKLY TIMETABLE FOR AUTHENTICATED STUDENT
        weekly_slots_qs = (
            TimetableSlot.objects.filter(
                timetable__status=Timetable.Status.PUBLISHED,
                division=division,
            )
            .filter(batch_filter)
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
        )
        day_index_map = {d: i for i, d in enumerate(cls.DAYS_ORDER)}
        weekly_slots_list = [cls.format_slot(s) for s in weekly_slots_qs]
        weekly_slots_list.sort(
            key=lambda s: (day_index_map.get(s["day"], 99), s["start_time"])
        )

        # 3. RESCHEDULED CLASSES RELEVANT TO STUDENT
        reschedules_qs = (
            SlotReschedule.objects.filter(
                Q(original_slot__division=division)
                | Q(new_timetable__semester=division.semester)
            )
            .select_related(
                "original_slot",
                "original_slot__subject",
                "original_slot__division",
                "original_slot__batch",
                "original_slot__classroom",
                "original_slot__laboratory",
                "original_slot__teacher",
                "original_slot__teacher__user",
                "new_teacher",
                "new_teacher__user",
                "new_classroom",
                "new_laboratory",
                "new_timetable",
            )
            .order_by("-created_at")[:15]
        )
        rescheduled_classes_data = []
        for r in reschedules_qs:
            # Check batch compatibility if batch is specified on original slot
            if r.original_slot and r.original_slot.batch and batch and r.original_slot.batch != batch:
                continue

            orig_slot_data = cls.format_slot(r.original_slot) if r.original_slot else None
            new_teacher_name = None
            if r.new_teacher and r.new_teacher.user:
                new_teacher_name = r.new_teacher.user.get_full_name() or r.new_teacher.user.username

            new_room = None
            if r.new_classroom:
                new_room = f"{r.new_classroom.building}-{r.new_classroom.room_number}"
            elif r.new_laboratory:
                new_room = f"{r.new_laboratory.building}-{r.new_laboratory.lab_number}"

            rescheduled_classes_data.append(
                {
                    "id": str(r.id),
                    "status": r.status,
                    "original_slot": orig_slot_data,
                    "new_day": r.new_day,
                    "new_start_time": str(r.new_start_time)[:5],
                    "new_end_time": str(r.new_end_time)[:5],
                    "new_teacher_name": new_teacher_name,
                    "new_room": new_room,
                    "reason": r.reason,
                    "created_at": r.created_at.isoformat(),
                }
            )

        # 4. NOTIFICATIONS (Strictly for authenticated user)
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

        # 5. RECENT TIMETABLE CHANGES (Relevant to student's division and semester)
        div_id_str = str(division.id)
        recent_changes_qs = (
            TimetableChangeLog.objects.filter(
                Q(timetable_slot__division=division)
                | Q(timetable__semester=division.semester)
                | Q(new_data__division_id=div_id_str)
                | Q(old_data__division_id=div_id_str)
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

        # 6. SUMMARY
        summary_data = {
            "today_classes_count": len(all_today_classes),
            "current_class": current_classes[0] if current_classes else None,
            "upcoming_classes_count": len(upcoming_classes),
            "completed_classes_count": len(completed_classes),
            "unread_notifications": unread_notifications_count,
            "today_rescheduled_classes_count": today_rescheduled_count or len(rescheduled_classes_data),
        }

        return {
            "summary": summary_data,
            "today": today_data,
            "weekly_timetable": weekly_slots_list,
            "rescheduled_classes": rescheduled_classes_data,
            "notifications": notifications_data,
            "recent_changes": recent_changes_data,
        }
