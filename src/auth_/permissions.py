"""Checks per-tool permissions.

Each tool has a boolean permission flag on `UserProfile`, such as `has_ets_permissions`.
A tool's views pass the flag's name to `ToolPermissionMixin` (class-based views) or
`tool_permission_required` (function-based views). Anonymous users are sent to sign in;
signed-in users without the flag get a 403.
"""

from collections.abc import Callable
from functools import wraps

from django.contrib.auth.mixins import AccessMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import HttpRequest, HttpResponseBase

from auth_.models import UserProfile

PERMISSION_DENIED_MESSAGE = "You don't have permission to access this page."


def has_tool_permission(request: HttpRequest, permission: str) -> bool:
    """Reports whether the request's user has the given tool permission flag.

    Args:
        request: The current request.
        permission: The name of a boolean field on `UserProfile`.

    Returns:
        True if the user is signed in and the flag is set on their profile.

    Raises:
        ImproperlyConfigured: If `UserProfile` has no field with that name.
    """
    field_names = {field.name for field in UserProfile._meta.get_fields()}  # ruff: ignore[private-member-access]
    if permission not in field_names:
        error_message = f"UserProfile has no permission flag named {permission!r}."
        raise ImproperlyConfigured(error_message)
    if not request.user.is_authenticated:
        return False
    profile = getattr(request.user, "profile", None)
    return isinstance(profile, UserProfile) and getattr(profile, permission)


class ToolPermissionMixin(AccessMixin):
    """Restricts a class-based view to users with a tool's permission flag.

    Set `tool_permission` to the name of the flag, such as "has_ets_permissions".
    """

    tool_permission: str = ""

    def dispatch(
        self,
        request: HttpRequest,
        *args,
        **kwargs,
    ) -> HttpResponseBase:
        """Checks the tool permission before dispatching.

        Returns:
            The view's response, or a redirect to sign in for anonymous users.

        Raises:
            PermissionDenied: When a signed-in user doesn't have the flag.
        """
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if has_tool_permission(request, self.tool_permission):
            return super().dispatch(request, *args, **kwargs)  # type: ignore
        raise PermissionDenied(PERMISSION_DENIED_MESSAGE)


def tool_permission_required(permission: str) -> Callable[[Callable], Callable]:
    """Restricts a function-based view to users with a tool's permission flag.

    Args:
        permission: The name of the flag, such as "has_ets_permissions".

    Returns:
        A decorator that wraps the view with the permission check.
    """

    def decorator(view_function: Callable) -> Callable:
        @wraps(view_function)
        def _wrapped_view(
            request: HttpRequest,
            *args,
            **kwargs,
        ) -> HttpResponseBase:
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if has_tool_permission(request, permission):
                return view_function(request, *args, **kwargs)
            raise PermissionDenied(PERMISSION_DENIED_MESSAGE)

        return _wrapped_view

    return decorator
