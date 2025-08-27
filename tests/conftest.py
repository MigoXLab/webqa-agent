import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        '--url',
        action='store',
        default=None,
        help='Target URL for crawling tests (overrides default)',
    )


@pytest.fixture
def test_url(request: pytest.FixtureRequest) -> str:
    # Priority: CLI --url > env WEBQA_TEST_URL > default example.com
    return request.config.getoption('--url') or 'https://google.com'
