"""
decision_comparator.py — V4 动作粒度裁决引擎（完整版）

职责：
    接收信号池，对每个候选动作进行非线性成本收益核算，返回最优动作。

V4 架构（GLM5 致命伤修复）：

1. 动作池从 param_snapshot.mechanisms.action_pool 读取，裁决层只读不写
2. 信号降维映射到四槽位：reward_gain / pressure_relief / cost / residue_cost
3. 逐候选动作打分：score = Σ weight(action, slot) × slot_value
4. Comfort 基线：comfort_baseline = 1/(1+relief_debt×k)，若所有动作 < baseline → comfort 胜出
5. 生理底线柔化：→ comfort_baseline 加权增强，不短路
6. Tie-break：得分差 < threshold 时加 epsilon 随机扰动
7. Target 加权选择：strength × module_weight，选最高分
8. Top-3 贡献者：记录在 _debug_meta.top_contributors

禁止将 AVOID 信号映射到正向槽位（reward_gain / pressure_relief）。
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import math
import random


# ============================================================================
# 类型别名
# ============================================================================

SlotName = str          # "reward_gain" | "pressure_relief" | "cost" | "residue_cost"
ActionPool = List[str]


# ============================================================================
# 默认参数（可被 param_snapshot 覆盖）
# ============================================================================

DEFAULT_PARAMS = {
    # Comfort 基线参数
    "comfort_relief_debt_k": 2.0,
    "comfort_baseline_weight": 0.3,

    # Tie-break
    "tie_break_threshold": 0.05,
    "tie_break_epsilon": 0.01,

    # 动作权重默认（action -> slot -> multiplier）
    # r=reward_gain, p=pressure_relief, c=cost, d=residue_cost
    "default_action_weights": {
        "reply_user":    {"reward_gain": 1.0, "pressure_relief": 0.8, "cost": 0.3, "residue_cost": 0.2},
        "rest":          {"reward_gain": 0.1, "pressure_relief": 1.0, "cost": 0.0, "residue_cost": 0.0},
        "explore_info":  {"reward_gain": 1.0, "pressure_relief": 0.5, "cost": 0.5, "residue_cost": 0.3},
        "change_topic":  {"reward_gain": 0.2, "pressure_relief": 0.9, "cost": 0.4, "residue_cost": 0.2},
    },

    # 四个槽的默认权重（用于加权求和）
    "slot_weights": {
        "reward_gain": 1.0,
        "pressure_relief": 1.0,
        "cost": -1.0,
        "residue_cost": -1.0,
    },
}


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ScoredAction:
    """单个候选动作的评分结果"""
    action: str
    slot_raw: Dict[SlotName, float]        # 四槽原始强度
    slot_weighted: Dict[SlotName, float]   # 四槽加权得分
    total_score: float                     # Σ weighted
    primary_slot: SlotName
    primary_signal_source: str
    top_contributors: List[dict]           # [{"source", "slot", "contribution", "strength"}]
    is_comfort_fallback: bool = False     # 是否由 comfort 基线胜出


@dataclass
class DecisionResult:
    """最终裁决结果"""
    action: str
    target: str
    priority: float
    primary_slot: SlotName
    slots: Dict[SlotName, float]          # 加权后槽位得分
    top_contributors: List[dict]          # Top 3 贡献者（调试用）
    payload: dict
    debug_meta: dict                      # 包含 top_contributors 等调试信息


# ============================================================================
# 主比较器
# ============================================================================

class DecisionComparator:
    """
    V4 动作粒度裁决引擎
    """

    def __init__(self, defaults: Optional[dict] = None):
        self.defaults: dict = {**DEFAULT_PARAMS, **(defaults or {})}

    # ------------------------------------------------------------------ #
    # 公开接口
    # ------------------------------------------------------------------ #

    def compare(
        self,
        signal_pool,              # List[DriveSignal]
        param_snapshot: dict,      # 从 param_snapshot 读取配置
        module_weights: Optional[dict] = None,  # 模块权重（用于 target 选择）
    ) -> ScoredAction:
        """
        主入口：对每个候选动作打分，返回最优动作。
        """
        ps = param_snapshot or {}
        defaults = self.defaults

        # ---- Step A: 读取配置（优先级：param_snapshot > defaults）----
        comfort_relief_debt_k = float(
            ps.get("comfort_relief_debt_k", defaults["comfort_relief_debt_k"])
        )
        comfort_baseline_weight = float(
            ps.get("comfort_baseline_weight", defaults["comfort_baseline_weight"])
        )
        tie_threshold = float(
            ps.get("tie_break_threshold", defaults["tie_break_threshold"])
        )
        tie_epsilon = float(
            ps.get("tie_break_epsilon", defaults["tie_break_epsilon"])
        )
        action_weights_map = ps.get("action_weights", defaults["default_action_weights"])
        slot_weights_map = ps.get("slot_weights", defaults["slot_weights"])

        # ---- Step B: 信号降维到四槽 ----
        slot_raw = self._build_slot_vector(signal_pool)

        # ---- Step C: Comfort 基线 ----
        comfort_baseline = self._compute_comfort_baseline(
            slot_raw, comfort_relief_debt_k, comfort_baseline_weight
        )

        # ---- Step D: 读取动作池 ----
        mechanisms = ps.get("mechanisms", {}) or {}
        action_pool: ActionPool = mechanisms.get("action_pool")
        if not (action_pool and isinstance(action_pool, list) and len(action_pool) > 0):
            action_pool = list(self.defaults["default_action_weights"].keys())

        # ---- Step E: 逐候选动作打分 ----
        scored = self._score_all_actions(
            action_pool, slot_raw, slot_weights_map, action_weights_map,
            signal_pool, module_weights or {}
        )

        # ---- Step F: Tie-break ----
        if len(scored) > 1:
            scored = self._apply_tie_break(scored, tie_threshold, tie_epsilon)

        # ---- Step G: 选择最优 ----
        # Comfort 基线对比：若所有动作得分 < baseline，胜出者为 comfort
        all_below_baseline = all(a.total_score < comfort_baseline for a in scored)
        if all_below_baseline:
            best = self._make_comfort_fallback(comfort_baseline, slot_raw, slot_weights_map)
        else:
            scored_above = [a for a in scored if a.total_score >= comfort_baseline]
            if scored_above:
                best = max(scored_above, key=lambda a: a.total_score)
            else:
                best = max(scored, key=lambda a: a.total_score)

        return best

    # ------------------------------------------------------------------ #
    # 内部步骤
    # ------------------------------------------------------------------ #

    def _build_slot_vector(self, signal_pool) -> Dict[SlotName, float]:
        """
        映射规则：
            seek + pressure_flag=True  → pressure_relief 槽
            seek + pressure_flag=False → reward_gain     槽
            avoid + residue_cost_flag=True  → residue_cost 槽
            avoid + residue_cost_flag=False → cost        槽
            comfort                      → cost            槽
        """
        slots: Dict[SlotName, float] = {
            "reward_gain": 0.0,
            "pressure_relief": 0.0,
            "cost": 0.0,
            "residue_cost": 0.0,
        }
        for sig in signal_pool:
            slot_name, strength = sig.to_slot()
            slots[slot_name] += strength
        return slots

    def _compute_comfort_baseline(
        self,
        slot_raw: Dict[SlotName, float],
        relief_debt_k: float,
        baseline_weight: float,
    ) -> float:
        """
        Comfort 基线：
            comfort_baseline = 1.0 / (1.0 + relief_debt × k) × baseline_weight

        relief_debt = pressure_relief + cost（越需要舒缓 = relief_debt 越高 → baseline 越低）
        """
        relief_debt = slot_raw.get("pressure_relief", 0.0) + slot_raw.get("cost", 0.0)
        return (1.0 / (1.0 + relief_debt * relief_debt_k)) * baseline_weight

    def _score_all_actions(
        self,
        action_pool: ActionPool,
        slot_raw: Dict[SlotName, float],
        slot_weights: Dict[str, float],
        action_weights_map: Dict[str, Dict[str, float]],
        signal_pool,
        module_weights: dict,
    ) -> List[ScoredAction]:
        """
        逐候选动作打分：
            score(action) = Σ weight(action, slot) × slot_raw[slot] × slot_weight[slot]

        其中：
            weight(action, slot) 来自 action_weights_map（若无，取 1.0）
            slot_weight[slot]     来自 slot_weights（reward_gain/pressure_relief=+1, cost/residue_cost=-1）
        """
        scored: List[ScoredAction] = []

        for action in action_pool:
            aw = action_weights_map.get(action, {})  # 该动作的四槽权重
            sw = slot_weights  # 全局槽权重

            weighted: Dict[SlotName, float] = {}
            total = 0.0
            for slot in ("reward_gain", "pressure_relief", "cost", "residue_cost"):
                action_mult = float(aw.get(slot, 1.0))
                slot_w = float(sw.get(slot, 1.0))
                raw = slot_raw.get(slot, 0.0)
                w = action_mult * raw * slot_w
                weighted[slot] = w
                total += w

            # primary_slot = 原始强度最大的槽
            primary_slot = max(slot_raw, key=lambda k: slot_raw[k])

            # payload 溯源：primary_slot 中加权强度最大的信号
            primary_source = self._find_best_source(primary_slot, signal_pool, module_weights)

            # Top-3 贡献者
            top3 = self._compute_top_contributors(
                weighted, slot_raw, signal_pool, module_weights
            )

            scored.append(ScoredAction(
                action=action,
                slot_raw=slot_raw.copy(),
                slot_weighted=weighted,
                total_score=total,
                primary_slot=primary_slot,
                primary_signal_source=primary_source,
                top_contributors=top3,
            ))

        return scored

    def _find_best_source(
        self,
        primary_slot: SlotName,
        signal_pool,
        module_weights: dict,
    ) -> str:
        """在信号池中找 primary_slot 中加权强度最大的信号源"""
        candidates = []
        for sig in signal_pool:
            slot_name, raw_strength = sig.to_slot()
            if slot_name == primary_slot:
                w = float(module_weights.get(sig.source, 1.0))
                candidates.append((sig.source, raw_strength * w))
        if candidates:
            return max(candidates, key=lambda x: x[1])[0]
        return "unknown"

    def _compute_top_contributors(
        self,
        weighted: Dict[SlotName, float],
        slot_raw: Dict[SlotName, float],
        signal_pool,
        module_weights: dict,
    ) -> List[dict]:
        """
        按 |weighted| 降序取 Top 3 贡献者。
        每个贡献者需要：slot / raw_strength / weighted_score / signal_source。
        """
        contributions = []
        for slot, wscore in weighted.items():
            raw = slot_raw.get(slot, 0.0)
            # 从信号池中找到该 slot 中最强的信号
            best_sig = None
            best_sig_score = -1.0
            for sig in signal_pool:
                sn, rs = sig.to_slot()
                if sn == slot:
                    ws = float(module_weights.get(sig.source, 1.0))
                    scored = rs * ws
                    if scored > best_sig_score:
                        best_sig_score = scored
                        best_sig = sig
            sig_src = best_sig.source if best_sig else f"_slot:{slot}"
            contributions.append({
                "slot": slot,
                "raw_strength": raw,
                "weighted_score": wscore,
                "abs_contribution": abs(wscore),
                "signal_source": sig_src,
            })
        contributions.sort(key=lambda x: x["abs_contribution"], reverse=True)
        return contributions[:3]

    def _apply_tie_break(
        self,
        scored: List[ScoredAction],
        threshold: float,
        epsilon: float,
    ) -> List[ScoredAction]:
        """得分接近时加随机扰动"""
        if len(scored) < 2 or threshold <= 0:
            return scored
        sorted_by_score = sorted(scored, key=lambda a: a.total_score, reverse=True)
        top, second = sorted_by_score[0], sorted_by_score[1]
        gap = top.total_score - second.total_score
        if gap < threshold:
            perturbation = random.uniform(-epsilon, epsilon)
            # 只在有区分度时才加扰动（避免全部变 0）
            for a in scored:
                a.total_score += perturbation
        return scored

    def _make_comfort_fallback(
        self,
        comfort_baseline: float,
        slot_raw: Dict[SlotName, float],
        slot_weights: Dict[str, float],
    ) -> ScoredAction:
        """所有候选动作得分 < comfort_baseline 时，comfort 胜出"""
        # comfort 在 cost 槽最强，reward_gain 最弱
        weighted = {
            "reward_gain": slot_raw.get("reward_gain", 0.0) * slot_weights.get("reward_gain", 1.0) * 0.1,
            "pressure_relief": slot_raw.get("pressure_relief", 0.0) * slot_weights.get("pressure_relief", 1.0) * 1.0,
            "cost": slot_raw.get("cost", 0.0) * slot_weights.get("cost", 1.0),
            "residue_cost": slot_raw.get("residue_cost", 0.0) * slot_weights.get("residue_cost", 1.0),
        }
        total = sum(weighted.values())
        return ScoredAction(
            action="rest",
            slot_raw=slot_raw.copy(),
            slot_weighted=weighted,
            total_score=comfort_baseline,
            primary_slot="cost",
            primary_signal_source="comfort_baseline",
            top_contributors=[
                {"slot": "pressure_relief", "raw_strength": slot_raw.get("pressure_relief", 0.0),
                 "weighted_score": weighted["pressure_relief"], "abs_contribution": abs(weighted["pressure_relief"]),
                 "signal_source": "comfort_baseline"},
            ],
            is_comfort_fallback=True,
        )


# ============================================================================
# 便捷入口
# ============================================================================

def compare_signals(
    signal_pool,
    param_snapshot: Optional[dict] = None,
    module_weights: Optional[dict] = None,
) -> ScoredAction:
    """便捷入口"""
    comp = DecisionComparator()
    return comp.compare(signal_pool, param_snapshot or {}, module_weights or {})
