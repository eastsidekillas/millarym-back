from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from app_auth.permissions import HasRight

from . import store


def overview() -> dict:
    found = store.copies()
    return {
        "copies": found,
        "state": store.state(),
        "queued": [t.get("action", "") for t in store.tasks()],
        "alive": store.alive(),
        "alerts": store.alerts(found),
        "history": store.history(),
        "schedule": settings.BACKUP_AT,
        "keep_days": settings.BACKUP_KEEP_DAYS,
    }


def refuse_if_busy() -> Response | None:
    if not store.alive():
        return Response({"detail": "Служба копий не отвечает — проверьте контейнер backup на сервере."}, status=409)
    if store.busy():
        return Response({"detail": "Служба копий уже занята — дождитесь окончания."}, status=409)
    return None


class BackupListView(APIView):
    permission_classes = [HasRight("backups")]

    @extend_schema(request=None, responses=dict)
    def get(self, request):
        return Response(overview())

    @extend_schema(request=None, responses=dict)
    def post(self, request):
        refused = refuse_if_busy()
        if refused:
            return refused
        store.enqueue("backup", request.user.short_name)
        return Response(overview(), status=status.HTTP_202_ACCEPTED)


class BackupRestoreView(APIView):
    permission_classes = [HasRight("backups")]

    @extend_schema(request=dict, responses=dict)
    def post(self, request, stamp):
        if not store.file_for(stamp, "db"):
            raise Http404
        if (request.data.get("confirm") or "").strip().upper() != store.CONFIRM_WORD:
            return Response({"detail": f"Для восстановления введите слово «{store.CONFIRM_WORD}»."}, status=400)
        refused = refuse_if_busy()
        if refused:
            return refused
        store.enqueue("restore", request.user.short_name, stamp)
        return Response(overview(), status=status.HTTP_202_ACCEPTED)


class BackupDownloadView(APIView):
    permission_classes = [HasRight("backups")]

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    def get(self, request, stamp, part):
        path = store.file_for(stamp, part)
        if not path:
            raise Http404
        name = f"milarum_{path.name}"
        if settings.BACKUP_ACCEL:
            # большой файл отдаёт nginx, а не воркер приложения
            response = HttpResponse(content_type="application/octet-stream")
            response["X-Accel-Redirect"] = settings.BACKUP_ACCEL + path.name
            response["Content-Disposition"] = f'attachment; filename="{name}"'
            return response
        return FileResponse(path.open("rb"), as_attachment=True, filename=name)


class MaintenanceView(APIView):
    """Без входа и без базы: заглушка у всех пользователей опрашивает его, пока идёт восстановление."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(responses=dict)
    def get(self, request):
        active = store.in_maintenance()
        return Response({"active": active, "text": store.maintenance_text() if active else ""})
