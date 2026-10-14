from urllib.parse import quote

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from app_production.queries import base_queryset

from .excel import build_xlsx
from .reports import BY_KIND, REPORTS, ReportError, free_stock_models, single_item

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PARAMS = [
    OpenApiParameter("models", str, description="id моделей через запятую, custom — вне справочника"),
    OpenApiParameter("q", str),
    OpenApiParameter("only_fg", bool),
    OpenApiParameter("from", str, description="ГГГГ-ММ-ДД"),
    OpenApiParameter("to", str, description="ГГГГ-ММ-ДД"),
]


def xlsx_response(result) -> HttpResponse:
    response = HttpResponse(build_xlsx(result), content_type=XLSX)
    name = f"{result.filename}.xlsx"
    response["Content-Disposition"] = f"attachment; filename=report.xlsx; filename*=UTF-8''{quote(name)}"
    response["Access-Control-Expose-Headers"] = "Content-Disposition"
    return response


def run(kind: str, params):
    report = BY_KIND.get(kind)
    if report is None:
        raise NotFound("Такого отчёта нет.")
    try:
        return report.build({k: params.get(k) for k in params})
    except ReportError as err:
        raise ValidationError({"detail": [str(err)]})


class ReportListView(APIView):
    @extend_schema(operation_id="reports_list", responses=OpenApiTypes.OBJECT)
    def get(self, request):
        return Response([r.as_json() for r in REPORTS])


class ReportView(APIView):
    @extend_schema(parameters=PARAMS, responses=OpenApiTypes.OBJECT)
    def get(self, request, kind: str):
        return Response(run(kind, request.query_params).as_json())


class ReportXlsxView(APIView):
    @extend_schema(parameters=PARAMS, responses={(200, XLSX): OpenApiTypes.BINARY})
    def get(self, request, kind: str):
        return xlsx_response(run(kind, request.query_params))


class FreeStockModelsView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        return Response(free_stock_models())


class ItemXlsxView(APIView):
    @extend_schema(responses={(200, XLSX): OpenApiTypes.BINARY})
    def get(self, request, pk: int):
        item = base_queryset().filter(pk=pk).first()
        if item is None:
            raise NotFound("Изделие не найдено.")
        return xlsx_response(single_item(item))
