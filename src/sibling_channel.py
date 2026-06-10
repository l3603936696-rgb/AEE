"""
姐妹通道 — 实体间无 LLM 通信

两个实体通过共享目录交换消息。
每个实体写自己的 outbox，读对方的 outbox。
消息就是她们语言系统产出的原始表达——不经过 LLM。

通道格式：{channel_dir}/{entity_name}.jsonl
每行一条消息：{"tick": int, "text": str, "ts": float}

用法：
    channel = SiblingChannel("E:/xia_channel", self_name="xia", peer_name="knuonuo")

    # 每 tick 开始时读
    msg = channel.poll()          # 返回最新未读消息的 text，或 None

    # 每 tick 结束时写
    channel.post("累……", tick=42)  # 把自己的表达发给对方
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SiblingChannel:
    """姐妹间的消息通道。"""

    def __init__(
        self,
        channel_dir: str,
        self_name: str,
        peer_name: str,
    ) -> None:
        self._dir = Path(channel_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._self_name = self_name
        self._peer_name = peer_name
        self._self_file = self._dir / f"{self_name}.jsonl"
        self._peer_file = self._dir / f"{peer_name}.jsonl"
        # 上次读到的位置（字节偏移），避免重复读
        self._last_read_pos = 0
        # 初始化：跳过已有消息（不读历史）
        if self._peer_file.exists():
            self._last_read_pos = self._peer_file.stat().st_size

    def post(self, text: str, tick: int) -> None:
        """把自己的表达写入 outbox。"""
        if not text or not text.strip():
            return
        msg = {
            "from": self._self_name,
            "tick": tick,
            "text": text.strip(),
            "ts": round(time.time(), 2),
        }
        try:
            with open(self._self_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"[SiblingChannel] post failed: {e}")

    def poll(self) -> Optional[str]:
        """
        读取对方的新消息。

        返回最新一条未读消息的 text，或 None。
        多条未读时只取最后一条（她只听到最近的那句）。
        """
        if not self._peer_file.exists():
            return None

        try:
            size = self._peer_file.stat().st_size
            if size <= self._last_read_pos:
                return None  # 没有新内容

            with open(self._peer_file, "r", encoding="utf-8") as f:
                f.seek(self._last_read_pos)
                new_lines = f.readlines()
                self._last_read_pos = f.tell()

            # 取最后一条有效消息
            for line in reversed(new_lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    text = msg.get("text", "")
                    if text:
                        logger.info(
                            f"[SiblingChannel] heard from {self._peer_name}: "
                            f"'{text}' (tick={msg.get('tick')})"
                        )
                        return text
                except json.JSONDecodeError:
                    continue

        except Exception as e:
            logger.warning(f"[SiblingChannel] poll failed: {e}")

        return None
