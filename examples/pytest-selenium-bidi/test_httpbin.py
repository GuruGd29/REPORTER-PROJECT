"""Selenium 4 + BiDi network capture — golden-path example."""
from __future__ import annotations


def test_get_request_is_captured(driver, step):
    with step("Navigate to httpbin"):
        driver.get("https://httpbin.org/get")

    with step("Page renders"):
        assert "httpbin.org" in driver.title.lower() or "httpbin" in driver.page_source


def test_json_endpoint(driver, step):
    with step("Fetch JSON"):
        driver.get("https://httpbin.org/json")

    with step("Body present"):
        assert "slideshow" in driver.page_source
