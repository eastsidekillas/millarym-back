from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Q
from rest_framework import filters, mixins, viewsets
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from app_auth.permissions import ReadOrRight

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
    viewsets.GenericViewSet,
):
    right = "catalog"
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["active"]
    search_fields = ["name"]
    pagination_class = None

    def get_permissions(self):
        return [ReadOrRight(self.right)()]


class CategoryViewSet(CatalogViewSet):
    queryset = Category.objects.annotate(models_count=Count("models", filter=Q(models__active=True))).order_by(
        "sort", "name"
    )
    serializer_class = CategorySerializer


class ProductModelViewSet(CatalogViewSet):
    queryset = ProductModel.objects.select_related("category").annotate(
        in_work=Count("items", filter=Q(items__trashed_at__isnull=True))
    ).order_by("name")
    serializer_class = ProductModelSerializer
    filterset_fields = ["active", "category"]
    parser_classes = [JSONParser, MultiPartParser, FormParser]


class FabricViewSet(CatalogViewSet):
    right = "fabrics"
    queryset = Fabric.objects.annotate(
        in_work=Count("item_fabrics__item", filter=Q(item_fabrics__item__trashed_at__isnull=True), distinct=True)
    )
    filter_backends = [*CatalogViewSet.filter_backends, filters.OrderingFilter]
    ordering_fields = ["name", "in_work", "created_at"]
    ordering = ["name"]
    serializer_class = FabricSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = LimitOffsetPagination


class KitOptionViewSet(CatalogViewSet):
    queryset = KitOption.objects.all()
    serializer_class = KitOptionSerializer


class TeamViewSet(CatalogViewSet):
    queryset = Team.objects.all()
    serializer_class = TeamSerializer
    search_fields = ["name", "foreman"]


class DeadlinesView(RetrieveUpdateAPIView):
    serializer_class = DeadlinesSerializer
    http_method_names = ["get", "patch", "put", "head", "options"]

    def get_permissions(self):
        return [ReadOrRight("catalog")()]

    def get_object(self):
        return Deadlines.get()
