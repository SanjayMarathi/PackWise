"""The AI assistant panel in a real browser.

The live server uses the real Anthropic SDK with a scripted transport
(assistant/tests/fakes.py): no API key or network, but real streaming,
tool execution, database writes and UI rendering.
"""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from assistant import agent
from assistant.tests.fakes import ScriptedAnthropic, message, text, tool
from orders.models import Order

pytestmark = pytest.mark.django_db(transaction=True)


def screenshot(page, name):
    target = os.environ.get("SCREENSHOT_DIR")
    if target:
        Path(target).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(target) / f"{name}.png"))


AI_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


@pytest.fixture(autouse=True)
def no_ai_keys(monkeypatch):
    for key in AI_KEYS:  # each test picks its provider explicitly; real keys never leak in
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def scripted_assistant(monkeypatch):
    def install(*responses):
        fake = ScriptedAnthropic(*responses)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(agent, "get_client", lambda: fake.client)
        return fake

    return install


def test_assistant_is_offline_without_an_api_key(app):
    app.get_by_test_id("assistant-open").click()
    expect(app.get_by_test_id("chat-offline")).to_contain_text("switched off")
    app.keyboard.press("Escape")
    expect(app.get_by_test_id("assistant-panel")).to_be_hidden()


def test_assistant_packs_an_order_and_links_to_the_3d_plan(app, scripted_assistant):
    fake = scripted_assistant(
        message(tool("list_products", {"search": "laptop"}), stop_reason="tool_use"),
        message(
            tool("recommend_box", {"items": [{"sku": "LAPTOP-14", "quantity": 2}, {"sku": "MOUSE-WL", "quantity": 1}]}),
            stop_reason="tool_use",
        ),
        message(text("Use the **Medium Flat** box (₹35). It fits:\n- 2 × LAPTOP-14\n- 1 × MOUSE-WL")),
    )
    app.get_by_test_id("assistant-open").click()
    app.get_by_role("button", name="Pack 2 laptops and a wireless mouse").click()

    card = app.get_by_test_id("chat-card")
    expect(card).to_contain_text("Recommended box")
    expect(card).to_contain_text("Medium Flat · ₹35")
    answer = app.get_by_test_id("chat-answer").last
    expect(answer.locator("strong")).to_have_text("Medium Flat")  # **bold** rendered safely
    expect(answer.locator("li")).to_have_count(2)
    assert len(fake.requests) == 3
    order = Order.objects.get()
    assert order.status == Order.Status.RECOMMENDED
    screenshot(app, "assistant-chat")

    # The conversation survives a reload (restored from the server-side transcript).
    app.reload()
    app.get_by_test_id("assistant-open").click()
    expect(app.get_by_test_id("chat-card")).to_contain_text("Medium Flat")
    expect(app.locator(".msg.user")).to_have_text("Pack 2 laptops and a wireless mouse")

    app.get_by_role("button", name="Open 3D plan").click()
    expect(app.locator("h1")).to_have_text(order.order_number)
    expect(app.get_by_test_id("recommended-box")).to_contain_text("Medium Flat")


def test_console_resizes_and_maximizes(app, scripted_assistant):
    scripted_assistant()
    settled = "document.getAnimations().length === 0"  # the open animation scales the panel briefly
    app.get_by_test_id("assistant-open").click()
    app.wait_for_function(settled)
    panel = app.get_by_test_id("assistant-panel")

    def drag_corner(dx, dy):
        corner = app.locator(".resize-handle.corner").bounding_box()
        app.mouse.move(corner["x"] + 5, corner["y"] + 5)
        app.mouse.down()
        app.mouse.move(corner["x"] + 5 + dx, corner["y"] + 5 + dy, steps=6)
        app.mouse.up()
        return panel.bounding_box()

    before = panel.bounding_box()
    smaller = drag_corner(60, 120)  # the corner is top-left: right/down shrinks the console
    assert smaller["width"] < before["width"] - 50
    assert smaller["height"] < before["height"] - 100
    after = drag_corner(-180, -40)  # left/up grows it again (height is capped by the viewport)
    assert after["width"] > smaller["width"] + 170
    assert after["height"] > smaller["height"]

    app.get_by_role("button", name="Maximize console").click()
    assert panel.bounding_box()["width"] > after["width"]
    app.get_by_role("button", name="Restore console size").click()
    assert abs(panel.bounding_box()["width"] - after["width"]) < 2

    app.reload()  # the chosen size is remembered
    app.get_by_test_id("assistant-open").click()
    app.wait_for_function(settled)
    assert abs(app.get_by_test_id("assistant-panel").bounding_box()["width"] - after["width"]) < 2


def test_theme_toggle_switches_and_persists(app):
    background = "getComputedStyle(document.body).backgroundColor"
    initial = app.evaluate(background)
    app.click("#theme-toggle")
    # The background fades for 0.2 s; wait for the final colour: pure black or pure white.
    target = "rgb(10, 10, 10)" if initial == "rgb(255, 255, 255)" else "rgb(255, 255, 255)"
    app.wait_for_function(f"{background} === {target!r}")
    app.reload()
    assert app.evaluate(background) == target


def test_assistant_shows_errors_and_can_start_over(app, scripted_assistant):
    scripted_assistant(429, message(text("Hello again!")))
    app.get_by_test_id("assistant-open").click()
    textarea = app.get_by_role("textbox", name="Message the assistant")
    textarea.fill("Hi")
    textarea.press("Enter")
    expect(app.locator(".msg.bot.error")).to_contain_text("busy")

    app.get_by_role("button", name=re.compile("New")).click()
    expect(app.locator(".chat-suggestions")).to_be_visible()
    textarea.fill("Hi")
    app.get_by_test_id("chat-send").click()
    expect(app.get_by_test_id("chat-answer").last).to_have_text("Hello again!")
