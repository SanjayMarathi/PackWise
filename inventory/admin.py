from django.contrib import admin

from .models import Product, ShippingBox


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "length", "width", "height", "weight", "is_active")
    list_filter = ("is_active",)
    search_fields = ("sku", "name")


@admin.register(ShippingBox)
class ShippingBoxAdmin(admin.ModelAdmin):
    list_display = (
        "box_code",
        "name",
        "internal_length",
        "internal_width",
        "internal_height",
        "max_weight",
        "cost",
        "is_active",
    )
    list_filter = ("is_active",)
    search_fields = ("box_code", "name")
