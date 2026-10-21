from django.urls import path

from .views import BackupDownloadView, BackupListView, BackupRestoreView, MaintenanceView

urlpatterns = [
    path("backups/", BackupListView.as_view(), name="backups"),
    path("backups/<str:stamp>/restore/", BackupRestoreView.as_view(), name="backup-restore"),
    path("backups/<str:stamp>/<str:part>/", BackupDownloadView.as_view(), name="backup-download"),
    path("maintenance/", MaintenanceView.as_view(), name="maintenance"),
]
