"""Conversion between API units (cm, kg) and exact integer engine units.

The database stores dimensions with 2 decimal places (0.01 cm) and weights
with 3 (0.001 kg). Scaling by 100 and 1000 maps every stored value to an
integer *without rounding*, so the engine's geometry is exact.
"""

from __future__ import annotations

from decimal import Decimal

LENGTH_SCALE = 100  # 1 engine length unit = 0.01 cm = 0.1 mm
WEIGHT_SCALE = 1000  # 1 engine weight unit = 0.001 kg = 1 g
VOLUME_SCALE = LENGTH_SCALE**3


def _to_units(value: Decimal | int | str, scale: int, what: str) -> int:
    scaled = Decimal(value) * scale
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{what} {value} has more precision than the engine supports.")
    return int(scaled)


def cm_to_units(value: Decimal | int | str) -> int:
    return _to_units(value, LENGTH_SCALE, "Length")


def kg_to_units(value: Decimal | int | str) -> int:
    return _to_units(value, WEIGHT_SCALE, "Weight")


def units_to_cm(units: int) -> float:
    return round(units / LENGTH_SCALE, 2)


def units_to_kg(units: int) -> float:
    return round(units / WEIGHT_SCALE, 3)


def volume_units_to_cm3(units: int) -> float:
    return round(units / VOLUME_SCALE, 2)
