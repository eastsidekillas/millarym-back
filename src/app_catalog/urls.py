from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    CategoryViewSet,
    DeadlinesView,
    FabricViewSet,
    KitOptionViewSet,
    ProductModelViewSet,
    TeamViewSet,
)

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("categories", CategoryViewSet)
router.register("models", ProductModelViewSet)
router.register("fabrics", FabricViewSet)
router.register("kit-options", KitOptionViewSet)
router.register("teams", TeamViewSet)

urlpatterns = [path("deadlines/", DeadlinesView.as_view(), name="deadlines"), *router.urls]
