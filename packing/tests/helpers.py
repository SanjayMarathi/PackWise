"""Small builders that keep the algorithm tests readable."""

from __future__ import annotations

from packing.algorithms import Container, Item, ItemLine, expand_quantities


def box(length: int, width: int, height: int, max_weight: int = 1_000_000, box_id="box") -> Container:
    return Container(box_id, length, width, height, max_weight)


def item(item_id: str, length: int, width: int, height: int, weight: int = 1, product_id=None) -> Item:
    return Item(
        item_id=item_id,
        product_id=product_id if product_id is not None else item_id.split("#")[0],
        length=length,
        width=width,
        height=height,
        weight=weight,
    )


def items(*specs: tuple[int, int, int], weight: int = 1) -> list[Item]:
    """``items((2, 2, 2), (3, 1, 1))`` -> items with ids p0#1, p1#1."""
    return [item(f"p{n}#1", *dims, weight=weight) for n, dims in enumerate(specs)]


def lines_to_items(*lines: ItemLine) -> list[Item]:
    return expand_quantities(lines)
