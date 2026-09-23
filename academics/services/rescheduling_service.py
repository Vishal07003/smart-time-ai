"""
Rescheduling Suggestion Service for SMART-TIME AI (Phase 10C).

Generates valid, constraint-compliant alternative scheduling suggestions
(substitute teacher, alternative time, alternative room, and combinations)
for affected published TimetableSlots and supports safe confirmation workflows.
"""

from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Q

from academics.models import (
    Classroom,
    Laboratory,
    Semester,
    SlotReschedule,
    Subject,
    TeacherAvailability,
    TeacherLeave,
    TeacherSubject,
    TeacherSubstitution,
    Timetable,
    TimetableConflict,
    TimetableSlot,
)
from academics.services.conflict_detection import ConflictDetectionService
from academics.services.substitute_service import SubstituteSuggestionService
from accounts.models import TeacherProfile, User


class ReschedulingSuggestionService:
    """
    Service to generate ranked, deterministic rescheduling suggestions
    for published TimetableSlots affected by teacher absences or schedule changes.
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
    def get_time_slots_for_timetable(cls, timetable: Timetable, default_start: time, default_end: time) -> List[Tuple[time, time]]:
        """
        Retrieves unique time slot intervals existing in the timetable.
        Falls back to standard daily intervals if few exist.
        """
        existing_slots = (
            TimetableSlot.objects.filter(timetable=timetable)
            .values_list("start_time", "end_time")
            .distinct()
        )
        time_pairs = set(existing_slots)
        time_pairs.add((default_start, default_end))

        # Add common hourly lecture slots between 09:00 and 17:00
        standard_hours = [
            (time(9, 0), time(10, 0)),
            (time(10, 0), time(11, 0)),
            (time(11, 0), time(12, 0)),
            (time(12, 0), time(13, 0)),
            (time(13, 0), time(14, 0)),
            (time(14, 0), time(15, 0)),
            (time(15, 0), time(16, 0)),
            (time(16, 0), time(17, 0)),
        ]
        for pair in standard_hours:
            time_pairs.add(pair)

        # Sort chronologically by start time, then end time
        return sorted(list(time_pairs), key=lambda x: (x[0], x[1]))

    @classmethod
    def is_teacher_on_leave_on_day(cls, teacher: TeacherProfile, day: str) -> bool:
        """
        Checks whether the teacher has any approved leave spanning this weekday.
        """
        approved_leaves = TeacherLeave.objects.filter(
            teacher=teacher,
            status=TeacherLeave.Status.APPROVED,
        )
        for leave in approved_leaves:
            leave_days = SubstituteSuggestionService.get_days_for_date_range(
                leave.start_date, leave.end_date
            )
            if day.upper() in leave_days:
                return True
        return False

    @classmethod
    def is_teacher_available_at(
        cls,
        teacher: TeacherProfile,
        day: str,
        start_time: time,
        end_time: time,
        exclude_slot_id: Optional[Any] = None,
    ) -> bool:
        """
        Verifies teacher active status, qualification, absence of leave, availability,
        and absence of published timetable / active substitution clashes.
        """
        if teacher.status != TeacherProfile.Status.ACTIVE or not teacher.user.is_active:
            return False

        if cls.is_teacher_on_leave_on_day(teacher, day):
            return False

        # Teacher Availability check
        has_unavail = TeacherAvailability.objects.filter(
            teacher=teacher,
            day=day,
            is_available=False,
            start_time__lt=end_time,
            end_time__gt=start_time,
        ).exists()
        if has_unavail:
            return False

        # Published Timetable class clash
        slot_clash_qs = TimetableSlot.objects.filter(
            timetable__status=Timetable.Status.PUBLISHED,
            teacher=teacher,
            day=day,
            start_time__lt=end_time,
            end_time__gt=start_time,
        )
        if exclude_slot_id:
            slot_clash_qs = slot_clash_qs.exclude(id=exclude_slot_id)
        if slot_clash_qs.exists():
            return False

        # Active confirmed substitution clash
        sub_clash_qs = TeacherSubstitution.objects.filter(
            status=TeacherSubstitution.Status.CONFIRMED,
            substitute_teacher=teacher,
            timetable_slot__day=day,
            timetable_slot__start_time__lt=end_time,
            timetable_slot__end_time__gt=start_time,
        )
        if exclude_slot_id:
            sub_clash_qs = sub_clash_qs.exclude(timetable_slot_id=exclude_slot_id)
        if sub_clash_qs.exists():
            return False

        return True

    @classmethod
    def is_division_available_at(
        cls,
        division: Any,
        batch: Optional[Any],
        day: str,
        start_time: time,
        end_time: time,
        exclude_slot_id: Optional[Any] = None,
    ) -> bool:
        """
        Verifies that the division and batch have no timetable class clash at day/time.
        """
        div_clash_qs = TimetableSlot.objects.filter(
            timetable__status=Timetable.Status.PUBLISHED,
            division=division,
            day=day,
            start_time__lt=end_time,
            end_time__gt=start_time,
        )
        if exclude_slot_id:
            div_clash_qs = div_clash_qs.exclude(id=exclude_slot_id)

        if batch:
            # For batch-specific slot, only conflicts if same batch or whole-division lecture
            div_clash_qs = div_clash_qs.filter(Q(batch=batch) | Q(batch__isnull=True))

        return not div_clash_qs.exists()

    @classmethod
    def is_room_available_at(
        cls,
        classroom: Optional[Classroom],
        laboratory: Optional[Laboratory],
        day: str,
        start_time: time,
        end_time: time,
        required_capacity: int,
        exclude_slot_id: Optional[Any] = None,
    ) -> bool:
        """
        Verifies room availability, status, capacity, and lack of published timetable clashes.
        """
        if classroom:
            if classroom.status != Classroom.Status.AVAILABLE or classroom.capacity < required_capacity:
                return False
            cr_clash_qs = TimetableSlot.objects.filter(
                timetable__status=Timetable.Status.PUBLISHED,
                classroom=classroom,
                day=day,
                start_time__lt=end_time,
                end_time__gt=start_time,
            )
            if exclude_slot_id:
                cr_clash_qs = cr_clash_qs.exclude(id=exclude_slot_id)
            return not cr_clash_qs.exists()

        if laboratory:
            if laboratory.status != Laboratory.Status.AVAILABLE or laboratory.capacity < required_capacity:
                return False
            lab_clash_qs = TimetableSlot.objects.filter(
                timetable__status=Timetable.Status.PUBLISHED,
                laboratory=laboratory,
                day=day,
                start_time__lt=end_time,
                end_time__gt=start_time,
            )
            if exclude_slot_id:
                lab_clash_qs = lab_clash_qs.exclude(id=exclude_slot_id)
            return not lab_clash_qs.exists()

        return True

    @classmethod
    def get_suggestions_for_slot(cls, slot_id: Any) -> Dict[str, Any]:
        """
        Generates deterministic, ranked rescheduling suggestions for an affected published TimetableSlot.
        """
        try:
            slot = TimetableSlot.objects.select_related(
                "timetable",
                "timetable__semester",
                "subject",
                "division",
                "batch",
                "teacher",
                "teacher__user",
                "classroom",
                "laboratory",
            ).get(id=slot_id)
        except (TimetableSlot.DoesNotExist, ValueError):
            raise ValidationError({"timetable_slot": "Timetable slot does not exist."})

        if slot.timetable.status != Timetable.Status.PUBLISHED:
            raise ValidationError(
                {"timetable_slot": "Rescheduling suggestions are only available for PUBLISHED timetable slots."}
            )

        absent_teacher = slot.teacher
        subject = slot.subject
        division = slot.division
        batch = slot.batch
        session_type = slot.session_type
        orig_classroom = slot.classroom
        orig_laboratory = slot.laboratory
        orig_day = slot.day
        orig_start = slot.start_time
        orig_end = slot.end_time
        required_capacity = batch.capacity if batch else (division.capacity if division else 30)

        # 1. Qualified Teachers for Subject
        qualified_teacher_profiles = list(
            TeacherProfile.objects.filter(
                teacher_subjects__subject=subject,
                status=TeacherProfile.Status.ACTIVE,
                user__is_active=True,
            )
            .select_related("user")
            .distinct()
        )

        # 2. Time intervals to test
        time_intervals = cls.get_time_slots_for_timetable(slot.timetable, orig_start, orig_end)

        # 3. Candidate Rooms
        candidate_classrooms: List[Classroom] = []
        candidate_laboratories: List[Laboratory] = []

        if session_type in [TimetableSlot.SessionType.LECTURE, TimetableSlot.SessionType.TUTORIAL]:
            candidate_classrooms = list(
                Classroom.objects.filter(
                    status=Classroom.Status.AVAILABLE,
                    capacity__gte=required_capacity,
                ).order_by("room_number")
            )
            if orig_classroom and orig_classroom not in candidate_classrooms:
                candidate_classrooms.insert(0, orig_classroom)
        else:
            candidate_laboratories = list(
                Laboratory.objects.filter(
                    status=Laboratory.Status.AVAILABLE,
                    capacity__gte=required_capacity,
                ).order_by("lab_number")
            )
            if orig_laboratory and orig_laboratory not in candidate_laboratories:
                candidate_laboratories.insert(0, orig_laboratory)

        suggestions: List[Dict[str, Any]] = []
        seen_keys: Set[Tuple[Any, str, str, str, Any, Any]] = set()

        def add_suggestion(
            s_type: str,
            teacher: TeacherProfile,
            day: str,
            start_t: time,
            end_t: time,
            c_room: Optional[Classroom],
            c_lab: Optional[Laboratory],
            score: int,
            reasons: List[str],
        ):
            key = (
                teacher.id,
                day,
                str(start_t)[:5],
                str(end_t)[:5],
                c_room.id if c_room else None,
                c_lab.id if c_lab else None,
            )
            if key in seen_keys:
                return
            seen_keys.add(key)

            teacher_name = teacher.user.get_full_name() or teacher.user.username
            suggestions.append(
                {
                    "type": s_type,
                    "teacher_id": str(teacher.id),
                    "teacher_name": teacher_name,
                    "day": day,
                    "start_time": str(start_t)[:5],
                    "end_time": str(end_t)[:5],
                    "classroom_id": str(c_room.id) if c_room else None,
                    "classroom_name": f"{c_room.building}-{c_room.room_number}" if c_room else None,
                    "laboratory_id": str(c_lab.id) if c_lab else None,
                    "laboratory_name": f"{c_lab.building}-{c_lab.lab_number}" if c_lab else None,
                    "score": score,
                    "reasons": reasons,
                }
            )

        # Priority 1: Qualified substitute at original time & original room
        for sub_teacher in qualified_teacher_profiles:
            if sub_teacher.id == absent_teacher.id:
                continue

            if cls.is_teacher_available_at(sub_teacher, orig_day, orig_start, orig_end, exclude_slot_id=slot.id):
                if cls.is_room_available_at(orig_classroom, orig_laboratory, orig_day, orig_start, orig_end, required_capacity, exclude_slot_id=slot.id):
                    add_suggestion(
                        s_type="SUBSTITUTE_TEACHER",
                        teacher=sub_teacher,
                        day=orig_day,
                        start_t=orig_start,
                        end_t=orig_end,
                        c_room=orig_classroom,
                        c_lab=orig_laboratory,
                        score=95,
                        reasons=[
                            "Qualified for subject",
                            "Available at original time",
                            "No timetable clash",
                            "Original room retained",
                        ],
                    )

        # Priority 2: Alternative Room at original time (if original room had clash or to offer alternatives)
        for room in (candidate_classrooms if session_type != TimetableSlot.SessionType.PRACTICAL else candidate_laboratories):
            c_room = room if session_type != TimetableSlot.SessionType.PRACTICAL else None
            c_lab = room if session_type == TimetableSlot.SessionType.PRACTICAL else None

            # Skip if same as original room
            if (c_room and orig_classroom and c_room.id == orig_classroom.id) or (c_lab and orig_laboratory and c_lab.id == orig_laboratory.id):
                continue

            if cls.is_room_available_at(c_room, c_lab, orig_day, orig_start, orig_end, required_capacity, exclude_slot_id=slot.id):
                # For each qualified substitute (or original teacher if free)
                for cand_teacher in qualified_teacher_profiles:
                    if cls.is_teacher_available_at(cand_teacher, orig_day, orig_start, orig_end, exclude_slot_id=slot.id):
                        is_sub = cand_teacher.id != absent_teacher.id
                        add_suggestion(
                            s_type="ALTERNATIVE_ROOM",
                            teacher=cand_teacher,
                            day=orig_day,
                            start_t=orig_start,
                            end_t=orig_end,
                            c_room=c_room,
                            c_lab=c_lab,
                            score=80 if is_sub else 82,
                            reasons=[
                                "Original time retained",
                                "Alternative room with adequate capacity",
                                "No room clash",
                            ],
                        )

        # Priority 3 & 4 & 5: Alternative Time slots across the week
        for day in cls.DAYS_ORDER:
            for start_t, end_t in time_intervals:
                is_orig_time = (day == orig_day and start_t == orig_start and end_t == orig_end)
                if is_orig_time:
                    continue  # Already handled above

                # Division must be free at this time
                if not cls.is_division_available_at(division, batch, day, start_t, end_t, exclude_slot_id=slot.id):
                    continue

                # Check original teacher at new time (Priority 3: ALTERNATIVE_TIME)
                if cls.is_teacher_available_at(absent_teacher, day, start_t, end_t, exclude_slot_id=slot.id):
                    # Check original room
                    if cls.is_room_available_at(orig_classroom, orig_laboratory, day, start_t, end_t, required_capacity, exclude_slot_id=slot.id):
                        add_suggestion(
                            s_type="ALTERNATIVE_TIME",
                            teacher=absent_teacher,
                            day=day,
                            start_t=start_t,
                            end_t=end_t,
                            c_room=orig_classroom,
                            c_lab=orig_laboratory,
                            score=85,
                            reasons=[
                                "Original teacher available at new time",
                                "Division available",
                                "Room available",
                            ],
                        )
                    else:
                        # Alternative room
                        for room in (candidate_classrooms if session_type != TimetableSlot.SessionType.PRACTICAL else candidate_laboratories):
                            c_room = room if session_type != TimetableSlot.SessionType.PRACTICAL else None
                            c_lab = room if session_type == TimetableSlot.SessionType.PRACTICAL else None
                            if cls.is_room_available_at(c_room, c_lab, day, start_t, end_t, required_capacity, exclude_slot_id=slot.id):
                                add_suggestion(
                                    s_type="ALTERNATIVE_TIME_ROOM",
                                    teacher=absent_teacher,
                                    day=day,
                                    start_t=start_t,
                                    end_t=end_t,
                                    c_room=c_room,
                                    c_lab=c_lab,
                                    score=75,
                                    reasons=[
                                        "Original teacher available at alternative time and room",
                                        "Division available",
                                        "No resource clash",
                                    ],
                                )

                # Check qualified substitute teachers at new time (Priority 2: SUBSTITUTE_ALTERNATIVE_TIME)
                for sub_teacher in qualified_teacher_profiles:
                    if sub_teacher.id == absent_teacher.id:
                        continue

                    if cls.is_teacher_available_at(sub_teacher, day, start_t, end_t, exclude_slot_id=slot.id):
                        if cls.is_room_available_at(orig_classroom, orig_laboratory, day, start_t, end_t, required_capacity, exclude_slot_id=slot.id):
                            add_suggestion(
                                s_type="SUBSTITUTE_ALTERNATIVE_TIME",
                                teacher=sub_teacher,
                                day=day,
                                start_t=start_t,
                                end_t=end_t,
                                c_room=orig_classroom,
                                c_lab=orig_laboratory,
                                score=90,
                                reasons=[
                                    "Qualified substitute",
                                    "Division and room available",
                                    "No schedule clash",
                                ],
                            )
                        else:
                            for room in (candidate_classrooms if session_type != TimetableSlot.SessionType.PRACTICAL else candidate_laboratories):
                                c_room = room if session_type != TimetableSlot.SessionType.PRACTICAL else None
                                c_lab = room if session_type == TimetableSlot.SessionType.PRACTICAL else None
                                if cls.is_room_available_at(c_room, c_lab, day, start_t, end_t, required_capacity, exclude_slot_id=slot.id):
                                    add_suggestion(
                                        s_type="ALTERNATIVE_TIME_ROOM",
                                        teacher=sub_teacher,
                                        day=day,
                                        start_t=start_t,
                                        end_t=end_t,
                                        c_room=c_room,
                                        c_lab=c_lab,
                                        score=75,
                                        reasons=[
                                            "Qualified substitute at alternative time and room",
                                            "All hard constraints satisfied",
                                            "No resource clash",
                                        ],
                                    )

        # Deterministic sorting: Highest score first, then day index, start time, teacher id
        day_index_map = {d: i for i, d in enumerate(cls.DAYS_ORDER)}
        suggestions.sort(
            key=lambda s: (
                -s["score"],
                day_index_map.get(s["day"], 99),
                str(s["start_time"]),
                str(s["teacher_id"]),
            )
        )

        return {
            "slot_id": str(slot.id),
            "original": {
                "teacher_id": str(absent_teacher.id),
                "teacher_name": absent_teacher.user.get_full_name() or absent_teacher.user.username,
                "subject_id": str(subject.id),
                "subject_name": subject.name,
                "day": orig_day,
                "start_time": str(orig_start)[:5],
                "end_time": str(orig_end)[:5],
                "classroom_id": str(orig_classroom.id) if orig_classroom else None,
                "classroom_name": f"{orig_classroom.building}-{orig_classroom.room_number}" if orig_classroom else None,
                "laboratory_id": str(orig_laboratory.id) if orig_laboratory else None,
                "laboratory_name": f"{orig_laboratory.building}-{orig_laboratory.lab_number}" if orig_laboratory else None,
            },
            "suggestions": suggestions,
        }

    @classmethod
    @transaction.atomic
    def confirm_reschedule(
        cls,
        slot_id: Any,
        teacher_id: Any,
        day: str,
        start_time: Any,
        end_time: Any,
        classroom_id: Optional[Any] = None,
        laboratory_id: Optional[Any] = None,
        reason: str = "",
        user: Optional[User] = None,
    ) -> Dict[str, Any]:
        """
        Validates the chosen reschedule parameters with zero-trust server-side checks,
        creates a new draft timetable version (status: GENERATED, preserving history),
        copies existing slots while updating the rescheduled slot,
        and records a SlotReschedule audit instance.
        """
        # 1. Fetch and validate original slot
        try:
            slot = TimetableSlot.objects.select_related(
                "timetable",
                "timetable__semester",
                "subject",
                "division",
                "batch",
                "teacher",
                "classroom",
                "laboratory",
            ).get(id=slot_id)
        except (TimetableSlot.DoesNotExist, ValueError):
            raise ValidationError({"timetable_slot": "Timetable slot does not exist."})

        if slot.timetable.status != Timetable.Status.PUBLISHED:
            raise ValidationError(
                {"timetable_slot": "Rescheduling is only allowed for PUBLISHED timetable slots."}
            )

        # 2. Fetch and validate Teacher
        try:
            new_teacher = TeacherProfile.objects.select_related("user").get(id=teacher_id)
        except (TeacherProfile.DoesNotExist, ValueError):
            raise ValidationError({"teacher": "Teacher does not exist."})

        if new_teacher.status != TeacherProfile.Status.ACTIVE or not new_teacher.user.is_active:
            raise ValidationError({"teacher": "Selected teacher is inactive."})

        # Qualification check
        is_qualified = TeacherSubject.objects.filter(
            teacher=new_teacher,
            subject=slot.subject,
        ).exists()
        if not is_qualified:
            raise ValidationError(
                {"teacher": f"Teacher is not qualified to teach subject '{slot.subject.name}'."}
            )

        # Normalize day & times
        day = day.strip().upper()
        if day not in TimetableSlot.Day.values:
            raise ValidationError({"day": f"Invalid day of week '{day}'."})

        # Parse times
        if isinstance(start_time, str):
            if len(start_time) == 5:
                start_time += ":00"
            start_t = datetime.strptime(start_time, "%H:%M:%S").time()
        elif isinstance(start_time, time):
            start_t = start_time
        else:
            raise ValidationError({"start_time": "Invalid start time format."})

        if isinstance(end_time, str):
            if len(end_time) == 5:
                end_time += ":00"
            end_t = datetime.strptime(end_time, "%H:%M:%S").time()
        elif isinstance(end_time, time):
            end_t = end_time
        else:
            raise ValidationError({"end_time": "Invalid end time format."})

        if start_t >= end_t:
            raise ValidationError({"end_time": "End time must be strictly after start time."})

        # Check Teacher Availability & Leave & Clashes
        if not cls.is_teacher_available_at(new_teacher, day, start_t, end_t, exclude_slot_id=slot.id):
            raise ValidationError(
                {"teacher": "Teacher is unavailable, on approved leave, or has a timetable clash at this time."}
            )

        # Check Division & Batch availability
        if not cls.is_division_available_at(slot.division, slot.batch, day, start_t, end_t, exclude_slot_id=slot.id):
            raise ValidationError(
                {"division": "Division or batch already has another class scheduled at this time."}
            )

        # Fetch and validate Room
        new_classroom = None
        new_laboratory = None
        required_capacity = slot.batch.capacity if slot.batch else (slot.division.capacity if slot.division else 30)

        if slot.session_type == TimetableSlot.SessionType.PRACTICAL:
            lab_target = laboratory_id or (slot.laboratory_id if slot.laboratory else None)
            if not lab_target:
                raise ValidationError({"laboratory": "A laboratory must be allocated for practical sessions."})
            try:
                new_laboratory = Laboratory.objects.get(id=lab_target)
            except (Laboratory.DoesNotExist, ValueError):
                raise ValidationError({"laboratory": "Laboratory does not exist."})
        else:
            cr_target = classroom_id or (slot.classroom_id if slot.classroom else None)
            if not cr_target:
                raise ValidationError({"classroom": "A classroom must be allocated for lecture/tutorial sessions."})
            try:
                new_classroom = Classroom.objects.get(id=cr_target)
            except (Classroom.DoesNotExist, ValueError):
                raise ValidationError({"classroom": "Classroom does not exist."})

        if not cls.is_room_available_at(new_classroom, new_laboratory, day, start_t, end_t, required_capacity, exclude_slot_id=slot.id):
            raise ValidationError(
                {"room": "The selected room/laboratory is unavailable, has insufficient capacity, or has a timetable clash."}
            )

        # 3. Create new draft Timetable version (status: GENERATED, preserving history)
        max_version = (
            Timetable.objects.filter(
                semester=slot.timetable.semester,
                academic_year=slot.timetable.academic_year,
            ).aggregate(Max("version"))["version__max"]
            or slot.timetable.version
        )
        new_version = max_version + 1

        new_timetable = Timetable.objects.create(
            semester=slot.timetable.semester,
            academic_year=slot.timetable.academic_year,
            version=new_version,
            status=Timetable.Status.GENERATED,  # Kept as GENERATED / review mode, NOT auto-published
            created_by=user,
        )

        # 4. Clone slots from original published timetable to new timetable
        original_slots = TimetableSlot.objects.filter(
            timetable=slot.timetable,
        ).exclude(status=TimetableSlot.Status.CANCELLED)

        created_slots = []
        for s in original_slots:
            if s.id == slot.id:
                # Create updated rescheduled slot on new timetable
                new_slot = TimetableSlot.objects.create(
                    timetable=new_timetable,
                    division=s.division,
                    batch=s.batch,
                    subject=s.subject,
                    teacher=new_teacher,
                    classroom=new_classroom,
                    laboratory=new_laboratory,
                    day=day,
                    start_time=start_t,
                    end_time=end_t,
                    session_type=s.session_type,
                    status=TimetableSlot.Status.SCHEDULED,
                )
                created_slots.append(new_slot)
            else:
                # Copy other existing slot intact
                copied_slot = TimetableSlot.objects.create(
                    timetable=new_timetable,
                    division=s.division,
                    batch=s.batch,
                    subject=s.subject,
                    teacher=s.teacher,
                    classroom=s.classroom,
                    laboratory=s.laboratory,
                    day=s.day,
                    start_time=s.start_time,
                    end_time=s.end_time,
                    session_type=s.session_type,
                    status=s.status,
                )
                created_slots.append(copied_slot)

        # 5. Record SlotReschedule instance
        reschedule = SlotReschedule.objects.create(
            original_slot=slot,
            new_teacher=new_teacher,
            new_day=day,
            new_start_time=start_t,
            new_end_time=end_t,
            new_classroom=new_classroom,
            new_laboratory=new_laboratory,
            new_timetable=new_timetable,
            reason=reason or "",
            status=SlotReschedule.Status.CONFIRMED,
            created_by=user,
        )

        return {
            "reschedule_id": str(reschedule.id),
            "status": reschedule.status,
            "original_slot_id": str(slot.id),
            "new_timetable": {
                "id": str(new_timetable.id),
                "version": new_timetable.version,
                "status": new_timetable.status,
                "academic_year": new_timetable.academic_year,
            },
            "new_assignment": {
                "teacher_id": str(new_teacher.id),
                "teacher_name": new_teacher.user.get_full_name() or new_teacher.user.username,
                "day": day,
                "start_time": str(start_t)[:5],
                "end_time": str(end_t)[:5],
                "classroom_id": str(new_classroom.id) if new_classroom else None,
                "laboratory_id": str(new_laboratory.id) if new_laboratory else None,
            },
            "reason": reschedule.reason,
        }
