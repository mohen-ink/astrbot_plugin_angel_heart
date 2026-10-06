"""Agent trace store tests."""

import json

from core.trace_store import MAX_TRACES, STORE_FILE_NAME, TraceStore


def test_trace_stages_persist_and_reload(tmp_path):
    store = TraceStore(str(tmp_path))
    assert store.create("trace-1", "group-1", "msg-1", "hello")
    assert store.append("trace-1", "decision", "秘书决策", data={"should_reply": True})
    assert store.append("trace-1", "sent", "回复已发送", status="completed", terminal=True)

    reloaded = TraceStore(str(tmp_path))
    trace = reloaded.get("trace-1")
    assert trace["status"] == "completed"
    assert [item["stage"] for item in trace["stages"]] == [
        "event_received",
        "decision",
        "sent",
    ]
    assert reloaded.list(chat_id="group-1")[0]["trace_id"] == "trace-1"


def test_trace_payload_redacts_media_and_bounds_text(tmp_path):
    store = TraceStore(str(tmp_path))
    store.create("trace-1", "group-1")
    store.append(
        "trace-1",
        "request",
        "最终请求",
        data={
            "contexts": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJDRA=="}},
                {"local_file_path": "C:\\secret\\image.png"},
            ],
            "prompt": "image data:image/png;base64,QUJDRA==",
        },
    )
    body = json.dumps(store.get("trace-1"), ensure_ascii=False)
    assert "QUJDRA==" not in body
    assert "C:\\secret\\image.png" not in body
    assert "[图片内容已脱敏]" in body
    assert "[本地路径已脱敏]" in body


def test_trace_disabled_does_not_persist(tmp_path):
    store = TraceStore(str(tmp_path), enabled=lambda: False)
    assert not store.create("trace-1", "group-1")
    assert not store.append("trace-1", "decision", "decision")
    assert store.get("trace-1") is None
    assert not (tmp_path / STORE_FILE_NAME).exists()


def test_trace_store_retains_only_latest_maximum(tmp_path):
    store = TraceStore(str(tmp_path))
    for index in range(MAX_TRACES + 1):
        trace_id = f"trace-{index}"
        store.create(trace_id, "group-1")
    assert len(store.list(limit=MAX_TRACES)) == MAX_TRACES
    assert store.get("trace-0") is None
    assert store.get(f"trace-{MAX_TRACES}") is not None
