"""Tools the assistant can call. Each one is a thin adapter over the existing services.

The model never computes fits or prices itself: every number it reports
comes from these functions, and so from the same packing engine and database
the rest of the app uses. All tools are read-only except ``recommend_box``,
which creates an order (the system's core action), exactly like the
"Pack order" page does.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db.models import Q

from common.exceptions import DomainError
from inventory.models import Product, ShippingBox
from inventory.services import active_boxes
from orders.models import Order, OrderItem
from orders.serializers import OrderCreateSerializer
from packing.algorithms import RANKING_STRATEGIES
from packing.serializers import outcome_payload, stored_payload
from packing.services.recommendation_service import evaluate_boxes, recommend_box_for_order
from packing.services.validation_service import OrderValidationError, validate_order_items

logger = logging.getLogger("packwise.assistant")


class ToolInputError(ValueError):
    """The model sent arguments that fail validation. Reported back to it as an error result."""


@dataclass(frozen=True)
class ToolOutcome:
    content: str  # JSON text returned to the model
    is_error: bool = False
    card: dict | None = None  # optional structured result for the chat UI


ITEMS_SCHEMA = {
    "type": "array",
    "description": "Order lines. Use exact SKUs from list_products.",
    "minItems": 1,
    "items": {
        "type": "object",
        "properties": {
            "sku": {"type": "string", "description": "Product SKU, e.g. LAPTOP-14"},
            "quantity": {"type": "integer", "minimum": 1},
        },
        "required": ["sku", "quantity"],
        "additionalProperties": False,
    },
}

# Frozen for the lifetime of a conversation: changing tools mid-conversation would
# invalidate earlier thinking blocks. Order and content never vary.
TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_products",
        "description": (
            "Search the product catalogue. Returns SKU, name, dimensions (cm), weight (kg) and whether "
            "the product can be ordered. Use it to turn product names the user mentions into SKUs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Case-insensitive match on name or SKU. Omit to list all."},
                "include_inactive": {"type": "boolean", "description": "Also list products that can't be ordered."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_boxes",
        "description": (
            "List the shipping boxes: code, name, inner dimensions (cm), maximum load (kg), cost (INR) "
            "and whether the box is in stock (active). Sorted cheapest first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"include_inactive": {"type": "boolean"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "recommend_box",
        "description": (
            "Create an order for the given items and run the 3D packing engine against every active box. "
            "Returns the recommended box, ranked alternatives and why every other box was rejected. "
            "This creates a real order; use it when the user wants a box chosen for items."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "items": ITEMS_SCHEMA,
                "strategy": {
                    "type": "string",
                    "enum": sorted(RANKING_STRATEGIES),
                    "description": "Ranking: lowest_cost (default), best_utilization or smallest_box.",
                },
            },
            "required": ["items"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_box_fit",
        "description": (
            "Check whether the given items fit one specific box, without creating an order. "
            "Use it to answer 'would these fit in box X?' or 'why not box X?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"items": ITEMS_SCHEMA, "box_code": {"type": "string", "description": "e.g. BX-S"}},
            "required": ["items", "box_code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_order",
        "description": (
            "Look up an existing order by its order number (e.g. ORD-20261105-1A2B3C4D): "
            "items, status and the stored recommendation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"order_number": {"type": "string"}},
            "required": ["order_number"],
            "additionalProperties": False,
        },
    },
]

# Human-readable progress line shown in the chat while a tool runs.
TOOL_LABELS = {
    "list_products": "Looking up products…",
    "list_boxes": "Checking the box catalogue…",
    "recommend_box": "Packing the order in 3D against every box…",
    "check_box_fit": "Test-packing the items in that box…",
    "get_order": "Fetching the order…",
}


def tool_definitions(eager_input_streaming: bool = True) -> list[dict[str, Any]]:
    # Requests are streamed, so tool inputs stream as generated; inputs are then validated here.
    return [{**tool, "eager_input_streaming": eager_input_streaming} for tool in TOOLS]


# ---------------------------------------------------------------- input validation helpers


def _object(args: Any) -> dict:
    if not isinstance(args, dict):
        raise ToolInputError("Arguments must be a JSON object.")
    return args


def _optional_bool(args: dict, key: str) -> bool:
    value = args.get(key, False)
    if not isinstance(value, bool):
        raise ToolInputError(f"'{key}' must be true or false.")
    return value


def _string(args: dict, key: str, *, required: bool) -> str | None:
    value = args.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError(f"'{key}' must be a non-empty string.")
    return value.strip()


def _items(args: dict) -> list[tuple[Product, int]]:
    """Validate order lines and resolve SKUs (case-insensitive) to products."""
    raw = args.get("items")
    if not isinstance(raw, list) or not raw:
        raise ToolInputError("'items' must be a non-empty list of {sku, quantity}.")
    quantities: dict[str, int] = {}
    for line in raw:
        if not isinstance(line, dict) or not isinstance(line.get("sku"), str) or not line["sku"].strip():
            raise ToolInputError("Each item needs a 'sku' string.")
        quantity = line.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ToolInputError(f"Quantity for {line['sku']} must be a whole number of at least 1.")
        sku = line["sku"].strip().upper()
        quantities[sku] = quantities.get(sku, 0) + quantity  # merge repeated SKUs
    products = {p.sku: p for p in Product.objects.filter(sku__in=quantities)}
    unknown = sorted(set(quantities) - set(products))
    if unknown:
        raise ToolInputError(f"Unknown SKU(s): {', '.join(unknown)}. Use list_products to find the right SKU.")
    return [(products[sku], qty) for sku, qty in quantities.items()]


def _dims(length, width, height) -> dict[str, float]:
    return {"length": float(length), "width": float(width), "height": float(height)}


def _summarize(payload: dict, include_rejected: bool = True) -> dict:
    """Compact version of a recommendation payload for the model (no placement lists)."""
    rec = payload.get("recommendation")
    summary = {
        "order_id": payload["order_id"],
        "order_number": payload["order_number"],
        "status": payload["status"],
        "strategy": payload.get("strategy"),
        "recommended": None,
        "alternatives": [
            {
                "rank": a["rank"],
                "box_code": a["box_code"],
                "box_name": a["box_name"],
                "cost_inr": float(a["cost"]),
                "utilization_pct": float(a["utilization"]),
            }
            for a in payload.get("alternatives", [])
        ],
    }
    if rec:
        summary["recommended"] = {
            "box_code": rec["box_code"],
            "box_name": rec["box_name"],
            "cost_inr": float(rec["cost"]),
            "utilization_pct": float(rec["utilization"]),
            "total_weight_kg": float(rec["total_weight"]),
            "box_max_weight_kg": float(rec["max_weight"]),
            "inner_dimensions_cm": rec["box_dimensions"],
            "items_placed": len(rec["placements"]),
            "rotated_items": sum(1 for p in rec["placements"] if p["rotated"]),
        }
    if include_rejected and "rejected_boxes" in payload:
        summary["rejected"] = [
            {
                "box_code": r["box_code"],
                "box_name": r["box_name"],
                "feasibility": r["feasibility"],
                "reasons": r["reasons"],
            }
            for r in payload["rejected_boxes"]
        ]
    return summary


def _card(payload: dict) -> dict:
    rec = payload.get("recommendation")
    return {
        "kind": "recommendation",
        "order_id": payload["order_id"],
        "order_number": payload["order_number"],
        "status": payload["status"],
        "box_name": rec["box_name"] if rec else None,
        "box_code": rec["box_code"] if rec else None,
        "cost": float(rec["cost"]) if rec else None,
        "utilization": float(rec["utilization"]) if rec else None,
        "items": len(rec["placements"]) if rec else None,
        "alternatives": len(payload.get("alternatives", [])),
    }


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=float)


# ---------------------------------------------------------------- tool implementations


def list_products(args: dict) -> ToolOutcome:
    args = _object(args)
    search = _string(args, "search", required=False)
    queryset = Product.objects.order_by("sku")
    if not _optional_bool(args, "include_inactive"):
        queryset = queryset.filter(is_active=True)
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(sku__icontains=search))
    products = [
        {
            "sku": p.sku,
            "name": p.name,
            "dimensions_cm": _dims(p.length, p.width, p.height),
            "weight_kg": float(p.weight),
            "active": p.is_active,
        }
        for p in queryset[:100]
    ]
    return ToolOutcome(_json({"count": len(products), "products": products}))


def list_boxes(args: dict) -> ToolOutcome:
    args = _object(args)
    queryset = (
        ShippingBox.objects.order_by("cost", "id") if _optional_bool(args, "include_inactive") else active_boxes()
    )
    boxes = [
        {
            "box_code": b.box_code,
            "name": b.name,
            "inner_dimensions_cm": _dims(b.internal_length, b.internal_width, b.internal_height),
            "max_weight_kg": float(b.max_weight),
            "cost_inr": float(b.cost),
            "active": b.is_active,
        }
        for b in queryset
    ]
    return ToolOutcome(_json({"count": len(boxes), "boxes": boxes}))


def recommend_box(args: dict) -> ToolOutcome:
    args = _object(args)
    lines = _items(args)
    strategy = _string(args, "strategy", required=False)
    if strategy and strategy not in RANKING_STRATEGIES:
        raise ToolInputError(f"'strategy' must be one of {sorted(RANKING_STRATEGIES)}.")
    # Reuse the API's order validation (active products, unit and line limits).
    serializer = OrderCreateSerializer(data={"items": [{"product_id": p.pk, "quantity": q} for p, q in lines]})
    if not serializer.is_valid():
        raise ToolInputError(f"The order is not valid: {serializer.errors}")
    order = serializer.save()
    payload = outcome_payload(recommend_box_for_order(order, strategy=strategy))
    return ToolOutcome(_json(_summarize(payload)), card=_card(payload))


def check_box_fit(args: dict) -> ToolOutcome:
    args = _object(args)
    lines = _items(args)
    code = _string(args, "box_code", required=True).upper()
    box = ShippingBox.objects.filter(box_code=code).first()
    if box is None:
        raise ToolInputError(f"No box with code {code}. Use list_boxes to see the codes.")
    try:
        item_lines = validate_order_items([OrderItem(product=p, quantity=q) for p, q in lines])
    except OrderValidationError as exc:
        raise ToolInputError(exc.message) from exc
    labels = {p.pk: f"{p.sku} ({p.length}×{p.width}×{p.height} cm)" for p, _ in lines}
    feasible, rejected = evaluate_boxes(
        item_lines, [box], strategy=settings.PACKWISE["RANKING_STRATEGY"], labels=labels
    )
    result: dict[str, Any] = {"box_code": box.box_code, "box_name": box.name, "box_active": box.is_active}
    if feasible:
        packing = feasible[0].result
        result.update(
            fits=True,
            feasibility="feasible",
            utilization_pct=packing.utilization_percentage,
            items_placed=len(packing.placements),
        )
    else:
        result.update(fits=False, feasibility=rejected[0].status, reasons=list(rejected[0].reasons))
    if not box.is_active:
        result["note"] = "This box is inactive (out of stock), so it is never recommended."
    return ToolOutcome(_json(result))


def get_order(args: dict) -> ToolOutcome:
    args = _object(args)
    number = _string(args, "order_number", required=True).upper()
    order = Order.objects.prefetch_related("items__product").filter(order_number=number).first()
    if order is None:
        raise ToolInputError(f"No order with number {number}.")
    rows = list(order.recommendations.select_related("box").order_by("rank"))
    payload = stored_payload(order, rows)
    data = _summarize(payload, include_rejected=False)
    data["items"] = [{"sku": i.product.sku, "name": i.product.name, "quantity": i.quantity} for i in order.items.all()]
    return ToolOutcome(_json(data), card=_card(payload) if rows else None)


HANDLERS = {
    "list_products": list_products,
    "list_boxes": list_boxes,
    "recommend_box": recommend_box,
    "check_box_fit": check_box_fit,
    "get_order": get_order,
}


def run_tool(name: str, args: Any) -> ToolOutcome:
    """Run one tool. Failures become error results the model can read and recover from."""
    handler = HANDLERS.get(name)
    if handler is None:
        return ToolOutcome(_json({"error": f"Unknown tool {name}."}), is_error=True)
    try:
        return handler(args)
    except ToolInputError as exc:
        return ToolOutcome(_json({"error": str(exc)}), is_error=True)
    except DomainError as exc:  # business rule from a service, e.g. too many units
        return ToolOutcome(_json({"error": exc.message}), is_error=True)
    except Exception:  # never let a tool bug crash the chat; details go to the log only
        logger.exception("assistant_tool_failed", extra={"tool": name})
        return ToolOutcome(_json({"error": "The tool failed unexpectedly. Try again or rephrase."}), is_error=True)
