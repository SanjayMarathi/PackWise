"""The browser interface: a single page that talks to the REST API.

All business logic stays behind the API. The page is a thin client, so
everything it can do can also be done (and is tested) through ``/api/``.
"""

from django.conf import settings
from django.shortcuts import render
from django.views.decorators.http import require_GET

from packing.algorithms import RANKING_STRATEGIES


@require_GET
def index(request):
    return render(
        request,
        "web/index.html",
        {
            "version": settings.APP_VERSION,
            "strategies": sorted(RANKING_STRATEGIES),
            "default_strategy": settings.PACKWISE["RANKING_STRATEGY"],
        },
    )
