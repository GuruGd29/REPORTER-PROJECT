"""Workspace-level conftest.

Disable the plugin in *this* repo's own self-tests so test runs don't
pollute the workspace with capture directories. Downstream projects
that install the package don't see this file.
"""
import sys


def pytest_configure(config):
    # Only disable if the user didn't pass an explicit flag
    has_dash_flag = any(arg.startswith("--qa-dashboard-") for arg in sys.argv[1:])
    if not has_dash_flag:
        config.option.qa_dashboard_disable = True
