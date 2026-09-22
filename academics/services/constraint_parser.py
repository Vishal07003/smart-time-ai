"""
Natural-Language Constraint Parsing Service for SMART-TIME AI (Phase 9A).

Converts natural-language timetable requirements into validated, typed structured
constraint objects for Staff users.
Does NOT generate timetables or replace OR-Tools CP-SAT.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
import json
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union


class ConstraintType(str, Enum):
    TEACHER_TIME_RESTRICTION = "TEACHER_TIME_RESTRICTION"
    TEACHER_DAY_RESTRICTION = "TEACHER_DAY_RESTRICTION"
    SUBJECT_DAY_RESTRICTION = "SUBJECT_DAY_RESTRICTION"
    SUBJECT_TIME_PREFERENCE = "SUBJECT_TIME_PREFERENCE"
    DIVISION_TIME_RESTRICTION = "DIVISION_TIME_RESTRICTION"
    SESSION_TIME_PREFERENCE = "SESSION_TIME_PREFERENCE"


class ConstraintMode(str, Enum):
    AVOID = "AVOID"
    PREFER = "PREFER"


class TimeRange(str, Enum):
    MORNING = "MORNING"       # 09:00 - 12:00
    AFTERNOON = "AFTERNOON"   # 12:00 - 16:00
    EVENING = "EVENING"       # 16:00 - 19:00


class SessionType(str, Enum):
    LECTURE = "LECTURE"
    PRACTICAL = "PRACTICAL"
    TUTORIAL = "TUTORIAL"


VALID_DAYS: Set[str] = {
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
}

TIME_RANGE_DEFAULTS: Dict[str, Tuple[str, str]] = {
    "MORNING": ("09:00", "12:00"),
    "AFTERNOON": ("12:00", "16:00"),
    "EVENING": ("16:00", "19:00"),
}


@dataclass
class StructuredConstraint:
    """Represents a validated, typed timetable scheduling constraint."""
    constraint_type: str
    mode: str = ConstraintMode.AVOID.value
    teacher: Optional[str] = None
    teacher_id: Optional[str] = None
    subject: Optional[str] = None
    subject_id: Optional[str] = None
    division: Optional[str] = None
    division_id: Optional[str] = None
    session_type: Optional[str] = None
    day: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    time_range: Optional[str] = None
    raw_instruction: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes constraint to a clean dictionary."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ParseResult:
    """Result of parsing and validating a natural-language constraint."""
    success: bool
    constraint: Optional[StructuredConstraint] = None
    errors: List[str] = field(default_factory=list)
    raw_llm_response: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "constraint": self.constraint.to_dict() if self.constraint else None,
            "errors": self.errors,
        }


@dataclass
class ParsingContext:
    """Academic context for entity validation and fuzzy resolution."""
    teachers: List[Dict[str, Any]] = field(default_factory=list)   # [{"id": "...", "name": "...", "employee_code": "..."}]
    subjects: List[Dict[str, Any]] = field(default_factory=list)   # [{"id": "...", "name": "...", "code": "..."}]
    divisions: List[Dict[str, Any]] = field(default_factory=list)  # [{"id": "...", "name": "..."}]
    allowed_days: List[str] = field(
        default_factory=lambda: ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]
    )


class ConstraintParserService:
    """
    Provider-agnostic natural language constraint parsing and validation service.
    """

    def __init__(self, llm_provider: Optional[Callable[[str, Optional[ParsingContext]], Dict[str, Any]]] = None):
        self.llm_provider = llm_provider

    def parse(
        self,
        instruction: str,
        context: Optional[ParsingContext] = None,
        llm_output: Optional[Union[Dict[str, Any], str]] = None,
    ) -> ParseResult:
        """
        Parses a natural-language constraint instruction and validates it.
        If `llm_output` is provided directly, validates the pre-parsed dictionary.
        Otherwise, uses the configured LLM provider or rule-based parser.
        """
        raw_text = (instruction or "").strip()
        errors: List[str] = []

        # 1. Handle pre-supplied or LLM output
        data: Optional[Dict[str, Any]] = None
        if llm_output is not None:
            if isinstance(llm_output, str):
                try:
                    data = json.loads(llm_output)
                except Exception as e:
                    return ParseResult(
                        success=False,
                        errors=[f"Malformed LLM JSON output: {str(e)}"],
                        raw_llm_response=llm_output,
                    )
            elif isinstance(llm_output, dict):
                data = llm_output
            else:
                return ParseResult(
                    success=False,
                    errors=[f"Malformed constraint data: expected dict or JSON string, got {type(llm_output).__name__}."],
                    raw_llm_response=llm_output,
                )
        elif self.llm_provider is not None:
            try:
                data = self.llm_provider(raw_text, context)
            except Exception as e:
                return ParseResult(
                    success=False,
                    errors=[f"LLM Provider execution error: {str(e)}"],
                )
        else:
            # Rule-based / pattern NLU fallback
            data = self._rule_based_parse(raw_text, context)
            if data is None:
                return ParseResult(
                    success=False,
                    errors=[f"Could not extract a supported timetable constraint from: '{raw_text}'."],
                )

        # 2. Validate structured data
        return self.validate_constraint_data(data, context=context, raw_text=raw_text)

    def validate_constraint_data(
        self,
        data: Any,
        context: Optional[ParsingContext] = None,
        raw_text: Optional[str] = None,
    ) -> ParseResult:
        """
        Validates raw structured constraint dictionary against supported constraint schema and academic context.
        """
        if not isinstance(data, dict):
            return ParseResult(
                success=False,
                errors=[f"Malformed constraint data: expected dict, got {type(data).__name__}."],
                raw_llm_response=data,
            )

        errors: List[str] = []

        # 1. Validate constraint_type
        raw_type = data.get("constraint_type")
        if not raw_type or not isinstance(raw_type, str):
            errors.append("Missing or invalid 'constraint_type' field.")
            return ParseResult(success=False, errors=errors, raw_llm_response=data)

        normalized_type = raw_type.strip().upper()
        supported_types = {t.value for t in ConstraintType}
        if normalized_type not in supported_types:
            errors.append(
                f"Unsupported constraint_type '{raw_type}'. Supported types: {sorted(list(supported_types))}."
            )
            return ParseResult(success=False, errors=errors, raw_llm_response=data)

        # 2. Validate mode
        raw_mode = data.get("mode", "AVOID")
        if not isinstance(raw_mode, str):
            errors.append("Field 'mode' must be a string ('AVOID' or 'PREFER').")
            normalized_mode = "AVOID"
        else:
            normalized_mode = raw_mode.strip().upper()
            if normalized_mode not in (ConstraintMode.AVOID.value, ConstraintMode.PREFER.value):
                errors.append(f"Invalid mode '{raw_mode}'. Must be 'AVOID' or 'PREFER'.")

        # 3. Validate day
        raw_day = data.get("day")
        normalized_day: Optional[str] = None
        if raw_day:
            if not isinstance(raw_day, str):
                errors.append("Field 'day' must be a string.")
            else:
                day_upper = raw_day.strip().upper()
                day_map = {
                    "MON": "MONDAY", "MONDAY": "MONDAY",
                    "TUE": "TUESDAY", "TUES": "TUESDAY", "TUESDAY": "TUESDAY",
                    "WED": "WEDNESDAY", "WEDNESDAY": "WEDNESDAY",
                    "THU": "THURSDAY", "THUR": "THURSDAY", "THURSDAY": "THURSDAY",
                    "FRI": "FRIDAY", "FRIDAY": "FRIDAY",
                    "SAT": "SATURDAY", "SATURDAY": "SATURDAY",
                    "SUN": "SUNDAY", "SUNDAY": "SUNDAY",
                }
                if day_upper in day_map:
                    normalized_day = day_map[day_upper]
                    if context and context.allowed_days and normalized_day not in context.allowed_days:
                        errors.append(f"Day '{normalized_day}' is not in allowed working days: {context.allowed_days}.")
                else:
                    errors.append(f"Invalid day '{raw_day}'. Valid days: {sorted(list(VALID_DAYS))}.")

        # 4. Validate time_range and start_time / end_time
        raw_time_range = data.get("time_range")
        normalized_time_range: Optional[str] = None
        if raw_time_range:
            if not isinstance(raw_time_range, str):
                errors.append("Field 'time_range' must be a string.")
            else:
                tr_upper = raw_time_range.strip().upper()
                if tr_upper in {r.value for r in TimeRange}:
                    normalized_time_range = tr_upper
                else:
                    errors.append(
                        f"Invalid time_range '{raw_time_range}'. Supported ranges: {[r.value for r in TimeRange]}."
                    )

        raw_start_time = data.get("start_time")
        raw_end_time = data.get("end_time")

        # If time_range provided and times missing, apply defaults
        if normalized_time_range and not raw_start_time and not raw_end_time:
            def_start, def_end = TIME_RANGE_DEFAULTS.get(normalized_time_range, (None, None))
            raw_start_time = def_start
            raw_end_time = def_end

        norm_start_time = self._validate_and_format_time(raw_start_time, "start_time", errors)
        norm_end_time = self._validate_and_format_time(raw_end_time, "end_time", errors)

        if norm_start_time and norm_end_time:
            if norm_start_time >= norm_end_time:
                errors.append(f"start_time ({norm_start_time}) must be strictly before end_time ({norm_end_time}).")

        # 5. Validate session_type
        raw_session_type = data.get("session_type")
        normalized_session_type: Optional[str] = None
        if raw_session_type:
            if not isinstance(raw_session_type, str):
                errors.append("Field 'session_type' must be a string.")
            else:
                st_upper = raw_session_type.strip().upper()
                if st_upper in {s.value for s in SessionType}:
                    normalized_session_type = st_upper
                else:
                    errors.append(
                        f"Invalid session_type '{raw_session_type}'. Supported types: {[s.value for s in SessionType]}."
                    )

        # 6. Entity References & Resolution (Teacher, Subject, Division)
        teacher_name = data.get("teacher")
        teacher_id = data.get("teacher_id")
        resolved_teacher, resolved_teacher_id = self._resolve_teacher(
            teacher_name, teacher_id, context, errors
        )

        subject_name = data.get("subject")
        subject_id = data.get("subject_id")
        resolved_subject, resolved_subject_id = self._resolve_subject(
            subject_name, subject_id, context, errors
        )

        division_name = data.get("division")
        division_id = data.get("division_id")
        resolved_division, resolved_division_id = self._resolve_division(
            division_name, division_id, context, errors
        )

        # 7. Constraint-Type Specific Completeness Checks
        if normalized_type in (
            ConstraintType.TEACHER_TIME_RESTRICTION.value,
            ConstraintType.TEACHER_DAY_RESTRICTION.value,
        ):
            if not resolved_teacher and not resolved_teacher_id:
                errors.append(f"{normalized_type} requires a valid 'teacher' or 'teacher_id'.")

            if normalized_type == ConstraintType.TEACHER_DAY_RESTRICTION.value and not normalized_day:
                errors.append(f"{normalized_type} requires a valid 'day'.")

            if normalized_type == ConstraintType.TEACHER_TIME_RESTRICTION.value:
                if not normalized_day and not norm_start_time and not normalized_time_range:
                    errors.append(f"{normalized_type} requires 'day' and/or time bounds ('start_time', 'time_range').")

        elif normalized_type == ConstraintType.SUBJECT_DAY_RESTRICTION.value:
            if not resolved_subject and not resolved_subject_id:
                errors.append(f"{normalized_type} requires a valid 'subject' or 'subject_id'.")
            if not normalized_day:
                errors.append(f"{normalized_type} requires a valid 'day'.")

        elif normalized_type == ConstraintType.SUBJECT_TIME_PREFERENCE.value:
            if not resolved_subject and not resolved_subject_id:
                errors.append(f"{normalized_type} requires a valid 'subject' or 'subject_id'.")
            if not norm_start_time and not normalized_time_range and not normalized_day:
                errors.append(f"{normalized_type} requires 'time_range', 'start_time', or 'day'.")

        elif normalized_type == ConstraintType.DIVISION_TIME_RESTRICTION.value:
            if not resolved_division and not resolved_division_id:
                errors.append(f"{normalized_type} requires a valid 'division' or 'division_id'.")
            if not normalized_day and not norm_start_time and not normalized_time_range:
                errors.append(f"{normalized_type} requires 'day' and/or time bounds.")

        elif normalized_type == ConstraintType.SESSION_TIME_PREFERENCE.value:
            if not normalized_session_type:
                errors.append(f"{normalized_type} requires a valid 'session_type' (e.g. LECTURE, PRACTICAL, TUTORIAL).")
            if not norm_start_time and not normalized_time_range and not normalized_day:
                errors.append(f"{normalized_type} requires 'time_range', 'start_time', or 'day'.")

        if errors:
            return ParseResult(
                success=False,
                errors=errors,
                raw_llm_response=data,
            )

        constraint = StructuredConstraint(
            constraint_type=normalized_type,
            mode=normalized_mode,
            teacher=resolved_teacher,
            teacher_id=resolved_teacher_id,
            subject=resolved_subject,
            subject_id=resolved_subject_id,
            division=resolved_division,
            division_id=resolved_division_id,
            session_type=normalized_session_type,
            day=normalized_day,
            start_time=norm_start_time,
            end_time=norm_end_time,
            time_range=normalized_time_range,
            raw_instruction=raw_text or data.get("raw_instruction"),
            metadata=data.get("metadata", {}),
        )

        return ParseResult(
            success=True,
            constraint=constraint,
            errors=[],
            raw_llm_response=data,
        )

    # -----------------------------------------------------------------
    # Helper Validation & Resolution Routines
    # -----------------------------------------------------------------

    def _validate_and_format_time(
        self,
        time_str: Any,
        field_name: str,
        errors: List[str],
    ) -> Optional[str]:
        """Validates and formats HH:MM or HH:MM:SS time string to HH:MM."""
        if not time_str:
            return None
        if not isinstance(time_str, str):
            errors.append(f"Field '{field_name}' must be a string, got {type(time_str).__name__}.")
            return None

        clean = time_str.strip()
        m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", clean)
        if not m:
            errors.append(f"Invalid {field_name} format '{time_str}'. Expected 'HH:MM' (24-hour).")
            return None

        hr = int(m.group(1))
        mn = int(m.group(2))
        if hr < 0 or hr > 23 or mn < 0 or mn > 59:
            errors.append(f"Invalid time values in {field_name} '{time_str}' (hour: 0-23, minute: 0-59).")
            return None

        return f"{hr:02d}:{mn:02d}"

    def _resolve_teacher(
        self,
        name: Optional[str],
        t_id: Optional[str],
        context: Optional[ParsingContext],
        errors: List[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Resolves teacher name/ID against parsing context."""
        if not name and not t_id:
            return None, None

        if not context or not context.teachers:
            return (name.strip() if isinstance(name, str) else None), (str(t_id).strip() if t_id else None)

        target_name = (name or "").strip().lower()
        target_id = str(t_id).strip() if t_id else None

        if target_id:
            for t in context.teachers:
                if str(t.get("id")) == target_id:
                    return t.get("name", name), target_id

        exact_matches = []
        partial_matches = []
        for t in context.teachers:
            t_name = str(t.get("name", "")).strip().lower()
            t_code = str(t.get("employee_code", "")).strip().lower()
            if target_name and (target_name == t_name or target_name == t_code):
                exact_matches.append(t)
            elif target_name and (target_name in t_name or t_name in target_name):
                partial_matches.append(t)

        if exact_matches:
            if len(exact_matches) == 1:
                return exact_matches[0].get("name"), str(exact_matches[0].get("id"))
            else:
                matched_names = [f"{m.get('name')} (ID: {m.get('id')})" for m in exact_matches]
                errors.append(
                    f"Ambiguous teacher reference '{name}'. Matches multiple teachers: {', '.join(matched_names)}."
                )
                return name, None
        elif partial_matches:
            if len(partial_matches) == 1:
                return partial_matches[0].get("name"), str(partial_matches[0].get("id"))
            else:
                matched_names = [f"{m.get('name')} (ID: {m.get('id')})" for m in partial_matches]
                errors.append(
                    f"Ambiguous teacher reference '{name}'. Matches multiple teachers: {', '.join(matched_names)}."
                )
                return name, None
        else:
            errors.append(f"Unknown teacher '{name}'. No matching teacher found in academic context.")
            return name, None

    def _resolve_subject(
        self,
        name: Optional[str],
        s_id: Optional[str],
        context: Optional[ParsingContext],
        errors: List[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Resolves subject name/ID against parsing context."""
        if not name and not s_id:
            return None, None

        if not context or not context.subjects:
            return (name.strip() if isinstance(name, str) else None), (str(s_id).strip() if s_id else None)

        target_name = (name or "").strip().lower()
        target_id = str(s_id).strip() if s_id else None

        if target_id:
            for s in context.subjects:
                if str(s.get("id")) == target_id:
                    return s.get("name", name), target_id

        exact_matches = []
        partial_matches = []
        for s in context.subjects:
            s_name = str(s.get("name", "")).strip().lower()
            s_code = str(s.get("code", "")).strip().lower()
            if target_name and (target_name == s_name or target_name == s_code):
                exact_matches.append(s)
            elif target_name and (target_name in s_name or s_name in target_name):
                partial_matches.append(s)

        if exact_matches:
            if len(exact_matches) == 1:
                return exact_matches[0].get("name"), str(exact_matches[0].get("id"))
            else:
                matched_names = [f"{m.get('name')} ({m.get('code')})" for m in exact_matches]
                errors.append(
                    f"Ambiguous subject reference '{name}'. Matches multiple subjects: {', '.join(matched_names)}."
                )
                return name, None
        elif partial_matches:
            if len(partial_matches) == 1:
                return partial_matches[0].get("name"), str(partial_matches[0].get("id"))
            else:
                matched_names = [f"{m.get('name')} ({m.get('code')})" for m in partial_matches]
                errors.append(
                    f"Ambiguous subject reference '{name}'. Matches multiple subjects: {', '.join(matched_names)}."
                )
                return name, None
        else:
            errors.append(f"Unknown subject '{name}'. No matching subject found in academic context.")
            return name, None

    def _resolve_division(
        self,
        name: Optional[str],
        d_id: Optional[str],
        context: Optional[ParsingContext],
        errors: List[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Resolves division name/ID against parsing context."""
        if not name and not d_id:
            return None, None

        if not context or not context.divisions:
            return (name.strip() if isinstance(name, str) else None), (str(d_id).strip() if d_id else None)

        target_name = (name or "").strip().lower()
        target_id = str(d_id).strip() if d_id else None

        if target_id:
            for d in context.divisions:
                if str(d.get("id")) == target_id:
                    return d.get("name", name), target_id

        exact_matches = []
        partial_matches = []
        for d in context.divisions:
            d_name = str(d.get("name", "")).strip().lower()
            if target_name and target_name == d_name:
                exact_matches.append(d)
            elif target_name and (target_name in d_name or d_name in target_name):
                partial_matches.append(d)

        if exact_matches:
            if len(exact_matches) == 1:
                return exact_matches[0].get("name"), str(exact_matches[0].get("id"))
            else:
                matched_names = [f"{m.get('name')}" for m in exact_matches]
                errors.append(
                    f"Ambiguous division reference '{name}'. Matches multiple divisions: {', '.join(matched_names)}."
                )
                return name, None
        elif partial_matches:
            if len(partial_matches) == 1:
                return partial_matches[0].get("name"), str(partial_matches[0].get("id"))
            else:
                matched_names = [f"{m.get('name')}" for m in partial_matches]
                errors.append(
                    f"Ambiguous division reference '{name}'. Matches multiple divisions: {', '.join(matched_names)}."
                )
                return name, None
        else:
            errors.append(f"Unknown division '{name}'. No matching division found in academic context.")
            return name, None

    # -----------------------------------------------------------------
    # Rule-Based / Pattern NLU Parser (Deterministic Offline Engine)
    # -----------------------------------------------------------------

    def _rule_based_parse(
        self,
        text: str,
        context: Optional[ParsingContext] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Deterministic pattern extraction for English/Hinglish natural language instructions.
        """
        clean_text = text.strip()
        lower = clean_text.lower()

        if not clean_text or len(clean_text) < 3:
            return None

        # 1. Determine Mode: AVOID vs PREFER
        mode = "AVOID"
        avoid_keywords = ["avoid", "mat do", "mat", "no ", "not ", "nahi", "don't", "dont", "restrict", "never", "off"]
        prefer_keywords = ["prefer", "chahiye", "rakho", "only", "first", "best", "want", "like"]

        is_avoid = any(k in lower for k in avoid_keywords)
        is_prefer = any(k in lower for k in prefer_keywords)

        if is_prefer and not is_avoid:
            mode = "PREFER"
        else:
            mode = "AVOID"

        # 2. Extract Day
        day = None
        day_patterns = [
            (r"\bmonday\b|\bmon\b|\bsomwar\b", "MONDAY"),
            (r"\btuesday\b|\btue\b|\bmangalwar\b", "TUESDAY"),
            (r"\bwednesday\b|\bwed\b|\bbudhwar\b", "WEDNESDAY"),
            (r"\bthursday\b|\bthu\b|\bguruwar\b", "THURSDAY"),
            (r"\bfriday\b|\bfri\b|\bshukrawar\b", "FRIDAY"),
            (r"\bsaturday\b|\bsat\b|\bshaniwar\b", "SATURDAY"),
        ]
        for pat, d_val in day_patterns:
            if re.search(pat, lower):
                day = d_val
                break

        # 3. Extract Time Range / Explicit Times
        time_range = None
        if "morning" in lower or "subah" in lower or "first half" in lower:
            time_range = "MORNING"
        elif "afternoon" in lower or "dophar" in lower or "post lunch" in lower or "second half" in lower:
            time_range = "AFTERNOON"
        elif "evening" in lower or "sham" in lower or "shaam" in lower:
            time_range = "EVENING"

        time_match = re.search(r"(\d{1,2}(?::\d{2})?)\s*(?:to|-|till|se)\s*(\d{1,2}(?::\d{2})?)", lower)
        start_time = None
        end_time = None
        if time_match:
            t1, t2 = time_match.group(1), time_match.group(2)
            start_time = t1 if ":" in t1 else f"{int(t1):02d}:00"
            end_time = t2 if ":" in t2 else f"{int(t2):02d}:00"

        # 4. Extract Session Type
        session_type = None
        if "practical" in lower or "lab" in lower:
            session_type = "PRACTICAL"
        elif "lecture" in lower or "theory" in lower:
            session_type = "LECTURE"
        elif "tutorial" in lower:
            session_type = "TUTORIAL"

        # 5. Determine Target Entity (Teacher vs Subject vs Division vs SessionType)
        matched_teacher = None
        matched_subject = None
        matched_division = None

        if context:
            # Check subjects
            exact_subjs = []
            partial_subjs = []
            for s in context.subjects:
                s_name = str(s.get("name", "")).strip().lower()
                s_code = str(s.get("code", "")).strip().lower()
                first_word = s_name.split()[0] if s_name else ""
                if (s_name and s_name in lower) or (s_code and s_code in lower):
                    exact_subjs.append(s)
                elif len(first_word) >= 3 and re.search(rf"\b{re.escape(first_word)}\b", lower):
                    partial_subjs.append(s)

            # Check teachers
            exact_teachers = []
            partial_teachers = []
            for t in context.teachers:
                t_name = str(t.get("name", "")).strip().lower()
                t_code = str(t.get("employee_code", "")).strip().lower()
                first_name = t_name.split()[0] if t_name else ""
                if (t_name and t_name in lower) or (t_code and t_code in lower):
                    exact_teachers.append(t)
                elif len(first_name) >= 3 and re.search(rf"\b{re.escape(first_name)}\b", lower):
                    partial_teachers.append(t)

            # Check divisions
            exact_divs = []
            partial_divs = []
            for d in context.divisions:
                d_name = str(d.get("name", "")).strip().lower()
                if d_name and d_name in lower:
                    exact_divs.append(d)
                elif re.search(rf"\b{re.escape(d_name)}\b", lower):
                    partial_divs.append(d)

            if exact_subjs:
                matched_subject = exact_subjs[0].get("name")
            elif partial_subjs:
                if len(partial_subjs) == 1:
                    matched_subject = partial_subjs[0].get("name")
                else:
                    for s in partial_subjs:
                        first_word = str(s.get("name", "")).split()[0]
                        if re.search(rf"\b{re.escape(first_word.lower())}\b", lower):
                            matched_subject = first_word
                            break

            if not matched_subject:
                if exact_teachers:
                    matched_teacher = exact_teachers[0].get("name")
                elif partial_teachers:
                    if len(partial_teachers) == 1:
                        matched_teacher = partial_teachers[0].get("name")
                    else:
                        for t in partial_teachers:
                            first_name = str(t.get("name", "")).split()[0]
                            if re.search(rf"\b{re.escape(first_name.lower())}\b", lower):
                                matched_teacher = first_name
                                break
                        if not matched_teacher:
                            matched_teacher = partial_teachers[0].get("name")

            if not matched_teacher and not matched_subject:
                if exact_divs:
                    matched_division = exact_divs[0].get("name")
                elif partial_divs:
                    matched_division = partial_divs[0].get("name")

        # Fallback entity matching via regex keywords
        if not matched_teacher and not matched_subject and not matched_division:
            subj_match = re.search(r"\b(java|python|dsa|data structures|maths|mathematics|physics|chemistry|os|dbms|networks)\b", lower)
            if subj_match:
                matched_subject = subj_match.group(1).capitalize()
            else:
                teacher_match = re.search(r"(?:prof\.?|dr\.?|teacher)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)", clean_text, re.IGNORECASE)
                if teacher_match:
                    matched_teacher = teacher_match.group(1).strip()
                else:
                    h_teacher = re.search(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:ko|sir|ma'am|mam)", clean_text)
                    if h_teacher:
                        cand = h_teacher.group(1).strip()
                        if cand.upper() not in VALID_DAYS:
                            matched_teacher = cand

                div_match = re.search(r"\b(div(?:ision)?[\s\-_]?[a-z0-9]+)\b", lower)
                if div_match:
                    matched_division = div_match.group(1).upper()

        # Fallback entity matching via regex keywords
        if not matched_teacher and not matched_subject and not matched_division:
            # Check for subject indicators e.g. "Java", "Maths", "Python", "Physics", "Data Structures"
            subj_match = re.search(r"\b(java|python|dsa|data structures|maths|mathematics|physics|chemistry|os|dbms|networks)\b", lower)
            if subj_match:
                matched_subject = subj_match.group(1).capitalize()
            else:
                teacher_match = re.search(r"(?:prof\.?|dr\.?|teacher)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)", clean_text, re.IGNORECASE)
                if teacher_match:
                    matched_teacher = teacher_match.group(1).strip()
                else:
                    h_teacher = re.search(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:ko|sir|ma'am|mam)", clean_text)
                    if h_teacher:
                        cand = h_teacher.group(1).strip()
                        if cand.upper() not in VALID_DAYS:
                            matched_teacher = cand

                div_match = re.search(r"\b(div(?:ision)?[\s\-_]?[a-z0-9]+)\b", lower)
                if div_match:
                    matched_division = div_match.group(1).upper()

        # 6. Classify Constraint Type
        if session_type and not matched_teacher and not matched_subject and not matched_division:
            return {
                "constraint_type": ConstraintType.SESSION_TIME_PREFERENCE.value,
                "session_type": session_type,
                "day": day,
                "time_range": time_range,
                "start_time": start_time,
                "end_time": end_time,
                "mode": mode,
            }

        if matched_teacher:
            if time_range or start_time:
                return {
                    "constraint_type": ConstraintType.TEACHER_TIME_RESTRICTION.value,
                    "teacher": matched_teacher,
                    "day": day,
                    "time_range": time_range,
                    "start_time": start_time,
                    "end_time": end_time,
                    "mode": mode,
                }
            elif day:
                return {
                    "constraint_type": ConstraintType.TEACHER_DAY_RESTRICTION.value,
                    "teacher": matched_teacher,
                    "day": day,
                    "mode": mode,
                }
            else:
                return {
                    "constraint_type": ConstraintType.TEACHER_TIME_RESTRICTION.value,
                    "teacher": matched_teacher,
                    "day": day,
                    "mode": mode,
                }

        if matched_subject:
            if time_range or start_time:
                return {
                    "constraint_type": ConstraintType.SUBJECT_TIME_PREFERENCE.value,
                    "subject": matched_subject,
                    "day": day,
                    "time_range": time_range,
                    "start_time": start_time,
                    "end_time": end_time,
                    "mode": mode,
                }
            elif day:
                return {
                    "constraint_type": ConstraintType.SUBJECT_DAY_RESTRICTION.value,
                    "subject": matched_subject,
                    "day": day,
                    "mode": mode,
                }
            else:
                return {
                    "constraint_type": ConstraintType.SUBJECT_DAY_RESTRICTION.value,
                    "subject": matched_subject,
                    "day": day,
                    "mode": mode,
                }

        if matched_division:
            return {
                "constraint_type": ConstraintType.DIVISION_TIME_RESTRICTION.value,
                "division": matched_division,
                "day": day,
                "time_range": time_range,
                "start_time": start_time,
                "end_time": end_time,
                "mode": mode,
            }

        return None
