from rest_framework.routers import DefaultRouter

from .views import ProductViewSet, ShippingBoxViewSet

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("products", ProductViewSet, basename="product")
router.register("boxes", ShippingBoxViewSet, basename="box")

urlpatterns = router.urls
