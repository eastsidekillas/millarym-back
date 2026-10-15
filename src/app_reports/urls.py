from django.urls import path

from .views import FreeStockModelsView, ItemXlsxView, PassportView, ReportListView, ReportView, ReportXlsxView

urlpatterns = [
    path("reports/", ReportListView.as_view(), name="reports"),
    path("reports/free-stock/models/", FreeStockModelsView.as_view(), name="free-stock-models"),
    path("reports/<slug:kind>/", ReportView.as_view(), name="report"),
    path("reports/<slug:kind>/xlsx/", ReportXlsxView.as_view(), name="report-xlsx"),
    path("passports/", PassportView.as_view(), name="passports"),
    path("items/<int:pk>/export/", ItemXlsxView.as_view(), name="item-xlsx"),
]
