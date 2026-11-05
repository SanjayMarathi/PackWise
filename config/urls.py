from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from common.views import health
from web.views import index

urlpatterns = [
    path("", index, name="home"),  # browser interface (single page over the REST API)
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("api/", include("assistant.urls")),
    path("api/", include("packing.urls")),
    path("api/", include("inventory.urls")),
    path("api/", include("orders.urls")),
]
