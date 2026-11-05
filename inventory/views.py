from django.db.models import Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets

from common.query import parse_bool_param

from . import services
from .models import Product, ShippingBox
from .serializers import ProductSerializer, ShippingBoxSerializer

IS_ACTIVE_PARAM = OpenApiParameter("is_active", OpenApiTypes.BOOL, description="Filter by active flag.")
SEARCH_PARAM = OpenApiParameter("search", OpenApiTypes.STR, description="Case-insensitive name/code match.")
CONFLICT_DOC = {409: OpenApiTypes.OBJECT}

# PUT is deliberately not offered: partial updates via PATCH are the only write path.
HTTP_METHODS = ["get", "post", "patch", "delete", "head", "options"]


@extend_schema_view(
    list=extend_schema(parameters=[IS_ACTIVE_PARAM, SEARCH_PARAM]),
    destroy=extend_schema(responses={204: None, **CONFLICT_DOC}),
)
@extend_schema(tags=["products"])
class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    http_method_names = HTTP_METHODS

    def get_queryset(self):
        queryset = Product.objects.all().order_by("id")
        is_active = parse_bool_param(self.request.query_params, "is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(sku__icontains=search))
        return queryset

    def perform_destroy(self, instance):
        services.delete_product(instance)


@extend_schema_view(
    list=extend_schema(parameters=[IS_ACTIVE_PARAM, SEARCH_PARAM]),
    destroy=extend_schema(responses={204: None, **CONFLICT_DOC}),
)
@extend_schema(tags=["boxes"])
class ShippingBoxViewSet(viewsets.ModelViewSet):
    serializer_class = ShippingBoxSerializer
    http_method_names = HTTP_METHODS

    def get_queryset(self):
        queryset = ShippingBox.objects.all().order_by("cost", "id")
        is_active = parse_bool_param(self.request.query_params, "is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(box_code__icontains=search))
        return queryset

    def perform_destroy(self, instance):
        services.delete_box(instance)
