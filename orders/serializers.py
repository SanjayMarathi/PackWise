from decimal import Decimal

from django.conf import settings
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from common.serializers import CodeField, StrictFieldsMixin
from inventory.models import Product

from . import services
from .models import Order, OrderItem


class OrderItemInputSerializer(StrictFieldsMixin, serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)


class OrderCreateSerializer(StrictFieldsMixin, serializers.Serializer):
    order_number = CodeField(
        max_length=40,
        required=False,
        validators=[UniqueValidator(Order.objects.all(), message="An order with this number already exists.")],
        help_text="Optional. Generated (ORD-YYYYMMDD-XXXXXXXX) when omitted.",
    )
    items = OrderItemInputSerializer(many=True, allow_empty=False)

    def validate_items(self, items):
        limits = settings.PACKWISE
        if len(items) > limits["MAX_LINES_PER_ORDER"]:
            raise serializers.ValidationError(f"An order may have at most {limits['MAX_LINES_PER_ORDER']} lines.")

        ids = [line["product_id"] for line in items]
        duplicates = sorted({pid for pid in ids if ids.count(pid) > 1})
        if duplicates:
            raise serializers.ValidationError(
                f"Duplicate product_id(s) {duplicates}: combine them into one line with the total quantity."
            )

        units = sum(line["quantity"] for line in items)
        if units > limits["MAX_ITEMS_PER_ORDER"]:
            raise serializers.ValidationError(
                f"An order may contain at most {limits['MAX_ITEMS_PER_ORDER']} units in total (got {units})."
            )

        products = Product.objects.in_bulk(ids)
        missing = sorted(pid for pid in ids if pid not in products)
        if missing:
            raise serializers.ValidationError(f"Unknown product_id(s): {missing}.")
        inactive = sorted(pid for pid in ids if not products[pid].is_active)
        if inactive:
            raise serializers.ValidationError(f"Inactive product_id(s) cannot be ordered: {inactive}.")

        for line in items:
            line["product"] = products[line["product_id"]]
        return items

    def create(self, validated_data):
        return services.create_order(
            lines=[(line["product"], line["quantity"]) for line in validated_data["items"]],
            order_number=validated_data.get("order_number"),
        )


class OrderItemSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(source="product.id", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)
    name = serializers.CharField(source="product.name", read_only=True)
    unit_weight = serializers.DecimalField(
        source="product.weight", max_digits=8, decimal_places=3, read_only=True, help_text="kg"
    )
    dimensions = serializers.SerializerMethodField(help_text="Product dimensions in cm.")

    class Meta:
        model = OrderItem
        fields = ["id", "product_id", "sku", "name", "quantity", "unit_weight", "dimensions"]

    def get_dimensions(self, obj) -> dict[str, float]:
        p = obj.product
        return {"length": float(p.length), "width": float(p.width), "height": float(p.height)}


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    total_units = serializers.SerializerMethodField()
    total_weight = serializers.SerializerMethodField(help_text="kg")

    class Meta:
        model = Order
        fields = ["id", "order_number", "status", "total_units", "total_weight", "items", "created_at", "updated_at"]

    def get_total_units(self, obj) -> int:
        return sum(item.quantity for item in obj.items.all())

    def get_total_weight(self, obj) -> float:
        return float(sum((item.line_weight for item in obj.items.all()), Decimal("0")))
