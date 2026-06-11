"""Shared Selenium driver fixture with BiDi/CDP network capture."""
from __future__ import annotations

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from qa_dashboard.integrations.selenium import bidi_network_capture


@pytest.fixture
def driver():
    opts = Options()
    opts.add_argument("--headless=new")
    d = webdriver.Chrome(options=opts)
    # Subscribes to Network events for the lifetime of the driver and
    # writes flows into the active qa-dashboard run.
    with bidi_network_capture(d):
        yield d
    d.quit()
