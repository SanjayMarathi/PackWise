"""The browser interface: page rendering and static assets (incl. production manifest storage)."""

import json
import re

import pytest
from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.test import override_settings

pytestmark = pytest.mark.django_db

ASSETS = [
    "web/css/app.css",
    "web/js/app.js",
    "web/js/api.js",
    "web/js/dom.js",
    "web/js/viewer.js",
    "web/js/views/pack.js",
    "web/js/views/result.js",
    "web/js/views/orders.js",
    "web/js/views/catalog.js",
    "web/vendor/three/three.module.min.js",
    "web/vendor/three/addons/controls/OrbitControls.js",
]


def test_home_page_renders_the_app_shell(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.content.decode()
    assert '<main id="app"' in html
    for route in ("#/pack", "#/orders", "#/products", "#/boxes"):
        assert f'href="{route}"' in html
    assert '<script type="importmap">' in html
    assert 'type="module"' in html


def test_page_passes_strategies_to_the_client(client, settings):
    settings.PACKWISE = {**settings.PACKWISE, "RANKING_STRATEGY": "smallest_box"}
    html = client.get("/").content.decode()
    strategies = re.search(r'<script id="strategies" type="application/json">(.*?)</script>', html).group(1)
    default = re.search(r'<script id="default-strategy" type="application/json">(.*?)</script>', html).group(1)
    assert json.loads(strategies) == ["best_utilization", "lowest_cost", "smallest_box"]
    assert json.loads(default) == "smallest_box"


def test_import_map_is_valid_json(client):
    html = client.get("/").content.decode()
    import_map = json.loads(re.search(r'<script type="importmap">(.*?)</script>', html, re.S).group(1))
    assert set(import_map["imports"]) == {"three", "three/addons/controls/OrbitControls.js"}


def test_home_page_only_accepts_get(client):
    assert client.post("/").status_code == 405


@pytest.mark.parametrize("asset", ASSETS)
def test_every_referenced_asset_exists(asset):
    assert finders.find(asset), f"missing static asset {asset}"


def test_assets_are_served(client):
    response = client.get("/static/web/js/app.js")
    assert response.status_code == 200
    assert b"import" in b"".join(response.streaming_content)


def test_page_renders_with_production_manifest_storage(client, tmp_path):
    """Hashed (manifest) static storage fails for any reference without a manifest entry.

    Directory references in the import map, for example, would work in
    development and break in production. Run collectstatic exactly as the
    Docker build does, then render the page.
    """
    storages = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    with override_settings(STATIC_ROOT=tmp_path, STORAGES=storages):
        call_command("collectstatic", interactive=False, verbosity=0)
        response = client.get("/")
    assert response.status_code == 200
    html = response.content.decode()
    assert re.search(r"/static/web/js/app\.[0-9a-f]{12}\.js", html)
    assert re.search(r"/static/web/vendor/three/three\.module\.min\.[0-9a-f]{12}\.js", html)
    # ES-module relative imports ("./api.js") resolve to the unhashed copies, which must exist too.
    assert (tmp_path / "web" / "js" / "api.js").exists()
    assert (tmp_path / "web" / "js" / "views" / "result.js").exists()
