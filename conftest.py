import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--phrase",
        default="Your order is one large pepperoni pizza for pickup. Does that sound right?",
        help="Phrase to synthesize in the TTS integration test.",
    )


@pytest.fixture
def tts_phrase(request):
    return request.config.getoption("--phrase")
