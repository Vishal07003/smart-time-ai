"""
Constraint Validation and Management Service for SMART-TIME AI (Phase 9B).

Validates structured constraints against database/business entities (Teachers,
Subjects, Divisions, Batches, Semesters, Classrooms, Laboratories) and normalizes
them to canonical UUID-based constraint objects.
"""

from dataclasses import dataclass, field, asdict
from datetime import time
from enum import Enum
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import uuid

from django.db.models import Q, Value
from django.db.models.functions import Concat

from academics.models import (
    Classroom,
    Division,
    Laboratory,
    PracticalBatch,
    Semester,
    Subject,
)
from academics.services.constraint_parser import (
    ConstraintMode,
    ConstraintType,
    SessionType,
    StructuredConstraint,
    TIME_RANGE_DEFAULTS,
    VALID_DAYS,
)
from accounts.models import TeacherProfile, User


class ValidationErrorCode(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    INACTIVE_TEACHER = "INACTIVE_TEACHER"
    RELATIONSHIP_MISMATCH = "RELATIONSHIP_MISMATCH"
    INVALID_VALUE = "INVALID_VALUE"
    INVALID_TIME_RANGE = "INVALID_TIME_RANGE"
    INVALID_MODE = "INVALID_MODE"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"


@dataclass
class ValidationErrorDetail:
    """Represents a structured validation error."""
    field: str
    code: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "field": self.field,
            "code": self.code,
            "message": self.message,
        }


@dataclass
class ValidationResult:
    """Result of validating and normalizing a scheduling constraint."""
    valid: bool
    constraint: Optional[Dict[str, Any]] = None
    errors: List[ValidationErrorDetail] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "constraint": self.constraint,
            "errors": [err.to_dict() for err in self.errors],
        }


class ConstraintValidatorService:
    """
    Validates structured constraint representations against SMART-TIME database entities.
    Resolves human-readable names/codes to database IDs, enforces business rules,
    and returns a canonical normalized constraint.
    """

    SUPPORTED_CONSTRAINT_TYPES: Set[str] = {
        ConstraintType.TEACHER_TIME_RESTRICTION.value,
        ConstraintType.TEACHER_DAY_RESTRICTION.value,
        ConstraintType.SUBJECT_DAY_RESTRICTION.value,
        ConstraintType.SUBJECT_TIME_PREFERENCE.value,
        ConstraintType.DIVISION_TIME_RESTRICTION.value,
        ConstraintType.SESSION_TIME_PREFERENCE.value,
    }

    VALID_MODES: Set[str] = {
        ConstraintMode.AVOID.value,
        ConstraintMode.PREFER.value,
    }

    VALID_SESSION_TYPES: Set[str] = {
        SessionType.LECTURE.value,
        SessionType.PRACTICAL.value,
        SessionType.TUTORIAL.value,
    }

    def validate(
        self,
        constraint_input: Union[StructuredConstraint, Dict[str, Any]],
        semester: Optional[Union[Semester, str, uuid.UUID]] = None,
    ) -> ValidationResult:
        """
        Validates a structured constraint against the database and business logic.

        Args:
            constraint_input: StructuredConstraint instance or dictionary.
            semester: Optional Semester instance or UUID to scope validation.

        Returns:
            ValidationResult containing valid flag, canonical dict, and error details.
        """
        raw_data = self._to_dict(constraint_input)
        errors: List[ValidationErrorDetail] = []

        # 1. Resolve Semester context if provided
        semester_obj = self._resolve_semester(semester, errors)

        # 2. Validate constraint_type
        c_type = raw_data.get("constraint_type")
        if not c_type or c_type not in self.SUPPORTED_CONSTRAINT_TYPES:
            errors.append(
                ValidationErrorDetail(
                    field="constraint_type",
                    code=ValidationErrorCode.UNSUPPORTED_TYPE.value,
                    message=f"Constraint type '{c_type}' is unsupported or missing.",
                )
            )
            return ValidationResult(valid=False, constraint=None, errors=errors)

        # 3. Validate mode
        raw_mode = raw_data.get("mode", ConstraintMode.AVOID.value)
        mode = str(raw_mode).strip().upper() if raw_mode else ConstraintMode.AVOID.value
        if mode not in self.VALID_MODES:
            errors.append(
                ValidationErrorDetail(
                    field="mode",
                    code=ValidationErrorCode.INVALID_MODE.value,
                    message=f"Mode must be 'AVOID' or 'PREFER', got '{raw_mode}'.",
                )
            )

        # 4. Validate Day
        day = self._validate_day(raw_data.get("day"), errors)

        # 5. Validate & Normalize Time
        start_time, end_time = self._validate_time(
            start_time_raw=raw_data.get("start_time"),
            end_time_raw=raw_data.get("end_time"),
            time_range_raw=raw_data.get("time_range"),
            errors=errors,
        )

        # 6. Validate Session Type
        session_type = self._validate_session_type(raw_data.get("session_type"), errors)

        # 7. Entity Resolutions
        teacher_id, teacher_obj = self._resolve_teacher(
            raw_id=raw_data.get("teacher_id"),
            raw_query=raw_data.get("teacher"),
            errors=errors,
        )

        subject_id, subject_obj = self._resolve_subject(
            raw_id=raw_data.get("subject_id"),
            raw_query=raw_data.get("subject"),
            semester=semester_obj,
            errors=errors,
        )

        division_id, division_obj = self._resolve_division(
            raw_id=raw_data.get("division_id"),
            raw_query=raw_data.get("division"),
            semester=semester_obj,
            errors=errors,
        )

        batch_id, batch_obj = self._resolve_batch(
            raw_id=raw_data.get("batch_id") or raw_data.get("practical_batch_id"),
            raw_query=raw_data.get("batch") or raw_data.get("practical_batch"),
            division=division_obj,
            errors=errors,
        )

        # 8. Type-specific requirement checks
        self._validate_type_requirements(
            c_type=c_type,
            teacher_id=teacher_id,
            subject_id=subject_id,
            division_id=division_id,
            day=day,
            start_time=start_time,
            end_time=end_time,
            session_type=session_type,
            raw_data=raw_data,
            errors=errors,
        )

        if errors:
            return ValidationResult(valid=False, constraint=None, errors=errors)

        # 9. Build canonical normalized dictionary
        canonical: Dict[str, Any] = {
            "constraint_type": c_type,
            "mode": mode,
        }

        if teacher_id:
            canonical["teacher_id"] = teacher_id
        if subject_id:
            canonical["subject_id"] = subject_id
        if division_id:
            canonical["division_id"] = division_id
        if batch_id:
            canonical["batch_id"] = batch_id
        if day:
            canonical["day"] = day
        if start_time:
            canonical["start_time"] = start_time
        if end_time:
            canonical["end_time"] = end_time
        if session_type:
            canonical["session_type"] = session_type

        return ValidationResult(valid=True, constraint=canonical, errors=[])

    def _to_dict(self, constraint_input: Union[StructuredConstraint, Dict[str, Any]]) -> Dict[str, Any]:
        if isinstance(constraint_input, StructuredConstraint):
            return constraint_input.to_dict()
        elif isinstance(constraint_input, dict):
            return dict(constraint_input)
        return {}

    def _is_valid_uuid(self, val: Any) -> bool:
        if not val:
            return False
        try:
            uuid.UUID(str(val).strip())
            return True
        except (ValueError, AttributeError, TypeError):
            return False

    def _resolve_semester(
        self,
        semester: Optional[Union[Semester, str, uuid.UUID]],
        errors: List[ValidationErrorDetail],
    ) -> Optional[Semester]:
        if not semester:
            return None
        if isinstance(semester, Semester):
            return semester
        if self._is_valid_uuid(semester):
            try:
                return Semester.objects.select_related("program").get(id=str(semester).strip())
            except Semester.DoesNotExist:
                errors.append(
                    ValidationErrorDetail(
                        field="semester",
                        code=ValidationErrorCode.NOT_FOUND.value,
                        message=f"Semester with ID '{semester}' was not found.",
                    )
                )
                return None
        errors.append(
            ValidationErrorDetail(
                field="semester",
                code=ValidationErrorCode.INVALID_VALUE.value,
                message=f"Invalid semester identifier '{semester}'.",
            )
        )
        return None

    def _resolve_teacher(
        self,
        raw_id: Optional[str],
        raw_query: Optional[str],
        errors: List[ValidationErrorDetail],
    ) -> Tuple[Optional[str], Optional[TeacherProfile]]:
        identifier = raw_id or raw_query
        if not identifier:
            return None, None

        identifier_str = str(identifier).strip()

        # 1. UUID lookup
        if self._is_valid_uuid(identifier_str):
            try:
                teacher = TeacherProfile.objects.select_related("user").get(id=identifier_str)
                if teacher.status != TeacherProfile.Status.ACTIVE or not teacher.user.is_active:
                    errors.append(
                        ValidationErrorDetail(
                            field="teacher",
                            code=ValidationErrorCode.INACTIVE_TEACHER.value,
                            message=f"Teacher '{teacher.user.get_full_name() or teacher.employee_code}' is inactive.",
                        )
                    )
                    return None, None
                return str(teacher.id), teacher
            except TeacherProfile.DoesNotExist:
                errors.append(
                    ValidationErrorDetail(
                        field="teacher",
                        code=ValidationErrorCode.NOT_FOUND.value,
                        message=f"Teacher with ID '{identifier_str}' was not found.",
                    )
                )
                return None, None

        # 2. String lookup by employee_code, username, or full name
        qs = TeacherProfile.objects.select_related("user")

        # Exact employee_code or username
        exact_code_qs = qs.filter(
            Q(employee_code__iexact=identifier_str) | Q(user__username__iexact=identifier_str)
        )
        if exact_code_qs.count() == 1:
            matched = exact_code_qs.first()
            if matched.status != TeacherProfile.Status.ACTIVE or not matched.user.is_active:
                errors.append(
                    ValidationErrorDetail(
                        field="teacher",
                        code=ValidationErrorCode.INACTIVE_TEACHER.value,
                        message=f"Teacher '{matched.user.get_full_name() or matched.employee_code}' is inactive.",
                    )
                )
                return None, None
            return str(matched.id), matched

        # Exact full name or single name
        name_qs = qs.annotate(
            full_name=Concat("user__first_name", Value(" "), "user__last_name")
        ).filter(
            Q(full_name__iexact=identifier_str)
            | Q(user__first_name__iexact=identifier_str)
            | Q(user__last_name__iexact=identifier_str)
        )

        matches = list(name_qs)
        if len(matches) == 1:
            matched = matches[0]
            if matched.status != TeacherProfile.Status.ACTIVE or not matched.user.is_active:
                errors.append(
                    ValidationErrorDetail(
                        field="teacher",
                        code=ValidationErrorCode.INACTIVE_TEACHER.value,
                        message=f"Teacher '{matched.user.get_full_name() or matched.employee_code}' is inactive.",
                    )
                )
                return None, None
            return str(matched.id), matched
        elif len(matches) > 1:
            errors.append(
                ValidationErrorDetail(
                    field="teacher",
                    code=ValidationErrorCode.AMBIGUOUS.value,
                    message=f"Multiple teachers matched '{identifier_str}'.",
                )
            )
            return None, None

        # Substring / partial lookup
        partial_qs = qs.filter(
            Q(user__first_name__icontains=identifier_str)
            | Q(user__last_name__icontains=identifier_str)
            | Q(employee_code__icontains=identifier_str)
        )
        partial_matches = list(partial_qs)
        if len(partial_matches) == 1:
            matched = partial_matches[0]
            if matched.status != TeacherProfile.Status.ACTIVE or not matched.user.is_active:
                errors.append(
                    ValidationErrorDetail(
                        field="teacher",
                        code=ValidationErrorCode.INACTIVE_TEACHER.value,
                        message=f"Teacher '{matched.user.get_full_name() or matched.employee_code}' is inactive.",
                    )
                )
                return None, None
            return str(matched.id), matched
        elif len(partial_matches) > 1:
            errors.append(
                ValidationErrorDetail(
                    field="teacher",
                    code=ValidationErrorCode.AMBIGUOUS.value,
                    message=f"Multiple teachers matched '{identifier_str}'.",
                )
            )
            return None, None

        errors.append(
            ValidationErrorDetail(
                field="teacher",
                code=ValidationErrorCode.NOT_FOUND.value,
                message=f"Teacher '{identifier_str}' was not found.",
            )
        )
        return None, None

    def _resolve_subject(
        self,
        raw_id: Optional[str],
        raw_query: Optional[str],
        semester: Optional[Semester],
        errors: List[ValidationErrorDetail],
    ) -> Tuple[Optional[str], Optional[Subject]]:
        identifier = raw_id or raw_query
        if not identifier:
            return None, None

        identifier_str = str(identifier).strip()

        # 1. UUID lookup
        if self._is_valid_uuid(identifier_str):
            try:
                subject = Subject.objects.select_related("program").get(id=identifier_str)
                if semester and subject.program_id != semester.program_id:
                    errors.append(
                        ValidationErrorDetail(
                            field="subject",
                            code=ValidationErrorCode.RELATIONSHIP_MISMATCH.value,
                            message=f"Subject '{subject.code}' does not belong to program '{semester.program.code}'.",
                        )
                    )
                    return None, None
                return str(subject.id), subject
            except Subject.DoesNotExist:
                errors.append(
                    ValidationErrorDetail(
                        field="subject",
                        code=ValidationErrorCode.NOT_FOUND.value,
                        message=f"Subject with ID '{identifier_str}' was not found.",
                    )
                )
                return None, None

        # 2. String lookup by code or name
        qs = Subject.objects.select_related("program")
        if semester:
            qs = qs.filter(program_id=semester.program_id)

        # Exact code or name
        exact_qs = qs.filter(
            Q(code__iexact=identifier_str) | Q(name__iexact=identifier_str)
        )
        exact_matches = list(exact_qs)
        if len(exact_matches) == 1:
            return str(exact_matches[0].id), exact_matches[0]
        elif len(exact_matches) > 1:
            errors.append(
                ValidationErrorDetail(
                    field="subject",
                    code=ValidationErrorCode.AMBIGUOUS.value,
                    message=f"Multiple subjects matched '{identifier_str}'.",
                )
            )
            return None, None

        # Substring search
        partial_qs = qs.filter(
            Q(code__icontains=identifier_str) | Q(name__icontains=identifier_str)
        )
        partial_matches = list(partial_qs)
        if len(partial_matches) == 1:
            return str(partial_matches[0].id), partial_matches[0]
        elif len(partial_matches) > 1:
            errors.append(
                ValidationErrorDetail(
                    field="subject",
                    code=ValidationErrorCode.AMBIGUOUS.value,
                    message=f"Multiple subjects matched '{identifier_str}'.",
                )
            )
            return None, None

        errors.append(
            ValidationErrorDetail(
                field="subject",
                code=ValidationErrorCode.NOT_FOUND.value,
                message=f"Subject '{identifier_str}' was not found.",
            )
        )
        return None, None

    def _resolve_division(
        self,
        raw_id: Optional[str],
        raw_query: Optional[str],
        semester: Optional[Semester],
        errors: List[ValidationErrorDetail],
    ) -> Tuple[Optional[str], Optional[Division]]:
        identifier = raw_id or raw_query
        if not identifier:
            return None, None

        identifier_str = str(identifier).strip()

        # 1. UUID lookup
        if self._is_valid_uuid(identifier_str):
            try:
                division = Division.objects.select_related("semester").get(id=identifier_str)
                if semester and division.semester_id != semester.id:
                    errors.append(
                        ValidationErrorDetail(
                            field="division",
                            code=ValidationErrorCode.RELATIONSHIP_MISMATCH.value,
                            message=f"Division '{division.name}' does not belong to the selected semester.",
                        )
                    )
                    return None, None
                return str(division.id), division
            except Division.DoesNotExist:
                errors.append(
                    ValidationErrorDetail(
                        field="division",
                        code=ValidationErrorCode.NOT_FOUND.value,
                        message=f"Division with ID '{identifier_str}' was not found.",
                    )
                )
                return None, None

        # Clean common prefixes e.g. "Div A" -> "A", "Division A" -> "A"
        clean_name = re.sub(r"^(?:div(?:ision)?[- ]*)", "", identifier_str, flags=re.IGNORECASE).strip()

        qs = Division.objects.select_related("semester")
        if semester:
            qs = qs.filter(semester=semester)

        # Exact name or cleaned name
        matches = list(qs.filter(Q(name__iexact=identifier_str) | Q(name__iexact=clean_name)).distinct())
        if len(matches) == 1:
            return str(matches[0].id), matches[0]
        elif len(matches) > 1:
            errors.append(
                ValidationErrorDetail(
                    field="division",
                    code=ValidationErrorCode.AMBIGUOUS.value,
                    message=f"Multiple divisions matched '{identifier_str}'.",
                )
            )
            return None, None

        errors.append(
            ValidationErrorDetail(
                field="division",
                code=ValidationErrorCode.NOT_FOUND.value,
                message=f"Division '{identifier_str}' was not found.",
            )
        )
        return None, None

    def _resolve_batch(
        self,
        raw_id: Optional[str],
        raw_query: Optional[str],
        division: Optional[Division],
        errors: List[ValidationErrorDetail],
    ) -> Tuple[Optional[str], Optional[PracticalBatch]]:
        identifier = raw_id or raw_query
        if not identifier:
            return None, None

        identifier_str = str(identifier).strip()

        # 1. UUID lookup
        if self._is_valid_uuid(identifier_str):
            try:
                batch = PracticalBatch.objects.select_related("division").get(id=identifier_str)
                if division and batch.division_id != division.id:
                    errors.append(
                        ValidationErrorDetail(
                            field="batch",
                            code=ValidationErrorCode.RELATIONSHIP_MISMATCH.value,
                            message=f"Batch '{batch.name}' does not belong to division '{division.name}'.",
                        )
                    )
                    return None, None
                return str(batch.id), batch
            except PracticalBatch.DoesNotExist:
                errors.append(
                    ValidationErrorDetail(
                        field="batch",
                        code=ValidationErrorCode.NOT_FOUND.value,
                        message=f"Batch with ID '{identifier_str}' was not found.",
                    )
                )
                return None, None

        # Clean common prefixes e.g. "Batch B1" -> "B1"
        clean_name = re.sub(r"^(?:batch[- ]*)", "", identifier_str, flags=re.IGNORECASE).strip()

        qs = PracticalBatch.objects.select_related("division")
        if division:
            qs = qs.filter(division=division)

        matches = list(qs.filter(Q(name__iexact=identifier_str) | Q(name__iexact=clean_name)).distinct())
        if len(matches) == 1:
            matched = matches[0]
            if division and matched.division_id != division.id:
                errors.append(
                    ValidationErrorDetail(
                        field="batch",
                        code=ValidationErrorCode.RELATIONSHIP_MISMATCH.value,
                        message=f"Batch '{matched.name}' does not belong to division '{division.name}'.",
                    )
                )
                return None, None
            return str(matched.id), matched
        elif len(matches) > 1:
            errors.append(
                ValidationErrorDetail(
                    field="batch",
                    code=ValidationErrorCode.AMBIGUOUS.value,
                    message=f"Multiple batches matched '{identifier_str}'.",
                )
            )
            return None, None

        # Check if the batch exists in any other division to give a clear relationship error
        other_division_batches = list(PracticalBatch.objects.filter(Q(name__iexact=identifier_str) | Q(name__iexact=clean_name)))
        if division and other_division_batches:
            errors.append(
                ValidationErrorDetail(
                    field="batch",
                    code=ValidationErrorCode.RELATIONSHIP_MISMATCH.value,
                    message=f"Batch '{identifier_str}' does not belong to division '{division.name}'.",
                )
            )
            return None, None

        errors.append(
            ValidationErrorDetail(
                field="batch",
                code=ValidationErrorCode.NOT_FOUND.value,
                message=f"Batch '{identifier_str}' was not found.",
            )
        )
        return None, None

    def _validate_day(
        self,
        raw_day: Optional[str],
        errors: List[ValidationErrorDetail],
    ) -> Optional[str]:
        if not raw_day:
            return None
        day_str = str(raw_day).strip().upper()
        if day_str not in VALID_DAYS:
            errors.append(
                ValidationErrorDetail(
                    field="day",
                    code=ValidationErrorCode.INVALID_VALUE.value,
                    message=f"Invalid day '{raw_day}'.",
                )
            )
            return None
        return day_str

    def _validate_time(
        self,
        start_time_raw: Optional[str],
        end_time_raw: Optional[str],
        time_range_raw: Optional[str],
        errors: List[ValidationErrorDetail],
    ) -> Tuple[Optional[str], Optional[str]]:
        start_time = None
        end_time = None

        if time_range_raw and not (start_time_raw and end_time_raw):
            tr_key = str(time_range_raw).strip().upper()
            if tr_key in TIME_RANGE_DEFAULTS:
                start_time, end_time = TIME_RANGE_DEFAULTS[tr_key]
            else:
                errors.append(
                    ValidationErrorDetail(
                        field="time_range",
                        code=ValidationErrorCode.INVALID_VALUE.value,
                        message=f"Invalid time range '{time_range_raw}'.",
                    )
                )

        if start_time_raw:
            start_time = self._parse_time_str(start_time_raw, "start_time", errors)
        if end_time_raw:
            end_time = self._parse_time_str(end_time_raw, "end_time", errors)

        if start_time and end_time:
            if start_time >= end_time:
                errors.append(
                    ValidationErrorDetail(
                        field="time_range",
                        code=ValidationErrorCode.INVALID_TIME_RANGE.value,
                        message=f"Start time '{start_time}' must be strictly before end time '{end_time}'.",
                    )
                )

        return start_time, end_time

    def _parse_time_str(
        self,
        val: Any,
        field_name: str,
        errors: List[ValidationErrorDetail],
    ) -> Optional[str]:
        if isinstance(val, time):
            return val.strftime("%H:%M")
        val_str = str(val).strip()
        match = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", val_str)
        if not match:
            errors.append(
                ValidationErrorDetail(
                    field=field_name,
                    code=ValidationErrorCode.INVALID_VALUE.value,
                    message=f"Invalid time format '{val_str}'. Expected 'HH:MM'.",
                )
            )
            return None
        hh, mm = int(match.group(1)), int(match.group(2))
        if hh < 0 or hh > 23 or mm < 0 or mm > 59:
            errors.append(
                ValidationErrorDetail(
                    field=field_name,
                    code=ValidationErrorCode.INVALID_VALUE.value,
                    message=f"Invalid time value '{val_str}'.",
                )
            )
            return None
        return f"{hh:02d}:{mm:02d}"

    def _validate_session_type(
        self,
        raw_session_type: Optional[str],
        errors: List[ValidationErrorDetail],
    ) -> Optional[str]:
        if not raw_session_type:
            return None
        st_str = str(raw_session_type).strip().upper()
        if st_str not in self.VALID_SESSION_TYPES:
            errors.append(
                ValidationErrorDetail(
                    field="session_type",
                    code=ValidationErrorCode.INVALID_VALUE.value,
                    message=f"Invalid session type '{raw_session_type}'. Must be one of LECTURE, PRACTICAL, TUTORIAL.",
                )
            )
            return None
        return st_str

    def _validate_type_requirements(
        self,
        c_type: str,
        teacher_id: Optional[str],
        subject_id: Optional[str],
        division_id: Optional[str],
        day: Optional[str],
        start_time: Optional[str],
        end_time: Optional[str],
        session_type: Optional[str],
        raw_data: Dict[str, Any],
        errors: List[ValidationErrorDetail],
    ) -> None:
        """Enforces mandatory field requirements per constraint type."""
        if c_type == ConstraintType.TEACHER_TIME_RESTRICTION.value:
            if not teacher_id and not raw_data.get("teacher"):
                errors.append(ValidationErrorDetail("teacher", ValidationErrorCode.MISSING_REQUIRED_FIELD.value, "Teacher is required for teacher time restriction."))
            if not day and not raw_data.get("day"):
                errors.append(ValidationErrorDetail("day", ValidationErrorCode.MISSING_REQUIRED_FIELD.value, "Day is required for teacher time restriction."))
            if not start_time or not end_time:
                errors.append(ValidationErrorDetail("time_range", ValidationErrorCode.MISSING_REQUIRED_FIELD.value, "Start and end time are required for teacher time restriction."))

        elif c_type == ConstraintType.TEACHER_DAY_RESTRICTION.value:
            if not teacher_id and not raw_data.get("teacher"):
                errors.append(ValidationErrorDetail("teacher", ValidationErrorCode.MISSING_REQUIRED_FIELD.value, "Teacher is required for teacher day restriction."))
            if not day and not raw_data.get("day"):
                errors.append(ValidationErrorDetail("day", ValidationErrorCode.MISSING_REQUIRED_FIELD.value, "Day is required for teacher day restriction."))

        elif c_type == ConstraintType.SUBJECT_DAY_RESTRICTION.value:
            if not subject_id and not raw_data.get("subject"):
                errors.append(ValidationErrorDetail("subject", ValidationErrorCode.MISSING_REQUIRED_FIELD.value, "Subject is required for subject day restriction."))
            if not day and not raw_data.get("day"):
                errors.append(ValidationErrorDetail("day", ValidationErrorCode.MISSING_REQUIRED_FIELD.value, "Day is required for subject day restriction."))

        elif c_type == ConstraintType.SUBJECT_TIME_PREFERENCE.value:
            if not subject_id and not raw_data.get("subject"):
                errors.append(ValidationErrorDetail("subject", ValidationErrorCode.MISSING_REQUIRED_FIELD.value, "Subject is required for subject time preference."))
            if not day and not (start_time and end_time) and not raw_data.get("day") and not raw_data.get("time_range"):
                errors.append(ValidationErrorDetail("time_preference", ValidationErrorCode.MISSING_REQUIRED_FIELD.value, "Day or time preference is required for subject time preference."))

        elif c_type == ConstraintType.DIVISION_TIME_RESTRICTION.value:
            if not division_id and not raw_data.get("division"):
                errors.append(ValidationErrorDetail("division", ValidationErrorCode.MISSING_REQUIRED_FIELD.value, "Division is required for division time restriction."))
            if not day and not raw_data.get("day"):
                errors.append(ValidationErrorDetail("day", ValidationErrorCode.MISSING_REQUIRED_FIELD.value, "Day is required for division time restriction."))
            if not start_time or not end_time:
                errors.append(ValidationErrorDetail("time_range", ValidationErrorCode.MISSING_REQUIRED_FIELD.value, "Start and end time are required for division time restriction."))

        elif c_type == ConstraintType.SESSION_TIME_PREFERENCE.value:
            if not session_type and not raw_data.get("session_type") and not subject_id:
                errors.append(ValidationErrorDetail("session_type", ValidationErrorCode.MISSING_REQUIRED_FIELD.value, "Session type or subject is required for session time preference."))
