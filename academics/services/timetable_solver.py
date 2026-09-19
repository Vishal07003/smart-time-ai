"""
OR-Tools CP-SAT Constraint Solver Foundation for SMART-TIME-AI Timetable Scheduling.
Phase 6: Reusable constraint satisfaction solver engine.
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from ortools.sat.python import cp_model


@dataclass
class TimeSlot:
    """Represents a discrete scheduling timeslot."""
    day: str
    slot_index: int
    start_time: str
    end_time: str


@dataclass
class SchedulingSession:
    """Represents an individual academic session requirement to schedule."""
    id: str
    subject_id: str
    division_id: str
    batch_id: Optional[str] = None
    session_type: str = "LECTURE"  # LECTURE, PRACTICAL, TUTORIAL
    duration_slots: int = 1
    preferred_teacher_id: Optional[str] = None
    preferred_room_id: Optional[str] = None
    allowed_teacher_ids: Optional[List[str]] = None
    allowed_room_ids: Optional[List[str]] = None


@dataclass
class TeacherInfo:
    """Teacher metadata and constraints for scheduling."""
    id: str
    name: str
    employee_code: str
    qualified_subject_ids: Set[str] = field(default_factory=set)
    unavailable_slots: Set[Tuple[str, str, str]] = field(default_factory=set)  # (day, start_time, end_time)
    leave_days: Set[str] = field(default_factory=set)  # days where teacher has approved leave


@dataclass
class RoomInfo:
    """Classroom or Laboratory resource."""
    id: str
    name: str
    room_type: str  # CLASSROOM, LABORATORY
    capacity: int = 60
    status: str = "AVAILABLE"  # AVAILABLE, UNAVAILABLE, MAINTENANCE


@dataclass
class DivisionInfo:
    """Division and associated practical batch structure."""
    id: str
    name: str
    batch_ids: List[str] = field(default_factory=list)


@dataclass
class OptimizationConfig:
    """Configuration weights and toggles for timetable soft constraints / optimization."""
    enabled: bool = True
    subject_distribution_weight: int = 10
    consecutive_subject_weight: int = 20
    teacher_consecutive_weight: int = 5
    division_gap_weight: int = 15
    daily_load_balance_weight: int = 10


@dataclass
class SolverConfig:
    """Solver grid, execution, and optimization configuration."""
    days: List[str] = field(
        default_factory=lambda: [
            "MONDAY",
            "TUESDAY",
            "WEDNESDAY",
            "THURSDAY",
            "FRIDAY",
            "SATURDAY",
        ]
    )
    daily_start_time: str = "09:00:00"
    daily_end_time: str = "17:00:00"
    slot_duration_minutes: int = 60
    time_limit_seconds: float = 30.0
    random_seed: int = 42
    deterministic: bool = True
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)


class TimetableSolver:
    """
    CP-SAT constraint solver engine for timetable generation, scheduling validation, and optimization.
    """

    STATUS_OPTIMAL = "OPTIMAL"
    STATUS_FEASIBLE = "FEASIBLE"
    STATUS_INFEASIBLE = "INFEASIBLE"
    STATUS_UNKNOWN = "UNKNOWN"

    def __init__(self, config: Optional[SolverConfig] = None):
        self.config = config or SolverConfig()
        self.time_slots: List[TimeSlot] = self._generate_time_slots()

    def _generate_time_slots(self) -> List[TimeSlot]:
        """Generates discrete time slots across configured working days and hours."""
        slots: List[TimeSlot] = []
        try:
            start_dt = datetime.strptime(self.config.daily_start_time, "%H:%M:%S" if len(self.config.daily_start_time) == 8 else "%H:%M")
            end_dt = datetime.strptime(self.config.daily_end_time, "%H:%M:%S" if len(self.config.daily_end_time) == 8 else "%H:%M")
        except ValueError:
            # Fallback format parsing
            start_dt = datetime.strptime("09:00:00", "%H:%M:%S")
            end_dt = datetime.strptime("17:00:00", "%H:%M:%S")

        duration = timedelta(minutes=self.config.slot_duration_minutes)
        if start_dt >= end_dt or self.config.slot_duration_minutes <= 0:
            return slots

        slot_idx = 0
        for day in self.config.days:
            current = start_dt
            while current + duration <= end_dt:
                slot_start_str = current.strftime("%H:%M:%S")
                slot_end_str = (current + duration).strftime("%H:%M:%S")
                slots.append(
                    TimeSlot(
                        day=day.upper(),
                        slot_index=slot_idx,
                        start_time=slot_start_str,
                        end_time=slot_end_str,
                    )
                )
                slot_idx += 1
                current += duration
        return slots

    def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes CP-SAT constraint satisfaction for provided structured input.
        Returns:
            {
                "status": "FEASIBLE | INFEASIBLE | UNKNOWN",
                "assignments": [...],
                "conflicts": [...],
                "errors": [...]
            }
        """
        errors: List[str] = []
        conflicts: List[str] = []

        # Validate input timeslot grid
        if not self.time_slots:
            errors.append("Invalid time configuration: no usable time slots generated.")
            return {
                "status": self.STATUS_INFEASIBLE,
                "assignments": [],
                "conflicts": conflicts,
                "errors": errors,
            }

        # Parse entities
        sessions_data = input_data.get("sessions_to_schedule", [])
        teachers_data = input_data.get("teachers", [])
        rooms_data = input_data.get("rooms", [])
        divisions_data = input_data.get("divisions", [])

        if not sessions_data:
            return {
                "status": self.STATUS_FEASIBLE,
                "assignments": [],
                "conflicts": [],
                "errors": [],
            }

        teachers_by_id: Dict[str, TeacherInfo] = {}
        for t in teachers_data:
            t_id = str(t["id"])
            teachers_by_id[t_id] = TeacherInfo(
                id=t_id,
                name=t.get("name", t_id),
                employee_code=t.get("employee_code", t_id),
                qualified_subject_ids={str(s) for s in t.get("qualified_subject_ids", [])},
                unavailable_slots={
                    (u["day"].upper(), u["start_time"], u["end_time"])
                    for u in t.get("unavailable_slots", [])
                },
                leave_days={d.upper() for d in t.get("leave_days", [])},
            )

        rooms_by_id: Dict[str, RoomInfo] = {}
        for r in rooms_data:
            r_id = str(r["id"])
            status = str(r.get("status", "AVAILABLE")).upper()
            rooms_by_id[r_id] = RoomInfo(
                id=r_id,
                name=r.get("name", r_id),
                room_type=str(r.get("room_type", "CLASSROOM")).upper(),
                capacity=r.get("capacity", 60),
                status=status,
            )

        divisions_by_id: Dict[str, DivisionInfo] = {}
        for d in divisions_data:
            d_id = str(d["id"])
            divisions_by_id[d_id] = DivisionInfo(
                id=d_id,
                name=d.get("name", d_id),
                batch_ids=[str(b) for b in d.get("batch_ids", [])],
            )

        # Parse sessions
        sessions: List[SchedulingSession] = []
        for s in sessions_data:
            sessions.append(
                SchedulingSession(
                    id=str(s["id"]),
                    subject_id=str(s["subject_id"]),
                    division_id=str(s["division_id"]),
                    batch_id=str(s["batch_id"]) if s.get("batch_id") else None,
                    session_type=str(s.get("session_type", "LECTURE")).upper(),
                    duration_slots=int(s.get("duration_slots", 1)),
                    preferred_teacher_id=str(s["preferred_teacher_id"]) if s.get("preferred_teacher_id") else None,
                    preferred_room_id=str(s["preferred_room_id"]) if s.get("preferred_room_id") else None,
                    allowed_teacher_ids=[str(tid) for tid in s.get("allowed_teacher_ids", [])] if s.get("allowed_teacher_ids") else None,
                    allowed_room_ids=[str(rid) for rid in s.get("allowed_room_ids", [])] if s.get("allowed_room_ids") else None,
                )
            )

        # -------------------------------------------------------------
        # CP-SAT Model Construction
        # -------------------------------------------------------------
        model = cp_model.CpModel()

        # Variable map: session_id -> list of (var, timeslot, teacher_id, room_id)
        session_var_map: Dict[str, List[Tuple[Any, TimeSlot, str, str]]] = {
            s.id: [] for s in sessions
        }

        # Track usage per resource and timeslot
        teacher_slot_vars: Dict[Tuple[str, int], List[Any]] = {}
        room_slot_vars: Dict[Tuple[str, int], List[Any]] = {}
        division_slot_vars: Dict[Tuple[str, int], List[Any]] = {}
        batch_slot_vars: Dict[Tuple[str, int], List[Any]] = {}

        for s in sessions:
            # 1. Determine qualified teachers
            candidate_teachers: List[TeacherInfo] = []
            for t_info in teachers_by_id.values():
                if s.allowed_teacher_ids and t_info.id not in s.allowed_teacher_ids:
                    continue
                if s.subject_id in t_info.qualified_subject_ids:
                    candidate_teachers.append(t_info)

            if not candidate_teachers:
                err_msg = (
                    f"Session {s.id} (Subject: {s.subject_id}) has no qualified teachers "
                    f"assigned via TeacherSubject."
                )
                errors.append(err_msg)
                conflicts.append(f"UNASSIGNED_TEACHER: {err_msg}")
                continue

            # 2. Determine eligible rooms by session type
            candidate_rooms: List[RoomInfo] = []
            for r_info in rooms_by_id.values():
                if r_info.status != "AVAILABLE":
                    continue
                if s.allowed_room_ids and r_info.id not in s.allowed_room_ids:
                    continue

                if s.session_type == "PRACTICAL":
                    if r_info.room_type == "LABORATORY":
                        candidate_rooms.append(r_info)
                elif s.session_type in ("LECTURE", "TUTORIAL"):
                    if r_info.room_type == "CLASSROOM":
                        candidate_rooms.append(r_info)

            if not candidate_rooms:
                err_msg = (
                    f"Session {s.id} (Type: {s.session_type}) has no available matching "
                    f"{'LABORATORY' if s.session_type == 'PRACTICAL' else 'CLASSROOM'} resources."
                )
                errors.append(err_msg)
                conflicts.append(f"RESOURCE_UNAVAILABLE: {err_msg}")
                continue

            # 3. Create decision variables for valid combinations
            for slot in self.time_slots:
                for teacher in candidate_teachers:
                    # Teacher Leave Check
                    if slot.day in teacher.leave_days:
                        continue

                    # Teacher Availability Check (slot within unavailable range)
                    is_unavailable = False
                    for u_day, u_start, u_end in teacher.unavailable_slots:
                        if slot.day == u_day:
                            if not (slot.end_time <= u_start or slot.start_time >= u_end):
                                is_unavailable = True
                                break
                    if is_unavailable:
                        continue

                    for room in candidate_rooms:
                        var_name = f"x_{s.id}_{slot.slot_index}_{teacher.id[:8]}_{room.id[:8]}"
                        x_var = model.NewBoolVar(var_name)

                        session_var_map[s.id].append((x_var, slot, teacher.id, room.id))

                        # Record for teacher overlap
                        teacher_key = (teacher.id, slot.slot_index)
                        teacher_slot_vars.setdefault(teacher_key, []).append(x_var)

                        # Record for room overlap
                        room_key = (room.id, slot.slot_index)
                        room_slot_vars.setdefault(room_key, []).append(x_var)

                        # Record for division/batch overlap
                        if s.batch_id:
                            batch_key = (s.batch_id, slot.slot_index)
                            batch_slot_vars.setdefault(batch_key, []).append(x_var)
                        else:
                            div_key = (s.division_id, slot.slot_index)
                            division_slot_vars.setdefault(div_key, []).append(x_var)

        # If any session has 0 candidate variables, the model is immediately infeasible
        has_empty_candidates = False
        for s in sessions:
            if not session_var_map[s.id]:
                has_empty_candidates = True
                conflicts.append(f"UNSCHEDULEABLE_SESSION: Session {s.id} cannot be placed in any valid timeslot/resource combination.")

        if errors or has_empty_candidates:
            return {
                "status": self.STATUS_INFEASIBLE,
                "assignments": [],
                "conflicts": conflicts,
                "errors": errors,
            }

        # -------------------------------------------------------------
        # Constraints Application
        # -------------------------------------------------------------

        # 1. Exactly one assignment per session
        for s in sessions:
            vars_for_session = [item[0] for item in session_var_map[s.id]]
            model.AddExactlyOne(vars_for_session)

        # 2. Teacher no-overlap constraint
        for (t_id, slot_idx), vars_list in teacher_slot_vars.items():
            if len(vars_list) > 1:
                model.AddAtMostOne(vars_list)

        # 3. Room no-overlap constraint (classroom or laboratory)
        for (r_id, slot_idx), vars_list in room_slot_vars.items():
            if len(vars_list) > 1:
                model.AddAtMostOne(vars_list)

        # 4. Division and Batch no-overlap constraints
        for slot in self.time_slots:
            slot_idx = slot.slot_index
            for d_id, div_info in divisions_by_id.items():
                full_div_vars = division_slot_vars.get((d_id, slot_idx), [])
                if len(full_div_vars) > 1:
                    model.AddAtMostOne(full_div_vars)

                # Full-division session cannot overlap with any batch session of the same division
                for b_id in div_info.batch_ids:
                    batch_vars = batch_slot_vars.get((b_id, slot_idx), [])
                    if len(batch_vars) > 1:
                        model.AddAtMostOne(batch_vars)

                    if full_div_vars and batch_vars:
                        # sum(full_div_vars) + sum(batch_vars) <= 1
                        model.Add(sum(full_div_vars) + sum(batch_vars) <= 1)

        # -------------------------------------------------------------
        # Soft Constraints / Objective Formulation (Phase 8)
        # -------------------------------------------------------------
        # Organize timeslots by day in chronological order
        slots_by_day: Dict[str, List[TimeSlot]] = {}
        for slot in self.time_slots:
            slots_by_day.setdefault(slot.day, []).append(slot)
        for d in slots_by_day:
            slots_by_day[d].sort(key=lambda sl: sl.start_time)

        penalties: List[Any] = []
        opt = self.config.optimization

        if opt.enabled:
            # 1. SUBJECT_DISTRIBUTION
            # Penalize multiple sessions of the same subject on the same day for a division
            if opt.subject_distribution_weight > 0:
                div_subj_sessions: Dict[Tuple[str, str], List[SchedulingSession]] = {}
                for s in sessions:
                    div_subj_sessions.setdefault((s.division_id, s.subject_id), []).append(s)

                for (d_id, subj_id), s_list in div_subj_sessions.items():
                    if len(s_list) > 1:
                        for day, day_slots in slots_by_day.items():
                            day_slot_indices = {sl.slot_index for sl in day_slots}
                            day_vars = []
                            for s in s_list:
                                for x_var, slot, _, _ in session_var_map[s.id]:
                                    if slot.slot_index in day_slot_indices:
                                        day_vars.append(x_var)

                            if len(day_vars) > 1:
                                excess = model.NewIntVar(0, len(day_vars), f"excess_subj_{d_id[:8]}_{subj_id[:8]}_{day}")
                                model.Add(excess >= sum(day_vars) - 1)
                                model.Add(excess >= 0)
                                penalties.append(excess * opt.subject_distribution_weight)

            # 2. CONSECUTIVE_SAME_SUBJECT
            # Penalize consecutive sessions of the same subject for the same division/batch
            if opt.consecutive_subject_weight > 0:
                div_subj_sessions = {}
                for s in sessions:
                    div_subj_sessions.setdefault((s.division_id, s.subject_id), []).append(s)

                for (d_id, subj_id), s_list in div_subj_sessions.items():
                    if len(s_list) > 1:
                        for day, day_slots in slots_by_day.items():
                            for k in range(len(day_slots) - 1):
                                slot_k = day_slots[k]
                                slot_k1 = day_slots[k + 1]
                                if slot_k.end_time == slot_k1.start_time:
                                    vars_k = [x for s in s_list for x, sl, _, _ in session_var_map[s.id] if sl.slot_index == slot_k.slot_index]
                                    vars_k1 = [x for s in s_list for x, sl, _, _ in session_var_map[s.id] if sl.slot_index == slot_k1.slot_index]
                                    if vars_k and vars_k1:
                                        is_consec = model.NewBoolVar(f"consec_subj_{d_id[:8]}_{subj_id[:8]}_{day}_{k}")
                                        model.Add(sum(vars_k) + sum(vars_k1) <= 1 + is_consec)
                                        penalties.append(is_consec * opt.consecutive_subject_weight)

            # 3. TEACHER_CONSECUTIVE_CLASSES
            # Penalize consecutive teaching blocks for the same teacher
            if opt.teacher_consecutive_weight > 0:
                for t_id in teachers_by_id:
                    for day, day_slots in slots_by_day.items():
                        for k in range(len(day_slots) - 1):
                            slot_k = day_slots[k]
                            slot_k1 = day_slots[k + 1]
                            if slot_k.end_time == slot_k1.start_time:
                                vars_k = teacher_slot_vars.get((t_id, slot_k.slot_index), [])
                                vars_k1 = teacher_slot_vars.get((t_id, slot_k1.slot_index), [])
                                if vars_k and vars_k1:
                                    t_consec = model.NewBoolVar(f"t_consec_{t_id[:8]}_{day}_{k}")
                                    model.Add(sum(vars_k) + sum(vars_k1) <= 1 + t_consec)
                                    penalties.append(t_consec * opt.teacher_consecutive_weight)

            # 4. DIVISION_GAPS
            # Penalize idle gap slots between classes for the same division on a day
            if opt.division_gap_weight > 0:
                for d_id, div_info in divisions_by_id.items():
                    for day, day_slots in slots_by_day.items():
                        m = len(day_slots)
                        if m >= 3:
                            occ_vars: List[Any] = []
                            for slot in day_slots:
                                d_vars = division_slot_vars.get((d_id, slot.slot_index), [])
                                b_vars = [bv for b_id in div_info.batch_ids for bv in batch_slot_vars.get((b_id, slot.slot_index), [])]
                                all_slot_div_vars = d_vars + b_vars
                                if not all_slot_div_vars:
                                    occ_k = model.NewBoolVar(f"occ_zero_{d_id[:8]}_{day}_{slot.slot_index}")
                                    model.Add(occ_k == 0)
                                    occ_vars.append(occ_k)
                                elif len(all_slot_div_vars) == 1:
                                    occ_vars.append(all_slot_div_vars[0])
                                else:
                                    occ_k = model.NewBoolVar(f"occ_{d_id[:8]}_{day}_{slot.slot_index}")
                                    model.Add(occ_k == sum(all_slot_div_vars))
                                    occ_vars.append(occ_k)

                            prefix_active: List[Any] = [None] * m
                            prefix_active[0] = occ_vars[0]
                            for k in range(1, m):
                                p_var = model.NewBoolVar(f"pref_{d_id[:8]}_{day}_{k}")
                                model.AddMaxEquality(p_var, [prefix_active[k - 1], occ_vars[k]])
                                prefix_active[k] = p_var

                            suffix_active: List[Any] = [None] * m
                            suffix_active[m - 1] = occ_vars[m - 1]
                            for k in range(m - 2, -1, -1):
                                s_var = model.NewBoolVar(f"suff_{d_id[:8]}_{day}_{k}")
                                model.AddMaxEquality(s_var, [suffix_active[k + 1], occ_vars[k]])
                                suffix_active[k] = s_var

                            for k in range(1, m - 1):
                                is_gap = model.NewBoolVar(f"gap_{d_id[:8]}_{day}_{k}")
                                model.AddBoolAnd([prefix_active[k - 1], suffix_active[k + 1], occ_vars[k].Not()]).OnlyEnforceIf(is_gap)
                                model.AddBoolOr([prefix_active[k - 1].Not(), suffix_active[k + 1].Not(), occ_vars[k]]).OnlyEnforceIf(is_gap.Not())
                                penalties.append(is_gap * opt.division_gap_weight)

            # 5. DAILY_LOAD_BALANCE
            # Penalize uneven number of sessions across days for the same division
            if opt.daily_load_balance_weight > 0 and len(slots_by_day) > 1:
                for d_id, div_info in divisions_by_id.items():
                    day_loads: List[Any] = []
                    max_possible = max(len(s_list) for s_list in slots_by_day.values())
                    for day, day_slots in slots_by_day.items():
                        day_div_vars = []
                        for slot in day_slots:
                            day_div_vars.extend(division_slot_vars.get((d_id, slot.slot_index), []))
                            for b_id in div_info.batch_ids:
                                day_div_vars.extend(batch_slot_vars.get((b_id, slot.slot_index), []))
                        day_loads.append(sum(day_div_vars))

                    max_load = model.NewIntVar(0, max_possible, f"max_load_{d_id[:8]}")
                    min_load = model.NewIntVar(0, max_possible, f"min_load_{d_id[:8]}")
                    for dl in day_loads:
                        model.Add(max_load >= dl)
                        model.Add(min_load <= dl)

                    load_diff = model.NewIntVar(0, max_possible, f"load_diff_{d_id[:8]}")
                    model.Add(load_diff == max_load - min_load)
                    penalties.append(load_diff * opt.daily_load_balance_weight)

        if penalties:
            model.Minimize(sum(penalties))

        # -------------------------------------------------------------
        # Solve Model
        # -------------------------------------------------------------
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.config.time_limit_seconds
        solver.parameters.random_seed = self.config.random_seed
        if self.config.deterministic:
            solver.parameters.num_search_workers = 1

        solver_status = solver.Solve(model)

        if solver_status == cp_model.OPTIMAL:
            status_str = self.STATUS_OPTIMAL
        elif solver_status == cp_model.FEASIBLE:
            status_str = self.STATUS_FEASIBLE
        elif solver_status == cp_model.INFEASIBLE:
            status_str = self.STATUS_INFEASIBLE
        else:
            status_str = self.STATUS_UNKNOWN

        if solver_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            assignments = []
            for s in sessions:
                for x_var, slot, teacher_id, room_id in session_var_map[s.id]:
                    if solver.Value(x_var) == 1:
                        room_info = rooms_by_id[room_id]
                        assignments.append(
                            {
                                "session_id": s.id,
                                "subject_id": s.subject_id,
                                "division_id": s.division_id,
                                "batch_id": s.batch_id,
                                "teacher_id": teacher_id,
                                "room_id": room_id,
                                "classroom_id": room_id if room_info.room_type == "CLASSROOM" else None,
                                "laboratory_id": room_id if room_info.room_type == "LABORATORY" else None,
                                "day": slot.day,
                                "start_time": slot.start_time,
                                "end_time": slot.end_time,
                                "session_type": s.session_type,
                            }
                        )
                        break

            res: Dict[str, Any] = {
                "status": status_str,
                "assignments": assignments,
                "conflicts": [],
                "errors": [],
            }
            if penalties and opt.enabled:
                res["objective_value"] = solver.ObjectiveValue()
            return res
        elif solver_status == cp_model.INFEASIBLE:
            return {
                "status": self.STATUS_INFEASIBLE,
                "assignments": [],
                "conflicts": ["MODEL_INFEASIBLE: Constraints cannot be simultaneously satisfied."],
                "errors": ["Schedule generation is infeasible under current constraints."],
            }
        else:
            return {
                "status": self.STATUS_UNKNOWN,
                "assignments": [],
                "conflicts": ["SOLVER_LIMIT: Solver reached time limit or returned unknown state."],
                "errors": ["Unable to determine feasibility within time limit."],
            }

    @classmethod
    def build_input_from_models(
        cls,
        semester: Any,
        sessions_to_schedule: Optional[List[Dict[str, Any]]] = None,
        config: Optional[SolverConfig] = None,
    ) -> Dict[str, Any]:
        """
        Extracts structured solver input from existing Django database models for a given Semester.
        """
        from academics.models import (
            Classroom,
            Division,
            Laboratory,
            PracticalBatch,
            Subject,
            TeacherAvailability,
            TeacherLeave,
            TeacherSubject,
        )
        from accounts.models import TeacherProfile

        # 1. Divisions and Batches
        divisions = list(Division.objects.filter(semester=semester).prefetch_related("batches"))
        divisions_data = []
        for d in divisions:
            divisions_data.append(
                {
                    "id": str(d.id),
                    "name": d.name,
                    "batch_ids": [str(b.id) for b in d.batches.all()],
                }
            )

        # 2. Subjects
        subjects = list(Subject.objects.filter(program=semester.program))
        subject_ids = [s.id for s in subjects]

        # 3. Teachers with TeacherSubject qualification, Availabilities, and Approved Leaves
        teacher_subjects = list(
            TeacherSubject.objects.filter(subject_id__in=subject_ids).select_related("teacher", "teacher__user")
        )
        qualified_by_teacher: Dict[str, Set[str]] = {}
        teacher_profiles: Dict[str, TeacherProfile] = {}
        for ts in teacher_subjects:
            t_id = str(ts.teacher_id)
            qualified_by_teacher.setdefault(t_id, set()).add(str(ts.subject_id))
            teacher_profiles[t_id] = ts.teacher

        teachers_data = []
        for t_id, t_profile in teacher_profiles.items():
            availabilities = list(
                TeacherAvailability.objects.filter(teacher=t_profile, is_available=False)
            )
            leaves = list(
                TeacherLeave.objects.filter(teacher=t_profile, status=TeacherLeave.Status.APPROVED)
            )

            leave_days = set()
            for l in leaves:
                # If leave covers specific dates, map to days of week if applicable or record directly
                pass

            teachers_data.append(
                {
                    "id": t_id,
                    "name": t_profile.user.get_full_name() or t_profile.user.username,
                    "employee_code": t_profile.employee_code,
                    "qualified_subject_ids": list(qualified_by_teacher.get(t_id, set())),
                    "unavailable_slots": [
                        {
                            "day": a.day,
                            "start_time": str(a.start_time),
                            "end_time": str(a.end_time),
                        }
                        for a in availabilities
                    ],
                    "leave_days": list(leave_days),
                }
            )

        # 4. Rooms: Classrooms & Laboratories
        rooms_data = []
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

        return {
            "semester_id": str(semester.id),
            "academic_year": semester.academic_year,
            "divisions": divisions_data,
            "teachers": teachers_data,
            "rooms": rooms_data,
            "sessions_to_schedule": sessions_to_schedule or [],
        }
