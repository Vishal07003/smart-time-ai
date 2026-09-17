from rest_framework.permissions import SAFE_METHODS, BasePermission
from accounts.models import User


class IsStaffOrReadOnlyAcademic(BasePermission):
    """
    Permission class for Academic Master Data:
    - STAFF: full CRUD access (GET, POST, PUT, PATCH, DELETE)
    - TEACHER: read-only access (GET, HEAD, OPTIONS)
    - STUDENT: read-only access (GET, HEAD, OPTIONS)
    - Unauthenticated: access denied (401 Unauthorized)
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False

        # Read-only permissions allowed for all authenticated users (Staff, Teacher, Student)
        if request.method in SAFE_METHODS:
            return True

        # Write/Update/Delete permissions restricted strictly to STAFF
        return request.user.role == User.Role.STAFF


class IsStaffOrTeacherOwnerAvailability(BasePermission):
    """
    Permission class for Teacher Availability:
    - STAFF: Full CRUD access across all availability records.
    - TEACHER: Can list, retrieve, create, update, delete only their own availability.
    - STUDENT / Unauthenticated: Access denied.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.user.role in (User.Role.STAFF, User.Role.TEACHER)

    def has_object_permission(self, request, view, obj):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.role == User.Role.STAFF:
            return True
        if request.user.role == User.Role.TEACHER:
            return obj.teacher.user_id == request.user.id
        return False


class IsStaffOrTeacherOwnerLeave(BasePermission):
    """
    Permission class for Teacher Leave:
    - STAFF: Full CRUD access across all leave records, can approve/reject.
    - TEACHER: Can list, retrieve, create, and manage only their own leave requests.
    - STUDENT / Unauthenticated: Access denied.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.user.role in (User.Role.STAFF, User.Role.TEACHER)

    def has_object_permission(self, request, view, obj):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.role == User.Role.STAFF:
            return True
        if request.user.role == User.Role.TEACHER:
            return obj.teacher.user_id == request.user.id
        return False


class IsStaffOrReadOnlyPublishedTimetable(BasePermission):
    """
    Permission class for Timetables and Timetable Slots:
    - STAFF: full CRUD access.
    - TEACHER / STUDENT: read-only access to published timetables/slots.
    - Unauthenticated: access denied.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False

        if request.method in SAFE_METHODS:
            return True

        return request.user.role == User.Role.STAFF

    def has_object_permission(self, request, view, obj):
        if not (request.user and request.user.is_authenticated):
            return False

        if request.user.role == User.Role.STAFF:
            return True

        if request.method in SAFE_METHODS:
            if hasattr(obj, "status") and hasattr(obj, "slots"):
                # Timetable object
                return obj.status == "PUBLISHED"
            elif hasattr(obj, "timetable"):
                # TimetableSlot object
                return obj.timetable.status == "PUBLISHED"
            return True

        return False

