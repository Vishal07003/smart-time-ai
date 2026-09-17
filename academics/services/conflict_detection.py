
"""
Timetable Clash / Conflict Detection Service.
Detects TEACHER_CLASH, CLASSROOM_CLASH, LAB_CLASH, DIVISION_CLASH, and BATCH_CLASH.
"""

from typing import List, Tuple
from django.db import transaction
from academics.models import Timetable, TimetableConflict, TimetableSlot


class ConflictDetectionService:
    """
    Service to detect and refresh timetable clashes across scheduled slots.
    """

    def __init__(self, timetable: Timetable):
        self.timetable = timetable

    def detect_conflicts(self) -> List[TimetableConflict]:
        """
        Executes conflict detection for the timetable, refreshes detected conflicts,
        and returns the active list of TimetableConflict records.
        """
        # Fetch all non-cancelled slots for this timetable with necessary relations
        slots = list(
            TimetableSlot.objects.filter(timetable=self.timetable)
            .exclude(status=TimetableSlot.Status.CANCELLED)
            .select_related(
                "division",
                "batch",
                "subject",
                "teacher",
                "teacher__user",
                "classroom",
                "laboratory",
            )
            .order_by("day", "start_time")
        )

        detected_conflict_instances: List[TimetableConflict] = []
        seen_pairs = set()

        # Compare each pair of slots on the same day
        num_slots = len(slots)
        for i in range(num_slots):
            s1 = slots[i]
            for j in range(i + 1, num_slots):
                s2 = slots[j]

                # Only slots on the same day can conflict
                if s1.day != s2.day:
                    continue

                # Check time range overlap: start1 < end2 and end1 > start2
                if not (s1.start_time < s2.end_time and s1.end_time > s2.start_time):
                    continue

                overlap_start = max(s1.start_time, s2.start_time)
                overlap_end = min(s1.end_time, s2.end_time)

                # Canonicalize slot pair ordering (slot_a has lower ID string representation)
                slot_a, slot_b = (s1, s2) if str(s1.id) <= str(s2.id) else (s2, s1)
                pair_key = (str(slot_a.id), str(slot_b.id))

                # 1. TEACHER_CLASH
                if s1.teacher_id and s2.teacher_id and s1.teacher_id == s2.teacher_id:
                    key = (TimetableConflict.ConflictType.TEACHER_CLASH, pair_key)
                    if key not in seen_pairs:
                        seen_pairs.add(key)
                        teacher_name = slot_a.teacher.user.get_full_name() or slot_a.teacher.user.username
                        desc = (
                            f"Teacher Clash: Teacher {teacher_name} ({slot_a.teacher.employee_code}) "
                            f"is assigned to overlapping slots '{slot_a.subject.code}' ({slot_a.division.name}) and "
                            f"'{slot_b.subject.code}' ({slot_b.division.name}) on {slot_a.day} between {overlap_start} and {overlap_end}."
                        )
                        detected_conflict_instances.append(
                            TimetableConflict(
                                timetable=self.timetable,
                                slot=slot_a,
                                conflicting_slot=slot_b,
                                conflict_type=TimetableConflict.ConflictType.TEACHER_CLASH,
                                severity=TimetableConflict.Severity.HIGH,
                                description=desc,
                                status=TimetableConflict.Status.DETECTED,
                            )
                        )

                # 2. CLASSROOM_CLASH
                if s1.classroom_id and s2.classroom_id and s1.classroom_id == s2.classroom_id:
                    key = (TimetableConflict.ConflictType.CLASSROOM_CLASH, pair_key)
                    if key not in seen_pairs:
                        seen_pairs.add(key)
                        cr = slot_a.classroom
                        desc = (
                            f"Classroom Clash: Classroom {cr.building} - {cr.room_number} "
                            f"is allocated to multiple slots ('{slot_a.subject.code}' and '{slot_b.subject.code}') "
                            f"on {slot_a.day} between {overlap_start} and {overlap_end}."
                        )
                        detected_conflict_instances.append(
                            TimetableConflict(
                                timetable=self.timetable,
                                slot=slot_a,
                                conflicting_slot=slot_b,
                                conflict_type=TimetableConflict.ConflictType.CLASSROOM_CLASH,
                                severity=TimetableConflict.Severity.HIGH,
                                description=desc,
                                status=TimetableConflict.Status.DETECTED,
                            )
                        )

                # 3. LAB_CLASH
                if s1.laboratory_id and s2.laboratory_id and s1.laboratory_id == s2.laboratory_id:
                    key = (TimetableConflict.ConflictType.LAB_CLASH, pair_key)
                    if key not in seen_pairs:
                        seen_pairs.add(key)
                        lab = slot_a.laboratory
                        desc = (
                            f"Laboratory Clash: Laboratory {lab.building} - {lab.lab_number} ({lab.name}) "
                            f"is allocated to multiple slots ('{slot_a.subject.code}' and '{slot_b.subject.code}') "
                            f"on {slot_a.day} between {overlap_start} and {overlap_end}."
                        )
                        detected_conflict_instances.append(
                            TimetableConflict(
                                timetable=self.timetable,
                                slot=slot_a,
                                conflicting_slot=slot_b,
                                conflict_type=TimetableConflict.ConflictType.LAB_CLASH,
                                severity=TimetableConflict.Severity.HIGH,
                                description=desc,
                                status=TimetableConflict.Status.DETECTED,
                            )
                        )

                # 4. DIVISION_CLASH
                # Occurs if same division and either slot is full-division (batch is None) or both are full-division
                if s1.division_id == s2.division_id:
                    if s1.batch_id is None or s2.batch_id is None:
                        key = (TimetableConflict.ConflictType.DIVISION_CLASH, pair_key)
                        if key not in seen_pairs:
                            seen_pairs.add(key)
                            desc = (
                                f"Division Clash: Division {slot_a.division.name} has overlapping sessions "
                                f"('{slot_a.subject.code}' and '{slot_b.subject.code}') on {slot_a.day} "
                                f"between {overlap_start} and {overlap_end}."
                            )
                            detected_conflict_instances.append(
                                TimetableConflict(
                                    timetable=self.timetable,
                                    slot=slot_a,
                                    conflicting_slot=slot_b,
                                    conflict_type=TimetableConflict.ConflictType.DIVISION_CLASH,
                                    severity=TimetableConflict.Severity.HIGH,
                                    description=desc,
                                    status=TimetableConflict.Status.DETECTED,
                                )
                            )

                # 5. BATCH_CLASH
                # Occurs if same batch is scheduled in multiple overlapping slots
                if s1.batch_id and s2.batch_id and s1.batch_id == s2.batch_id:
                    key = (TimetableConflict.ConflictType.BATCH_CLASH, pair_key)
                    if key not in seen_pairs:
                        seen_pairs.add(key)
                        desc = (
                            f"Batch Clash: Batch {slot_a.batch.name} in Division {slot_a.division.name} "
                            f"has overlapping sessions ('{slot_a.subject.code}' and '{slot_b.subject.code}') "
                            f"on {slot_a.day} between {overlap_start} and {overlap_end}."
                        )
                        detected_conflict_instances.append(
                            TimetableConflict(
                                timetable=self.timetable,
                                slot=slot_a,
                                conflicting_slot=slot_b,
                                conflict_type=TimetableConflict.ConflictType.BATCH_CLASH,
                                severity=TimetableConflict.Severity.HIGH,
                                description=desc,
                                status=TimetableConflict.Status.DETECTED,
                            )
                        )

        # Refresh existing detected conflicts for this timetable in an atomic transaction
        with transaction.atomic():
            # 1. Delete all old DETECTED conflicts for this timetable
            TimetableConflict.objects.filter(
                timetable=self.timetable,
                status=TimetableConflict.Status.DETECTED,
            ).delete()

            # 2. Normalize and deduplicate any existing retained conflicts (RESOLVED, IGNORED)
            existing_retained = list(
                TimetableConflict.objects.filter(timetable=self.timetable)
                .exclude(status=TimetableConflict.Status.DETECTED)
            )
            retained_keys = set()
            for c in existing_retained:
                if c.slot_id and c.conflicting_slot_id and str(c.slot_id) > str(c.conflicting_slot_id):
                    c.slot_id, c.conflicting_slot_id = c.conflicting_slot_id, c.slot_id
                    norm_key = (c.conflict_type, str(c.slot_id), str(c.conflicting_slot_id))
                    if norm_key in retained_keys:
                        c.delete()
                        continue
                    else:
                        c.save(update_fields=["slot", "conflicting_slot"])
                else:
                    norm_key = (c.conflict_type, str(c.slot_id), str(c.conflicting_slot_id))
                    if norm_key in retained_keys:
                        c.delete()
                        continue
                retained_keys.add(norm_key)

            # 3. Create newly detected conflicts that are not already in retained conflicts
            if detected_conflict_instances:
                to_create = []
                for inst in detected_conflict_instances:
                    slot_id_str = str(inst.slot_id or inst.slot.id)
                    conflicting_slot_id_str = str(inst.conflicting_slot_id or inst.conflicting_slot.id)
                    key = (inst.conflict_type, slot_id_str, conflicting_slot_id_str)
                    if key not in retained_keys:
                        to_create.append(inst)

                if to_create:
                    TimetableConflict.objects.bulk_create(to_create)

        # Return active conflict list for this timetable
        return list(
            TimetableConflict.objects.filter(timetable=self.timetable)
            .select_related(
                "slot",
                "conflicting_slot",
                "resolved_by",
                "slot__subject",
                "slot__division",
                "slot__teacher__user",
                "conflicting_slot__subject",
                "conflicting_slot__division",
                "conflicting_slot__teacher__user",
            )
            .order_by("-severity", "-created_at")
        )
