from django.contrib.auth import authenticate, login, logout
from django.db import IntegrityError
from django.http import HttpRequest
from django.middleware.csrf import get_token
from ninja import Router, Status
from ninja.errors import HttpError

from quanthecy.accounts.models import User
from quanthecy.accounts.services import register_user

from .auth import csrf_guard, current_user
from .schemas import Credentials, CsrfToken, Message, UserOut

router = Router(tags=["Accounts"])


@router.get("/auth/csrf", auth=None, response=CsrfToken)
def csrf(request: HttpRequest) -> CsrfToken:
    return CsrfToken(csrf_token=get_token(request))


@router.post("/auth/register", auth=csrf_guard, response={201: UserOut})
def register(request: HttpRequest, payload: Credentials) -> Status[UserOut]:
    try:
        user = register_user(email=payload.email, password=payload.password)
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None)
        if constraint not in {"accounts_user_email_key", "accounts_user_email_ci_unique"}:
            raise
        raise HttpError(409, "Unable to register this email") from exc
    login(request, user)
    return Status(201, UserOut.from_user(user))


@router.post("/auth/login", auth=csrf_guard, response=UserOut)
def sign_in(request: HttpRequest, payload: Credentials) -> UserOut:
    user = authenticate(request, email=payload.email, password=payload.password)
    if not isinstance(user, User):
        raise HttpError(401, "Invalid email or password")
    login(request, user)
    return UserOut.from_user(user)


@router.post("/auth/logout", response=Message)
def sign_out(request: HttpRequest) -> Message:
    logout(request)
    return Message(detail="Signed out")


@router.get("/me", response=UserOut)
def me(request: HttpRequest) -> UserOut:
    return UserOut.from_user(current_user(request))
