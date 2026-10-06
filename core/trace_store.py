"""有界持久化的 Agent 运行链路记录。"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional

STORE_FILE_NAME = "agent_traces.json"
MAX_TRACES = 100
MAX_TEXT_CHARS = 60000

_DATA_URL_RE = re.compile(r"data:[^;\s]+;base64,[A-Za-z0-9+/=\r\n]+", re.IGNORECASE)
_BASE64_URL_RE = re.compile(r"base64://[A-Za-z0-9+/=\r\n]+", re.IGNORECASE)
_FILE_URL_RE = re.compile(r"file://[^\s\"']+", re.IGNORECASE)
_WINDOWS_PATH_RE = re.compile(r"(?<![\w])(?:[A-Za-z]:\\|\\\\)[^\s\"']+")


class TraceStore:
    """线程安全、原子落盘的最近 Agent trace 存储。"""

    def __init__(self, data_dir: str, enabled: Optional[Callable[[], bool]] = None):
        self._file_path = os.path.join(data_dir, STORE_FILE_NAME)
        self._enabled = enabled or (lambda: True)
        self._lock = threading.RLock()
        self._traces: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._loaded = False

    def _is_enabled(self) -> bool:
        try:
            return bool(self._enabled())
        except Exception:
            return False

    @staticmethod
    def new_trace_id() -> str:
        return uuid.uuid4().hex

    def create(
        self,
        trace_id: str,
        chat_id: str,
        message_id: str = "",
        summary: str = "",
    ) -> bool:
        if not self._is_enabled() or not trace_id:
            return False
        now = time.time()
        with self._lock:
            self._ensure_loaded()
            self._traces[trace_id] = {
                "trace_id": str(trace_id),
                "chat_id": str(chat_id or ""),
                "message_id": str(message_id or ""),
                "summary": str(self._sanitize(str(summary or "")))[:500],
                "created_at": now,
                "updated_at": now,
                "status": "running",
                "stages": [],
            }
            self._append_locked(
                trace_id,
                "event_received",
                "收到消息事件",
                data={"message_id": message_id, "summary": summary},
            )
            self._trim_locked()
            self._save_locked()
        return True

    def append(
        self,
        trace_id: str,
        stage: str,
        title: str,
        *,
        status: str = "info",
        data: Any = None,
        terminal: bool = False,
    ) -> bool:
        if not self._is_enabled() or not trace_id:
            return False
        with self._lock:
            self._ensure_loaded()
            if trace_id not in self._traces:
                return False
            self._append_locked(trace_id, stage, title, status=status, data=data)
            trace = self._traces[trace_id]
            if terminal:
                trace["status"] = status
            self._trim_locked()
            self._save_locked()
        return True

    def _append_locked(
        self,
        trace_id: str,
        stage: str,
        title: str,
        *,
        status: str = "info",
        data: Any = None,
    ) -> None:
        trace = self._traces.get(trace_id)
        if trace is None:
            return
        stage_data = self._sanitize(data)
        stage_data = self._bound_payload(stage_data)
        now = time.time()
        trace["stages"].append(
            {
                "at": now,
                "stage": str(stage or "unknown")[:100],
                "title": str(title or stage or "运行阶段")[:200],
                "status": str(status or "info")[:40],
                "data": stage_data,
            }
        )
        trace["updated_at"] = now
        if stage in {"sent", "not_sent", "blocked", "error", "completed"}:
            trace["status"] = status

    def get(self, trace_id: str) -> Optional[Dict[str, Any]]:
        if not self._is_enabled():
            return None
        with self._lock:
            self._ensure_loaded()
            item = self._traces.get(str(trace_id or ""))
            return self._copy(item) if item else None

    def list(self, chat_id: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        if not self._is_enabled():
            return []
        try:
            limit = max(1, min(100, int(limit)))
        except (TypeError, ValueError):
            limit = 50
        with self._lock:
            self._ensure_loaded()
            entries = sorted(
                self._traces.values(),
                key=lambda item: item.get("updated_at", 0),
                reverse=True,
            )
            if chat_id:
                entries = [item for item in entries if item.get("chat_id") == chat_id]
            return [
                {
                    "trace_id": item["trace_id"],
                    "chat_id": item["chat_id"],
                    "message_id": item["message_id"],
                    "summary": item["summary"],
                    "created_at": item["created_at"],
                    "updated_at": item["updated_at"],
                    "status": item["status"],
                    "stage_count": len(item["stages"]),
                    "last_stage": item["stages"][-1]["stage"] if item["stages"] else "",
                }
                for item in entries[:limit]
            ]

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            with open(self._file_path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, json.JSONDecodeError, TypeError):
            return
        records = data.get("traces", []) if isinstance(data, dict) else []
        if not isinstance(records, list):
            return
        for item in records[-MAX_TRACES:]:
            if not isinstance(item, dict) or not item.get("trace_id"):
                continue
            self._traces[str(item["trace_id"])] = item

    def _trim_locked(self) -> None:
        while len(self._traces) > MAX_TRACES:
            self._traces.popitem(last=False)

    def _save_locked(self) -> None:
        os.makedirs(os.path.dirname(self._file_path), exist_ok=True)
        tmp_path = self._file_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as stream:
            json.dump(
                {"version": 1, "traces": list(self._traces.values())},
                stream,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        os.replace(tmp_path, self._file_path)

    def _sanitize(self, value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            if value.get("type") == "image_url":
                return {"type": "image_url", "image_url": {"url": "[图片内容已脱敏]"}}
            cleaned = {}
            for child_key, child in value.items():
                name = str(child_key)
                if name.lower() in {"local_file_path", "cache_path", "file_path", "filepath"}:
                    cleaned[name] = "[本地路径已脱敏]"
                elif name.lower() in {"image", "image_data", "binary", "base64"}:
                    cleaned[name] = "[媒体内容已脱敏]"
                else:
                    cleaned[name] = self._sanitize(child, name)
            return cleaned
        if isinstance(value, (list, tuple)):
            return [self._sanitize(item, key) for item in value]
        if isinstance(value, bytes):
            return "[二进制内容已脱敏]"
        if isinstance(value, str):
            text = _DATA_URL_RE.sub("[图片内容已脱敏]", value)
            text = _BASE64_URL_RE.sub("[媒体内容已脱敏]", text)
            text = _FILE_URL_RE.sub("[本地路径已脱敏]", text)
            text = _WINDOWS_PATH_RE.sub("[本地路径已脱敏]", text)
            if key.lower() in {"url", "image_url", "original_url", "source_url"}:
                if text.startswith(("/", "\\", "[本地路径")):
                    text = "[媒体链接已脱敏]"
            if len(text) > MAX_TEXT_CHARS:
                return text[:MAX_TEXT_CHARS] + "…[内容截断]"
            return text
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:MAX_TEXT_CHARS]

    def _bound_payload(self, data: Any) -> Any:
        try:
            encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return {"value": str(data)[:MAX_TEXT_CHARS]}
        if len(encoded) <= MAX_TEXT_CHARS * 2:
            return data
        return {"truncated": True, "preview": encoded[:MAX_TEXT_CHARS] + "…[阶段数据截断]"}

    @staticmethod
    def _copy(value: Dict[str, Any]) -> Dict[str, Any]:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
