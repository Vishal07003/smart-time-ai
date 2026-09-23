"""
Timetable History & Change Tracking Service for SMART-TIME AI (Phase 11).

Provides an immutable audit logging mechanism for timetable lifecycle events,
slot reschedules, and substitute teacher assignments.
"""

from typing import Any, Dict, Optional
import uuid

from django.core.exceptions import ValidationError
from django.db import models

from academics.models import (
    SlotReschedule,
    TeacherSubstitution,
    Timetable,
    TimetableChangeLog,
    TimetableSlot,
)
from accounts.models import User


class TimetableHistoryService:
    """
    Central service for recording and retrieving immutable timetable change logs.
    """

    @classmethod
    def slot_to_dict(cls, slot: Optional[TimetableSlot]) -> Optional[Dict[str, Any]]:
        """
        Converts a TimetableSlot instance into a JSON-serializable snapshot dict.
        Contains only scheduling/academic fields; no sensitive or authentication data.
        """
        if not slot:
            return None

        teacher_name = None
        if slot.teacher and slot.teacher.user:
            teacher_name = slot.teacher.user.get_full_name() or slot.teacher.user.username

        classroom_name = None
        if slot.classroom:
            classroom_name = f"{slot.classroom.building}-{slot.classroom.room_number}"

        laboratory_name = None
        if slot.laboratory:
            laboratory_name = f"{slot.laboratory.building}-{slot.laboratory.lab_number}"

        return {
            "slot_id": str(slot.id),
            "teacher_id": str(slot.teacher_id) if slot.teacher_id else None,
            "teacher": teacher_name,
            "subject_id": str(slot.subject_id) if slot.subject_id else None,
            "subject": slot.subject.name if slot.subject else None,
            "division_id": str(slot.division_id) if slot.division_id else None,
            "division": slot.division.name if slot.division else None,
            "batch_id": str(slot.batch_id) if slot.batch_id else None,
            "batch": slot.batch.name if slot.batch else None,
            "day": slot.day,
            "start_time": str(slot.start_time)[:5] if slot.start_time else None,
            "end_time": str(slot.end_time)[:5] if slot.end_time else None,
            "classroom_id": str(slot.classroom_id) if slot.classroom_id else None,
            "classroom": classroom_name,
            "laboratory_id": str(slot.laboratory_id) if slot.laboratory_id else None,
            "laboratory": laboratory_name,
            "session_type": slot.session_type,
            "status": slot.status,
        }

    @classmethod
    def timetable_to_dict(cls, timetable: Optional[Timetable]) -> Optional[Dict[str, Any]]:
        """
        Converts a Timetable instance into a JSON-serializable summary dict.
        """
        if not timetable:
            return None

        return {
            "timetable_id": str(timetable.id),
            "semester_id": str(timetable.semester_id) if timetable.semester_id else None,
            "semester": str(timetable.semester) if timetable.semester else None,
            "academic_year": timetable.academic_year,
            "version": timetable.version,
            "status": timetable.status,
        }

    @classmethod
    def log_event(
        cls,
        timetable: Timetable,
        action: str,
        changed_by: Optional[User] = None,
        timetable_slot: Optional[TimetableSlot] = None,
        reason: Optional[str] = None,
        old_data: Optional[Dict[str, Any]] = None,
        new_data: Optional[Dict[str, Any]] = None,
    ) -> TimetableChangeLog:
        """
        Records an immutable change log entry with de-duplication safeguard.
        """
        # De-duplication check: if identical action with identical old/new data exists as latest log
        latest_log = (
            TimetableChangeLog.objects.filter(
                timetable=timetable,
                action=action,
            )
            .order_by("-created_at")
            .first()
        )
        if latest_log:
            same_slot = (latest_log.timetable_slot_id == (timetable_slot.id if timetable_slot else None))
            same_old = (latest_log.old_data == old_data)
            same_new = (latest_log.new_data == new_data)
            if same_slot and same_old and same_new:
                return latest_log

        log_entry = TimetableChangeLog(
            timetable=timetable,
            timetable_slot=timetable_slot,
            action=action,
            changed_by=changed_by,
            reason=reason or "",
            old_data=old_data,
            new_data=new_data,
        )
        log_entry.save()
        return log_entry

    @classmethod
    def log_timetable_created(
        cls,
        timetable: Timetable,
        changed_by: Optional[User] = None,
        reason: Optional[str] = "Timetable created",
    ) -> TimetableChangeLog:
        return cls.log_event(
            timetable=timetable,
            action=TimetableChangeLog.Action.TIMETABLE_CREATED,
            changed_by=changed_by,
            reason=reason,
            new_data=cls.timetable_to_dict(timetable),
        )

    @classmethod
    def log_timetable_generated(
        cls,
        timetable: Timetable,
        changed_by: Optional[User] = None,
        reason: Optional[str] = "Timetable generated by solver",
    ) -> TimetableChangeLog:
        return cls.log_event(
            timetable=timetable,
            action=TimetableChangeLog.Action.TIMETABLE_GENERATED,
            changed_by=changed_by,
            reason=reason,
            new_data=cls.timetable_to_dict(timetable),
        )

    @classmethod
    def log_timetable_published(
        cls,
        timetable: Timetable,
        changed_by: Optional[User] = None,
        reason: Optional[str] = "Timetable published",
        old_status: str = "GENERATED",
    ) -> TimetableChangeLog:
        old_snap = cls.timetable_to_dict(timetable)
        if old_snap:
            old_snap["status"] = old_status
        new_snap = cls.timetable_to_dict(timetable)
        return cls.log_event(
            timetable=timetable,
            action=TimetableChangeLog.Action.TIMETABLE_PUBLISHED,
            changed_by=changed_by,
            reason=reason,
            old_data=old_snap,
            new_data=new_snap,
        )

    @classmethod
    def log_timetable_archived(
        cls,
        timetable: Timetable,
        changed_by: Optional[User] = None,
        reason: Optional[str] = "Timetable archived",
        old_status: str = "PUBLISHED",
    ) -> TimetableChangeLog:
        old_snap = cls.timetable_to_dict(timetable)
        if old_snap:
            old_snap["status"] = old_status
        new_snap = cls.timetable_to_dict(timetable)
        return cls.log_event(
            timetable=timetable,
            action=TimetableChangeLog.Action.TIMETABLE_ARCHIVED,
            changed_by=changed_by,
            reason=reason,
            old_data=old_snap,
            new_data=new_snap,
        )

    @classmethod
    def log_slot_rescheduled(
        cls,
        old_slot: TimetableSlot,
        new_slot: TimetableSlot,
        changed_by: Optional[User] = None,
        reason: Optional[str] = None,
        new_timetable: Optional[Timetable] = None,
    ) -> TimetableChangeLog:
        target_timetable = new_timetable or new_slot.timetable or old_slot.timetable
        old_data = cls.slot_to_dict(old_slot)
        new_data = cls.slot_to_dict(new_slot)
        return cls.log_event(
            timetable=target_timetable,
            timetable_slot=new_slot,
            action=TimetableChangeLog.Action.SLOT_RESCHEDULED,
            changed_by=changed_by,
            reason=reason or "Slot rescheduled",
            old_data=old_data,
            new_data=new_data,
        )

    @classmethod
    def log_substitute_assigned(
        cls,
        substitution: TeacherSubstitution,
        changed_by: Optional[User] = None,
        reason: Optional[str] = None,
    ) -> TimetableChangeLog:
        slot = substitution.timetable_slot
        old_data = cls.slot_to_dict(slot)
        new_data = cls.slot_to_dict(slot)
        if new_data and substitution.substitute_teacher:
            new_data["teacher_id"] = str(substitution.substitute_teacher.id)
            sub_user = substitution.substitute_teacher.user
            new_data["teacher"] = sub_user.get_full_name() or sub_user.username

        return cls.log_event(
            timetable=slot.timetable,
            timetable_slot=slot,
            action=TimetableChangeLog.Action.SUBSTITUTE_ASSIGNED,
            changed_by=changed_by or substitution.assigned_by,
            reason=reason or substitution.reason or "Substitute assigned",
            old_data=old_data,
            new_data=new_data,
        )

    @classmethod
    def log_substitute_accepted(
        cls,
        substitution: TeacherSubstitution,
        user: Optional[User] = None,
    ) -> TimetableChangeLog:
        slot = substitution.timetable_slot
        return cls.log_event(
            timetable=slot.timetable,
            timetable_slot=slot,
            action=TimetableChangeLog.Action.SUBSTITUTE_ACCEPTED,
            changed_by=user or (substitution.substitute_teacher.user if substitution.substitute_teacher else None),
            reason="Substitute assignment accepted",
            old_data={"status": "PENDING"},
            new_data={
                "status": "CONFIRMED",
                "substitute_teacher_id": str(substitution.substitute_teacher_id),
                "substitute_teacher": (
                    substitution.substitute_teacher.user.get_full_name()
                    or substitution.substitute_teacher.user.username
                ) if substitution.substitute_teacher and substitution.substitute_teacher.user else None,
            },
        )

    @classmethod
    def log_substitute_declined(
        cls,
        substitution: TeacherSubstitution,
        user: Optional[User] = None,
        reason: Optional[str] = None,
    ) -> TimetableChangeLog:
        slot = substitution.timetable_slot
        return cls.log_event(
            timetable=slot.timetable,
            timetable_slot=slot,
            action=TimetableChangeLog.Action.SUBSTITUTE_DECLINED,
            changed_by=user or (substitution.substitute_teacher.user if substitution.substitute_teacher else None),
            reason=reason or "Substitute assignment declined",
            old_data={"status": "PENDING"},
            new_data={
                "status": "DECLINED",
                "substitute_teacher_id": str(substitution.substitute_teacher_id),
                "substitute_teacher": (
                    substitution.substitute_teacher.user.get_full_name()
                    or substitution.substitute_teacher.user.username
                ) if substitution.substitute_teacher and substitution.substitute_teacher.user else None,
            },
        )
