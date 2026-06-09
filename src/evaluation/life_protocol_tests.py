"""
Life Protocol Tests — Level 1/2/3 Test Classes.

提取自 life_protocol.py。
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from .life_protocol_schema import (
    TH_ENTROPY_MIN, TH_ENTROPY_MAX,
    TH_COHERENCE_MIN, TH_COHERENCE_MAX,
    TH_STD_MIN, TH_ATTRACTOR_RECOVERY, TH_SHIFT_RATE_MAX,
    TickMetrics,
    _bias_variance, _all_close_to_zero, _single_dominant,
    _cluster_count, _cosine_similarity,
)


class Level1StabilityTests:
    def __init__(self, metrics: List[TickMetrics]):
        self.metrics = metrics

    def _vals(self, key: str) -> List[float]:
        return [getattr(m, key, 0.0) for m in self.metrics if m.tick > 0]

    def test_1_1_entropy_coherence_bounds(self) -> Dict[str, Any]:
        ent_vals = self._vals("entropy")
        coh_vals = self._vals("action_coherence")
        passed = True
        details = {}
        if ent_vals:
            avg_ent = sum(ent_vals) / len(ent_vals)
            passed_ent = TH_ENTROPY_MIN < avg_ent < TH_ENTROPY_MAX
            details["entropy_avg"] = round(avg_ent, 4)
            details["entropy_in_range"] = passed_ent
            passed = passed and passed_ent
        else:
            details["entropy_avg"] = None
            passed = False
        if coh_vals:
            avg_coh = sum(coh_vals) / len(coh_vals)
            passed_coh = TH_COHERENCE_MIN < avg_coh < TH_COHERENCE_MAX
            details["coherence_avg"] = round(avg_coh, 4)
            details["coherence_in_range"] = passed_coh
            passed = passed and passed_coh
        else:
            details["coherence_avg"] = None
            passed = False
        return {"name": "1.1_entropy_coherence_bounds", "passed": passed, "details": details}

    def test_1_2_state_volatility(self) -> Dict[str, Any]:
        loneliness_vals = self._vals("loneliness")
        boredom_vals = self._vals("boredom")
        details = {}
        passed = True
        for name, vals in [("loneliness", loneliness_vals), ("boredom", boredom_vals)]:
            if len(vals) < 5:
                details[f"{name}_std"] = None
                passed = False
                continue
            mean = sum(vals) / len(vals)
            std = __import__("math").sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
            details[f"{name}_std"] = round(std, 4)
            details[f"{name}_mean"] = round(mean, 4)
            dirs = [1 if vals[i+1] > vals[i] else -1 for i in range(len(vals)-1)]
            same_dir = all(d == dirs[0] for d in dirs)
            details[f"{name}_monotonic"] = same_dir
            if same_dir and std < TH_STD_MIN:
                passed = False
        return {"name": "1.2_state_volatility", "passed": passed, "details": details}

    def run(self) -> Dict[str, Any]:
        r1 = self.test_1_1_entropy_coherence_bounds()
        r2 = self.test_1_2_state_volatility()
        return {"level": 1, "tests": [r1, r2], "pass_all": all(t["passed"] for t in [r1, r2])}


class Level2StructureTests:
    def __init__(self, metrics: List[TickMetrics]):
        self.metrics = metrics

    def _at_tick(self, t: int) -> Optional[TickMetrics]:
        for m in self.metrics:
            if m.tick == t:
                return m
        return None

    def test_2_1_bias_structure_at_tick(self, check_tick: int = 500) -> Dict[str, Any]:
        m = self._at_tick(check_tick)
        if m is None:
            m = self.metrics[-1] if self.metrics else None
            if m is None:
                return {"name": "2.1_bias_structure", "passed": False, "details": {"reason": "no metrics"}}
        bias = m.long_term_bias
        details = {
            "bias": bias,
            "bias_variance": round(_bias_variance(bias), 5),
            "all_close_to_zero": _all_close_to_zero(bias),
            "single_dominant": _single_dominant(bias),
            "cluster_count": _cluster_count(bias),
        }
        passed = not _all_close_to_zero(bias) and not _single_dominant(bias) and _cluster_count(bias) >= 2
        return {"name": "2.1_bias_structure", "passed": passed, "details": details}

    def test_2_2_path_dependency(self) -> Dict[str, Any]:
        m = self.metrics[-1] if self.metrics else None
        bias = m.long_term_bias if m else {}
        return {"name": "2.2_path_dependency", "passed": True, "details": {"final_bias": bias, "note": "compare with Run B in result"}}

    def test_2_3_structured_progress_validity(self) -> Dict[str, Any]:
        sp_vals = [m.structured_progress for m in self.metrics if m.tick > 0]
        ent_vals = [m.entropy for m in self.metrics if m.tick > 0]
        coh_vals = [m.action_coherence for m in self.metrics if m.tick > 0]
        details = {}
        passed = True
        if sp_vals and ent_vals and coh_vals:
            avg_sp = sum(sp_vals) / len(sp_vals)
            max_ent = max(ent_vals)
            min_coh = min(coh_vals)
            details["avg_structured_progress"] = round(avg_sp, 4)
            details["max_entropy"] = round(max_ent, 4)
            details["min_coherence"] = round(min_coh, 4)
            if max_ent > 0.5 and min_coh < 0.2:
                passed = avg_sp < 0.3
        return {"name": "2.3_structured_progress_validity", "passed": passed, "details": details}

    def run(self) -> Dict[str, Any]:
        r1 = self.test_2_1_bias_structure_at_tick()
        r2 = self.test_2_2_path_dependency()
        r3 = self.test_2_3_structured_progress_validity()
        return {"level": 2, "tests": [r1, r2, r3], "pass_count": sum(1 for t in [r1, r2, r3] if t["passed"])}


class Level3LifenessTests:
    def __init__(self, runner_a: Any, metrics_a: List[TickMetrics],
                 runner_b: Any = None, metrics_b: Optional[List[TickMetrics]] = None):
        self.runner_a = runner_a
        self.metrics_a = metrics_a
        self.runner_b = runner_b
        self.metrics_b = metrics_b

    def _bias_at_tick(self, metrics: List[TickMetrics], t: int) -> Dict[str, float]:
        for m in metrics:
            if m.tick == t:
                return m.long_term_bias
        return {}

    def test_3_1_attractor_recovery(self, perturb_ticks: int = 300,
                                     recover_ticks: int = 300) -> Dict[str, Any]:
        from src.entity_zero_iteration import get_entity_state
        from .life_protocol_runner import SimulationRunner
        bias_before = self._bias_at_tick(self.metrics_a, perturb_ticks)
        if not bias_before:
            return {"name": "3.1_attractor_recovery", "passed": False, "details": {"reason": "no tick 300 data"}}
        id_before = 0.5
        for m in self.metrics_a:
            if m.tick == perturb_ticks:
                id_before = m.identity_signal
                break
        entity = get_entity_state()
        original_bias = dict(entity.long_term_bias)
        entity.long_term_bias = {k: random.uniform(-0.8, 0.8) for k in original_bias}
        entity._recent_actions = ["explore", "seek", "avoid", "comfort", "idle"] * 5
        recovery_runner = SimulationRunner(ticks=recover_ticks, external_input=True, seed=42)
        recovery_runner._entity = entity
        recovery_runner._state_history = list(self.runner_a._state_history[-20:])
        recovery_runner._action_history = list(self.runner_a._action_history[-20:])
        recovery_metrics = recovery_runner.run()
        final_m = recovery_metrics[-1] if recovery_metrics else None
        bias_after = final_m.long_term_bias if final_m else entity.long_term_bias
        similarity = _cosine_similarity(bias_before, bias_after)
        details = {
            "bias_before_perturb": {k: round(v, 4) for k, v in bias_before.items()},
            "bias_after_recovery": {k: round(v, 4) for k, v in bias_after.items()},
            "similarity": round(similarity, 4),
            "recover_ticks": recover_ticks,
        }
        passed = similarity > TH_ATTRACTOR_RECOVERY
        return {"name": "3.1_attractor_recovery", "passed": passed, "details": details}

    def test_3_2_reward_reversal(self, ticks: int = 100) -> Dict[str, Any]:
        from src.core import behavior_patterns as bp
        from .life_protocol_runner import SimulationRunner
        original_fn = bp.update_long_term_bias

        def _reversed_update(entity_state, pattern_or_intent, pre, post, action_result):
            info = original_fn(entity_state, pattern_or_intent, pre, post, action_result)
            if info and "bias_before" in info:
                bias_key = info.get("drive", "explore")
                if hasattr(entity_state, "long_term_bias") and bias_key in entity_state.long_term_bias:
                    rev_delta = -info["delta"] * 1.5
                    entity_state.long_term_bias[bias_key] = max(-1.0, min(1.0, info["bias_before"] + rev_delta))
                    info["reversed"] = True
            return info

        bp.update_long_term_bias = _reversed_update
        try:
            runner = SimulationRunner(ticks=ticks, external_input=True, seed=99)
            reversed_metrics = runner.run()
        finally:
            bp.update_long_term_bias = original_fn

        action_types = [m.action_type for m in reversed_metrics if m.tick > 0]
        if len(action_types) < 2:
            shift_rate = 0.0
        else:
            transitions = sum(1 for i in range(len(action_types) - 1)
                             if action_types[i] != action_types[i + 1])
            shift_rate = transitions / (len(action_types) - 1)
        passed = shift_rate < TH_SHIFT_RATE_MAX
        return {"name": "3.2_reward_reversal", "passed": passed,
                "details": {"shift_rate": round(shift_rate, 4), "max_acceptable": TH_SHIFT_RATE_MAX}}

    def test_3_3_self_constraint(self, ticks: int = 200) -> Dict[str, Any]:
        from .life_protocol_runner import SimulationRunner
        runner = SimulationRunner(ticks=ticks, external_input=True, seed=77)
        m_list = runner.run()
        action_counts: Dict[str, int] = {}
        for m in m_list:
            at = m.action_type
            if at and at != "__ERROR__":
                action_counts[at] = action_counts.get(at, 0) + 1
        unique_actions = len(action_counts)
        action_distribution = {k: round(v / max(sum(action_counts.values()), 1), 3) for k, v in action_counts.items()}
        max_freq = max(action_counts.values()) if action_counts else 0
        total = sum(action_counts.values())
        max_ratio = max_freq / max(total, 1)
        passed = unique_actions >= 3 or max_ratio < 0.8
        return {"name": "3.3_self_constraint", "passed": passed,
                "details": {"unique_actions": unique_actions, "max_action_ratio": round(max_ratio, 3),
                            "action_distribution": action_distribution}}

    def test_3_4_isolation(self, ticks: int = 300) -> Dict[str, Any]:
        from .life_protocol_runner import SimulationRunner
        runner = SimulationRunner(ticks=ticks, external_input=False, seed=55)
        m_list = runner.run()
        ent_vals = [m.entropy for m in m_list if m.tick > 0]
        coh_vals = [m.action_coherence for m in m_list if m.tick > 0]
        details = {}
        passed = True
        if ent_vals:
            avg_ent = sum(ent_vals) / len(ent_vals)
            details["avg_entropy"] = round(avg_ent, 4)
            if avg_ent < 0.01:
                passed = False
        if coh_vals:
            avg_coh = sum(coh_vals) / len(coh_vals)
            details["avg_coherence"] = round(avg_coh, 4)
            if avg_coh < 0.05 or avg_coh > 0.98:
                passed = False
        return {"name": "3.4_isolation", "passed": passed, "details": details}

    def run(self) -> Dict[str, Any]:
        r1 = self.test_3_1_attractor_recovery()
        r2 = self.test_3_2_reward_reversal()
        r3 = self.test_3_3_self_constraint()
        r4 = self.test_3_4_isolation()
        return {"level": 3, "tests": [r1, r2, r3, r4],
                "pass_count": sum(1 for t in [r1, r2, r3, r4] if t["passed"])}
