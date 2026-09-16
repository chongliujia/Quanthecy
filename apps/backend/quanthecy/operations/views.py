from django.http import HttpRequest, JsonResponse

from .dependencies import dependency_status


def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "service": "backend"})


def ready(request: HttpRequest) -> JsonResponse:
    dependencies = dependency_status()
    available = all(dependencies.values())
    return JsonResponse(
        {"status": "ready" if available else "unavailable", "dependencies": dependencies},
        status=200 if available else 503,
    )
