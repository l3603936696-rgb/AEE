"""
Recursive Construction — 递归构式（v1.0）

让构式的槽位可以填另一个构式，实现多层嵌套表达。

核心区别（vs construction_grammar.py 的平面构式）：
    平面：好{WORD}啊……          → "好累啊……"
    递归：好{WORD}啊……{CLAUSE}   → "好累啊……想找人说话但又没力气"
                       ↓
              {DESIRE}但又{OBSTACLE}
                 ↓          ↓
            想找人说话     没力气

数据结构：
    Slot 有两种类型：
        WORD  — 填一个锚点词（从词汇表）
        CLAUSE — 填另一个 ClausePattern（递归）

    ClausePattern = 带类型槽的结构模板
        schema: "{DESIRE}但又{OBSTACLE}"
        slot_types: {0: "desire", 1: "obstacle"}
        drive_trigger: 什么驱动力状态下触发这个模式

学习来源：
    1. 手工种子模式（启动用，约 30 个）
    2. 从 LLM explore/seek 输出中提取（reading_acquisition 的结构版）
    3. 从成功的组合中强化/衰减

设计原则：
    - 全连续：模式评分 + softmax，不做 if-else 门控
    - 递归深度上限 = 3（防止无限嵌套）
    - 和 construction_grammar.py 兼容：递归结果可以填入平面构式的 CLAUSE 槽
"""

import logging
import math
import random
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── 超参 ───────────────────────────────────────────────────────────────────
_MAX_DEPTH = 3              # 递归深度上限
_MAX_CLAUSE_PATTERNS = 60   # 子句模式库上限
_STRENGTH_DECAY = 0.995     # 每 tick 衰减
_STRENGTH_BOOST = 0.12      # 成功使用的强度增益
_MIN_STRENGTH = 0.01        # 淘汰阈值


# ─── 子句模式 ────────────────────────────────────────────────────────────────

class ClausePattern:
    """
    一个子句模式——可以填入构式的 CLAUSE 槽。

    schema 示例：
        "{desire}但又{obstacle}"
        "因为{reason}"
        "想{action}又怕{fear}"
        "{state}了一点"

    slot_roles 定义每个槽的语义角色，用于匹配驱动力状态。
    """
    __slots__ = (
        "schema", "slot_roles", "drive_trigger",
        "strength", "use_count", "born_tick",
    )

    def __init__(
        self,
        schema: str,
        slot_roles: Dict[str, str],    # slot_name → role type
        drive_trigger: Dict[str, float],  # 什么驱动力场下触发
        born_tick: int = 0,
    ):
        self.schema = schema
        self.slot_roles = slot_roles
        self.drive_trigger = drive_trigger
        self.strength: float = 0.3
        self.use_count: int = 0
        self.born_tick: int = born_tick

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "slot_roles": dict(self.slot_roles),
            "drive_trigger": dict(self.drive_trigger),
            "strength": self.strength,
            "use_count": self.use_count,
            "born_tick": self.born_tick,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ClausePattern":
        cp = cls(
            d["schema"],
            d.get("slot_roles", {}),
            d.get("drive_trigger", {}),
            d.get("born_tick", 0),
        )
        cp.strength = d.get("strength", 0.3)
        cp.use_count = d.get("use_count", 0)
        return cp


# ─── 语义角色 → 词汇映射 ─────────────────────────────────────────────────────
# 每个角色对应一组可能的填充词/短语
# 这些从锚点词汇表 + 构式习得中动态扩展

ROLE_FILLERS: Dict[str, List[str]] = {
    # 欲望/意图
    "desire":   ["想找人说话", "想看看", "想休息", "想动一动", "想知道"],
    "action":   ["看看", "动一动", "试试", "找人", "休息"],
    # 障碍/阻力
    "obstacle": ["没力气", "太累了", "不敢", "懒得动", "没人"],
    "fear":     ["出错", "没用", "更累"],
    # 原因
    "reason":   ["太累了", "一个人待太久了", "什么都没做", "刚才那个没用"],
    # 状态描述
    "state":    [],  # 从锚点词汇表动态填充
    # 结果/评价
    "result":   ["好了点", "没什么用", "更累了", "还是一样"],
    # 时间
    "time":     ["刚才", "之前", "一直"],
    # 对象
    "topic":    [],  # 从回忆/阅读习得中动态填充
}


def _fill_role_from_state(
    role: str,
    drive_state: Dict[str, float],
    anchor_words: List[str],
) -> str:
    """根据驱动力状态和语义角色，选择最合适的填充词。"""

    # "state" 角色直接从锚点词汇表选
    if role == "state" and anchor_words:
        return random.choice(anchor_words[:5]) if anchor_words else "累"

    fillers = ROLE_FILLERS.get(role, [])
    if not fillers:
        return ""

    # 根据驱动力状态加权选择
    if role == "desire":
        loneliness = drive_state.get("loneliness", 0.0)
        curiosity = drive_state.get("curiosity", 0.0)
        fatigue = drive_state.get("fatigue", 0.0)
        # 加权：孤独 → 想找人，好奇 → 想看看，累 → 想休息
        weights = [
            loneliness * 2.0,       # 想找人说话
            curiosity * 2.0,        # 想看看
            fatigue * 2.0,          # 想休息
            (1 - fatigue) * 1.0,    # 想动一动
            curiosity * 1.5,        # 想知道
        ]
    elif role == "obstacle":
        fatigue = drive_state.get("fatigue", 0.0)
        anxiety = drive_state.get("anxiety", 0.0)
        loneliness = drive_state.get("loneliness", 0.0)
        weights = [
            fatigue * 2.0,          # 没力气
            fatigue * 1.5,          # 太累了
            anxiety * 2.0,          # 不敢
            fatigue * 1.0,          # 懒得动
            loneliness * 1.5,       # 没人
        ]
    elif role == "reason":
        fatigue = drive_state.get("fatigue", 0.0)
        loneliness = drive_state.get("loneliness", 0.0)
        boredom = drive_state.get("boredom", 0.0)
        weights = [
            fatigue * 2.0,
            loneliness * 2.0,
            boredom * 2.0,
            0.3,
        ]
    else:
        weights = [1.0] * len(fillers)

    # 截断或补齐 weights 到和 fillers 一样长
    weights = weights[:len(fillers)]
    while len(weights) < len(fillers):
        weights.append(0.5)

    # 归一化
    total = sum(max(0.01, w) for w in weights)
    probs = [max(0.01, w) / total for w in weights]

    return random.choices(fillers, weights=probs, k=1)[0]


# ─── 种子子句模式 ─────────────────────────────────────────────────────────────

SEED_CLAUSE_PATTERNS: List[Dict] = [
    # ── 欲望-障碍（冲突型）──
    {
        "schema": "{desire}但又{obstacle}",
        "slot_roles": {"desire": "desire", "obstacle": "obstacle"},
        "drive_trigger": {"fatigue": 0.5, "loneliness": 0.4},
    },
    {
        "schema": "想{action}又怕{fear}",
        "slot_roles": {"action": "action", "fear": "fear"},
        "drive_trigger": {"anxiety": 0.5, "curiosity": 0.3},
    },
    {
        "schema": "想{action}但{obstacle}",
        "slot_roles": {"action": "action", "obstacle": "obstacle"},
        "drive_trigger": {"approach_drive": 0.4, "fatigue": 0.3},
    },
    # ── 因果型 ──
    {
        "schema": "因为{reason}",
        "slot_roles": {"reason": "reason"},
        "drive_trigger": {"unresolved": 0.4},
    },
    {
        "schema": "大概是{reason}吧",
        "slot_roles": {"reason": "reason"},
        "drive_trigger": {"unresolved": 0.3},
    },
    {
        "schema": "可能是{reason}",
        "slot_roles": {"reason": "reason"},
        "drive_trigger": {"unresolved": 0.3, "anxiety": 0.2},
    },
    # ── 结果/评价型 ──
    {
        "schema": "然后就{result}",
        "slot_roles": {"result": "result"},
        "drive_trigger": {},
    },
    {
        "schema": "结果{result}",
        "slot_roles": {"result": "result"},
        "drive_trigger": {},
    },
    # ── 时间型 ──
    {
        "schema": "{time}就开始这样了",
        "slot_roles": {"time": "time"},
        "drive_trigger": {"fatigue": 0.3, "boredom": 0.3},
    },
    # ── 让步型 ──
    {
        "schema": "虽然{state}但还好",
        "slot_roles": {"state": "state"},
        "drive_trigger": {"fatigue": 0.3},
    },
    {
        "schema": "不过{result}",
        "slot_roles": {"result": "result"},
        "drive_trigger": {},
    },
    # ── 递进型 ──
    {
        "schema": "而且越来越{state}了",
        "slot_roles": {"state": "state"},
        "drive_trigger": {},
    },
    {
        "schema": "还有点{state}",
        "slot_roles": {"state": "state"},
        "drive_trigger": {},
    },
]


# ─── 递归生成器 ──────────────────────────────────────────────────────────────

class RecursiveGenerator:
    """
    递归构式生成器。

    用法：
        gen = RecursiveGenerator()
        clause = gen.generate_clause(drive_state, anchor_words, depth=0)
        # clause = "想找人说话但又没力气"

    然后把 clause 填入平面构式的 CLAUSE 槽：
        "好{WORD}啊……{CLAUSE}" → "好累啊……想找人说话但又没力气"
    """

    def __init__(self):
        self._patterns: List[ClausePattern] = []
        self._load_seeds()

    def _load_seeds(self) -> None:
        """加载种子模式。"""
        for seed in SEED_CLAUSE_PATTERNS:
            cp = ClausePattern(
                schema=seed["schema"],
                slot_roles=seed["slot_roles"],
                drive_trigger=seed["drive_trigger"],
            )
            self._patterns.append(cp)

    def generate_clause(
        self,
        drive_state: Dict[str, float],
        anchor_words: List[str],
        depth: int = 0,
        avoid_words: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        根据驱动力状态生成一个子句。

        depth 控制递归深度（0 = 顶层）。
        avoid_words 避免和外层锚点语义重复。
        返回填充好的子句字符串，或 None。
        """
        if depth >= _MAX_DEPTH:
            return None
        if not self._patterns:
            return None

        # 对每个模式评分
        scores = []
        for cp in self._patterns:
            s = self._score_pattern(cp, drive_state) * cp.strength
            scores.append(s)

        # softmax 采样
        idx = _softmax_sample(scores, temperature=0.5)
        chosen = self._patterns[idx]

        # 填充槽位
        _avoid = set(avoid_words or [])
        filled = chosen.schema
        for slot_name, role in chosen.slot_roles.items():
            filler = _fill_role_from_state(role, drive_state, anchor_words)
            if not filler:
                return None
            # 避免和外层锚点重复（"好累啊……因为太累了"→不好）
            if _avoid and any(aw in filler for aw in _avoid):
                # 重试一次
                filler = _fill_role_from_state(role, drive_state, anchor_words)
                if any(aw in filler for aw in _avoid):
                    continue  # 跳过这个槽（不完美但避免重复）
            filled = filled.replace("{" + slot_name + "}", filler, 1)

        chosen.use_count += 1
        return filled

    def _score_pattern(
        self,
        cp: ClausePattern,
        drive_state: Dict[str, float],
    ) -> float:
        """评分：驱动力匹配度。"""
        if not cp.drive_trigger:
            return 0.3  # 无条件模式给基础分

        score = 0.0
        for dim, weight in cp.drive_trigger.items():
            val = float(drive_state.get(dim, 0.0))
            score += val * weight
        return score

    def reinforce(self, schema: str, efficiency: float) -> None:
        """对使用过的模式反馈强化。"""
        for cp in self._patterns:
            if cp.schema == schema:
                delta = _STRENGTH_BOOST * (efficiency - 0.03)
                cp.strength = max(0.0, min(1.0, cp.strength + delta))
                break

    def decay_all(self) -> None:
        """衰减所有模式。"""
        for cp in self._patterns:
            cp.strength *= _STRENGTH_DECAY

    def add_pattern(self, cp: ClausePattern) -> None:
        """添加从 LLM 输出中学到的新模式。"""
        # 去重
        existing = {p.schema for p in self._patterns}
        if cp.schema in existing:
            return
        self._patterns.append(cp)
        # 淘汰弱模式
        if len(self._patterns) > _MAX_CLAUSE_PATTERNS:
            self._patterns.sort(key=lambda p: p.strength, reverse=True)
            self._patterns = self._patterns[:_MAX_CLAUSE_PATTERNS]
        logger.info(f"[RecCxG] New clause pattern: '{cp.schema}'")

    def to_dict(self) -> dict:
        return {
            "patterns": [p.to_dict() for p in self._patterns],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RecursiveGenerator":
        gen = cls.__new__(cls)
        gen._patterns = []
        for pd in d.get("patterns", []):
            gen._patterns.append(ClausePattern.from_dict(pd))
        # 补充种子（如果新版本加了新种子）
        existing = {p.schema for p in gen._patterns}
        for seed in SEED_CLAUSE_PATTERNS:
            if seed["schema"] not in existing:
                gen._patterns.append(ClausePattern(
                    seed["schema"], seed["slot_roles"], seed["drive_trigger"],
                ))
        return gen

    @property
    def pattern_count(self) -> int:
        return len(self._patterns)


# ─── softmax ─────────────────────────────────────────────────────────────────

def _softmax_sample(scores: List[float], temperature: float = 0.5) -> int:
    if not scores:
        return 0
    max_s = max(scores)
    weights = [math.exp((s - max_s) / max(temperature, 0.01)) for s in scores]
    total = sum(weights)
    probs = [w / max(total, 1e-9) for w in weights]
    return random.choices(range(len(scores)), weights=probs, k=1)[0]
