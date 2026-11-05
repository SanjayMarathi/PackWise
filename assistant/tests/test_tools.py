"""Each assistant tool against real services and PostgreSQL."""

import json

import pytest

from assistant import tools
from orders.models import Order

pytestmark = pytest.mark.django_db


def call(name, args):
    outcome = tools.run_tool(name, args)
    return outcome, json.loads(outcome.content)


def test_list_products_search_and_inactive(catalog, make_product):
    make_product(name="Retired laptop", sku="LAPTOP-OLD", is_active=False)
    _, data = call("list_products", {"search": "laptop"})
    assert [p["sku"] for p in data["products"]] == ["LAPTOP"]
    assert data["products"][0]["dimensions_cm"] == {"length": 33.0, "width": 23.0, "height": 2.0}
    _, data = call("list_products", {"search": "laptop", "include_inactive": True})
    assert [p["sku"] for p in data["products"]] == ["LAPTOP", "LAPTOP-OLD"]


def test_list_boxes(catalog):
    _, data = call("list_boxes", {})
    assert data["count"] == 4
    assert data["boxes"][0] == {
        "box_code": "SMALL",
        "name": "Small",
        "inner_dimensions_cm": {"length": 25.0, "width": 20.0, "height": 10.0},
        "max_weight_kg": 5.0,
        "cost_inr": 20.0,
        "active": True,
    }
    _, data = call("list_boxes", {"include_inactive": True})
    assert "RETIRED" in [b["box_code"] for b in data["boxes"]]


def test_recommend_box_creates_order_and_card(catalog):
    outcome, data = call(
        "recommend_box", {"items": [{"sku": "laptop", "quantity": 1}, {"sku": "MOUSE", "quantity": 1}]}
    )
    assert not outcome.is_error
    assert data["recommended"]["box_code"] == "MEDIUM-FLAT"
    assert data["recommended"]["items_placed"] == 2
    assert {r["box_code"]: r["feasibility"] for r in data["rejected"]} == {"SMALL": "proven_infeasible"}
    assert outcome.card["order_number"] == data["order_number"]
    assert Order.objects.filter(order_number=data["order_number"]).exists()


def test_recommend_box_merges_repeated_skus(catalog):
    _, data = call("recommend_box", {"items": [{"sku": "MOUSE", "quantity": 1}, {"sku": "mouse", "quantity": 2}]})
    order = Order.objects.get(pk=data["order_id"])
    assert [(i.product.sku, i.quantity) for i in order.items.all()] == [("MOUSE", 3)]


def test_recommend_box_with_strategy(catalog):
    _, data = call("recommend_box", {"items": [{"sku": "MOUSE", "quantity": 1}], "strategy": "best_utilization"})
    assert data["strategy"] == "best_utilization"


@pytest.mark.parametrize(
    ("args", "fragment"),
    [
        ({}, "'items' must be a non-empty list"),
        ({"items": []}, "'items' must be a non-empty list"),
        ({"items": [{"quantity": 1}]}, "needs a 'sku'"),
        ({"items": [{"sku": "MOUSE", "quantity": 0}]}, "at least 1"),
        ({"items": [{"sku": "MOUSE", "quantity": True}]}, "at least 1"),
        ({"items": [{"sku": "NOPE", "quantity": 1}]}, "Unknown SKU"),
        ({"items": [{"sku": "MOUSE", "quantity": 1}], "strategy": "random"}, "'strategy' must be one of"),
        ("not an object", "must be a JSON object"),
    ],
)
def test_recommend_box_validation(catalog, args, fragment):
    outcome, data = call("recommend_box", args)
    assert outcome.is_error
    assert fragment in data["error"]
    assert not Order.objects.exists()


def test_recommend_box_rejects_inactive_products(catalog, make_product):
    make_product(sku="OLD-1", is_active=False)
    outcome, data = call("recommend_box", {"items": [{"sku": "OLD-1", "quantity": 1}]})
    assert outcome.is_error
    assert "Inactive" in data["error"]


def test_recommend_box_respects_unit_limit(catalog, settings):
    settings.PACKWISE = {**settings.PACKWISE, "MAX_ITEMS_PER_ORDER": 3}
    outcome, data = call("recommend_box", {"items": [{"sku": "MOUSE", "quantity": 4}]})
    assert outcome.is_error
    assert "at most 3 units" in data["error"]


def test_check_box_fit(catalog):
    outcome, data = call("check_box_fit", {"items": [{"sku": "LAPTOP", "quantity": 1}], "box_code": "small"})
    assert not outcome.is_error
    assert data["fits"] is False
    assert data["feasibility"] == "proven_infeasible"
    assert "cannot fit inside the box in any orientation" in data["reasons"][0]

    _, data = call("check_box_fit", {"items": [{"sku": "MOUSE", "quantity": 2}], "box_code": "SMALL"})
    assert data["fits"] is True
    assert data["items_placed"] == 2
    assert not Order.objects.exists()  # checking never creates an order


def test_check_box_fit_mentions_inactive_box_and_unknown_codes(catalog):
    _, data = call("check_box_fit", {"items": [{"sku": "MOUSE", "quantity": 1}], "box_code": "RETIRED"})
    assert data["fits"] is True and "inactive" in data["note"]
    outcome, data = call("check_box_fit", {"items": [{"sku": "MOUSE", "quantity": 1}], "box_code": "NOPE"})
    assert outcome.is_error and "No box with code NOPE" in data["error"]


def test_get_order(catalog):
    _, created = call("recommend_box", {"items": [{"sku": "MOUSE", "quantity": 1}]})
    outcome, data = call("get_order", {"order_number": created["order_number"].lower()})
    assert data["status"] == "success"
    assert data["items"] == [{"sku": "MOUSE", "name": "Mouse", "quantity": 1}]
    assert data["recommended"]["box_code"] == created["recommended"]["box_code"]
    assert outcome.card is not None
    outcome, data = call("get_order", {"order_number": "ORD-NOPE"})
    assert outcome.is_error


def test_unknown_tool_and_unexpected_failures(catalog, monkeypatch):
    outcome, data = call("delete_everything", {})
    assert outcome.is_error and "Unknown tool" in data["error"]

    def explode(args):
        raise RuntimeError("secret internals")

    monkeypatch.setitem(tools.HANDLERS, "list_boxes", explode)
    outcome, data = call("list_boxes", {})
    assert outcome.is_error
    assert "secret" not in data["error"]


def test_tool_definitions_are_frozen_and_streamed():
    first, second = tools.tool_definitions(), tools.tool_definitions()
    assert first == second
    assert all(t["eager_input_streaming"] for t in first)
    assert set(tools.TOOL_LABELS) == {t["name"] for t in tools.TOOLS} == set(tools.HANDLERS)
