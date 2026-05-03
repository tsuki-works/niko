"""Global test fixtures for the niko test suite.

Sets testing_mode=True on the shared settings singleton so that
security dependencies (e.g. Twilio signature validation) bypass
real-credential checks. Tests that need validation enabled override
this via their own monkeypatch fixtures.
"""

import pytest
from app.config import settings


@pytest.fixture(autouse=True)
def _enable_testing_mode():
    original = settings.testing_mode
    settings.testing_mode = True
    yield
    settings.testing_mode = original
