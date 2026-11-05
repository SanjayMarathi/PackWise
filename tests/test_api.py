"""End-to-end API tests through DRF's APIClient (real PostgreSQL)."""

from decimal import Decimal

import pytest
from django.db import DatabaseError

from inventory.models import Product, ShippingBox
from orders.models import Order

pytestmark = pytest.mark.django_db

PRODUCT = {"name": "Laptop", "sku": "lap-14", "length": "33.00", "width": 23, "height": 2.5, "weight": "1.400"}
BOX = {
    "name": "Medium",
    "box_code": "bx-m",
    "internal_length": 40,
    "internal_width": 30,
    "internal_height": 20,
    "max_weight": 15,
    "cost": "35.00",
}


def assert_error(response, status_code, code):
    assert response.status_code == status_code, response.content
    body = response.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == code
    return body["error"]


# ---------------------------------------------------------------- products


def test_product_create_and_retrieve(api_client):
    created = api_client.post("/api/products/", PRODUCT, format="json")
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["sku"] == "LAP-14"  # normalised
    assert body["length"] == 33.0 and body["height"] == 2.5 and body["weight"] == 1.4
    assert body["volume"] == pytest.approx(33 * 23 * 2.5)
    assert body["is_active"] is True

    fetched = api_client.get(f"/api/products/{body['id']}/")
    assert fetched.status_code == 200
    assert fetched.json() == body


def test_product_list_is_paginated_and_filterable(api_client, make_product):
    for n in range(3):
        make_product(name=f"Phone {n}", sku=f"PHONE-{n}")
    make_product(name="Old cable", sku="CABLE-OLD", is_active=False)

    page = api_client.get("/api/products/", {"page_size": 2}).json()
    assert page["count"] == 4
    assert len(page["results"]) == 2
    assert page["next"] is not None

    active = api_client.get("/api/products/", {"is_active": "false"}).json()
    assert [p["sku"] for p in active["results"]] == ["CABLE-OLD"]
    assert api_client.get("/api/products/", {"search": "phone"}).json()["count"] == 3


def test_product_list_rejects_invalid_boolean_filter(api_client):
    assert_error(api_client.get("/api/products/", {"is_active": "maybe"}), 400, "validation_error")


def test_product_patch(api_client, make_product):
    product = make_product()
    response = api_client.patch(f"/api/products/{product.pk}/", {"weight": "2.5", "is_active": False}, format="json")
    assert response.status_code == 200
    product.refresh_from_db()
    assert product.weight == Decimal("2.5")
    assert product.is_active is False


def test_put_is_not_allowed(api_client, make_product):
    product = make_product()
    assert_error(api_client.put(f"/api/products/{product.pk}/", PRODUCT, format="json"), 405, "method_not_allowed")


@pytest.mark.parametrize(
    ("field", "value"),
    [("length", 0), ("width", -1), ("height", "abc"), ("weight", 0), ("length", "10.555"), ("weight", None)],
)
def test_invalid_product_values_are_rejected(api_client, field, value):
    error = assert_error(
        api_client.post("/api/products/", {**PRODUCT, field: value}, format="json"), 400, "validation_error"
    )
    assert field in error["details"]
    assert not Product.objects.exists()


def test_missing_required_product_fields(api_client):
    error = assert_error(api_client.post("/api/products/", {"name": "x"}, format="json"), 400, "validation_error")
    assert {"sku", "length", "width", "height", "weight"} <= set(error["details"])


def test_duplicate_sku_is_rejected_case_insensitively(api_client):
    assert api_client.post("/api/products/", PRODUCT, format="json").status_code == 201
    error = assert_error(
        api_client.post("/api/products/", {**PRODUCT, "sku": "LAP-14"}, format="json"), 400, "validation_error"
    )
    assert "sku" in error["details"]


def test_invalid_sku_characters_are_rejected(api_client):
    assert_error(
        api_client.post("/api/products/", {**PRODUCT, "sku": "bad sku!"}, format="json"), 400, "validation_error"
    )


def test_unknown_and_read_only_fields_are_rejected(api_client):
    error = assert_error(
        api_client.post("/api/products/", {**PRODUCT, "id": 999, "colour": "red"}, format="json"),
        400,
        "validation_error",
    )
    assert error["details"] == {"id": ["This field is read-only."], "colour": ["Unknown field."]}


def test_all_validation_problems_are_reported_together(api_client):
    payload = {**PRODUCT, "length": 0, "width": -2, "colour": "red"}
    error = assert_error(api_client.post("/api/products/", payload, format="json"), 400, "validation_error")
    assert set(error["details"]) == {"length", "width", "colour"}


def test_product_delete(api_client, make_product):
    product = make_product()
    assert api_client.delete(f"/api/products/{product.pk}/").status_code == 204
    assert not Product.objects.filter(pk=product.pk).exists()


def test_deleting_a_product_used_by_an_order_is_a_conflict(api_client, make_product, make_order):
    product = make_product()
    make_order((product, 1))
    assert_error(api_client.delete(f"/api/products/{product.pk}/"), 409, "product_in_use")
    assert Product.objects.filter(pk=product.pk).exists()


def test_nonexistent_product_returns_404(api_client):
    error = assert_error(api_client.get("/api/products/999999/"), 404, "not_found")
    assert error["message"]
    assert_error(api_client.patch("/api/products/999999/", {"name": "x"}, format="json"), 404, "not_found")
    assert_error(api_client.delete("/api/products/999999/"), 404, "not_found")


# ---------------------------------------------------------------- boxes


def test_box_create_and_retrieve(api_client):
    created = api_client.post("/api/boxes/", BOX, format="json")
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["box_code"] == "BX-M"
    assert body["internal_volume"] == 24000.0
    assert body["cost"] == 35.0
    assert api_client.get(f"/api/boxes/{body['id']}/").json() == body


def test_box_list_orders_by_cost(api_client, make_box):
    make_box(cost=50, box_code="B")
    make_box(cost=10, box_code="A")
    codes = [b["box_code"] for b in api_client.get("/api/boxes/").json()["results"]]
    assert codes == ["A", "B"]


def test_box_list_filters(api_client, make_box):
    make_box(box_code="MAILER-1", name="Mailer")
    make_box(box_code="CRATE-1", name="Crate", is_active=False)
    inactive = api_client.get("/api/boxes/", {"is_active": "false"}).json()["results"]
    assert [b["box_code"] for b in inactive] == ["CRATE-1"]
    assert [b["box_code"] for b in api_client.get("/api/boxes/", {"search": "mail"}).json()["results"]] == ["MAILER-1"]


@pytest.mark.parametrize(
    ("field", "value"),
    [("internal_length", 0), ("internal_width", -5), ("internal_height", 0), ("max_weight", 0), ("cost", -1)],
)
def test_invalid_box_values_are_rejected(api_client, field, value):
    error = assert_error(api_client.post("/api/boxes/", {**BOX, field: value}, format="json"), 400, "validation_error")
    assert field in error["details"]
    assert not ShippingBox.objects.exists()


def test_free_box_is_allowed(api_client):
    assert api_client.post("/api/boxes/", {**BOX, "cost": 0}, format="json").status_code == 201


def test_box_patch_and_delete(api_client, make_box):
    box = make_box()
    assert api_client.patch(f"/api/boxes/{box.pk}/", {"is_active": False}, format="json").json()["is_active"] is False
    assert api_client.delete(f"/api/boxes/{box.pk}/").status_code == 204


def test_deleting_a_box_with_stored_recommendations_is_a_conflict(api_client, make_box, make_product, make_order):
    box = make_box()
    order = make_order((make_product(), 1))
    assert api_client.post(f"/api/orders/{order.pk}/recommend/", {}, format="json").status_code == 200
    assert_error(api_client.delete(f"/api/boxes/{box.pk}/"), 409, "box_in_use")


def test_nonexistent_box_returns_404(api_client):
    assert_error(api_client.get("/api/boxes/424242/"), 404, "not_found")


# ---------------------------------------------------------------- orders


def test_order_creation(api_client, make_product):
    laptop, mouse = make_product(sku="LAPTOP"), make_product(sku="MOUSE", weight="0.1")
    response = api_client.post(
        "/api/orders/",
        {"items": [{"product_id": laptop.pk, "quantity": 2}, {"product_id": mouse.pk, "quantity": 1}]},
        format="json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["order_number"].startswith("ORD-")
    assert body["status"] == "pending"
    assert body["total_units"] == 3
    assert body["total_weight"] == 2.1
    assert [(i["sku"], i["quantity"]) for i in body["items"]] == [("LAPTOP", 2), ("MOUSE", 1)]
    assert response["Location"] == f"/api/orders/{body['id']}/"


def test_order_with_explicit_number(api_client, make_product):
    product = make_product()
    payload = {"order_number": "web-1001", "items": [{"product_id": product.pk, "quantity": 1}]}
    assert api_client.post("/api/orders/", payload, format="json").json()["order_number"] == "WEB-1001"
    error = assert_error(api_client.post("/api/orders/", payload, format="json"), 400, "validation_error")
    assert "order_number" in error["details"]


@pytest.mark.parametrize(
    ("items", "expected_fragment"),
    [
        ([], "empty"),
        (None, "null"),
        ("not-a-list", "list"),
        ([{"product_id": 1}], "required"),
        ([{"product_id": 1, "quantity": 0}], "greater than or equal to 1"),
        ([{"product_id": 1, "quantity": "two"}], "valid integer"),
        ([{"product_id": 999999, "quantity": 1}], "Unknown product_id"),
    ],
)
def test_invalid_order_payloads_are_rejected(api_client, items, expected_fragment):
    response = api_client.post("/api/orders/", {"items": items}, format="json")
    error = assert_error(response, 400, "validation_error")
    assert expected_fragment in str(error["details"])
    assert not Order.objects.exists()


def test_order_without_items_key_is_rejected(api_client):
    error = assert_error(api_client.post("/api/orders/", {}, format="json"), 400, "validation_error")
    assert "items" in error["details"]


def test_order_rejects_duplicate_and_inactive_products(api_client, make_product):
    product = make_product()
    inactive = make_product(is_active=False)
    dup = [{"product_id": product.pk, "quantity": 1}, {"product_id": product.pk, "quantity": 2}]
    assert "Duplicate" in str(
        assert_error(api_client.post("/api/orders/", {"items": dup}, format="json"), 400, "validation_error")
    )
    inactive_items = [{"product_id": inactive.pk, "quantity": 1}]
    assert "Inactive" in str(
        assert_error(api_client.post("/api/orders/", {"items": inactive_items}, format="json"), 400, "validation_error")
    )


def test_order_rejects_too_many_units(api_client, make_product, settings):
    settings.PACKWISE = {**settings.PACKWISE, "MAX_ITEMS_PER_ORDER": 5}
    product = make_product()
    response = api_client.post("/api/orders/", {"items": [{"product_id": product.pk, "quantity": 6}]}, format="json")
    assert "at most 5 units" in str(assert_error(response, 400, "validation_error"))


def test_order_rejects_too_many_lines(api_client, make_product, settings):
    settings.PACKWISE = {**settings.PACKWISE, "MAX_LINES_PER_ORDER": 2}
    items = [{"product_id": make_product().pk, "quantity": 1} for _ in range(3)]
    response = api_client.post("/api/orders/", {"items": items}, format="json")
    assert "at most 2 lines" in str(assert_error(response, 400, "validation_error"))


def test_order_rejects_mass_assigned_status(api_client, make_product):
    product = make_product()
    payload = {"status": "recommended", "items": [{"product_id": product.pk, "quantity": 1}]}
    error = assert_error(api_client.post("/api/orders/", payload, format="json"), 400, "validation_error")
    assert error["details"] == {"status": ["Unknown field."]}


def test_order_list_retrieve_and_status_filter(api_client, make_product, make_order):
    product = make_product()
    first = make_order((product, 1))
    second = make_order((product, 2))
    Order.objects.filter(pk=second.pk).update(status=Order.Status.RECOMMENDED)

    listing = api_client.get("/api/orders/").json()
    assert listing["count"] == 2
    assert [o["id"] for o in listing["results"]] == [second.pk, first.pk]  # newest first
    assert [o["id"] for o in api_client.get("/api/orders/", {"status": "recommended"}).json()["results"]] == [second.pk]
    assert_error(api_client.get("/api/orders/", {"status": "lost"}), 400, "validation_error")
    assert api_client.get(f"/api/orders/{first.pk}/").json()["order_number"] == first.order_number


def test_order_items_endpoint(api_client, make_product, make_order):
    a, b = make_product(sku="A-1", length=5), make_product(sku="B-1")
    order = make_order((a, 3), (b, 1))
    body = api_client.get(f"/api/orders/{order.pk}/items/").json()
    assert body["count"] == 2
    assert body["results"][0] == {
        "id": body["results"][0]["id"],
        "product_id": a.pk,
        "sku": "A-1",
        "name": a.name,
        "quantity": 3,
        "unit_weight": 1.0,
        "dimensions": {"length": 5.0, "width": 10.0, "height": 10.0},
    }


def test_orders_are_immutable(api_client, make_product, make_order):
    order = make_order((make_product(), 1))
    assert_error(api_client.patch(f"/api/orders/{order.pk}/", {}, format="json"), 405, "method_not_allowed")
    assert_error(api_client.delete(f"/api/orders/{order.pk}/"), 405, "method_not_allowed")


def test_nonexistent_order_returns_404(api_client):
    assert_error(api_client.get("/api/orders/999999/"), 404, "not_found")
    assert_error(api_client.get("/api/orders/999999/items/"), 404, "not_found")


# ---------------------------------------------------------------- recommendations


@pytest.fixture
def ordered_laptops(api_client, catalog):
    p = catalog["products"]
    response = api_client.post(
        "/api/orders/",
        {"items": [{"product_id": p["laptop"].pk, "quantity": 2}, {"product_id": p["mouse"].pk, "quantity": 1}]},
        format="json",
    )
    return response.json()


def test_recommendation_generation(api_client, ordered_laptops, catalog):
    response = api_client.post(f"/api/orders/{ordered_laptops['id']}/recommend/", {}, format="json")
    assert response.status_code == 200, response.content
    body = response.json()

    assert body["status"] == "success"
    assert body["order_id"] == ordered_laptops["id"]
    assert body["order_status"] == "recommended"
    assert body["strategy"] == "lowest_cost"
    rec = body["recommendation"]
    assert rec["box_code"] == "MEDIUM-FLAT"  # 35 INR, fuller than the equally priced MEDIUM
    assert rec["cost"] == 35.0
    assert rec["total_weight"] == 2.9
    assert rec["packing_feasible"] is True
    assert 0 < rec["utilization"] <= 100
    assert len(rec["placements"]) == 3
    assert [a["box_code"] for a in body["alternatives"]] == ["MEDIUM", "LARGE"]
    assert {r["box_code"]: r["feasibility"] for r in body["rejected_boxes"]} == {"SMALL": "proven_infeasible"}
    assert body["summary"]["boxes_evaluated"] == 4
    assert body["summary"]["feasible_boxes"] == 3

    for placement in rec["placements"]:
        pos, dims = placement["position"], placement["dimensions"]
        assert pos["x"] + dims["length"] <= rec["box_dimensions"]["length"]
        assert pos["y"] + dims["width"] <= rec["box_dimensions"]["width"]
        assert pos["z"] + dims["height"] <= rec["box_dimensions"]["height"]


def test_recommendation_retrieval_matches_generation(api_client, ordered_laptops):
    order_id = ordered_laptops["id"]
    generated = api_client.post(
        f"/api/orders/{order_id}/recommend/", {"strategy": "smallest_box"}, format="json"
    ).json()
    stored = api_client.get(f"/api/orders/{order_id}/recommendations/")
    assert stored.status_code == 200
    body = stored.json()
    assert body["status"] == "success"
    assert body["strategy"] == "smallest_box"
    assert body["recommendation"] == generated["recommendation"]
    assert body["alternatives"] == generated["alternatives"]
    assert body["generated_at"] == generated["generated_at"]


def test_recommendations_before_generation(api_client, ordered_laptops):
    body = api_client.get(f"/api/orders/{ordered_laptops['id']}/recommendations/").json()
    assert body["status"] == "not_generated"
    assert body["recommendation"] is None
    assert body["alternatives"] == []


def test_no_feasible_box_is_a_successful_computation(api_client, catalog):
    dumbbell = catalog["products"]["dumbbell"]
    order = api_client.post(
        "/api/orders/", {"items": [{"product_id": dumbbell.pk, "quantity": 3}]}, format="json"
    ).json()

    body = api_client.post(f"/api/orders/{order['id']}/recommend/", {}, format="json").json()
    assert body["status"] == "no_feasible_box"
    assert body["recommendation"] is None
    assert len(body["rejected_boxes"]) == 4
    stored = api_client.get(f"/api/orders/{order['id']}/recommendations/").json()
    assert stored["status"] == "no_feasible_box"
    assert stored["order_status"] == "no_feasible_box"


@pytest.mark.parametrize(
    ("payload", "field"),
    [({"strategy": "random"}, "strategy"), ({"strategy": "lowest_cost", "force": True}, "force")],
)
def test_invalid_recommendation_requests(api_client, ordered_laptops, payload, field):
    response = api_client.post(f"/api/orders/{ordered_laptops['id']}/recommend/", payload, format="json")
    assert field in assert_error(response, 400, "validation_error")["details"]


def test_recommend_for_nonexistent_order(api_client):
    assert_error(api_client.post("/api/orders/999999/recommend/", {}, format="json"), 404, "not_found")
    assert_error(api_client.get("/api/orders/999999/recommendations/"), 404, "not_found")


def test_recommend_for_empty_order_is_unprocessable(api_client, catalog):
    order = Order.objects.create(order_number="ADMIN-EMPTY")
    assert_error(api_client.post(f"/api/orders/{order.pk}/recommend/", {}, format="json"), 422, "empty_order")


def test_recommend_requires_post(api_client, ordered_laptops):
    assert_error(api_client.get(f"/api/orders/{ordered_laptops['id']}/recommend/"), 405, "method_not_allowed")


# ---------------------------------------------------------------- cross-cutting behaviour


def test_malformed_json_returns_parse_error(api_client):
    response = api_client.post("/api/products/", data="{not json", content_type="application/json")
    assert_error(response, 400, "parse_error")


def test_unsupported_media_type(api_client):
    response = api_client.post("/api/products/", data="a=b", content_type="application/x-www-form-urlencoded")
    assert_error(response, 415, "unsupported_media_type")


def test_unexpected_errors_do_not_leak_internals(api_client, ordered_laptops, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("secret database password is hunter2")

    monkeypatch.setattr("packing.views.recommend_box_for_order", explode)
    response = api_client.post(f"/api/orders/{ordered_laptops['id']}/recommend/", {}, format="json")
    error = assert_error(response, 500, "server_error")
    assert "hunter2" not in response.content.decode()
    assert error["message"] == "An unexpected error occurred."


def test_recommend_endpoint_is_throttled(api_client, ordered_laptops, monkeypatch):
    from django.core.cache import cache
    from rest_framework.throttling import ScopedRateThrottle

    cache.clear()
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"recommend": "2/minute"})
    url = f"/api/orders/{ordered_laptops['id']}/recommend/"
    assert [api_client.post(url, {}, format="json").status_code for _ in range(2)] == [200, 200]
    throttled = api_client.post(url, {}, format="json")
    assert_error(throttled, 429, "throttled")
    assert "Retry-After" in throttled
    cache.clear()


def test_health_check(api_client):
    response = api_client.get("/api/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "version": "1.0.0"}


def test_health_check_reports_database_outage(api_client, monkeypatch):
    class BrokenConnection:
        def cursor(self):
            raise DatabaseError("connection refused")

    monkeypatch.setattr("common.health.connection", BrokenConnection())
    response = api_client.get("/api/health/")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable", "version": "1.0.0"}


def test_health_check_accepts_probe_hosts_but_other_paths_do_not(api_client):
    """Probes connect by IP; that Host is not in ALLOWED_HOSTS, yet the probe must succeed."""
    assert api_client.get("/api/health/", HTTP_HOST="10.0.0.7:8000").status_code == 200
    assert api_client.get("/api/products/", HTTP_HOST="10.0.0.7:8000").status_code == 400


def test_health_view_documents_the_same_payload(rf):
    from common.views import health

    response = health(rf.get("/api/health/"))
    assert response.status_code == 200
    assert response.data["database"] == "ok"


def test_openapi_schema_and_docs_are_served(api_client):
    schema = api_client.get("/api/schema/")
    assert schema.status_code == 200
    content = schema.content.decode()
    for path in ("/api/products/", "/api/boxes/", "/api/orders/{id}/items/", "/api/orders/{order_id}/recommend/"):
        assert path in content
    assert api_client.get("/api/docs/").status_code == 200
    assert api_client.get("/").status_code == 302
