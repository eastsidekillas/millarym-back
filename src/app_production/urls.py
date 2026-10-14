from rest_framework.routers import DefaultRouter

from .views import EventViewSet, ItemViewSet

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("items", ItemViewSet, basename="item")
router.register("events", EventViewSet, basename="event")

urlpatterns = router.urls
