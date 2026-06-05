"""speaker_model — 说话者信任权重

职责（一句话）：根据刻板印象树节点置信度和互动历史，
计算说话者信任权重，用于调制 parse_input() 驱动力变化幅度。

信任权重 ∈ [MIN_TRUST, MAX_TRUST]：
    - 完全陌生的说话者     → 0.40（陌生人基线）
    - 有节点但交互较少     → 0.50–0.65
    - bcyq（≥30 次交互） → ~0.80
    - 绝对信任上限         → 0.92（保留不确定性余量）

全连续计算：
    trust = STRANGER_TRUST
          + sigmoid(节点置信度) × CONFIDENCE_MAX_BONUS
          + (1 − exp(−交互次数/饱和点)) × INTERACTION_MAX_BONUS

无 if-else 路由；节点缺失时平滑退回陌生人基线。
"""
import math
from typing import Any

# ── 超参数 ────────────────────────────────────────────────────────────────────
# 陌生人基线信任（无节点、无历史时的默认值）
STRANGER_TRUST: float = 0.40

# 节点置信度贡献的最大加成（置信度=1.0 时可叠加此量）
CONFIDENCE_MAX_BONUS: float = 0.35

# 节点置信度 sigmoid 的中心点与斜率
# center=0.5：置信度=0.5 时加成为 CONFIDENCE_MAX_BONUS / 2
# slope=5.0：上升较陡，置信度 0.5→0.7 已覆盖大部分范围
CONFIDENCE_SIGMOID_CENTER: float = 0.50
CONFIDENCE_SIGMOID_SLOPE: float = 5.0

# 互动次数贡献的最大加成
INTERACTION_MAX_BONUS: float = 0.20

# 互动次数饱和点（超过此值后加成接近 INTERACTION_MAX_BONUS）
INTERACTION_SATURATION: float = 30.0

# 信任权重下限（最不信任的说话者也保留最低影响力）
MIN_TRUST: float = 0.15

# 信任权重上限（永远保留不确定性余量）
MAX_TRUST: float = 0.92


# ── 公开接口 ──────────────────────────────────────────────────────────────────

def get_trust_weight(entity: Any, speaker_id: str) -> float:
    """
    计算说话者信任权重 ∈ [MIN_TRUST, MAX_TRUST]。

    参数：
        entity    : EntityState 实例（只读）
        speaker_id: 说话者 ID（如 "bcyq"、"external"）

    返回：
        信任权重 float ∈ [MIN_TRUST, MAX_TRUST]

    示例（bcyq，节点 confidence=0.6，45 次交互）：
        confidence_bonus = 0.35 × sigmoid((0.6−0.5) × 5) × has_node = 0.35 × 0.622 × 1 ≈ 0.218
        interaction_bonus = 0.20 × (1−exp(−45/30))                  = 0.20 × 0.777     ≈ 0.155
        trust = 0.40 + 0.218 + 0.155 ≈ 0.773

    无节点时 has_node=0.0，confidence_bonus=0，退回：
        trust = 0.40 + 0 + interaction_bonus
    """
    node_conf, has_node = _node_confidence(entity, speaker_id)
    n_interact = _interaction_count(entity, speaker_id)

    # has_node 作为门控：无节点时置信度加成为 0（保持陌生人基线）
    confidence_bonus = CONFIDENCE_MAX_BONUS * _sigmoid(
        (node_conf - CONFIDENCE_SIGMOID_CENTER) * CONFIDENCE_SIGMOID_SLOPE
    ) * has_node

    interaction_bonus = INTERACTION_MAX_BONUS * (
        1.0 - math.exp(-n_interact / max(1.0, INTERACTION_SATURATION))
    )

    trust = STRANGER_TRUST + confidence_bonus + interaction_bonus
    return max(MIN_TRUST, min(MAX_TRUST, trust))


# ── 内部工具 ──────────────────────────────────────────────────────────────────

def _sigmoid(x: float) -> float:
    """数值稳定的 sigmoid 函数，防止 overflow。"""
    x = max(-30.0, min(30.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def _node_confidence(entity: Any, speaker_id: str) -> tuple:
    """
    从刻板印象树 _individuals 获取说话者节点置信度和节点存在标志。

    返回：(confidence: float, has_node: float)
        has_node ∈ {0.0, 1.0} — 无节点时为 0.0，供调用方用作门控乘子。
    """
    try:
        trees = getattr(entity, "_stereotype_trees", None)
        if not trees:
            return (0.0, 0.0)
        tree = trees.get("default")
        if tree is None:
            return (0.0, 0.0)
        node = getattr(tree, "_individuals", {}).get(speaker_id)
        has_node = float(node is not None)
        conf = float(getattr(node, "confidence", 0.0)) * has_node
        return (conf, has_node)
    except Exception:
        return (0.0, 0.0)


def _interaction_count(entity: Any, speaker_id: str) -> float:
    """
    从 _source_profiles 读取互动次数。
    优先查精确 speaker_id，找不到再查 "external"（向后兼容旧数据）。
    """
    try:
        profiles = getattr(entity, "_source_profiles", {})
        profile = profiles.get(speaker_id) or profiles.get("external") or {}
        return float(profile.get("interaction_count", 0))
    except Exception:
        return 0.0
