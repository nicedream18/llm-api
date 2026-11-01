import pytest

from app.domain.gateway import GatewayService


@pytest.mark.parametrize('status', [400, 401, 403, 404, 422])
def test_non_retryable_status(status):
    assert not GatewayService._retryable_status(status)

@pytest.mark.parametrize('status', [408, 425, 429, 500, 502, 503, 504])
def test_retryable_status(status):
    assert GatewayService._retryable_status(status)
