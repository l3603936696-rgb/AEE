"""
TetraMem Persistence — 降级持久层

TetraMem 不可用时的本地 JSON 降级读写。
供 tetramem_adapter.py 调用。

设计原则（核心原则：状态驱动，禁止时钟驱动）：
    - 所有操作跟随"经验流"或"动作流"，而非时钟
    - 任一模块失败必须可跳过，不阻断主循环
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# 路径常量
# ============================================================================

_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
MEMORIES_STAGED_PATH = _DATA_DIR / "memories_staged.json"


# ============================================================================
# 底层读写
# ============================================================================

def _load_staged() -> List[Dict[str, Any]]:
    """加载已暂存的结构化记忆条目。"""
    if not MEMORIES_STAGED_PATH.exists():
        return []
    try:
        with open(MEMORIES_STAGED_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[TetraMemAdapter] Failed to load memories_staged.json: {e}")
        return []


def _save_staged(entries: List[Dict[str, Any]]) -> None:
    """保存结构化记忆条目到本地 JSON。"""
    try:
        with open(MEMORIES_STAGED_PATH, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[TetraMemAdapter] Failed to save memories_staged.json: {e}")


# ============================================================================
# 规范化
# ============================================================================

def _normalize_tetramem_results(raw: List[Any]) -> List[Dict[str, Any]]:
    """将 TetraMem 返回的记录规范化为 memory_bias 所需格式。"""
    results = []
    for item in raw:
        if isinstance(item, dict):
            results.append({
                "emotion": float(item.get("emotion", 0.0)),
                "intent": str(item.get("intent", "")),
                "timestamp": float(item.get("timestamp", 0.0)),
                "metadata": {
                    "content": item.get("content", ""),
                    "outcome": item.get("outcome", "neutral"),
                    "weight": float(item.get("weight", 1.0)),
                    "source": "tetramem",
                },
            })
    return results


# ============================================================================
# 降级检索
# ============================================================================

def _retrieve_from_staged(
    intent: str,
    emotion: float,
    limit: int,
) -> List[Dict[str, Any]]:
    """
    从 memories_staged.json 降级检索。

    策略：
        1. 过滤包含 intent:xxx 或相同意图前缀的条目
        2. 按 weight * 情绪相似度 排序
        3. 取 top N
    """
    entries = _load_staged()
    if not entries:
        return []

    scored = []
    for entry in entries:
        tags = entry.get("tags", [])
        entry_intent = _extract_intent_tag(tags)
        if not entry_intent:
            continue
        if entry_intent == intent or entry_intent.startswith(intent) or intent.startswith(entry_intent):
            entry_emotion = float(entry.get("state", {}).get("emotion_polarity", 0.0))
            emotion_sim = 1.0 - min(abs(emotion - entry_emotion) / 2.0, 1.0)
            weight = float(entry.get("weight", 1.0))
            score = weight * (0.5 + 0.5 * emotion_sim)
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, entry in scored[:limit]:
        results.append({
            "emotion": float(entry.get("state", {}).get("emotion_polarity", 0.0)),
            "intent": _extract_intent_tag(entry.get("tags", [])) or "",
            "timestamp": 0.0,
            "metadata": {
                "content": entry.get("content", ""),
                "outcome": "neutral",
                "weight": float(entry.get("weight", 1.0)),
                "source": "staged",
            },
        })
    return results


def _extract_intent_tag(tags: List[str]) -> Optional[str]:
    """从标签列表中提取 intent:xxx 标签。"""
    for tag in tags:
        if tag.startswith("intent:"):
            return tag[len("intent:"):]
    return None
