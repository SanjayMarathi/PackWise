from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import Order
from .serializers import OrderCreateSerializer, OrderItemSerializer, OrderSerializer

STATUS_PARAM = OpenApiParameter("status", OpenApiTypes.STR, enum=Order.Status.values, description="Filter by status.")


@extend_schema_view(
    list=extend_schema(parameters=[STATUS_PARAM]),
    create=extend_schema(request=OrderCreateSerializer, responses={201: OrderSerializer}),
)
@extend_schema(tags=["orders"])
class OrderViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Orders are immutable once created. Recommendations live under /recommend/."""

    serializer_class = OrderSerializer

    def get_queryset(self):
        queryset = Order.objects.prefetch_related("items__product").order_by("-created_at", "-id")
        if self.action == "list":
            status_filter = self.request.query_params.get("status")
            if status_filter:
                if status_filter not in Order.Status.values:
                    raise ValidationError({"status": [f"Must be one of {Order.Status.values}."]})
                queryset = queryset.filter(status=status_filter)
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        output = OrderSerializer(self.get_queryset().get(pk=order.pk)).data
        location = reverse("order-detail", args=[order.pk])
        return Response(output, status=status.HTTP_201_CREATED, headers={"Location": location})

    @extend_schema(responses={200: OrderItemSerializer(many=True)})
    @action(detail=True, methods=["get"], url_path="items")
    def items(self, request, pk=None):
        order = self.get_object()
        page = self.paginate_queryset(order.items.select_related("product").order_by("id"))
        return self.get_paginated_response(OrderItemSerializer(page, many=True).data)
