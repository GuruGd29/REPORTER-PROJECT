"""A trivial pytest test to demonstrate the dashboard.

Run with: pytest --qa-dashboard-mitm-skip
"""


def test_addition_works():
    assert 1 + 1 == 2


def test_string_methods():
    assert "qa-dashboard".upper() == "QA-DASHBOARD"


def test_with_steps(step):
    """`step` is the auto-injected fixture for named step breakdowns."""
    with step("Prepare inputs"):
        items = list(range(10))

    with step("Compute sum") as s:
        s.substep("Even items", lambda: sum(x for x in items if x % 2 == 0))
        s.substep("Odd items", lambda: sum(x for x in items if x % 2 == 1))

    with step("Assert"):
        assert sum(items) == 45
