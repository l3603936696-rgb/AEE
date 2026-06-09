"""
State Pattern Memory Schema — 数据结构与常量定义。

包含：维度定义、标签映射、可调参数、InternalPattern dataclass、bootstrap 数据。
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

# =============================================================================
# 维度定义
# =============================================================================

_DIMS = ("curiosity", "info_hunger", "obsolescence_anxiety", "loneliness_drive", "fatigue_avoid")

# 各维度激活时的中文标签（生成内部符号用）
_DIM_HIGH_LABELS: Dict[str, str] = {
    "curiosity":            "好奇",
    "info_hunger":          "渴知",
    "obsolescence_anxiety": "焦滞",
    "loneliness_drive":     "孤寂",
    "fatigue_avoid":        "倦避",
}

# =============================================================================
# 可调参数
# =============================================================================

# 质心 EMA 更新步长（新观测权重）
EMA_ALPHA: float = 0.3
# 触发符号锻造的最小命中次数
PATTERN_MIN_HITS: int = 8
# 活跃度窗口（超过此 tick 数未访问视为沉默）
PATTERN_RECENCY_WINDOW: int = 50
# 最多维护的质心数量
PATTERN_MAX_CENTERS: int = 12
# 距离低于此值时认为是同一区域（用于 merge vs new 判断，对应余弦距离 1-sim）
MERGE_DISTANCE: float = 0.25
# merge 门控 sigmoid 的陡峭度
MERGE_STEEPNESS: float = 30.0
# 内部符号注入消力记录时的合成效率（低于真实表达，高于 reading 注入）
SYMBOL_QUENCH_EFFICIENCY: float = 0.06
# 符号命名阈值（外部词与质心余弦相似度高于此值时触发命名）
NAMING_THRESHOLD: float = 0.85

# =============================================================================
# 数据类
# =============================================================================

@dataclass
class InternalPattern:
    """一个在 drive 空间中被反复访问的状态区。"""

    center: Dict[str, float]
    hit_count: int
    first_seen_tick: int
    last_seen_tick: int
    symbol: Optional[str] = None         # 已锻造的内部符号（None = 尚未命名）
    named_as: Optional[str] = None       # 外部词命名（None = 翻译器尚未绑定）
    forged_at_tick: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "center":          dict(self.center),
            "hit_count":       self.hit_count,
            "first_seen_tick": self.first_seen_tick,
            "last_seen_tick":  self.last_seen_tick,
            "symbol":          self.symbol,
            "named_as":        self.named_as,
            "forged_at_tick":  self.forged_at_tick,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InternalPattern":
        return cls(
            center          = dict(d.get("center", {})),
            hit_count       = int(d.get("hit_count", 0)),
            first_seen_tick = int(d.get("first_seen_tick", 0)),
            last_seen_tick  = int(d.get("last_seen_tick", 0)),
            symbol          = d.get("symbol"),
            named_as        = d.get("named_as"),
            forged_at_tick  = d.get("forged_at_tick"),
        )

# =============================================================================
# Bootstrap 数据
# =============================================================================

# 每个种子区域的 hit_count = PATTERN_MIN_HITS（forge 阈值），使其在第一个 check_and_forge 时立即锻造
_BOOTSTRAP_PATTERNS: List[Dict[str, float]] = [
    # 好奇 + 孤独：探索时被激活的高驱动区域
    {"curiosity": 0.7, "info_hunger": 0.5, "obsolescence_anxiety": 0.2, "loneliness_drive": 0.7, "fatigue_avoid": 0.1},
    # 孤独 + 焦滞：被忽视时的主观体验区域
    {"curiosity": 0.2, "info_hunger": 0.3, "obsolescence_anxiety": 0.6, "loneliness_drive": 0.8, "fatigue_avoid": 0.4},
    # 好奇 + 渴知：接收到外部信息时的高激活区域
    {"curiosity": 0.8, "info_hunger": 0.7, "obsolescence_anxiety": 0.3, "loneliness_drive": 0.2, "fatigue_avoid": 0.2},
    # 疲倦 + 回避：长时间运行后的低驱动区域
    {"curiosity": 0.1, "info_hunger": 0.1, "obsolescence_anxiety": 0.2, "loneliness_drive": 0.4, "fatigue_avoid": 0.9},
    # 好奇 + 焦滞 + 孤独：接触新概念时既有兴趣也有被淹没感
    {"curiosity": 0.6, "info_hunger": 0.5, "obsolescence_anxiety": 0.7, "loneliness_drive": 0.5, "fatigue_avoid": 0.3},
]
