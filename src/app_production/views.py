from datetime import datetime, time

from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view, inline_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from app_catalog.models import Deadlines

from . import services
from .errors import ActionError
from .models import Item, ItemEvent
from .queries import ORDERINGS, STAGE_FILTERS, base_queryset, counters, filter_items
from .serializers import (
    BulkMoveSerializer,
    EventSerializer,
    ItemCreateSerializer,
    ItemDetailSerializer,
    ItemSerializer,
    ItemUpdateSerializer,
    MoveSerializer,
    ReserveSerializer,
)


LIST_PARAMS = [
    OpenApiParameter("stage", str, enum=STAGE_FILTERS),
    OpenApiParameter("q", str, description="номер (26/7965 или 7965), модель, ткань, резерв, бригада"),
    OpenApiParameter("model", str, description="id моделей через запятую"),
    OpenApiParameter("free", bool),
    OpenApiParameter("reserved", bool),
    OpenApiParameter("indiv", bool),
    OpenApiParameter("late", bool),
    OpenApiParameter("ordering", str, enum=list(ORDERINGS)),
]

STAGE_COUNT = inline_serializer("StageCount", {"total": serializers.IntegerField(), "late": serializers.IntegerField()})
COUNTERS = inline_serializer(
    "Counters",
    {
        "stages": serializers.DictField(child=STAGE_COUNT),
        "free": serializers.IntegerField(),
        "late": serializers.IntegerField(),
        "trash": serializers.IntegerField(),
    },
)


@extend_schema_view(list=extend_schema(parameters=LIST_PARAMS))
class ItemViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Item.objects.none()
    serializer_class = ItemSerializer

    def get_queryset(self):
        qs = base_queryset()
        if self.action == "list":
            stage = self.request.query_params.get("stage") or ""
            if stage not in ("", *STAGE_FILTERS):
                raise ValidationError({"stage": [f"Неизвестный этап: {stage}."]})
            qs = filter_items(qs, self.request.query_params)
        return qs

    def get_serializer_class(self):
        return ItemDetailSerializer if self.action != "list" else ItemSerializer

    def get_object(self):
        try:
            return super().get_object()
        except Http404:
            purged = Item.all_objects.filter(pk=self.kwargs.get("pk"), purged_at__isnull=False).first()
            if purged:
                day = timezone.localtime(purged.purged_at).strftime("%d.%m.%y")
                raise NotFound(f"Изделие {purged.number} удалено из Корзины окончательно {day}. История осталась в журнале.")
            raise NotFound("Изделие не найдено.")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "deadlines": Deadlines.get(), "today": timezone.localdate()}

    def detail_response(self, item, code=status.HTTP_200_OK):
        item = base_queryset().get(pk=item.pk)
        return Response(ItemDetailSerializer(item, context=self.get_serializer_context()).data, status=code)

    def list_response(self, items, code=status.HTTP_200_OK):
        items = base_queryset().filter(pk__in=[i.pk for i in items]).order_by("period", "seq")
        return Response(ItemSerializer(items, many=True, context=self.get_serializer_context()).data, status=code)

    def valid(self, serializer_class):
        serializer = serializer_class(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    @extend_schema(request=ItemCreateSerializer, responses={201: ItemSerializer(many=True)})
    def create(self, request):
        data = self.valid(ItemCreateSerializer)
        items = services.create_items(request.user, **data)
        return self.list_response(items, status.HTTP_201_CREATED)

    @extend_schema(request=ItemUpdateSerializer, responses=ItemDetailSerializer)
    def partial_update(self, request, pk=None):
        data = self.valid(ItemUpdateSerializer)
        return self.detail_response(services.update_item(request.user, self.item_id(pk), **data))

    def item_id(self, pk) -> int:
        if not str(pk).isdigit() or not Item.objects.filter(pk=pk).exists():
            raise ActionError("Изделие не найдено.")
        return int(pk)

    @extend_schema(responses=COUNTERS)
    @action(detail=False)
    def counters(self, request):
        return Response(counters())

    @extend_schema(request=MoveSerializer, responses=ItemDetailSerializer)
    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        data = self.valid(MoveSerializer)
        return self.detail_response(services.move(request.user, self.item_id(pk), data["to"], data.get("team")))

    @extend_schema(request=BulkMoveSerializer, responses=ItemSerializer(many=True))
    @action(detail=False, methods=["post"], url_path="bulk-move")
    def bulk_move(self, request):
        data = self.valid(BulkMoveSerializer)
        items = services.bulk_move(request.user, data["ids"], data["to"], data.get("team"))
        return self.list_response(items)

    @extend_schema(request=None, responses=ItemDetailSerializer)
    @action(detail=True, methods=["post"], url_path="fabric-arrived")
    def fabric_arrived(self, request, pk=None):
        return self.detail_response(services.mark_fabric_arrived(request.user, self.item_id(pk)))

    @extend_schema(request=None, responses=ItemDetailSerializer)
    @action(detail=True, methods=["post"])
    def sew(self, request, pk=None):
        return self.detail_response(services.mark_sew(request.user, self.item_id(pk)))

    @extend_schema(request=None, responses=ItemDetailSerializer)
    @action(detail=True, methods=["post"], url_path="cover-ready")
    def cover_ready(self, request, pk=None):
        return self.detail_response(services.mark_cover_ready(request.user, self.item_id(pk)))

    @extend_schema(request=ReserveSerializer, responses=ItemDetailSerializer)
    @action(detail=True, methods=["post"])
    def reserve(self, request, pk=None):
        data = self.valid(ReserveSerializer)
        return self.detail_response(services.set_reserve(request.user, self.item_id(pk), data["reserve"]))

    @extend_schema(request=None, responses=ItemDetailSerializer)
    @action(detail=True, methods=["post"])
    def ship(self, request, pk=None):
        return self.detail_response(services.ship(request.user, self.item_id(pk)))

    @extend_schema(request=None, responses=ItemDetailSerializer)
    @action(detail=True, methods=["post"])
    def trash(self, request, pk=None):
        return self.detail_response(services.trash(request.user, self.item_id(pk)))

    @extend_schema(request=None, responses=ItemDetailSerializer)
    @action(detail=True, methods=["post"], url_path="ack-changes")
    def ack_changes(self, request, pk=None):
        return self.detail_response(services.ack_changes(request.user, self.item_id(pk)))

    @extend_schema(request=None, responses=ItemDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self.detail_response(services.cancel_order(request.user, self.item_id(pk)))

    @extend_schema(request=None, responses=ItemDetailSerializer)
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        return self.detail_response(services.restore(request.user, self.item_id(pk)))

    @extend_schema(request=None, responses=ItemDetailSerializer)
    @action(detail=True, methods=["post"], url_path="return-to-work")
    def return_to_work(self, request, pk=None):
        return self.detail_response(services.return_to_work(request.user, self.item_id(pk)))

    @extend_schema(request=None, responses=ItemDetailSerializer)
    @action(detail=True, methods=["post"])
    def copy(self, request, pk=None):
        item = services.copy_item(request.user, self.item_id(pk))
        return self.detail_response(item, status.HTTP_201_CREATED)


def _day_bound(value: str, end: bool):
    day = parse_date(value or "")
    if not day:
        raise ValidationError({"to" if end else "from": ["Дата в формате ГГГГ-ММ-ДД."]})
    return timezone.make_aware(datetime.combine(day, time.max if end else time.min))


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("user", int),
            OpenApiParameter("item", int),
            OpenApiParameter("kind", str),
            OpenApiParameter("from", str, description="ГГГГ-ММ-ДД"),
            OpenApiParameter("to", str, description="ГГГГ-ММ-ДД"),
            OpenApiParameter("q", str, description="номер, текст события или резерв"),
        ]
    )
)
class EventViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = EventSerializer

    def get_queryset(self):
        params = self.request.query_params
        qs = ItemEvent.objects.select_related("user", "item").order_by("-at", "-id")
        if params.get("user", "").isdigit():
            qs = qs.filter(user_id=int(params["user"]))
        if params.get("item", "").isdigit():
            qs = qs.filter(item_id=int(params["item"]))
        if params.get("kind"):
            qs = qs.filter(kind=params["kind"])
        if params.get("from"):
            qs = qs.filter(at__gte=_day_bound(params["from"], end=False))
        if params.get("to"):
            qs = qs.filter(at__lte=_day_bound(params["to"], end=True))
        text = (params.get("q") or "").strip()
        if text:
            qs = qs.filter(Q(item__number__icontains=text) | Q(text__icontains=text) | Q(item__reserve__icontains=text))
        return qs
