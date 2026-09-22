"""
Natural-Language Constraint Integration Service for SMART-TIME AI (Phase 9C).

Connects validated/normalized constraints (from Phase 9B ConstraintValidatorService)
to the OR-Tools CP-SAT Timetable Solver (Phase 6-8).

Converts:
- mode=AVOID  -> Hard solver restrictions (banning assignments during restricted days/times)
- mode=PREFER -> Soft optimization penalties (penalizing non-preferred assignments in CP-SAT objective)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import uuid

from academics.services.constraint_parser import (
    ConstraintMode,
    ConstraintType,
    SessionType,
    StructuredConstraint,
)
from academics.services.constraint_validator import (
    ConstraintValidatorService,
    ValidationResult,
)


def _normalize_time_str(t_str: Optional[str]) -> Optional[str]:
    """Normalizes time string to HH:MM:SS for robust interval comparisons."""
    if not t_str:
        return None
    s = str(t_str).strip()
    if len(s) == 5:  # HH:MM
        return f"{s}:00"
    elif len(s) == 8:  # HH:MM:SS
        return s
    return s


def _intervals_overlap(s1: str, e1: str, s2: str, e2: str) -> bool:
    """Checks whether two half-open time intervals [s1, e1) and [s2, e2) overlap."""
    n_s1 = _normalize_time_str(s1)
    n_e1 = _normalize_time_str(e1)
    n_s2 = _normalize_time_str(s2)
    n_e2 = _normalize_time_str(e2)
    return not (n_e1 <= n_s2 or n_s1 >= n_e2)


@dataclass
class HardRestrictions:
    """Container for hard solver restrictions (mode=AVOID)."""
    # (teacher_id, day, start_time, end_time)
    teacher_time_bans: List[Tuple[str, str, str, str]] = field(default_factory=list)
    # (teacher_id, day)
    teacher_day_bans: Set[Tuple[str, str]] = field(default_factory=set)
    # (subject_id, day)
    subject_day_bans: Set[Tuple[str, str]] = field(default_factory=set)
    # (subject_id, day, start_time, end_time)
    subject_time_bans: List[Tuple[str, str, str, str]] = field(default_factory=list)
    # (division_id, day, start_time, end_time)
    division_time_bans: List[Tuple[str, str, str, str]] = field(default_factory=list)
    # (division_id, day)
    division_day_bans: Set[Tuple[str, str]] = field(default_factory=set)


@dataclass
class SoftPreference:
    """Soft optimization preference penalty (mode=PREFER)."""
    constraint_type: str
    target_id: Optional[str] = None  # subject_id, teacher_id, or division_id
    session_type: Optional[str] = None
    preferred_day: Optional[str] = None
    preferred_start_time: Optional[str] = None
    preferred_end_time: Optional[str] = None
    penalty_weight: int = 25


@dataclass
class SolverConstraintMap:
    """Compiled restrictions and preferences ready for CP-SAT solver consumption."""
    hard_restrictions: HardRestrictions = field(default_factory=HardRestrictions)
    soft_preferences: List[SoftPreference] = field(default_factory=list)

    def is_assignment_banned(
        self,
        teacher_id: Optional[str],
        subject_id: Optional[str],
        division_id: Optional[str],
        day: str,
        slot_start: str,
        slot_end: str,
    ) -> bool:
        """
        Evaluates whether a candidate assignment violates any active hard restrictions.
        """
        day_upper = day.upper()

        # 1. Teacher Day Ban
        if teacher_id and (teacher_id, day_upper) in self.hard_restrictions.teacher_day_bans:
            return True

        # 2. Teacher Time Ban
        if teacher_id:
            for t_id, t_day, t_start, t_end in self.hard_restrictions.teacher_time_bans:
                if t_id == teacher_id and t_day == day_upper:
                    if _intervals_overlap(slot_start, slot_end, t_start, t_end):
                        return True

        # 3. Subject Day Ban
        if subject_id and (subject_id, day_upper) in self.hard_restrictions.subject_day_bans:
            return True

        # 4. Subject Time Ban
        if subject_id:
            for s_id, s_day, s_start, s_end in self.hard_restrictions.subject_time_bans:
                if s_id == subject_id and (not s_day or s_day == day_upper):
                    if _intervals_overlap(slot_start, slot_end, s_start, s_end):
                        return True

        # 5. Division Day Ban
        if division_id and (division_id, day_upper) in self.hard_restrictions.division_day_bans:
            return True

        # 6. Division Time Ban
        if division_id:
            for d_id, d_day, d_start, d_end in self.hard_restrictions.division_time_bans:
                if d_id == division_id and d_day == day_upper:
                    if _intervals_overlap(slot_start, slot_end, d_start, d_end):
                        return True

        return False


class ConstraintIntegrationService:
    """
    Transforms validated natural-language constraints into solver constraints and preferences.
    """

    DEFAULT_PREFERENCE_WEIGHT: int = 25

    def __init__(self, validator: Optional[ConstraintValidatorService] = None):
        self.validator = validator or ConstraintValidatorService()

    def compile_constraints(
        self,
        constraints: List[Union[Dict[str, Any], StructuredConstraint, ValidationResult]],
        semester: Optional[Any] = None,
        default_pref_weight: int = DEFAULT_PREFERENCE_WEIGHT,
    ) -> SolverConstraintMap:
        """
        Validates (if necessary) and maps constraints into hard restrictions and soft preferences.

        Args:
            constraints: List of validated dicts, StructuredConstraint, or ValidationResults.
            semester: Optional semester context for validation if needed.
            default_pref_weight: Penalty weight applied to soft preferences.

        Returns:
            SolverConstraintMap containing hard restrictions and soft preferences.
        """
        compiled = SolverConstraintMap()

        for c_item in constraints:
            # 1. Normalize input to canonical dictionary
            c_data = self._extract_canonical_dict(c_item, semester)
            if not c_data:
                continue

            c_type = c_data.get("constraint_type")
            mode = str(c_data.get("mode", ConstraintMode.AVOID.value)).upper()

            # 2. Map TEACHER_TIME_RESTRICTION
            if c_type == ConstraintType.TEACHER_TIME_RESTRICTION.value:
                teacher_id = str(c_data.get("teacher_id"))
                day = str(c_data.get("day", "")).upper()
                start_time = c_data.get("start_time")
                end_time = c_data.get("end_time")

                if mode == ConstraintMode.AVOID.value:
                    if teacher_id and day and start_time and end_time:
                        compiled.hard_restrictions.teacher_time_bans.append(
                            (teacher_id, day, start_time, end_time)
                        )
                elif mode == ConstraintMode.PREFER.value:
                    compiled.soft_preferences.append(
                        SoftPreference(
                            constraint_type=c_type,
                            target_id=teacher_id,
                            preferred_day=day,
                            preferred_start_time=start_time,
                            preferred_end_time=end_time,
                            penalty_weight=default_pref_weight,
                        )
                    )

            # 3. Map TEACHER_DAY_RESTRICTION
            elif c_type == ConstraintType.TEACHER_DAY_RESTRICTION.value:
                teacher_id = str(c_data.get("teacher_id"))
                day = str(c_data.get("day", "")).upper()

                if mode == ConstraintMode.AVOID.value:
                    if teacher_id and day:
                        compiled.hard_restrictions.teacher_day_bans.add((teacher_id, day))
                elif mode == ConstraintMode.PREFER.value:
                    compiled.soft_preferences.append(
                        SoftPreference(
                            constraint_type=c_type,
                            target_id=teacher_id,
                            preferred_day=day,
                            penalty_weight=default_pref_weight,
                        )
                    )

            # 4. Map SUBJECT_DAY_RESTRICTION
            elif c_type == ConstraintType.SUBJECT_DAY_RESTRICTION.value:
                subject_id = str(c_data.get("subject_id"))
                day = str(c_data.get("day", "")).upper()

                if mode == ConstraintMode.AVOID.value:
                    if subject_id and day:
                        compiled.hard_restrictions.subject_day_bans.add((subject_id, day))
                elif mode == ConstraintMode.PREFER.value:
                    compiled.soft_preferences.append(
                        SoftPreference(
                            constraint_type=c_type,
                            target_id=subject_id,
                            preferred_day=day,
                            penalty_weight=default_pref_weight,
                        )
                    )

            # 5. Map SUBJECT_TIME_PREFERENCE
            elif c_type == ConstraintType.SUBJECT_TIME_PREFERENCE.value:
                subject_id = str(c_data.get("subject_id"))
                day = str(c_data.get("day", "")).upper() if c_data.get("day") else None
                start_time = c_data.get("start_time")
                end_time = c_data.get("end_time")

                if mode == ConstraintMode.PREFER.value:
                    compiled.soft_preferences.append(
                        SoftPreference(
                            constraint_type=c_type,
                            target_id=subject_id,
                            preferred_day=day,
                            preferred_start_time=start_time,
                            preferred_end_time=end_time,
                            penalty_weight=default_pref_weight,
                        )
                    )
                elif mode == ConstraintMode.AVOID.value:
                    if day and start_time and end_time:
                        compiled.hard_restrictions.subject_time_bans.append(
                            (subject_id, day, start_time, end_time)
                        )
                    elif day:
                        compiled.hard_restrictions.subject_day_bans.add((subject_id, day))

            # 6. Map DIVISION_TIME_RESTRICTION
            elif c_type == ConstraintType.DIVISION_TIME_RESTRICTION.value:
                division_id = str(c_data.get("division_id"))
                day = str(c_data.get("day", "")).upper()
                start_time = c_data.get("start_time")
                end_time = c_data.get("end_time")

                if mode == ConstraintMode.AVOID.value:
                    if division_id and day and start_time and end_time:
                        compiled.hard_restrictions.division_time_bans.append(
                            (division_id, day, start_time, end_time)
                        )
                elif mode == ConstraintMode.PREFER.value:
                    compiled.soft_preferences.append(
                        SoftPreference(
                            constraint_type=c_type,
                            target_id=division_id,
                            preferred_day=day,
                            preferred_start_time=start_time,
                            preferred_end_time=end_time,
                            penalty_weight=default_pref_weight,
                        )
                    )

            # 7. Map SESSION_TIME_PREFERENCE
            elif c_type == ConstraintType.SESSION_TIME_PREFERENCE.value:
                session_type = c_data.get("session_type")
                subject_id = str(c_data.get("subject_id")) if c_data.get("subject_id") else None
                day = str(c_data.get("day", "")).upper() if c_data.get("day") else None
                start_time = c_data.get("start_time")
                end_time = c_data.get("end_time")

                if mode == ConstraintMode.PREFER.value:
                    compiled.soft_preferences.append(
                        SoftPreference(
                            constraint_type=c_type,
                            target_id=subject_id,
                            session_type=session_type,
                            preferred_day=day,
                            preferred_start_time=start_time,
                            preferred_end_time=end_time,
                            penalty_weight=default_pref_weight,
                        )
                    )

        return compiled

    def _extract_canonical_dict(
        self,
        c_item: Union[Dict[str, Any], StructuredConstraint, ValidationResult],
        semester: Optional[Any],
    ) -> Optional[Dict[str, Any]]:
        """Extracts canonical dictionary from input item, validating if unvalidated."""
        if isinstance(c_item, ValidationResult):
            return c_item.constraint if c_item.valid else None

        if isinstance(c_item, (StructuredConstraint, dict)):
            # If already canonical with UUIDs and constraint_type
            data = c_item.to_dict() if isinstance(c_item, StructuredConstraint) else dict(c_item)

            # Check if this requires validation or is already validated
            has_id = (
                "teacher_id" in data
                or "subject_id" in data
                or "division_id" in data
                or data.get("constraint_type") in self.validator.SUPPORTED_CONSTRAINT_TYPES
            )

            # Run through validator to ensure entity integrity
            val_res = self.validator.validate(data, semester=semester)
            if val_res.valid:
                return val_res.constraint

        return None
