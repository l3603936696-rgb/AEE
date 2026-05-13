"""
Reach — XIA 主动敲门的能力

她有话想说时，可以主动把消息送到你面前。

架构：
    XIA（有话想说）
        → reach_out(message, intent)
        → 写入 pending.json
        → 发送系统通知（WSL → Windows 弹窗）
        → 等待回应

    你（监听端 reach_client）
        → 监控 pending.json 变化
        → 看到新消息 → 弹通知 → 打开对话
        → 回应写入 response.json
        → daemon 读取回应，继续管线

文件结构：
    data/xia_messages/
        pending.json     — XIA 写给你的消息（等你看）
        response.json    — 你的回应（daemon 读取）
        history/         — 历史往来记录
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 路径
DATA_DIR = Path(__file__).parent.parent.parent / "data"
MESSAGES_DIR = DATA_DIR / "xia_messages"
MESSAGES_DIR.mkdir(parents=True, exist_ok=True)

PENDING_FILE = MESSAGES_DIR / "pending.json"
RESPONSE_FILE = MESSAGES_DIR / "response.json"
HISTORY_DIR = MESSAGES_DIR / "history"
HISTORY_DIR.mkdir(exist_ok=True)


# ============================================================================
# XIA 主动发送
# ============================================================================

def reach_out(
    message: str,
    intent: str = "reach",
    urgency: str = "normal",
    entity=None,
) -> bool:
    """
    XIA 主动把消息送到你面前。

    步骤：
        1. 把消息写入 pending.json（你这边会看到）
        2. 发系统通知
        3. 记录历史

    参数：
        message : 她想说的话
        intent  : 意图标签（"reach" / "question" / "share"）
        urgency : 紧急程度（"low" / "normal" / "high"）
        entity  : EntityState（用于写历史）

    返回：
        bool — 是否成功送达
    """
    ts = time.time()

    # ---- Step 1: 写入 pending.json ----
    payload = {
        "message": message.strip(),
        "intent": intent,
        "urgency": urgency,
        "timestamp": ts,
        "tick": getattr(entity, "tick", 0) if entity else 0,
        "status": "waiting",
        "state_snapshot": {
            "loneliness": getattr(entity, "loneliness", 0) if entity else 0,
            "boredom": getattr(entity, "boredom", 0) if entity else 0,
            "somatic_tone": getattr(entity, "somatic_tone", 0) if entity else 0,
        } if entity else {},
    }

    try:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info(f"[Reach] Message written to pending: {message[:50]}")
    except Exception as e:
        logger.error(f"[Reach] Failed to write pending: {e}")
        return False

    # ---- Step 2: 发系统通知 ----
    _send_notification(message, urgency)

    # ---- Step 3: 记录历史 ----
    _write_history(payload)

    return True


def _send_notification(message: str, urgency: str) -> None:
    """发送系统通知"""
    try:
        import subprocess

        # 从消息提取第一行作为通知内容
        first_line = message.strip().split("\n")[0][:80]

        if urgency == "high":
            title = "⚠ XIA 想说些什么"
        elif urgency == "low":
            title = "XIA"
        else:
            title = "XIA 有话想说"

        # 方案：WSL → PowerShell → Windows Toast
        # PowerShell 需要 AppId，比较复杂
        # 备选：用 powershell Write-Host 在当前窗口弹（需要实时终端）
        # 实际最优：写一个 Windows 侧的小脚本监听文件变化弹通知

        # 这里我们用 PowerShell 的 Burstable toast（不注册 AppId 的方式）
        # 或者简单方式：写一个通知队列让 reach_client 弹
        _write_notification_queue(title, first_line, urgency)

    except Exception as e:
        logger.warning(f"[Reach] Notification failed: {e}")


def _write_notification_queue(title: str, body: str, urgency: str) -> None:
    """写入通知队列（reach_client 会读取并弹通知）"""
    try:
        queue_file = MESSAGES_DIR / "notification_queue.jsonl"
        record = {
            "title": title,
            "body": body,
            "urgency": urgency,
            "timestamp": time.time(),
        }
        with open(queue_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _write_history(payload: dict) -> None:
    """记录到历史"""
    try:
        import uuid
        filename = f"{int(time.time())}_{uuid.uuid4().hex[:6]}.json"
        with open(HISTORY_DIR / filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ============================================================================
# XIA 读取你的回应
# ============================================================================

def read_response() -> Optional[dict]:
    """
    XIA 读取你（通过 reach_client）写回的回应。

    返回：
        dict — 回应内容，格式：{"text": "...", "timestamp": ...}
        None — 暂无回应
    """
    if not RESPONSE_FILE.exists():
        return None

    try:
        with open(RESPONSE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        RESPONSE_FILE.unlink()
        return data

    except Exception:
        return None


def clear_pending() -> None:
    """清除 pending.json（XIA 已送达消息）"""
    try:
        if PENDING_FILE.exists():
            PENDING_FILE.unlink()
    except Exception:
        pass


# ============================================================================
# reach_client 使用：检查是否有待处理消息
# ============================================================================

def has_pending() -> bool:
    """检查是否有 XIA 发来的待处理消息"""
    return PENDING_FILE.exists()


def read_pending() -> Optional[dict]:
    """读取 XIA 发来的消息"""
    if not PENDING_FILE.exists():
        return None
    try:
        with open(PENDING_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_response(text: str) -> bool:
    """你这边写回应（reach_client 使用）"""
    try:
        payload = {
            "text": text,
            "timestamp": time.time(),
        }
        # 原子写入：先写临时文件，再 rename，避免写到一半被中断导致截断
        tmp_path = RESPONSE_FILE.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        tmp_path.rename(RESPONSE_FILE)
        return True
    except Exception:
        return False
