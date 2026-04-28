"""Unit tests for app.orders.validation (Sprint 2.2 #105)."""

import pytest

from app.orders.validation import validate_delivery_address


@pytest.mark.parametrize(
    "addr, expected",
    [
        # Acceptable: non-empty + has at least one digit
        ("14 Main", True),
        ("Apartment 3", True),
        ("123", True),
        ("14 Spadina Ave", True),
        ("  14 Spadina  ", True),  # surrounding whitespace tolerated
        # Rejected: empty, whitespace-only, missing digit, garbage
        ("", False),
        ("   ", False),
        (None, False),
        (".", False),
        ("uhh", False),
        ("Main Street", False),  # no digit
        ("yes that's right", False),  # no digit
    ],
)
def test_validate_delivery_address(addr, expected):
    assert validate_delivery_address(addr) is expected
