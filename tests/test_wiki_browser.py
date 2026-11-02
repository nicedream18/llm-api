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
    username = os.environ.get("WALIAPI_BROWSER_USER")
    password = os.environ.get("WALIAPI_BROWSER_PASSWORD")
    if not base_url or not username or not password:
        pytest.skip("WALIAPI_BROWSER_URL, WALIAPI_BROWSER_USER and WALIAPI_BROWSER_PASSWORD are required")
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(base_url.rstrip("/") + "/admin/", wait_until="networkidle")
        page.get_by_label("用户名").fill(username)
        page.get_by_label("密码").fill(password)
        page.get_by_role("button", name="登录控制台", exact=True).click()
        page.get_by_role("link", name="Wiki", exact=True).click()
        page.get_by_role("heading", name="Wiki", exact=True).wait_for()
        page.get_by_role("link", name="渠道", exact=True).click()
        page.get_by_role("heading", name="上游渠道", exact=True).wait_for()
        page.get_by_role("link", name="Wiki", exact=True).click()
        page.get_by_role("heading", name="Wiki", exact=True).wait_for()
        browser.close()


@pytest.mark.browser
def test_wiki_authenticated_navigation_and_theme():
    base_url = os.environ.get("WALIAPI_BROWSER_URL")
    username = os.environ.get("WALIAPI_BROWSER_USER")
    password = os.environ.get("WALIAPI_BROWSER_PASSWORD")
    if not base_url or not username or not password:
        pytest.skip("WALIAPI_BROWSER_URL, WALIAPI_BROWSER_USER and WALIAPI_BROWSER_PASSWORD are required")
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(base_url.rstrip("/") + "/admin/", wait_until="networkidle")
        page.get_by_label("用户名").fill(username)
        page.get_by_label("密码").fill(password)
        page.get_by_role("button", name="登录控制台", exact=True).click()
        page.get_by_role("link", name="Wiki", exact=True).click()
        page.get_by_role("heading", name="Wiki", exact=True).wait_for()
        page.get_by_role("button", name="切换到深色模式", exact=True).click()
        assert page.locator("html").get_attribute("data-theme") == "dark"
        page.get_by_role("button", name="切换到浅色模式", exact=True).click()
        assert page.locator("html").get_attribute("data-theme") == "light"
        assert page.get_by_role("button", name="退出登录", exact=True).is_visible()
        browser.close()
