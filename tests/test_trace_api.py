"""Agent trace WebUI API tests."""

import pytest

from core.chat_profile import ChatProfileStore
from core.config_manager import ConfigManager
from core.trace_store import TraceStore


class FakeContext:
    def __init__(self):
        self.routes = []

    def register_web_api(self, route, handler, methods, desc):
        self.routes.append((route, handler, methods, desc))


@pytest.mark.asyncio
async def test_trace_list_and_detail_routes(tmp_path):
    from quart import Quart

    import web_api as web_api_module

    trace_store = TraceStore(str(tmp_path))
    trace_store.create("trace-1", "default:GroupMessage:1", "m1", "hello")
    trace_store.append("trace-1", "decision", "秘书决策", data={"should_reply": True})

    fake = FakeContext()
    web_api_module.register_all_routes(
        fake,
        ChatProfileStore(str(tmp_path)),
        ConfigManager({}),
        type("Ledger", (), {"get_all_chat_ids": staticmethod(lambda: [])})(),
        trace_store=trace_store,
    )

    app = Quart(__name__)
    for route, handler, methods, _ in fake.routes:
        app.add_url_rule("/api/plug" + route, endpoint=route, view_func=handler, methods=methods)

    client = app.test_client()
    response = await client.get(
        "/api/plug/astrbot_plugin_angel_heart/traces?chat_id=default:GroupMessage:1"
    )
    body = await response.get_json()
    assert body["status"] == "ok"
    assert body["data"][0]["trace_id"] == "trace-1"

    response = await client.get(
        "/api/plug/astrbot_plugin_angel_heart/traces/trace-1"
    )
    body = await response.get_json()
    assert body["data"]["stages"][1]["stage"] == "decision"

    response = await client.get(
        "/api/plug/astrbot_plugin_angel_heart/traces/not-found"
    )
    assert response.status_code == 404
