from functools import wraps
from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from accounts.models import User


class StaffRequiredMixin(AccessMixin):
    """
    CBV mixin that enforces:
    1. User must be authenticated -> redirect to staff:login.
    2. User must possess the STAFF role -> raise PermissionDenied (403 Forbidden).
    """

    login_url = "staff:login"
    raise_exception = False

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if getattr(request.user, "role", None) != User.Role.STAFF:
            raise PermissionDenied("Access restricted to staff members.")

        return super().dispatch(request, *args, **kwargs)


def staff_required(view_func):
    """
    View decorator enforcing staff authentication and STAFF role.
    """

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/staff/login/?next={request.path}")
        if getattr(request.user, "role", None) != User.Role.STAFF:
            raise PermissionDenied("Access restricted to staff members.")
        return view_func(request, *args, **kwargs)

    return _wrapped_view
