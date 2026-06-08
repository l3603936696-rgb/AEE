"""
State Pattern Memory — XIA 的内部符号涌现（v1）

原理：
    状态有，词无 → 锻造符号。

    每 tick 记录 drive_vector。当某个 drive 区域被反复访问（hit >= PATTERN_MIN_HITS），
    为该区域锻造一个内部符号（如 "∅-好奇孤寂"），注入 quenching_data 积累消力信用，
    进入 word_warmup 闭环。

    后续当外部词（来自 reading/social）与该质心高度相似时，
    内部符号被"命名"——翻译器找到了对应的词。

无 if/else：控制流用 max(strategies) + 连续权重。
维度空间：仅在 5D drive_vector 空间工作，不与 somatic_dictionary 的 energy/avoid 空间混用。
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..observability import observe

_DIMS = ("curiosity", "info_hunger", "obsolescence_anxiety", "loneliness_drive", "fatigue_avoid")

# 各维度激活时的中文标签（生成内部符号用）
_DIM_HIGH_LABELS: Dict[str, str] = {
    "curiosity":            "好奇",
    "info_hunger":          "渴知",
    "obsolescence_anxiety": "焦滞",
    "loneliness_drive":     "孤寂",
    "fatigue_avoid":        "倦避",
}

# ---- 可调参数 ----
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


# ============================================================================
# 核心数学工具
# ============================================================================

def _cosine_similarity(a: Dict[str, float], b: Dict[str, float]) -> float:
    """5D drive 空间余弦相似度。"""
    try:
        av = tuple(float(a.get(d, 0.0)) for d in _DIMS)
        bv = tuple(float(b.get(d, 0.0)) for d in _DIMS)
        dot = sum(x * y for x, y in zip(av, bv))
        mag = math.sqrt(sum(x * x for x in av)) * math.sqrt(sum(x * x for x in bv))
        return dot / mag if mag > 1e-9 else 0.0
    except Exception:
        return 0.0


def _ema_update(center: Dict[str, float], new_vec: Dict[str, float]) -> Dict[str, float]:
    """指数移动平均更新质心。"""
    return {
        d: center.get(d, 0.0) * (1.0 - EMA_ALPHA) + float(new_vec.get(d, 0.0)) * EMA_ALPHA
        for d in _DIMS
    }


def _forge_symbol(center: Dict[str, float]) -> str:
    """
    从 drive 质心的主导维度锻造内部符号。
    取激活最强的 top-2 维度的标签，生成类似 "∅-好奇孤寂" 的符号。
    激活值低于 0.2 的维度不参与命名（避免生成无意义标签）。
    """
    ranked = sorted(
        [(d, float(center.get(d, 0.0))) for d in _DIMS],
        key=lambda x: x[1],
        reverse=True,
    )
    top = [_DIM_HIGH_LABELS[d] for d, v in ranked[:2] if v > 0.2]
    label = "".join(top) if top else "混沌"
    return f"∅-{label}"


# ============================================================================
# 数据类
# ============================================================================

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


# ============================================================================
# 主类
# ============================================================================

class StatePatternMemory:
    """
    内部状态模式记忆。

    每 tick observe() 一次 drive_vector，维护至多 PATTERN_MAX_CENTERS 个质心。
    check_and_forge() 检测满足条件的质心并锻造内部符号。
    """

    def __init__(self) -> None:
        self._patterns: List[InternalPattern] = []

    # ------------------------------------------------------------------ #
    # 观测 & 质心维护
    # ------------------------------------------------------------------ #

    def observe(self, drive_vector: Dict[str, float], tick: int) -> None:
        """记录一次 drive_vector 观测，更新或新建质心。"""
        try:
            dv = {d: float(drive_vector.get(d, 0.0)) for d in _DIMS}

            # 找最近质心（没有质心时用 sentinel）
            scored = [(i, _cosine_similarity(dv, p.center)) for i, p in enumerate(self._patterns)]
            scored.append((-1, -1.0))  # sentinel: 无质心
            best_idx, best_sim = max(scored, key=lambda x: x[1])

            # merge 门控：sim 高时趋 1（合并），低时趋 0（新建）
            # 合并条件 ≈ sim > (1 - MERGE_DISTANCE)
            merge_threshold = 1.0 - MERGE_DISTANCE
            merge_w = 1.0 / (1.0 + math.exp(-MERGE_STEEPNESS * (best_sim - merge_threshold)))
            new_w   = 1.0 - merge_w

            def _do_merge(idx=best_idx):
                p = self._patterns[idx]
                p.center        = _ema_update(p.center, dv)
                p.hit_count    += 1
                p.last_seen_tick = tick

            def _do_new():
                # 超出容量：移除访问最久远的质心
                excess = max(0, len(self._patterns) - (PATTERN_MAX_CENTERS - 1))
                if excess > 0:
                    self._patterns.sort(key=lambda p: p.last_seen_tick)
                    self._patterns = self._patterns[excess:]
                self._patterns.append(InternalPattern(
                    center          = dict(dv),
                    hit_count       = 1,
                    first_seen_tick = tick,
                    last_seen_tick  = tick,
                ))

            max(
                {
                    "merge": (merge_w, _do_merge),
                    "new":   (new_w,   _do_new),
                }.items(),
                key=lambda kv: kv[1][0],
            )[1][1]()

        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # 符号锻造
    # ------------------------------------------------------------------ #

    def check_and_forge(self, current_tick: int) -> List[str]:
        """
        遍历所有质心，对满足条件的质心锻造内部符号。

        锻造条件（连续权重乘积）：
            hit_strength  = min(1, hit_count / PATTERN_MIN_HITS)  — 够老
            recency       = 1 - (age / RECENCY_WINDOW)            — 够新
            not_forged_w  = 1 - float(symbol is not None)         — 未锻造

        forge_score = hit_strength * recency * not_forged_w
        forge_score > skip_score (= 1 - forge_score) → 锻造。

        返回本次新锻造的符号列表。
        """
        new_symbols = []
        try:
            for p in self._patterns:
                hit_strength = min(1.0, p.hit_count / max(1, PATTERN_MIN_HITS))
                recency      = max(0.0, 1.0 - (current_tick - p.last_seen_tick)
                                              / max(1, PATTERN_RECENCY_WINDOW))
                not_forged_w = 1.0 - min(1.0, float(p.symbol is not None))

                forge_score = hit_strength * recency * not_forged_w
                skip_score  = 1.0 - forge_score

                def _do_forge(pattern=p):
                    pattern.symbol         = _forge_symbol(pattern.center)
                    pattern.forged_at_tick = current_tick
                    new_symbols.append(pattern.symbol)

                max(
                    {
                        "forge": (forge_score, _do_forge),
                        "skip":  (skip_score,  lambda: None),
                    }.items(),
                    key=lambda kv: kv[1][0],
                )[1][1]()

        except Exception:
            pass

        return new_symbols

    # ------------------------------------------------------------------ #
    # 外部词命名
    # ------------------------------------------------------------------ #

    def try_name_symbol(
        self,
        word: str,
        word_drive_vector: Dict[str, float],
        current_tick: int,
    ) -> bool:
        """
        尝试用外部词命名最匹配的内部符号。

        word_drive_vector 必须是 5D drive 空间的向量（不是 somatic_dictionary 的 profile）。
        调用方负责映射。

        当余弦相似度 > NAMING_THRESHOLD 时，把该词绑定到对应的内部符号上。
        返回是否成功命名。
        """
        try:
            for p in self._patterns:
                # 只对已锻造但尚未命名的质心命名
                has_symbol  = float(p.symbol is not None)
                not_named_w = 1.0 - min(1.0, float(p.named_as is not None))

                sim     = _cosine_similarity(word_drive_vector, p.center)
                name_w  = has_symbol * not_named_w * (
                    1.0 / (1.0 + math.exp(-40.0 * (sim - NAMING_THRESHOLD)))
                )
                skip_w  = 1.0 - min(1.0, name_w)

                named = False

                def _do_name(pattern=p):
                    nonlocal named
                    pattern.named_as = word
                    named = True

                max(
                    {
                        "name": (name_w, _do_name),
                        "skip": (skip_w, lambda: None),
                    }.items(),
                    key=lambda kv: kv[1][0],
                )[1][1]()

                if named:
                    return True

        except Exception:
            pass

        return False

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #

    def get_active_symbols(self, current_tick: int) -> List[Tuple[str, int]]:
        """
        返回所有最近活跃且已锻造符号的质心。
        格式：[(symbol, hit_count), ...]
        """
        result = []
        try:
            for p in self._patterns:
                recency  = max(0.0, 1.0 - (current_tick - p.last_seen_tick)
                                          / max(1, PATTERN_RECENCY_WINDOW))
                has_sym  = float(p.symbol is not None)
                active_w = recency * has_sym
                skip_w   = 1.0 - active_w

                def _add(pattern=p):
                    result.append((pattern.symbol, pattern.hit_count))

                max(
                    {
                        "add":  (active_w, _add),
                        "skip": (skip_w,   lambda: None),
                    }.items(),
                    key=lambda kv: kv[1][0],
                )[1][1]()

        except Exception:
            pass

        return result

    def pattern_count(self) -> int:
        return len(self._patterns)

    # ------------------------------------------------------------------ #
    # 序列化
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        return {"patterns": [p.to_dict() for p in self._patterns]}

    @classmethod
    def from_dict(cls, d: dict) -> "StatePatternMemory":
        obj = cls()
        obj._patterns = [InternalPattern.from_dict(p) for p in d.get("patterns", [])]
        return obj


# ============================================================================
# 冷启动 bootstrap
# ============================================================================

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


def _bootstrap_spm(spm: "StatePatternMemory", current_tick: int) -> "StatePatternMemory":
    """
    当 SPM 没有任何质心时，用预定义的种子区域初始化。

    每个种子区域的 hit_count = PATTERN_MIN_HITS，使 check_and_forge
    在当前 tick 立即为其锻造内部符号——不等待慢慢积累。

    这样第一个 tick 起，理解链路就有真实符号可用了。
    """
    for i, center in enumerate(_BOOTSTRAP_PATTERNS):
        spm._patterns.append(InternalPattern(
            center          = dict(center),
            hit_count       = PATTERN_MIN_HITS,
            first_seen_tick = current_tick - len(_BOOTSTRAP_PATTERNS) + i,
            last_seen_tick  = current_tick,
        ))
    return spm


# ============================================================================
# tick_engine 集成接口
# ============================================================================

@observe("state_pattern_memory", category="language")
def run_symbol_tick(
    entity,
    drive_vector: Dict[str, float],
    current_tick: int,
) -> List[str]:
    """
    每 tick 调用一次。

    职责：
        1. 从 entity._state_pattern_data 恢复 SPM
        2. observe 本 tick 的 drive_vector
        3. check_and_forge — 返回新锻造的符号
        4. 将新符号注入 entity._quenching_data（合成消力记录，template_idx=-3）
        5. 保存 SPM 回 entity._state_pattern_data

    返回本次新锻造的符号列表（供日志用）。
    """
    new_symbols: List[str] = []
    try:
        spm_data = getattr(entity, "_state_pattern_data", {})
        spm = StatePatternMemory.from_dict(spm_data) if spm_data else StatePatternMemory()

        # 冷启动：没有质心时注入种子区域，立即锻造内部符号
        if not spm._patterns:
            spm = _bootstrap_spm(spm, current_tick)

        spm.observe(drive_vector, current_tick)
        new_symbols = spm.check_and_forge(current_tick)

        if new_symbols:
            quenching = getattr(entity, "_quenching", None)
            if quenching is not None:
                drive_state = {
                    "loneliness": float(getattr(entity, "loneliness", 0.0)),
                    "fatigue":    float(getattr(entity, "fatigue",    0.0)),
                    "curiosity":  float(getattr(entity, "curiosity",  0.0)),
                    "somatic_tone": float(getattr(entity, "somatic_tone", 0.0)),
                    "approach_drive": float(getattr(entity, "approach_drive", 0.0)),
                    "info_gap":   float(getattr(entity, "info_gap",   0.0)),
                    "unresolved": float(getattr(entity, "unresolved", 0.0)),
                }
                for sym in new_symbols:
                    try:
                        quenching.record(
                            drive_state            = drive_state,
                            expression             = sym,
                            delta_unresolved_before = SYMBOL_QUENCH_EFFICIENCY,
                            delta_unresolved_after  = 0.0,
                            tick                   = current_tick,
                            template_idx           = -3,  # -3 = 内部符号锻造
                        )
                    except Exception:
                        pass

        entity._state_pattern_data = spm.to_dict()

    except Exception:
        pass

    return new_symbols
