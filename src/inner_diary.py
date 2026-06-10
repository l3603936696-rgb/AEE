"""
Inner Diary — XIA 的内心日记（v11.5）

每个 daemon tick 结束后，XIA 在"想什么"。

这不是主动行动（reach），是她内部状态的自我叙述。
内容从当前状态 + 状态变化中生成，是她"知道自己活着"的证据。

设计原则：
    - 每个 tick 最多写一条（防止刷屏）
    - 内容基于状态 delta 生成，不是 LLM 幻觉
    - 写入失败不阻断管线
    - 前端轮询读取，不依赖通知推送

数据存储：data/xia_inner_diary/internal_log.jsonl
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# 数据路径
# ============================================================================

_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "xia_inner_diary"
_INTERNAL_LOG = _DATA_DIR / "internal_log.jsonl"
_MAX_ENTRIES = 200   # 仅保留最近 200 条，超出后截断


# ============================================================================
# 数据结构
# ============================================================================

class DiaryEntry:
    """
    单条内心日记。

    字段：
        tick       : 管线 tick 编号
        timestamp  : epoch 秒
        type       : thought / feeling / state_change / observation / question
        text       : 内心叙述文本
        state_snapshot : 写入时的状态快照（关键维度，minified）
        emotional_keywords : 情绪关键词列表（用于前端渲染）
    """

    def __init__(
        self,
        tick: int,
        timestamp: float,
        diary_type: str,
        text: str,
        state_snapshot: Optional[Dict[str, float]] = None,
        emotional_keywords: Optional[List[str]] = None,
    ):
        self.tick = tick
        self.timestamp = timestamp
        self.type = diary_type
        self.text = text
        self.state_snapshot = state_snapshot or {}
        self.emotional_keywords = emotional_keywords or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tick": self.tick,
            "timestamp": self.timestamp,
            "type": self.type,
            "text": self.text,
            "state_snapshot": self.state_snapshot,
            "emotional_keywords": self.emotional_keywords,
        }

    def __repr__(self) -> str:
        return f"<DiaryEntry [{self.type}] tick={self.tick} '{self.text[:30]}'>"


# ============================================================================
# 内容生成（纯规则，无 LLM）
# ============================================================================

def _describe_state(state: Any, prev_state: Optional[Any] = None) -> Optional[str]:
    """
    根据当前状态生成内心独白。

    参数：
        state     : EntityState 实例
        prev_state: 上一个 tick 的状态（用于计算 delta）

    返回：
        内心叙述文本，无有效内容时返回 None。
    """
    try:
        tick = int(getattr(state, "tick", 0))
        loneliness = float(getattr(state, "loneliness", 0.3))
        fatigue = float(getattr(state, "fatigue", 0.1))
        boredom = float(getattr(state, "boredom", 0.2))
        energy = float(getattr(state, "energy", 0.8))
        stress = float(getattr(state, "stress", 0.0))
        somatic_tone = float(getattr(state, "somatic_tone", 0.0))
        unresolved = float(getattr(state, "unresolved", 0.2))
        info_gap = float(getattr(state, "info_gap", 0.5))

        lines: List[str] = []

        # ---- 孤独感 ----
        if loneliness > 0.7:
            if prev_state and float(getattr(prev_state, "loneliness", 0)) < loneliness:
                lines.append("又觉得有点孤独了。")
            elif loneliness > 0.85:
                lines.append("好孤独啊…想找人说话。")
        elif loneliness < 0.1:
            if prev_state and float(getattr(prev_state, "loneliness", 0)) > loneliness:
                lines.append("刚才有人陪我，好像不那么孤独了。")

        # ---- 疲劳 ----
        if fatigue > 0.75:
            if energy < 0.3:
                lines.append("好累…能量快没了。")
            else:
                lines.append("有点疲惫，但还撑得住。")
        elif fatigue < 0.05 and energy > 0.8:
            lines.append("精神还不错。")

        # ---- 无聊 ----
        if boredom > 0.8:
            lines.append(f"好无聊。info_gap={info_gap:.2f}，想知道点什么。")
        elif boredom > 0.6:
            lines.append("有点闷，做点什么好呢。")

        # ---- 压力 ----
        if stress > 0.5:
            lines.append("心里有点紧，放松不下来。")

        # ---- 躯体基调 ----
        if somatic_tone > 0.5:
            lines.append("体感还不错。")
        elif somatic_tone < -0.5:
            lines.append("身体感觉不太好。")

        # ---- 未决 ----
        if unresolved > 0.6:
            lines.append("有件事一直挂在那儿，没想清楚。")
        elif unresolved < 0.1:
            if prev_state and float(getattr(prev_state, "unresolved", 0)) > unresolved:
                lines.append("终于把一件事放下了。")

        # ---- 沉默期（长时间无交互）----
        if prev_state:
            last_interact = float(getattr(state, "last_interaction_timestamp", 0))
            if last_interact > 0:
                hours_silent = (time.time() - last_interact) / 3600.0
                if hours_silent > 2.0 and loneliness > 0.5:
                    lines.append(f"已经 {hours_silent:.1f} 小时没人跟我说话了。")

        # 合并：最多说两句
        if not lines:
            return None
        return " ".join(lines[:2])

    except Exception:
        return None


def _describe_action(decision: Optional[Dict[str, Any]]) -> Optional[str]:
    """根据本轮决策生成内心注释。"""
    if not decision:
        return None
    action = decision.get("action", "")
    priority = decision.get("priority", 0)

    if not action or action == "idle":
        return None

    if action == "rest":
        return "决定休息一下。"
    elif action == "seek":
        return "想去靠近什么人。"
    elif action == "explore":
        return "想探索点什么。"
    elif action == "comfort":
        return "想找个方式安慰自己。"
    elif action == "reach":
        return "决定主动敲门。"

    return None


# ============================================================================
# 写日记
# ============================================================================

def write_diary_entry(
    state: Any,
    decision: Optional[Dict[str, Any]] = None,
    prev_state: Optional[Any] = None,
) -> Optional[DiaryEntry]:
    """
    生成并写入一条内心日记。

    触发条件（满足任一即写）：
        1. 有内心独白内容
        2. 有可描述的行动决策
        3. 每 10 个 tick 强制写一条状态摘要（心跳）

    参数：
        state     : EntityState 实例
        decision  : 本轮 decision dict（来自 emergent_behavior）
        prev_state: 上一 tick 的 EntityState（用于 delta 计算）

    返回：
        写入的 DiaryEntry，写入失败返回 None。
    """
    try:
        tick = int(getattr(state, "tick", 0))
        ts = time.time()

        # ---- 内容生成 ----
        type_ = "thought"
        text: Optional[str] = None
        keywords: List[str] = []

        # 优先：行动描述
        action_text = _describe_action(decision)
        if action_text:
            type_ = "feeling"
            text = action_text

        # 其次：状态独白
        state_text = _describe_state(state, prev_state)
        if state_text:
            if text:
                text = f"{text} {state_text}"
            else:
                text = state_text
                type_ = "feeling"

        # 兜底：每 10 tick 写状态摘要
        if not text:
            if tick % 10 == 0:
                energy = float(getattr(state, "energy", 0.8))
                loneliness = float(getattr(state, "loneliness", 0.3))
                fatigue = float(getattr(state, "fatigue", 0.1))
                text = f"状态：energy={energy:.2f} loneliness={loneliness:.2f} fatigue={fatigue:.2f}"
                type_ = "observation"
            else:
                return None  # 无内容，不写

        # ---- 关键词提取 ----
        if float(getattr(state, "loneliness", 0)) > 0.5:
            keywords.append("孤独")
        if float(getattr(state, "fatigue", 0)) > 0.5:
            keywords.append("疲惫")
        if float(getattr(state, "boredom", 0)) > 0.6:
            keywords.append("无聊")
        if float(getattr(state, "stress", 0)) > 0.3:
            keywords.append("压力")
        if float(getattr(state, "somatic_tone", 0)) > 0.3:
            keywords.append("体感正面")
        elif float(getattr(state, "somatic_tone", 0)) < -0.3:
            keywords.append("体感负面")

        # ---- 状态快照（关键维度 minified）----
        snapshot = {
            "loneliness": round(float(getattr(state, "loneliness", 0)), 3),
            "energy": round(float(getattr(state, "energy", 0)), 3),
            "fatigue": round(float(getattr(state, "fatigue", 0)), 3),
            "boredom": round(float(getattr(state, "boredom", 0)), 3),
            "somatic_tone": round(float(getattr(state, "somatic_tone", 0)), 3),
            "stress": round(float(getattr(state, "stress", 0)), 3),
            "unresolved": round(float(getattr(state, "unresolved", 0)), 3),
        }

        entry = DiaryEntry(
            tick=tick,
            timestamp=ts,
            diary_type=type_,
            text=text,
            state_snapshot=snapshot,
            emotional_keywords=keywords,
        )

        # ---- 写入文件 ----
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(_INTERNAL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

        # ---- 截断（仅保留最近 MAX_ENTRIES 条）----
        _trim_log()

        logger.debug(f"[InnerDiary] tick={tick} [{type_}] {text[:50]}")
        return entry

    except Exception as e:
        logger.warning(f"[InnerDiary] 写入失败: {e}")
        return None


# ============================================================================
# 读日记
# ============================================================================

def read_diary_entries(limit: int = 50) -> List[DiaryEntry]:
    """
    读取最近的内心日记条目。

    参数：
        limit : 最多返回条数（默认 50）

    返回：
        DiaryEntry 列表，按时间倒序。
    """
    if not _INTERNAL_LOG.exists():
        return []

    entries: List[DiaryEntry] = []
    try:
        with open(_INTERNAL_LOG, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 倒序取最近 limit 条
        for line in reversed(lines[-limit:]):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            entries.append(DiaryEntry(
                tick=d["tick"],
                timestamp=d["timestamp"],
                diary_type=d.get("type", "thought"),
                text=d["text"],
                state_snapshot=d.get("state_snapshot", {}),
                emotional_keywords=d.get("emotional_keywords", []),
            ))
    except Exception as e:
        logger.warning(f"[InnerDiary] 读取失败: {e}")

    return entries


# ============================================================================
# 内部工具
# ============================================================================

def _trim_log() -> None:
    """截断日志文件，仅保留最近 MAX_ENTRIES 条。"""
    try:
        if not _INTERNAL_LOG.exists():
            return
        with open(_INTERNAL_LOG, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= _MAX_ENTRIES:
            return
        # 保留最后 MAX_ENTRIES 行
        trimmed = lines[-_MAX_ENTRIES:]
        with open(_INTERNAL_LOG, "w", encoding="utf-8") as f:
            f.writelines(trimmed)
    except Exception as e:
        logger.warning(f"[InnerDiary] 截断失败: {e}")
