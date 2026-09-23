"""
Teacher Replacement & Substitute Suggestion Service for SMART-TIME AI (Phase 10A).

Identifies timetable slots affected by approved TeacherLeaves and finds eligible,
conflict-free substitute teacher candidates with server-side validation.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone

from academics.models import (
    Notification,
    TeacherAvailability,
    TeacherLeave,
    TeacherSubject,
    TeacherSubstitution,
    Timetable,
    TimetableSlot,
)
from accounts.models import TeacherProfile, User


class SubstituteSuggestionService:
    """
    Service to find timetable slots affected by teacher leaves and suggest qualified,
    available substitute candidates without clashes.
    """

    @classmethod
    def get_days_for_date_range(cls, start_date: datetime.date, end_date: datetime.date) -> Set[str]:
        """Returns set of uppercase weekday names (e.g. {'MONDAY', 'TUESDAY'}) for a date range."""
        days = set()
        delta = (end_date - start_date).days
        if delta >= 7:
            return {
                "MONDAY",
                "TUESDAY",
                "WEDNESDAY",
                "THURSDAY",
                "FRIDAY",
                "SATURDAY",
                "SUNDAY",
            }
        curr = start_date
        while curr <= end_date:
            days.add(curr.strftime("%A").upper())
            curr += timedelta(days=1)
        return days

    @classmethod
    def get_suggestions_for_leave(cls, leave: TeacherLeave) -> Dict[str, Any]:
        """
        Extracts affected published timetable slots and calculates candidate substitutes.

        Args:
            leave: TeacherLeave instance (must be APPROVED).

        Returns:
            Structured dictionary with teacher info and affected slots with candidates.
        """
        if leave.status != TeacherLeave.Status.APPROVED:
            raise ValidationError("Teacher leave must be in APPROVED status to suggest substitutes.")

        covered_days = cls.get_days_for_date_range(leave.start_date, leave.end_date)

        # 1. Find affected published slots for the absent teacher
        affected_slots_qs = (
            TimetableSlot.objects.filter(
                timetable__status=Timetable.Status.PUBLISHED,
                teacher=leave.teacher,
                day__in=covered_days,
            )
            .select_related(
                "subject",
                "division",
                "batch",
                "classroom",
                "laboratory",
                "timetable",
            )
            .order_by("day", "start_time")
        )

        affected_slots_data = []

        for slot in affected_slots_qs:
            candidates = cls.find_candidates_for_slot(slot, leave)
            slot_data = {
                "slot_id": str(slot.id),
                "day": slot.day,
                "start_time": str(slot.start_time),
                "end_time": str(slot.end_time),
                "subject": {
                    "id": str(slot.subject.id),
                    "name": slot.subject.name,
                    "code": slot.subject.code,
                },
                "division": {
                    "id": str(slot.division.id),
                    "name": slot.division.name,
                },
                "batch": {
                    "id": str(slot.batch.id),
                    "name": slot.batch.name,
                }
                if slot.batch
                else None,
                "classroom": {
                    "id": str(slot.classroom.id),
                    "room_number": slot.classroom.room_number,
                    "building": slot.classroom.building,
                }
                if slot.classroom
                else None,
                "laboratory": {
                    "id": str(slot.laboratory.id),
                    "lab_number": slot.laboratory.lab_number,
                    "name": slot.laboratory.name,
                }
                if slot.laboratory
                else None,
                "candidates": candidates,
            }
            affected_slots_data.append(slot_data)

        teacher_name = (
            leave.teacher.user.get_full_name() or leave.teacher.user.username
        )

        return {
            "teacher_leave": str(leave.id),
            "teacher": {
                "id": str(leave.teacher.id),
                "name": teacher_name,
                "employee_code": leave.teacher.employee_code,
            },
            "affected_slots": affected_slots_data,
        }

    @classmethod
    def find_candidates_for_slot(
        cls,
        slot: TimetableSlot,
        leave: Optional[TeacherLeave] = None,
    ) -> List[Dict[str, Any]]:
        """
        Finds all active, qualified, available substitute teacher candidates without clashes for a given slot.
        """
        # 1. Qualified teachers for the subject
        qualified_ts = TeacherSubject.objects.filter(
            subject=slot.subject
        ).select_related("teacher", "teacher__user")

        candidates: List[Dict[str, Any]] = []
        seen_teacher_ids: Set[str] = set()

        for ts in qualified_ts:
            teacher = ts.teacher
            teacher_id_str = str(teacher.id)

            if teacher_id_str in seen_teacher_ids:
                continue

            # Check 1: Active teacher
            if teacher.status != TeacherProfile.Status.ACTIVE or not teacher.user.is_active:
                continue

            # Check 2: Not the absent teacher
            if teacher.id == slot.teacher_id:
                continue

            # Check 3: Availability check on slot day/time
            unavail_exists = TeacherAvailability.objects.filter(
                teacher=teacher,
                day=slot.day,
                is_available=False,
                start_time__lt=slot.end_time,
                end_time__gt=slot.start_time,
            ).exists()
            if unavail_exists:
                continue

            # Check 4: Approved leave on that date/range if leave is provided
            if leave:
                leave_conflict = TeacherLeave.objects.filter(
                    teacher=teacher,
                    status=TeacherLeave.Status.APPROVED,
                    start_date__lte=leave.end_date,
                    end_date__gte=leave.start_date,
                ).exists()
                if leave_conflict:
                    continue

            # Check 5: Published timetable slot clash at the same day & time
            slot_clash = (
                TimetableSlot.objects.filter(
                    timetable__status=Timetable.Status.PUBLISHED,
                    teacher=teacher,
                    day=slot.day,
                    start_time__lt=slot.end_time,
                    end_time__gt=slot.start_time,
                )
                .exclude(id=slot.id)
                .exists()
            )
            if slot_clash:
                continue

            # Check 6: Active confirmed substitution clash at the same day & time
            sub_clash = (
                TeacherSubstitution.objects.filter(
                    status=TeacherSubstitution.Status.CONFIRMED,
                    substitute_teacher=teacher,
                    timetable_slot__day=slot.day,
                    timetable_slot__start_time__lt=slot.end_time,
                    timetable_slot__end_time__gt=slot.start_time,
                )
                .exclude(timetable_slot=slot)
                .exists()
            )
            if sub_clash:
                continue

            seen_teacher_ids.add(teacher_id_str)
            candidates.append(
                {
                    "teacher_id": teacher_id_str,
                    "name": teacher.user.get_full_name() or teacher.user.username,
                    "employee_code": teacher.employee_code,
                    "qualification_match": True,
                    "available": True,
                    "has_clash": False,
                }
            )

        return candidates

    @classmethod
    def confirm_substitution(
        cls,
        slot_id: Any,
        substitute_teacher_id: Any,
        reason: str = "",
        assigned_by: Optional[User] = None,
        teacher_leave_id: Optional[Any] = None,
    ) -> TeacherSubstitution:
        """
        Validates eligibility conditions server-side and creates a TeacherSubstitution record.
        Does NOT modify the original TimetableSlot teacher.
        """
        # 1. Fetch TimetableSlot
        try:
            slot = TimetableSlot.objects.select_related(
                "timetable", "teacher", "teacher__user", "subject", "division"
            ).get(id=slot_id)
        except TimetableSlot.DoesNotExist:
            raise ValidationError({"timetable_slot": "Timetable slot does not exist."})

        if slot.timetable.status != Timetable.Status.PUBLISHED:
            raise ValidationError(
                {"timetable_slot": "Substitutions can only be assigned to PUBLISHED timetable slots."}
            )

        # 2. Fetch Substitute Teacher
        try:
            substitute = TeacherProfile.objects.select_related("user").get(id=substitute_teacher_id)
        except TeacherProfile.DoesNotExist:
            raise ValidationError({"substitute_teacher": "Substitute teacher does not exist."})

        if substitute.status != TeacherProfile.Status.ACTIVE or not substitute.user.is_active:
            raise ValidationError({"substitute_teacher": "Substitute teacher is inactive."})

        # 3. Check Not Same Teacher
        if substitute.id == slot.teacher_id:
            raise ValidationError(
                {"substitute_teacher": "Substitute teacher cannot be the same as the absent teacher."}
            )

        # 4. Check Qualification
        is_qualified = TeacherSubject.objects.filter(
            teacher=substitute, subject=slot.subject
        ).exists()
        if not is_qualified:
            raise ValidationError(
                {"substitute_teacher": f"Teacher is not qualified to teach subject '{slot.subject.name}'."}
            )

        # 5. Check Availability
        is_unavailable = TeacherAvailability.objects.filter(
            teacher=substitute,
            day=slot.day,
            is_available=False,
            start_time__lt=slot.end_time,
            end_time__gt=slot.start_time,
        ).exists()
        if is_unavailable:
            raise ValidationError(
                {"substitute_teacher": "Teacher is marked unavailable during this time slot."}
            )

        # 6. Check Leave Conflict if leave is linked
        teacher_leave = None
        if teacher_leave_id:
            try:
                teacher_leave = TeacherLeave.objects.get(id=teacher_leave_id)
                sub_leave_conflict = TeacherLeave.objects.filter(
                    teacher=substitute,
                    status=TeacherLeave.Status.APPROVED,
                    start_date__lte=teacher_leave.end_date,
                    end_date__gte=teacher_leave.start_date,
                ).exists()
                if sub_leave_conflict:
                    raise ValidationError(
                        {"substitute_teacher": "Substitute teacher is on approved leave during this period."}
                    )
            except TeacherLeave.DoesNotExist:
                pass

        # 7. Check Timetable Slot Clash
        slot_clash = (
            TimetableSlot.objects.filter(
                timetable__status=Timetable.Status.PUBLISHED,
                teacher=substitute,
                day=slot.day,
                start_time__lt=slot.end_time,
                end_time__gt=slot.start_time,
            )
            .exclude(id=slot.id)
            .exists()
        )
        if slot_clash:
            raise ValidationError(
                {"substitute_teacher": "Substitute teacher already has a teaching class scheduled at this time."}
            )

        # 8. Check Existing Active Substitution Clash for the substitute
        existing_sub_clash = (
            TeacherSubstitution.objects.filter(
                status=TeacherSubstitution.Status.CONFIRMED,
                substitute_teacher=substitute,
                timetable_slot__day=slot.day,
                timetable_slot__start_time__lt=slot.end_time,
                timetable_slot__end_time__gt=slot.start_time,
            )
            .exclude(timetable_slot=slot)
            .exists()
        )
        if existing_sub_clash:
            raise ValidationError(
                {"substitute_teacher": "Substitute teacher is already assigned to another substitution at this time."}
            )

        # 9. Check Duplicate Active Substitution for the same slot
        duplicate_sub = TeacherSubstitution.objects.filter(
            timetable_slot=slot,
            status=TeacherSubstitution.Status.CONFIRMED,
        ).exists()
        if duplicate_sub:
            raise ValidationError(
                {"timetable_slot": "This slot already has an active confirmed substitution."}
            )

        # 10. Create TeacherSubstitution
        substitution = TeacherSubstitution.objects.create(
            timetable_slot=slot,
            absent_teacher=slot.teacher,
            substitute_teacher=substitute,
            teacher_leave=teacher_leave,
            reason=reason or "",
            status=TeacherSubstitution.Status.CONFIRMED,
            assigned_by=assigned_by,
        )

        # 11. Create Notification for substitute teacher
        start_str = slot.start_time.strftime("%H:%M") if hasattr(slot.start_time, "strftime") else str(slot.start_time)[:5]
        end_str = slot.end_time.strftime("%H:%M") if hasattr(slot.end_time, "strftime") else str(slot.end_time)[:5]
        div_str = f", Division {slot.division.name}" if slot.division else ""
        sub_name = slot.subject.name if slot.subject else "Class"
        day_str = slot.day.capitalize() if slot.day else ""

        Notification.objects.create(
            recipient=substitute.user,
            notification_type=Notification.NotificationType.SUBSTITUTION_ASSIGNED,
            title="Substitute Class Assigned",
            message=f"You have been assigned as substitute for {sub_name}, {day_str} {start_str}–{end_str}{div_str}.",
            related_substitution=substitution,
        )

        return substitution

    @classmethod
    def accept_substitution(cls, substitution_id: Any, user: User) -> TeacherSubstitution:
        """
        Allows the assigned substitute teacher to accept a substitution assignment.
        Revalidates eligibility before confirming and notifies the assigning staff member.
        """
        try:
            substitution = TeacherSubstitution.objects.select_related(
                "substitute_teacher",
                "substitute_teacher__user",
                "absent_teacher",
                "absent_teacher__user",
                "timetable_slot",
                "timetable_slot__timetable",
                "timetable_slot__subject",
                "timetable_slot__division",
                "assigned_by",
            ).get(id=substitution_id)
        except (TeacherSubstitution.DoesNotExist, ValueError):
            raise ValidationError({"substitution": "Substitution record does not exist."})

        # Check authorization: user must be the assigned substitute teacher
        if substitution.substitute_teacher.user != user:
            raise PermissionDenied("Only the assigned substitute teacher can accept this substitution assignment.")

        # Check state transitions
        if substitution.status == TeacherSubstitution.Status.CONFIRMED:
            raise ValidationError({"detail": "Substitution has already been accepted/confirmed."})

        if substitution.status in [TeacherSubstitution.Status.CANCELLED, TeacherSubstitution.Status.DECLINED]:
            raise ValidationError({"detail": "Cannot accept a cancelled or declined substitution."})

        slot = substitution.timetable_slot
        substitute = substitution.substitute_teacher

        # Revalidate eligibility server-side
        if slot.timetable.status != Timetable.Status.PUBLISHED:
            raise ValidationError({"timetable_slot": "Substitutions can only be assigned to PUBLISHED timetable slots."})

        if substitute.status != TeacherProfile.Status.ACTIVE or not substitute.user.is_active:
            raise ValidationError({"substitute_teacher": "Substitute teacher is inactive."})

        # Availability check
        is_unavail = TeacherAvailability.objects.filter(
            teacher=substitute,
            day=slot.day,
            is_available=False,
            start_time__lt=slot.end_time,
            end_time__gt=slot.start_time,
        ).exists()
        if is_unavail:
            raise ValidationError({"substitute_teacher": "Teacher is marked unavailable during this time slot."})

        # Timetable slot clash
        slot_clash = (
            TimetableSlot.objects.filter(
                timetable__status=Timetable.Status.PUBLISHED,
                teacher=substitute,
                day=slot.day,
                start_time__lt=slot.end_time,
                end_time__gt=slot.start_time,
            )
            .exclude(id=slot.id)
            .exists()
        )
        if slot_clash:
            raise ValidationError({"substitute_teacher": "Substitute teacher already has a teaching class scheduled at this time."})

        # Other active substitution clash
        other_sub_clash = (
            TeacherSubstitution.objects.filter(
                status=TeacherSubstitution.Status.CONFIRMED,
                substitute_teacher=substitute,
                timetable_slot__day=slot.day,
                timetable_slot__start_time__lt=slot.end_time,
                timetable_slot__end_time__gt=slot.start_time,
            )
            .exclude(id=substitution.id)
            .exists()
        )
        if other_sub_clash:
            raise ValidationError({"substitute_teacher": "Substitute teacher is already assigned to another active substitution at this time."})

        # Update status
        substitution.status = TeacherSubstitution.Status.CONFIRMED
        substitution.save(update_fields=["status", "updated_at"])

        # Notify assigning staff member
        if substitution.assigned_by and substitution.assigned_by != user:
            start_str = slot.start_time.strftime("%H:%M") if hasattr(slot.start_time, "strftime") else str(slot.start_time)[:5]
            end_str = slot.end_time.strftime("%H:%M") if hasattr(slot.end_time, "strftime") else str(slot.end_time)[:5]
            div_str = f", Division {slot.division.name}" if slot.division else ""
            sub_name = slot.subject.name if slot.subject else "Class"
            day_str = slot.day.capitalize() if slot.day else ""
            teacher_name = user.get_full_name() or user.username

            Notification.objects.create(
                recipient=substitution.assigned_by,
                notification_type=Notification.NotificationType.SUBSTITUTION_ACCEPTED,
                title="Substitute Assignment Accepted",
                message=f"{teacher_name} accepted substitute assignment for {sub_name}, {day_str} {start_str}–{end_str}{div_str}.",
                related_substitution=substitution,
            )

        return substitution

    @classmethod
    def decline_substitution(cls, substitution_id: Any, user: User) -> TeacherSubstitution:
        """
        Allows the assigned substitute teacher to decline a substitution assignment.
        Updates status to DECLINED and notifies the assigning staff member.
        """
        try:
            substitution = TeacherSubstitution.objects.select_related(
                "substitute_teacher",
                "substitute_teacher__user",
                "absent_teacher",
                "absent_teacher__user",
                "timetable_slot",
                "timetable_slot__timetable",
                "timetable_slot__subject",
                "timetable_slot__division",
                "assigned_by",
            ).get(id=substitution_id)
        except (TeacherSubstitution.DoesNotExist, ValueError):
            raise ValidationError({"substitution": "Substitution record does not exist."})

        # Check authorization: user must be the assigned substitute teacher
        if substitution.substitute_teacher.user != user:
            raise PermissionDenied("Only the assigned substitute teacher can decline this substitution assignment.")

        # Check state transitions
        if substitution.status in [TeacherSubstitution.Status.CANCELLED, TeacherSubstitution.Status.DECLINED]:
            raise ValidationError({"detail": "Substitution has already been declined/cancelled."})

        slot = substitution.timetable_slot
        substitute = substitution.substitute_teacher

        # Update status
        substitution.status = TeacherSubstitution.Status.DECLINED
        substitution.save(update_fields=["status", "updated_at"])

        # Notify assigning staff member
        if substitution.assigned_by and substitution.assigned_by != user:
            start_str = slot.start_time.strftime("%H:%M") if hasattr(slot.start_time, "strftime") else str(slot.start_time)[:5]
            end_str = slot.end_time.strftime("%H:%M") if hasattr(slot.end_time, "strftime") else str(slot.end_time)[:5]
            div_str = f", Division {slot.division.name}" if slot.division else ""
            sub_name = slot.subject.name if slot.subject else "Class"
            day_str = slot.day.capitalize() if slot.day else ""
            teacher_name = user.get_full_name() or user.username

            Notification.objects.create(
                recipient=substitution.assigned_by,
                notification_type=Notification.NotificationType.SUBSTITUTION_DECLINED,
                title="Substitute Assignment Declined",
                message=f"{teacher_name} declined substitute assignment for {sub_name}, {day_str} {start_str}–{end_str}{div_str}.",
                related_substitution=substitution,
            )

        return substitution

