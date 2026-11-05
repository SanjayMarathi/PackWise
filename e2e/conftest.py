"""Browser end-to-end tests: a real browser (Playwright) against a live Django server.

Run with:  pytest e2e                       (CI: Playwright's Chromium)
           pytest e2e --browser-channel chrome   (locally, using installed Chrome)
"""

import os

import pytest
from django.core.management import call_command

# Playwright's sync API runs an asyncio loop in the test thread. Django's ORM refuses
# to run in a thread with a running loop unless explicitly allowed. The ORM calls
# here are test setup in the same thread, not concurrent async code.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    # Software WebGL, so the 3D viewer renders in headless CI machines without a GPU.
    return {**browser_type_launch_args, "args": ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"]}


@pytest.fixture
def app(live_server, page):
    """The PackWise UI with the demo catalogue loaded, failing the test on any JS error."""
    call_command("seed_demo_data", verbosity=0)
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.set_default_timeout(15_000)
    page.goto(live_server.url + "/")
    page.wait_for_selector("[data-sku='LAPTOP-14']")
    yield page
    assert errors == [], f"JavaScript errors: {errors}"
