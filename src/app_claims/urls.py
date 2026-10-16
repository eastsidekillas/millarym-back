from rest_framework.routers import DefaultRouter

from .views import ClaimViewSet

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("claims", ClaimViewSet, basename="claim")

urlpatterns = router.urls
