"""Load a small demo catalogue (idempotent: safe to run on every deploy).

Box sizes and prices live here, as data, never in the packing algorithm.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import Product, ShippingBox

BOXES = [
    # code, name, L, W, H (cm), max kg, cost INR
    ("BX-XS", "Extra Small Mailer", "15", "10", "5", "1", "12"),
    ("BX-S", "Small", "25", "20", "10", "5", "20"),
    ("BX-M", "Medium", "40", "30", "20", "15", "35"),
    ("BX-M-FLAT", "Medium Flat", "50", "40", "10", "15", "35"),
    ("BX-L", "Large", "60", "40", "40", "25", "55"),
    ("BX-XL", "Extra Large", "80", "60", "50", "35", "90"),
]

PRODUCTS = [
    # sku, name, L, W, H (cm), kg
    ("LAPTOP-14", "14-inch Laptop", "33", "23", "2", "1.4"),
    ("MOUSE-WL", "Wireless Mouse", "12", "7", "4", "0.1"),
    ("HEADPH-OE", "Over-ear Headphones", "22", "18", "9", "0.35"),
    ("BOOK-HC", "Hardcover Book", "24", "16", "4", "0.8"),
    ("MUG-CER", "Ceramic Mug (boxed)", "12", "10", "10", "0.45"),
    ("MONITOR-27", "27-inch Monitor (boxed)", "70", "45", "15", "7.5"),
    ("KETTLE-EL", "Electric Kettle (boxed)", "25", "20", "22", "1.3"),
    ("CABLE-USB", "USB-C Cable", "15", "10", "2", "0.05"),
]


class Command(BaseCommand):
    help = "Create or update the demo shipping boxes and products."

    @transaction.atomic
    def handle(self, *args, **options):
        for code, name, length, width, height, max_weight, cost in BOXES:
            ShippingBox.objects.update_or_create(
                box_code=code,
                defaults={
                    "name": name,
                    "internal_length": Decimal(length),
                    "internal_width": Decimal(width),
                    "internal_height": Decimal(height),
                    "max_weight": Decimal(max_weight),
                    "cost": Decimal(cost),
                    "is_active": True,
                },
            )
        for sku, name, length, width, height, weight in PRODUCTS:
            Product.objects.update_or_create(
                sku=sku,
                defaults={
                    "name": name,
                    "length": Decimal(length),
                    "width": Decimal(width),
                    "height": Decimal(height),
                    "weight": Decimal(weight),
                    "is_active": True,
                },
            )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(BOXES)} boxes and {len(PRODUCTS)} products."))
