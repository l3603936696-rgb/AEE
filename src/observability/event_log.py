"""JSONL 事件写入器 — 按事件类型路由到不同日志文件。"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Union

from .events import DriftEvent, RuleLifecycleEvent, ShatteringEvent, TensionSnapshot

logger = logging.getLogger(__name__)

_LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

_FILE_MAP = {
    "drift":             "drift_trace.jsonl",
    "rule_lifecycle":    "rule_lifecycle.jsonl",
    "shattering":        "shattering_events.jsonl",
    "tension_snapshot":  "tension_snapshots.jsonl",
}

_write_lock = threading.Lock()


def emit_event(event: Union[DriftEvent, RuleLifecycleEvent, ShatteringEvent, TensionSnapshot]) -> None:
    """
    将事件写入对应的 JSONL 日志文件。

    线程安全，失败静默（只打 warning）。
    """
    try:
        event_dict = event.to_dict()
        event_type = event_dict.get("event_type", "unknown")
        filename = _FILE_MAP.get(event_type)
        if not filename:
            logger.warning(f"[observability] Unknown event type: {event_type}")
            return

        line = json.dumps(event_dict, ensure_ascii=False, default=str) + "\n"
        filepath = _LOGS_DIR / filename

        with _write_lock:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(line)

    except Exception as e:
        logger.warning(f"[observability] Failed to emit event: {e}")


def read_events(event_type: str, limit: int = 200) -> list:
    """
    读取最近 N 条指定类型的事件（用于前端展示/调试）。

    参数：
        event_type: "drift" | "rule_lifecycle" | "shattering" | "tension_snapshot"
        limit: 最多返回多少条

    返回：
        list[dict] — 最近的事件，按时间倒序
    """
    filename = _FILE_MAP.get(event_type)
    if not filename:
        return []

    filepath = _LOGS_DIR / filename
    if not filepath.exists():
        return []

    try:
        lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()
        recent = lines[-limit:]
        result = []
        for line in reversed(recent):
            line = line.strip()
            if line:
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return result
    except Exception as e:
        logger.warning(f"[observability] Failed to read events: {e}")
        return []


def clear_events(event_type: str) -> bool:
    """清空指定类型的事件日志（调试用）。"""
    filename = _FILE_MAP.get(event_type)
    if not filename:
        return False
    filepath = _LOGS_DIR / filename
    try:
        with _write_lock:
            filepath.write_text("", encoding="utf-8")
        return True
    except Exception:
        return False
