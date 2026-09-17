from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from ninja import NinjaAPI
from ninja.security import django_auth
from quanthecy_analytics.storage.clickhouse import AnalyticsUnavailable

from .accounts import router as accounts_router
from .agents import router as agents_router
from .markets import router as markets_router
from .organizations import router as organizations_router
from .research import router as research_router
from .watchlists import router as watchlists_router

api = NinjaAPI(title="Quanthecy API", version="1.0.0", auth=django_auth)


@api.exception_handler(ValidationError)
def invalid_request(request: HttpRequest, exc: ValidationError) -> HttpResponse:
    return api.create_response(request, {"detail": exc.messages}, status=422)


@api.exception_handler(PermissionDenied)
def permission_denied(request: HttpRequest, exc: PermissionDenied) -> HttpResponse:
    return api.create_response(request, {"detail": str(exc)}, status=403)


api.add_router("", accounts_router)
api.add_router("/organizations", organizations_router)
api.add_router("/organizations", agents_router)
api.add_router("/organizations", watchlists_router)
api.add_router("", markets_router)
api.add_router("", research_router)


@api.exception_handler(AnalyticsUnavailable)
def analytics_unavailable(request: HttpRequest, exc: AnalyticsUnavailable) -> HttpResponse:
    return api.create_response(request, {"detail": str(exc)}, status=503)
