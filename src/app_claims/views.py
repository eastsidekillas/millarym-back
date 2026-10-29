from pathlib import Path
from urllib.parse import quote

from django.db.models import Count
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from app_auth.permissions import ReadOrRight
from app_reports.pdf import render_pdf

from .blank import build_blank
from .models import Claim, ClaimFile, ClaimPhoto, ClaimState
from .queries import filter_claims, stats
from .serializers import (
    CHOICES,
    ClaimFileSerializer,
    ClaimListSerializer,
    ClaimPhotoSerializer,
    ClaimSerializer,
    CloseSerializer,
)

FILTERS = [
    OpenApiParameter("q", str, description="номер акта, контрагент, изделие, номер изделия, описание"),
    OpenApiParameter("claim_type", str),
    OpenApiParameter("defect_type", str),
    OpenApiParameter("sender", str),
    OpenApiParameter("state", str, description="open, done, withdrawn или closed (выполнена и снята)"),
    OpenApiParameter("from", str, description="ГГГГ-ММ-ДД"),
    OpenApiParameter("to", str, description="ГГГГ-ММ-ДД"),
]

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def pdf_response(content: bytes, name: str) -> HttpResponse:
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f"inline; filename=claim.pdf; filename*=UTF-8''{quote(name)}"
    response["Access-Control-Expose-Headers"] = "Content-Disposition"
    return response


@extend_schema_view(list=extend_schema(parameters=FILTERS))
class ClaimViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Claim.objects.none()
    pagination_class = LimitOffsetPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        return [ReadOrRight("claims")()]

    def get_queryset(self):
        qs = Claim.objects.select_related("manager", "item", "created_by", "updated_by")
        if self.action == "list":
            qs = filter_claims(qs.annotate(photos_count=Count("photos")), self.request.query_params)
        return qs.prefetch_related("photos", "files__created_by")

    def get_serializer_class(self):
        return ClaimListSerializer if self.action == "list" else ClaimSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    @extend_schema(parameters=FILTERS, responses=OpenApiTypes.OBJECT)
    @action(detail=False)
    def stats(self, request):
        return Response(stats(request.query_params))

    @extend_schema(responses=OpenApiTypes.OBJECT)
    @action(detail=False)
    def choices(self, request):
        return Response(CHOICES)

    @extend_schema(request=CloseSerializer, responses=ClaimSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        claim = self.get_object()
        data = CloseSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        claim.state = data.validated_data["state"]
        claim.close_note = data.validated_data["note"].strip()
        claim.closed_at = timezone.now()
        claim.closed_by = claim.updated_by = request.user
        claim.save()
        return Response(ClaimSerializer(claim, context=self.get_serializer_context()).data)

    @extend_schema(request=None, responses=ClaimSerializer)
    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        claim = self.get_object()
        claim.state = ClaimState.OPEN
        claim.closed_at = claim.closed_by = None
        claim.updated_by = request.user
        claim.save()
        return Response(ClaimSerializer(claim, context=self.get_serializer_context()).data)

    @extend_schema(request=ClaimPhotoSerializer, responses=ClaimPhotoSerializer)
    @action(detail=True, methods=["post"])
    def photos(self, request, pk=None):
        claim = self.get_object()
        serializer = ClaimPhotoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(claim=claim)
        claim.updated_by = request.user
        claim.save(update_fields=["updated_by", "updated_at"])
        return Response(serializer.data, status=201)

    @extend_schema(request=ClaimFileSerializer, responses=ClaimFileSerializer)
    @action(detail=True, methods=["post"])
    def files(self, request, pk=None):
        claim = self.get_object()
        serializer = ClaimFileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(claim=claim, created_by=request.user)
        claim.updated_by = request.user
        claim.save(update_fields=["updated_by", "updated_at"])
        return Response(serializer.data, status=201)

    @extend_schema(responses={204: None})
    @action(detail=True, methods=["delete"], url_path=r"files/(?P<file_id>\d+)")
    def delete_file(self, request, pk=None, file_id=None):
        claim = self.get_object()
        doc = ClaimFile.objects.filter(claim=claim, pk=file_id).first()
        if doc is None:
            raise NotFound("Файл не найден.")
        if doc.file:
            doc.file.storage.delete(doc.file.name)
        doc.delete()
        return Response(status=204)

    @extend_schema(responses={204: None})
    @action(detail=True, methods=["delete"], url_path=r"photos/(?P<photo_id>\d+)")
    def delete_photo(self, request, pk=None, photo_id=None):
        claim = self.get_object()
        photo = ClaimPhoto.objects.filter(claim=claim, pk=photo_id).first()
        if photo is None:
            raise NotFound("Фото не найдено.")
        storage = photo.photo.storage
        for path in (photo.photo.name, photo.photo_thumb.name):
            if path:
                storage.delete(path)
        photo.delete()
        return Response(status=204)

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    @action(detail=True, url_path="pdf")
    def act(self, request, pk=None):
        claim = self.get_object()
        photos = [Path(p.photo.path).as_uri() for p in claim.photos.all()[:6] if p.photo]
        content = render_pdf("claims/act.html", {"claim": claim, "photos": photos})
        return pdf_response(content, f"Акт-претензия {claim.number.replace('/', '-')}.pdf")

    @extend_schema(responses={(200, XLSX): OpenApiTypes.BINARY})
    @action(detail=False)
    def blank(self, request):
        response = HttpResponse(build_blank(), content_type=XLSX)
        name = quote("Акт-претензия, бланк для клиента.xlsx")
        response["Content-Disposition"] = f"attachment; filename=claim-blank.xlsx; filename*=UTF-8''{name}"
        response["Access-Control-Expose-Headers"] = "Content-Disposition"
        return response
