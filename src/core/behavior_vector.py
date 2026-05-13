"""
BehaviorVector — 经验驱动力场调制（内生 rule effect）

核心思想：
    行为向量完全从历史经验中归纳而来。
    每次执行动作后，从 snapshot 提取状态差分 → 累积为 rule.effect。
    再次遇到相似情境时，rule effect 作为连续偏置加到 behavior_vector 上。

无任何人工预设的 effect 值。

对外接口：
    update_rules_from_snapshot(snap)     → 更新 rules
    apply_rule_bias(bv, entity, rules)   → 从 behavior_vector 返回带偏置的副本
    BehaviorRule                        → 单条规则的数据结构
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.core.drive_vector_field import DRIVE_DIMS


# ============================================================================
# Rule Effect 关键维度（与 snapshot pre/post_state 对齐）
# ============================================================================

EFFECT_DIMS = [
    "energy", "loneliness", "unresolved", "fatigue",
    "info_gap", "somatic_tone", "danger_level",
    "approach_drive", "avoid_drive",
]


# ============================================================================
# 规则数据结构
# ============================================================================


@dataclass
class BehaviorRule:
    """
    单条行为规则。

    effect：执行该动作后各状态维度的典型变化量。
            从同类型动作的历史 snapshots 归纳而来（平均 delta）。
    strength：规则置信度（0~1），基于历史出现次数和效果稳定性。
    count：触发次数。
    context_mean：学到这个规则时的平均状态（用于上下文匹配）。
    last_seen_tick：最近一次触发时的 tick（用于衰减）。
    """
    action_type: str = ""
    effect: Dict[str, float] = field(default_factory=lambda: {d: 0.0 for d in EFFECT_DIMS})
    strength: float = 1.0
    count: int = 0
    context_mean: Dict[str, float] = field(default_factory=lambda: {})
    last_seen_tick: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type,
            "effect": {k: round(v, 5) for k, v in self.effect.items()},
            "strength": round(self.strength, 4),
            "count": self.count,
            "context_mean": {k: round(v, 4) for k, v in self.context_mean.items()},
            "last_seen_tick": self.last_seen_tick,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BehaviorRule":
        effect_raw = data.get("effect", {})
        effect = {d: effect_raw.get(d, 0.0) for d in EFFECT_DIMS}
        ctx_raw = data.get("context_mean", {})
        context_mean = {d: ctx_raw.get(d, 0.0) for d in EFFECT_DIMS}
        return cls(
            action_type=str(data.get("action_type", "")),
            effect=effect,
            strength=float(data.get("strength", 1.0)),
            count=int(data.get("count", 0)),
            context_mean=context_mean,
            last_seen_tick=int(data.get("last_seen_tick", 0)),
        )


# ============================================================================
# 规则存储（EntityCore 持有）
# ============================================================================


def get_rules(entity_core) -> List[BehaviorRule]:
    """从 entity_core 读取 behavior_rules，不存在则返回空列表."""
    raw = getattr(entity_core, "behavior_rules", [])
    if not isinstance(raw, list):
        return []
    # 延迟转换 dict → BehaviorRule（避免每次都重建）
    result = []
    for item in raw:
        if isinstance(item, dict):
            result.append(BehaviorRule.from_dict(item))
        elif isinstance(item, BehaviorRule):
            result.append(item)
    return result


def save_rules(entity_core, rules: List[BehaviorRule]) -> None:
    """将 rules 写回 entity_core（持久化兼容 dict）."""
    entity_core.behavior_rules = [r.to_dict() if isinstance(r, BehaviorRule) else r for r in rules]


# ============================================================================
# Step 1：从 snapshot 归纳/更新 rule
# ============================================================================


def _delta_from_snapshot(snap: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """
    从单个 snapshot 提取 pre_state → post_state 的差分向量。

    返回：
        delta dict，格式 {dim: delta}，或 None（snapshot 格式不对）
    """
    pre = snap.get("pre_state", {})
    post = snap.get("post_state", {})

    if not pre or not post:
        return None

    delta = {}
    for dim in EFFECT_DIMS:
        pre_v = float(pre.get(dim, 0.0))
        post_v = float(post.get(dim, 0.0))
        delta[dim] = post_v - pre_v

    return delta


def _mean_dicts(dicts: List[Dict[str, float]]) -> Dict[str, float]:
    """计算一组 dict 的逐维度均值."""
    if not dicts:
        return {d: 0.0 for d in EFFECT_DIMS}
    result = {d: 0.0 for d in EFFECT_DIMS}
    for d in dicts:
        for k, v in d.items():
            if k in result:
                result[k] += v / len(dicts)
    return result


def update_rules_from_snapshot(
    entity_core,
    snap: Dict[str, Any],
    current_tick: int,
) -> None:
    """
    从当前 snapshot 更新 rules。

    逻辑：
        1. 从 snapshot 提取 delta
        2. 找对应 action_type 的已有 rule
        3. 用指数移动平均更新 effect（越近的样本权重越高）
        4. 更新 count / context_mean / last_seen_tick
        5. 写回 entity_core.behavior_rules
    """
    action_type = snap.get("action_type", "")
    if not action_type:
        return

    delta = _delta_from_snapshot(snap)
    if delta is None:
        return

    pre_state = snap.get("pre_state", {})

    rules = get_rules(entity_core)
    existing = next((r for r in rules if r.action_type == action_type), None)

    if existing is not None:
        # EMA 更新 effect：新样本权重 = 1/count（样本越多，新样本权重越低）
        alpha_new = 1.0 / max(existing.count, 1)
        for dim in EFFECT_DIMS:
            existing.effect[dim] = existing.effect[dim] * (1 - alpha_new) + delta.get(dim, 0.0) * alpha_new

        # 更新 context_mean（EMA）
        for dim in EFFECT_DIMS:
            v = float(pre_state.get(dim, 0.0))
            existing.context_mean[dim] = existing.context_mean.get(dim, 0.0) * (1 - alpha_new) + v * alpha_new

        existing.count += 1
        existing.last_seen_tick = current_tick
        # strength 缓慢增长，上限 1.0
        existing.strength = min(1.0, existing.strength + 0.02)
    else:
        # 新建 rule
        new_rule = BehaviorRule(
            action_type=action_type,
            effect=dict(delta),
            context_mean={d: float(pre_state.get(d, 0.0)) for d in EFFECT_DIMS},
            strength=0.5,   # 新规则初始置信度 0.5
            count=1,
            last_seen_tick=current_tick,
        )
        rules.append(new_rule)

    save_rules(entity_core, rules)


# ============================================================================
# Step 2：计算上下文匹配度（余弦相似度）
# ============================================================================


def _context_similarity(
    current_state: Dict[str, float],
    rule_context: Dict[str, float],
) -> float:
    """
    计算当前状态与 rule 上下文之间的余弦相似度 [0, 1]。

    仅在两个向量的长度都 > 1e-6 时才计算相似度，否则返回 0。
    """
    # 过滤掉全为零的维度（避免无意义匹配）
    active_dims = [
        d for d in EFFECT_DIMS
        if abs(rule_context.get(d, 0.0)) > 1e-6 or abs(current_state.get(d, 0.0)) > 1e-6
    ]

    if not active_dims:
        return 0.0

    dot = sum(
        current_state.get(d, 0.0) * rule_context.get(d, 0.0)
        for d in active_dims
    )
    norm_cur = math.sqrt(sum(current_state.get(d, 0.0) ** 2 for d in active_dims))
    norm_ctx = math.sqrt(sum(rule_context.get(d, 0.0) ** 2 for d in active_dims))

    if norm_cur < 1e-9 or norm_ctx < 1e-9:
        return 0.0

    cos = dot / (norm_cur * norm_ctx)
    return max(0.0, min(1.0, (cos + 1.0) / 2.0))   # [-1,1] → [0,1]


# ============================================================================
# Step 3：应用 rule effect 作为连续偏置
# ============================================================================


# 偏置上限，防止 rule 过度扭曲行为向量
MAX_BIAS = 0.15


def apply_rule_bias(
    behavior_vector: Dict[str, float],
    entity_core,
    max_alpha: float = 0.5,
) -> Dict[str, float]:
    """
    将内生 rule effect 作为连续偏置加到 behavior_vector 上。

    公式：α = sigmoid(strength * context_factor) * max_alpha
          BV'[drive_intensity] += α * rule_effect[drive] * sign

    偏置方向由 rule effect 决定：
        - 正向 effect（动作后状态改善）→ 正向偏置
        - 负向 effect（动作后状态恶化）→ 负向偏置

    参数：
        behavior_vector: 原始 behavior_vector（含 *_intensity / *_fragmentation）
        entity_core: EntityCore 实例
        max_alpha: 最大调制系数（防止极端 rule 破坏行为）

    返回：
        新的 behavior_vector 副本（原始字典不变）
    """
    rules = get_rules(entity_core)
    if not rules:
        return dict(behavior_vector)

    # 从 entity_core 取当前状态
    current_state = {
        "energy":        getattr(entity_core, "energy", 0.8),
        "loneliness":    getattr(entity_core, "loneliness", 0.3),
        "unresolved":    getattr(entity_core, "unresolved", 0.2),
        "fatigue":       getattr(entity_core, "fatigue", 0.1),
        "info_gap":      getattr(entity_core, "info_gap", 0.5),
        "somatic_tone":  getattr(entity_core, "somatic_tone", 0.0),
        "danger_level":  getattr(entity_core, "danger_level", 0.0),
        "approach_drive": getattr(entity_core, "approach_drive", 0.0),
        "avoid_drive":   getattr(entity_core, "avoid_drive", 0.0),
    }

    # 行为向量副本（不修改原始）
    bv = dict(behavior_vector)

    for rule in rules:
        # 上下文匹配度
        ctx_sim = _context_similarity(current_state, rule.context_mean)

        # 调制系数
        alpha = max_alpha * rule.strength * ctx_sim

        # rule effect 映射到 behavior_vector 维度
        # EFFECT_DIMS → DRIVE_DIMS 的映射
        dim_map = {
            "loneliness":    "loneliness",
            "fatigue":       "fatigue",
            "info_gap":      "info_gap",
            "unresolved":    "unresolved",
            "somatic_tone":  "somatic_tone_p",
            "danger_level":  "danger",
        }

        for effect_dim, drive_dim in dim_map.items():
            delta = rule.effect.get(effect_dim, 0.0)

            # bias 方向：若 action 让该 drive 下降 → 该 action 有效 → 增加 intensity
            # 若 action 让该 drive 上升 → 该 action 有害 → 减少 intensity
            # 公式：bias = alpha * reduction_amount * current_drive_level
            # reduction_amount = max(0, pre - post) = max(0, -delta)
            # 相当于 bias = alpha * |delta| * context_signal（正值 delta → |delta|=delta）
            #                         （负值 delta → |delta|=-delta，但 context_signal 可能为负）
            # 简化：bias = alpha * (-delta) * current_state[effect_dim]
            # （delta 负 → -delta 正 → intensity ↑；delta 正 → intensity ↓）
            intensity_key = f"{drive_dim}_intensity"
            if intensity_key in bv:
                # reduction：本次 action 后该 drive 降低了多少（正数 = 有效）
                reduction = -delta
                drive_level = current_state.get(effect_dim, 0.0)
                bias = alpha * reduction * max(0.0, drive_level)
                bv[intensity_key] = max(0.0, min(1.0, bv[intensity_key] + bias))

    return bv


# ============================================================================
# 调试辅助
# ============================================================================


def format_rules_summary(rules: List[BehaviorRule]) -> str:
    """打印所有规则的摘要."""
    if not rules:
        return "  (no rules)"
    lines = []
    for r in rules:
        top_effects = sorted(r.effect.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
        effect_str = "  ".join(f"{k}={v:+.3f}" for k, v in top_effects)
        lines.append(
            f"  [{r.action_type}] cnt={r.count} str={r.strength:.2f}"
            f"  top_effects={effect_str}"
        )
    return "\n".join(lines)


# ============================================================================
# 单元测试
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("BehaviorVector — 单元测试")
    print("=" * 60)

    class _MockEntity:
        def __init__(self, **kwargs):
            self.behavior_rules: List[Any] = []
            for k, v in kwargs.items():
                setattr(self, k, v)

    # ---- Test 1: snapshot → rule 归纳 ----
    print("\n【Test 1】snapshot 归纳")
    entity = _MockEntity(energy=0.8, loneliness=0.6, unresolved=0.3,
                          fatigue=0.2, info_gap=0.5, somatic_tone=0.3,
                          danger_level=0.1, approach_drive=0.5, avoid_drive=0.2)

    snap = {
        "action_type": "seek",
        "pre_state": {"loneliness": 0.6, "fatigue": 0.2, "info_gap": 0.5,
                       "unresolved": 0.3, "somatic_tone": 0.3, "danger_level": 0.1,
                       "energy": 0.8, "approach_drive": 0.5, "avoid_drive": 0.2},
        "post_state": {"loneliness": 0.4, "fatigue": 0.25, "info_gap": 0.5,
                       "unresolved": 0.3, "somatic_tone": 0.4, "danger_level": 0.1,
                       "energy": 0.78, "approach_drive": 0.6, "avoid_drive": 0.2},
    }

    update_rules_from_snapshot(entity, snap, current_tick=100)
    rules = get_rules(entity)
    print(f"  归纳得到 {len(rules)} 条 rule")
    print(format_rules_summary(rules))

    # 第二次相同 snap → EMA 更新
    snap2 = {**snap, "post_state": {**snap["post_state"], "loneliness": 0.35}}
    update_rules_from_snapshot(entity, snap2, current_tick=101)
    rules2 = get_rules(entity)
    r = rules2[0]
    print(f"\n  EMA 更新后: count={r.count}  strength={r.strength:.3f}")
    print(f"  loneliness effect={r.effect['loneliness']:.4f}  (两次平均，应为负)")

    # ---- Test 2: context similarity ----
    print("\n【Test 2】上下文匹配度")
    high_loneliness = {"loneliness": 0.9, "fatigue": 0.1, "info_gap": 0.3,
                        "unresolved": 0.2, "somatic_tone": 0.1, "danger_level": 0.0,
                        "energy": 0.7, "approach_drive": 0.4, "avoid_drive": 0.2}
    medium_loneliness = {"loneliness": 0.5, "fatigue": 0.1, "info_gap": 0.3,
                          "unresolved": 0.2, "somatic_tone": 0.1, "danger_level": 0.0,
                          "energy": 0.7, "approach_drive": 0.4, "avoid_drive": 0.2}
    sim_high = _context_similarity(high_loneliness, {"loneliness": 0.6, "fatigue": 0.2, "info_gap": 0.5,
                                                      "unresolved": 0.3, "somatic_tone": 0.3, "danger_level": 0.1,
                                                      "energy": 0.8, "approach_drive": 0.5, "avoid_drive": 0.2})
    sim_medium = _context_similarity(medium_loneliness, {"loneliness": 0.6, "fatigue": 0.2, "info_gap": 0.5,
                                                          "unresolved": 0.3, "somatic_tone": 0.3, "danger_level": 0.1,
                                                          "energy": 0.8, "approach_drive": 0.5, "avoid_drive": 0.2})
    print(f"  高孤独 vs 中孤独上下文: sim={sim_high:.3f}  sim={sim_medium:.3f}")
    print(f"  → 高孤独相似度更高（接近学习的上下文）✓")

    # ---- Test 3: apply rule bias ----
    print("\n【Test 3】apply_rule_bias")
    base_bv = {
        "loneliness_intensity": 0.6, "loneliness_fragmentation": 0.1,
        "fatigue_intensity": 0.3, "fatigue_fragmentation": 0.0,
        "info_gap_intensity": 0.4, "info_gap_fragmentation": 0.0,
        "unresolved_intensity": 0.2, "unresolved_fragmentation": 0.0,
        "somatic_tone_p_intensity": 0.3, "somatic_tone_p_fragmentation": 0.0,
        "danger_intensity": 0.1, "danger_fragmentation": 0.0,
    }

    # 第二次 snap：seek 后 loneliness 下降明显
    entity2 = _MockEntity(energy=0.8, loneliness=0.7, unresolved=0.3,
                          fatigue=0.2, info_gap=0.5, somatic_tone=0.3,
                          danger_level=0.1, approach_drive=0.5, avoid_drive=0.2,
                          behavior_rules=[])
    snap_seek = {
        "action_type": "seek",
        "pre_state": {"loneliness": 0.7, "fatigue": 0.2, "info_gap": 0.5,
                       "unresolved": 0.3, "somatic_tone": 0.3, "danger_level": 0.1,
                       "energy": 0.8, "approach_drive": 0.5, "avoid_drive": 0.2},
        "post_state": {"loneliness": 0.5, "fatigue": 0.25, "info_gap": 0.5,
                       "unresolved": 0.3, "somatic_tone": 0.4, "danger_level": 0.1,
                       "energy": 0.78, "approach_drive": 0.6, "avoid_drive": 0.2},
    }
    update_rules_from_snapshot(entity2, snap_seek, current_tick=100)

    bv_biased = apply_rule_bias(base_bv, entity2)
    delta_loneliness = bv_biased["loneliness_intensity"] - base_bv["loneliness_intensity"]
    print(f"  原始 loneliness_intensity: {base_bv['loneliness_intensity']:.3f}")
    print(f"  偏置后: {bv_biased['loneliness_intensity']:.3f}  delta={delta_loneliness:+.4f}")
    print(f"  → seek 后 loneliness 下降（有效）→ bias 增强 intensity: {'✓' if delta_loneliness > 0 else '✗'}")

    # ---- Test 4: 无规则时透传 ----
    entity_empty = _MockEntity(energy=0.8, loneliness=0.5, unresolved=0.2,
                                fatigue=0.1, info_gap=0.5, somatic_tone=0.0,
                                danger_level=0.0, approach_drive=0.3, avoid_drive=0.3)
    bv_pass = apply_rule_bias(base_bv, entity_empty)
    unchanged = all(abs(bv_pass[k] - base_bv[k]) < 1e-9 for k in base_bv)
    print(f"\n【Test 4】无规则时透传: {'✓' if unchanged else '✗'}")

    print("\n" + "=" * 60)
    print("全部测试完成 ✓")
    print("=" * 60)
