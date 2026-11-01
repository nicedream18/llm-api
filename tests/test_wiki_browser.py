"""Optional real-browser Wiki smoke test.

The test is intentionally skipped unless a running deployment URL and a local
Playwright browser are supplied. CI can opt in with ``WALIAPI_BROWSER_URL`` and
the normal Playwright browser installation step.
"""

import os

import pytest


@pytest.mark.browser
def test_wiki_mobile_browser_smoke():
    base_url = os.environ.get("WALIAPI_BROWSER_URL")
    if not base_url:
        pytest.skip("WALIAPI_BROWSER_URL is required for browser acceptance")
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(base_url.rstrip("/") + "/admin/", wait_until="networkidle")
        page.get_by_text("Wiki", exact=True).click()
        assert page.get_by_text("Wiki 项目").is_visible()
        browser.close()
