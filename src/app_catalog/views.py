from dataclasses import asdict
from urllib.parse import quote

from django.http import Http404, HttpResponse
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from django.db.models import Count, ProtectedError, Q
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from app_auth.permissions import ReadOrRight, no_right_message
from app_production.models import Item

from . import exchange
from .images import jpeg_bytes
from .models import Category, Deadlines, Fabric, KitOption, ProductModel, Team
from .serializers import (
    CategorySerializer,
    DeadlinesSerializer,
    FabricSerializer,
    KitOptionSerializer,
    ProductModelSerializer,
    TeamSerializer,
)


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def jpeg_response(obj) -> HttpResponse:
    if not obj.photo:
        raise Http404
    try:
        data = jpeg_bytes(obj.photo.path)
    except OSError:
        raise Http404
    response = HttpResponse(data, content_type="image/jpeg")
    name = f"{obj.name}.jpg"
    response["Content-Disposition"] = f"inline; filename=photo.jpg; filename*=UTF-8''{quote(name)}"
    response["Cache-Control"] = "private, max-age=86400"
    return response


class CatalogViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    right = "catalog"
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["active"]
    search_fields = ["name"]
    pagination_class = None

    def get_permissions(self):
        return [ReadOrRight(self.right)()]

    def in_use(self, obj) -> str:
        """Почему нельзя удалить; пусто — можно."""
        return ""

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        reason = self.in_use(obj)
        if not reason:
            try:
                photos = [f.name for f in (getattr(obj, "photo", None), getattr(obj, "photo_thumb", None)) if f]
                obj.delete()
            except ProtectedError:
                reason = "Запись используется — удалить нельзя, можно скрыть из справочника."
            else:
                for path in photos:
                    obj.photo.storage.delete(path)
                return Response(status=status.HTTP_204_NO_CONTENT)
        return Response({"detail": reason}, status=status.HTTP_409_CONFLICT)


def used_text(n: int) -> str:
    return f"Есть в {n} изд. (вместе с Корзиной и отгруженными) — удалить нельзя, иначе у них пропадёт запись. Можно скрыть из справочника."


class CategoryViewSet(CatalogViewSet):
    queryset = Category.objects.annotate(
        models_count=Count("models", filter=Q(models__active=True)), used=Count("models")
    ).order_by("sort", "name")
    serializer_class = CategorySerializer

    def in_use(self, obj):
        n = obj.models.count()
        return f"В категории {n} моделей — сначала перенесите их в другую категорию." if n else ""


class ProductModelViewSet(CatalogViewSet):
    queryset = ProductModel.objects.select_related("category").annotate(
        in_work=Count("items", filter=Q(items__trashed_at__isnull=True)), used=Count("items")
    ).order_by("name")
    serializer_class = ProductModelSerializer

    filterset_fields = ["active", "category"]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def in_use(self, obj):
        n = Item.all_objects.filter(model=obj).count()
        return used_text(n) if n else ""

    @extend_schema(responses={(200, "image/jpeg"): bytes})
    def jpeg(self, request, pk=None, filename=None):
        return jpeg_response(self.get_object())


class FabricViewSet(CatalogViewSet):
    right = "fabrics"
    queryset = Fabric.objects.annotate(
        in_work=Count("item_fabrics__item", filter=Q(item_fabrics__item__trashed_at__isnull=True), distinct=True),
        used=Count("item_fabrics__item", distinct=True),
    )
    filter_backends = [*CatalogViewSet.filter_backends, filters.OrderingFilter]
    ordering_fields = ["name", "in_work", "created_at"]
    ordering = ["name"]
    serializer_class = FabricSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = LimitOffsetPagination

    def in_use(self, obj):
        n = obj.item_fabrics.values("item").distinct().count()
        return used_text(n) if n else ""

    @extend_schema(responses={(200, "image/jpeg"): bytes})
    def jpeg(self, request, pk=None, filename=None):
        return jpeg_response(self.get_object())


class KitOptionViewSet(CatalogViewSet):
    queryset = KitOption.objects.all()
    serializer_class = KitOptionSerializer


class TeamViewSet(CatalogViewSet):
    queryset = Team.objects.annotate(used=Count("items"))
    serializer_class = TeamSerializer
    search_fields = ["name", "foreman"]

    def in_use(self, obj):
        n = Item.all_objects.filter(team=obj).count()
        return used_text(n) if n else ""


class DeadlinesView(RetrieveUpdateAPIView):
    serializer_class = DeadlinesSerializer
    http_method_names = ["get", "patch", "put", "head", "options"]

    def get_permissions(self):
        return [ReadOrRight("catalog")()]

    def get_object(self):
        return Deadlines.get()


class CatalogExportView(APIView):
    @extend_schema(responses={(200, XLSX): bytes})
    def get(self, request):
        response = HttpResponse(exchange.build_xlsx(), content_type=XLSX)
        name = f"Справочники {timezone.localdate():%d.%m.%y}.xlsx"
        response["Content-Disposition"] = f"attachment; filename=catalog.xlsx; filename*=UTF-8''{quote(name)}"
        response["Access-Control-Expose-Headers"] = "Content-Disposition"
        return response


class CatalogImportView(APIView):
    """?dry_run=1 — только показать, что изменится."""

    parser_classes = [MultiPartParser]

    @extend_schema(request={"multipart/form-data": dict}, responses=dict)
    def post(self, request):
        user = request.user
        if not (user.has_perm("app_auth.catalog") or user.has_perm("app_auth.fabrics")):
            return Response({"detail": no_right_message("catalog")}, status=status.HTTP_403_FORBIDDEN)
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "Выберите файл .xlsx."}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size > 10 * 1024 * 1024:
            return Response({"detail": "Файл больше 10 МБ — это точно выгрузка справочников?"}, status=status.HTTP_400_BAD_REQUEST)
        dry_run = request.query_params.get("dry_run") in ("1", "true")
        try:
            reports, foreign = exchange.import_xlsx(upload.read(), lambda right: user.has_perm(f"app_auth.{right}"), dry_run)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        has_errors = any(r.errors for r in reports)
        return Response(
            {
                "applied": not dry_run and not has_errors,
                "has_errors": has_errors,
                "foreign": foreign,
                "sheets": [asdict(r) for r in reports],
            }
        )
