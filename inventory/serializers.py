from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from common.serializers import CodeField, StrictFieldsMixin

from .models import Product, ShippingBox


class ProductSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    sku = CodeField(
        max_length=64,
        validators=[UniqueValidator(Product.objects.all(), message="A product with this SKU already exists.")],
    )
    volume = serializers.DecimalField(max_digits=20, decimal_places=4, read_only=True, help_text="cm³")

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "sku",
            "length",
            "width",
            "height",
            "weight",
            "volume",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ShippingBoxSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    box_code = CodeField(
        max_length=32,
        validators=[UniqueValidator(ShippingBox.objects.all(), message="A box with this code already exists.")],
    )
    internal_volume = serializers.DecimalField(max_digits=20, decimal_places=4, read_only=True, help_text="cm³")

    class Meta:
        model = ShippingBox
        fields = [
            "id",
            "name",
            "box_code",
            "internal_length",
            "internal_width",
            "internal_height",
            "internal_volume",
            "max_weight",
            "cost",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
