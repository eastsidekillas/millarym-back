from urllib.parse import quote

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from app_production.queries import base_queryset
from millarym_core.xls import excel_response

from .excel import build_xlsx
from .passport import MAX_ITEMS, mark_printed, render_passports
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
    return excel_response(build_xlsx(result), result.filename, "report")


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


def parse_ids(raw: str | None) -> list[int]:
    try:
        ids = list(dict.fromkeys(int(x) for x in (raw or "").split(",") if x.strip()))
    except ValueError:
        raise ValidationError({"detail": ["Номера изделий указаны неверно."]})
    if not ids:
        raise ValidationError({"detail": ["Выберите изделия для печати."]})
    if len(ids) > MAX_ITEMS:
        raise ValidationError({"detail": [f"За раз можно напечатать не больше {MAX_ITEMS} паспортов."]})
    return ids


class PassportView(APIView):
    @extend_schema(
        operation_id="passports_pdf",
        parameters=[OpenApiParameter("ids", str, required=True, description="id изделий через запятую")],
        responses={(200, "application/pdf"): OpenApiTypes.BINARY},
    )
    def get(self, request):
        ids = parse_ids(request.query_params.get("ids"))
        found = {i.pk: i for i in base_queryset().filter(pk__in=ids)}
        missing = [i for i in ids if i not in found]
        if missing:
            raise NotFound("Изделие не найдено." if len(missing) == 1 else "Некоторые изделия не найдены.")
        items = [found[i] for i in ids]
        pdf = render_passports(items)
        mark_printed(request.user, items)
        name = f"Паспорт {items[0].number.replace('/', '-')}.pdf" if len(items) == 1 else f"Паспорта, {len(items)} шт.pdf"
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f"inline; filename=passport.pdf; filename*=UTF-8''{quote(name)}"
        response["Access-Control-Expose-Headers"] = "Content-Disposition"
        return response
