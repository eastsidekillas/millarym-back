from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, ProtectedError, Q
from rest_framework import filters, mixins, status, viewsets
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from app_auth.permissions import ReadOrRight
from app_production.models import Item

from .models import Category, Deadlines, Fabric, KitOption, ProductModel, Team
from .serializers import (
    CategorySerializer,
    DeadlinesSerializer,
    FabricSerializer,
    KitOptionSerializer,
    ProductModelSerializer,
    TeamSerializer,
)


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

    def in_use(self, obj):
        n = Item.all_objects.filter(model=obj).count()
        return used_text(n) if n else ""
    filterset_fields = ["active", "category"]
    parser_classes = [JSONParser, MultiPartParser, FormParser]


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
