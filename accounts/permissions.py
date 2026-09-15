from rest_framework.permissions import BasePermission
from .models import User


class IsStaffRole(BasePermission):
    """
    Allows access only to users with the STAFF role.
    Staff is the highest application role in SMART-TIME AI.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Role.STAFF
        )


class IsTeacherRole(BasePermission):
    """
    Allows access only to users with the TEACHER role.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Role.TEACHER
        )


class IsStudentRole(BasePermission):
    """
    Allows access only to users with the STUDENT role (Mobile App users).
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Role.STUDENT
        )


class IsStaffOrTeacher(BasePermission):
    """
    Allows access to users with either STAFF or TEACHER roles (Web App users).
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in (User.Role.STAFF, User.Role.TEACHER)
        )
