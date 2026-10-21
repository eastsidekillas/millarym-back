from django.http import JsonResponse

from . import store

OPEN_PATHS = ("/api/v1/maintenance/",)


class MaintenanceMiddleware:
    """Пока служба копий восстанавливает базу, API отвечает 503 — чтобы никто ничего не внёс в заменяемую базу."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if store.needs_migrate():
            store.finish_restore()
        if store.in_maintenance() and request.path.startswith("/api/") and request.path not in OPEN_PATHS:
            return JsonResponse({"detail": store.maintenance_text(), "code": "maintenance"}, status=503)
        return self.get_response(request)
