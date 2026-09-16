from django.http import HttpRequest
from ninja.errors import HttpError
from ninja.utils import check_csrf

from quanthecy.accounts.models import User


def csrf_guard(request: HttpRequest) -> bool:
    """Protect anonymous login/registration with Django's standard CSRF check."""
    if check_csrf(request):
        raise HttpError(403, "CSRF check failed")
    return True


def current_user(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User) or not user.is_active:
        raise HttpError(401, "Authentication required")
    return user
