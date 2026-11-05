from django.urls import path

from .views import RecommendationListView, RecommendView

urlpatterns = [
    path("orders/<int:order_id>/recommend/", RecommendView.as_view(), name="order-recommend"),
    path("orders/<int:order_id>/recommendations/", RecommendationListView.as_view(), name="order-recommendations"),
]
