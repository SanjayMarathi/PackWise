"""User journeys through the web interface, end to end (browser -> API -> engine -> PostgreSQL)."""

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.django_db(transaction=True)


def add(page, sku, quantity=1):
    for _ in range(quantity):
        page.click(f"[data-sku='{sku}'] button[aria-label^='Add one']")


def find_box(page):
    page.click("[data-testid=find-box]")
    expect(page.get_by_test_id("recommended-box")).to_be_visible()


def test_pack_an_order_shows_box_3d_plan_and_instructions(app):
    add(app, "LAPTOP-14", 2)
    add(app, "MOUSE-WL", 1)
    expect(app.get_by_test_id("units")).to_have_text("3")
    find_box(app)

    expect(app.get_by_test_id("recommended-box")).to_contain_text("Medium Flat")
    expect(app.locator("[data-testid=instructions] tbody tr")).to_have_count(3)
    expect(app.get_by_test_id("option")).to_have_count(4)
    expect(app.get_by_test_id("rejected")).to_contain_text("Cannot fit (proven)")
    expect(app.get_by_test_id("rejected")).to_contain_text("BX-S")
    expect(app.locator("[data-testid=viewer] canvas")).to_be_visible()
    expect(app.get_by_test_id("stats")).to_contain_text("2.9 kg / 15 kg")

    # Loading sequence: clicking an instruction row shows the box up to that step.
    app.locator("[data-testid=instructions] tbody tr").first.click()
    expect(app.get_by_test_id("step-label")).to_contain_text("Step 1 of 3")

    # Alternatives can be inspected in 3D too.
    app.get_by_test_id("option").nth(1).click()
    expect(app.locator(".viewer-card .card-head h2")).to_contain_text("Alternative #2")
    expect(app.get_by_test_id("stats")).to_contain_text("Medium")


def test_order_builder_stays_reachable_while_the_page_scrolls(app):
    """Regression: the sticky builder was taller than the window, so its totals and button
    stayed off-screen until the page reached its very end."""
    app.set_viewport_size({"width": 1440, "height": 780})
    add(app, "LAPTOP-14", 2)
    add(app, "BOOK-HC", 2)
    find_box(app)
    scroll_room = app.evaluate("document.documentElement.scrollHeight - innerHeight")
    assert scroll_room > 600  # the results are much taller than the window
    for fraction in (0.35, 0.7):
        target = int(fraction * scroll_room)
        app.evaluate(f"window.scrollTo(0, {target})")
        app.wait_for_function(f"Math.abs(scrollY - {target}) < 2")
        button = app.get_by_test_id("find-box").bounding_box()
        assert button["y"] >= 0, (fraction, button)
        assert button["y"] + button["height"] <= 780, (fraction, button)
    # The product list scrolls inside the card instead.
    assert app.get_by_test_id("product-list").evaluate("e => e.scrollHeight > e.clientHeight")


def test_order_that_no_box_can_hold(app):
    add(app, "MONITOR-27", 6)  # 45 kg of 70 cm monitors
    find_box(app)
    expect(app.get_by_test_id("recommended-box")).to_have_text("No active box can hold this order")
    expect(app.locator("[data-testid=rejected] .reject")).to_have_count(6)
    expect(app.get_by_test_id("rejected")).to_contain_text("exceeds the box limit")


def test_rerun_with_another_strategy_from_the_order_page(app):
    add(app, "HEADPH-OE", 1)
    find_box(app)
    app.get_by_role("link", name=re.compile(r"^ORD-")).click()
    expect(app.locator("h1")).to_have_text(re.compile(r"^ORD-"))
    expect(app.get_by_test_id("result")).to_be_visible()
    app.locator(".hero select").select_option("best_utilization")
    app.get_by_role("button", name="Re-run").click()
    expect(app.locator(".toast", has_text="Recomputed")).to_be_visible()  # earlier toasts may still be showing
    expect(app.get_by_test_id("rejected")).to_be_visible()  # a fresh run also explains rejections

    app.click("a[data-route=orders]")
    expect(app.locator("[data-testid=orders-table] tbody tr")).to_have_count(1)
    expect(app.get_by_test_id("orders-table")).to_contain_text("Box recommended")


def test_product_create_validate_edit_delete(app):
    app.click("a[data-route=products]")
    expect(app.get_by_test_id("products-table")).to_be_visible()

    app.click("[data-testid=add-product]")
    app.fill("#f-products-name", "Bluetooth Speaker")
    app.fill("#f-products-sku", "bad sku!")
    app.fill("#f-products-weight", "0.65")
    app.fill("#f-products-length", "0")
    app.fill("#f-products-width", "8")
    app.fill("#f-products-height", "8")
    app.click("[data-testid=catalog-form] button[type=submit]")
    # Server-side validation errors are shown next to the right fields.
    expect(app.locator("[data-field=sku] .error")).to_contain_text("Use only letters")
    expect(app.locator("[data-field=length] .error")).to_contain_text("greater than or equal to 0.01")

    app.fill("#f-products-sku", "spk-bt-01")
    app.fill("#f-products-length", "18")
    app.click("[data-testid=catalog-form] button[type=submit]")
    row = app.locator("tr[data-code='SPK-BT-01']")
    expect(row).to_contain_text("Bluetooth Speaker")
    expect(row).to_contain_text("18 × 8 × 8 cm")

    row.get_by_role("button", name="Edit Bluetooth Speaker").click()
    app.fill("#f-products-name", "Bluetooth Speaker Mini")
    app.click("[data-testid=catalog-form] button[type=submit]")
    expect(row).to_contain_text("Bluetooth Speaker Mini")

    app.once("dialog", lambda dialog: dialog.accept())
    row.get_by_role("button", name="Delete Bluetooth Speaker Mini").click()
    expect(row).to_have_count(0)


def test_product_used_in_an_order_cannot_be_deleted(app):
    add(app, "MUG-CER", 1)
    find_box(app)
    app.click("a[data-route=products]")
    app.once("dialog", lambda dialog: dialog.accept())
    app.locator("tr[data-code='MUG-CER']").get_by_role("button", name=re.compile("^Delete")).click()
    expect(app.locator(".toast.error", has_text="Cannot delete: still in use")).to_be_visible()
    expect(app.locator("tr[data-code='MUG-CER']")).to_have_count(1)


def test_deactivated_box_is_no_longer_recommended(app):
    app.click("a[data-route=boxes]")
    flat = app.locator("tr[data-code='BX-M-FLAT']")
    flat.get_by_role("checkbox").uncheck()
    expect(flat).to_have_class(re.compile("inactive"))

    app.click("a[data-route=pack]")
    add(app, "LAPTOP-14", 1)
    find_box(app)
    # The equally priced flat box is out of stock, so the regular Medium box wins.
    expect(app.get_by_test_id("recommended-box")).to_contain_text("Medium BX-M")
    expect(app.get_by_test_id("options")).not_to_contain_text("BX-M-FLAT")
