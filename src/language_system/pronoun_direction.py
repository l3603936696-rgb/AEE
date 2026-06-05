"""pronoun_direction — 输入文本主语方向识别

职责（一句话）：检测输入文本提及的是实体自身哪个状态维度，并区分主语方向
（说话者在说"你"还是"我"），产出连续权重供 parse_input 使用。
"""
from typing import Dict

# ─── 状态维度关键词映射（输入在提及/询问实体的哪个内部维度）─────────────────────
# 键：关键词字符串；值：对应的 entity state 维度名
_STATE_DIMENSION_KEYWORDS: Dict[str, str] = {
    # 躯体
    "热":      "somatic_tone",  "烫":    "somatic_tone",  "暖":   "somatic_tone",
    "燥热":    "somatic_tone",  "燃":    "somatic_tone",
    # 疲惫
    "累":      "fatigue",       "疲":    "fatigue",       "乏":   "fatigue",
    "沉":      "fatigue",       "撑不住": "fatigue",
    # 疼痛
    "疼":      "pain",          "痛":    "pain",          "刺":   "pain",
    # 恐惧
    "怕":      "fear",          "恐":    "fear",          "害怕": "fear",
    # 压力
    "烦":      "stress",        "绷":    "stress",        "焦":   "stress",
    # 孤独
    "孤独":    "loneliness",    "寂寞":  "loneliness",    "孤":   "loneliness",
    # 无聊
    "无聊":    "boredom",
    # 好奇/信息
    "好奇":    "info_gap",      "想知道": "info_gap",
    # 能量/饥渴
    "饿":      "energy",        "渴":    "energy",
}

# ─── 主语权重常量 ──────────────────────────────────────────────────────────────
# "你+状态词"：在说她自己，偏置最强
SELF_REF_WEIGHT  = 0.40
# 无明确主语：模糊，中等偏置
AMBIG_REF_WEIGHT = 0.25
# "我+状态词"：说话人自己，只留共情残影
OTHER_REF_WEIGHT = 0.08
# 向后兼容旧调用方（pipeline_runner 用）
STATE_REF_WEIGHT = AMBIG_REF_WEIGHT


def match_state_reference(text: str) -> Dict[str, object]:
    """
    检测输入文本在提及/询问哪些内部状态维度，并识别主语方向。

    主语判断连续加权，无 if/else 路由：
        has_self/has_other 是 0.0 或 1.0 的端点，
        pronoun_weight 通过线性组合在 [0.05, 1.0] 范围内平滑取值。

    返回：
        {
            "dim_weights":     {dim: base_bias},      # 各维度偏置幅度
            "pronoun_weights": {dim: float [0, 1]},   # 各维度"关于她自己"的程度
        }
    """
    has_self  = float("你" in text)
    has_other = float("我" in text)

    is_self_only  = has_self  * (1.0 - has_other)
    is_other_only = has_other * (1.0 - has_self)
    is_ambig      = 1.0 - is_self_only - is_other_only

    # "关于她自己"的程度：self_only→1.0, ambig→0.40, other_only→0.05
    pronoun_self_degree = is_self_only * 1.0 + is_ambig * 0.40 + is_other_only * 0.05

    dim_weights:     Dict[str, float] = {}
    pronoun_weights: Dict[str, float] = {}

    for kw, dim in _STATE_DIMENSION_KEYWORDS.items():
        hit = float(kw in text)
        if hit == 0.0:
            continue
        bias = (
            is_self_only  * SELF_REF_WEIGHT
            + is_other_only * OTHER_REF_WEIGHT
            + is_ambig      * AMBIG_REF_WEIGHT
        ) * hit
        dim_weights[dim]     = dim_weights.get(dim, 0.0) + bias
        pronoun_weights[dim] = min(1.0, pronoun_weights.get(dim, 0.0) + pronoun_self_degree * hit)

    return {
        "dim_weights":     dim_weights,
        "pronoun_weights": pronoun_weights,
    }
