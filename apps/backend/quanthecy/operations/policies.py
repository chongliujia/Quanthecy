from django.core.exceptions import PermissionDenied

from quanthecy.accounts.models import User


def require_operator(actor: User, permission: str) -> None:
    if not actor.is_active or not actor.is_staff or not actor.has_perm(permission):
        raise PermissionDenied("This platform operation requires an authorized staff account.")
