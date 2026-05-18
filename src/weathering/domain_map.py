"""Domain → 参数路径映射。确定每个 domain 可以影响哪些参数。"""

from __future__ import annotations
from typing import Dict, FrozenSet


DOMAIN_PARAM_SCOPE: Dict[str, FrozenSet[str]] = {
    "social": frozenset({
        "personality.trust_threshold",
        "personality.rejection_sensitivity",
        "personality.introverted_bias",
        "personality.social_risk_weight",
        "personality.extroverted_bias",
        "conversion.approach_synthesis.social",
        "conversion.failure_metabolite.approach_suppress",
        "conversion.failure_metabolite.avoid_increase",
    }),
    "information": frozenset({
        "web_search.info_hunger_threshold",
        "personality.novelty_reward",
        "conversion.approach_synthesis.explore",
    }),
    "survival": frozenset({
        "decision.survival_override_threshold",
        "personality.recovery_rate",
    }),
    "expression": frozenset({
        "conversion.quench_feedback.quench_rate",
    }),
    "emotion": frozenset({
        "conversion.emotion_drive_mod.approach.joy",
        "conversion.emotion_drive_mod.approach.anger",
        "conversion.emotion_drive_mod.avoid.fear",
        "conversion.emotion_drive_mod.avoid.disgust",
        "conversion.conflict_to_unresolved.conflict_rate",
    }),
}


def get_allowed_params(domain: str) -> FrozenSet[str] | None:
    """
    返回该 domain 允许影响的参数路径集合。
    "general" 返回 None（表示不限制）。
    未知 domain 也返回 None。
    """
    if domain == "general":
        return None
    return DOMAIN_PARAM_SCOPE.get(domain)
