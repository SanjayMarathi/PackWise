from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from orders.models import Order

from .serializers import (
    RecommendationResponseSerializer,
    RecommendRequestSerializer,
    StoredRecommendationsSerializer,
    outcome_payload,
    stored_payload,
)
from .services.recommendation_service import recommend_box_for_order

ERRORS = {400: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT, 422: OpenApiTypes.OBJECT, 429: OpenApiTypes.OBJECT}


class RecommendView(APIView):
    throttle_scope = "recommend"  # packing is CPU-bound, so it gets a tighter limit

    @extend_schema(
        tags=["recommendations"],
        summary="Compute, store and return the best box for an order",
        description=(
            "Runs the 3D packing engine against every active box. Feasible boxes are ranked "
            "(default: lowest cost, then highest utilization, then smallest volume) and stored, "
            "replacing earlier results. A result of `no_feasible_box` is a successful "
            "computation, so it returns HTTP 200."
        ),
        request=RecommendRequestSerializer,
        responses={200: RecommendationResponseSerializer, **ERRORS},
        examples=[
            OpenApiExample("Default strategy", value={}, request_only=True),
            OpenApiExample("Best utilization", value={"strategy": "best_utilization"}, request_only=True),
        ],
    )
    def post(self, request, order_id: int):
        order = get_object_or_404(Order, pk=order_id)
        params = RecommendRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        outcome = recommend_box_for_order(order, strategy=params.validated_data.get("strategy"))
        return Response(RecommendationResponseSerializer(outcome_payload(outcome)).data)


class RecommendationListView(APIView):
    @extend_schema(
        tags=["recommendations"],
        summary="Return the stored recommendation and ranked alternatives for an order",
        responses={200: StoredRecommendationsSerializer, 404: OpenApiTypes.OBJECT},
    )
    def get(self, request, order_id: int):
        order = get_object_or_404(Order, pk=order_id)
        rows = list(order.recommendations.select_related("box").order_by("rank"))
        return Response(StoredRecommendationsSerializer(stored_payload(order, rows)).data)
