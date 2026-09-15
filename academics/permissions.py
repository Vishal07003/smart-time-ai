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
