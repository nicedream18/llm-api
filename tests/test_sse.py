import json
from types import SimpleNamespace

import pytest

from app.application.services.misc_services import ProxyService


def test_sse_payload_is_json():
    payload = json.dumps({'choices': [{'delta': {'content': 'hi'}}]})
    assert json.loads(payload)['choices'][0]['delta']['content'] == 'hi'


class FakeGateway:
    async def stream(self, _request):
        for line in ["event: message", "data: {\"choices\":", "data: [{\"delta\":{\"content\":\"hi\"}}]}", "", "data: [DONE]", ""]:
            yield line


class FakeLog:
    def insert_log(self, _entry):
        pass


@pytest.mark.asyncio
async def test_streaming_sse_preserves_event_and_multiline_data():
    settings = SimpleNamespace(enabled=False, scan_response=False, fail_closed=True)
    service = ProxyService(FakeGateway(), None, settings, FakeLog())
    result = [item async for item in service.forward_stream_async('{"model":"demo"}', {})]
    assert "event: message\n" in result
    assert "data: {\"choices\":\n" in result
    assert "data: [{\"delta\":{\"content\":\"hi\"}}]}\n" in result
    assert result[-1] == "data: [DONE]\n\n"
