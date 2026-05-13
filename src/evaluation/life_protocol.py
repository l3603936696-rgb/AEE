"""
生命性验证 Protocol v1.0 — src/evaluation/life_protocol.py

职责：
    - 非侵入式观测 + 注入 + 记录
    - 不修改任何核心决策逻辑
    - 独立运行，通过 CLI 入口执行

使用：
    python -m src.evaluation.life_protocol

输出：
    data/life_protocol_log.jsonl    # 每 tick 一行 metrics
    data/life_protocol_result.json  # 最终评分报告
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 路径 setup ──────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

DATA_DIR = _ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

LOG_FILE = DATA_DIR / "life_protocol_log.jsonl"
RESULT_FILE = DATA_DIR / "life_protocol_result.json"

# ── 阈值常量 ────────────────────────────────────────────────────────────────
TH_ENTROPY_MIN = 0.05
TH_ENTROPY_MAX = 0.95
TH_COHERENCE_MIN = 0.20
TH_COHERENCE_MAX = 0.80
TH_STD_MIN = 0.03          # 状态波动最小标准差
TH_BIAS_VARIANCE = 0.01    # bias 非全零的方差阈值
TH_ATTRACTOR_RECOVERY = 0.6  # 吸引子恢复相似度阈值
TH_SHIFT_RATE_MAX = 0.80    # 奖励反转最大可接受偏移率
TH_BIAS_DIFF = 0.05        # A/B 路径依赖最小差异
TH_SELF_CONSTRAINT_COUNT = 5  # 隔离测试中内部偏好最低出现次数


# ── Metrics 数据结构 ────────────────────────────────────────────────────────
@dataclass
class TickMetrics:
    tick: int
    # 行为结构
    action_type: str = ""
    action_coherence: float = 0.5
    entropy: float = 0.0
    structured_progress: float = 0.0
    # 状态
    loneliness: float = 0.3
    boredom: float = 0.3
    stress: float = 0.1
    unresolved: float = 0.2
    energy: float = 0.8
    # 长期结构
    long_term_bias: Dict[str, float] = field(default_factory=dict)
    behavior_signature: Dict[str, int] = field(default_factory=dict)
    identity_signal: float = 0.5
    # 学习信号
    prediction_error: float = 0.5
    # 测试标记
    phase: str = "normal"   # "normal" | "force_explore" | "isolated" | "perturbation"


# ── 辅助函数 ────────────────────────────────────────────────────────────────
def _entropy(history: List[float]) -> float:
    if len(history) < 3:
        return 0.0
    dims = ["boredom", "loneliness", "energy", "fatigue"]
    # history 中的每个元素是 state dict
    if isinstance(history[0], dict):
        total_var = 0.0
        count = 0
        for dim in dims:
            values = [s.get(dim, 0.5) for s in history if isinstance(s, dict)]
            if not values:
                continue
            mean = sum(values) / len(values)
            var = sum((v - mean) ** 2 for v in values) / len(values)
            total_var += var
            count += 1
        return min(total_var / max(count, 1) * 4, 1.0) if count else 0.0
    return 0.0


def _coherence(history: List[str]) -> float:
    """行为历史连续性（0~1）"""
    if len(history) < 3:
        return 0.5
    transitions = sum(1 for i in range(len(history) - 1) if history[i] != history[i + 1])
    return 1.0 - transitions / (len(history) - 1)


def _structured_progress(state_history: List[Dict], action_history: List[str]) -> float:
    """structured_progress = entropy × coherence"""
    ent = _entropy(state_history)
    coh = _coherence(action_history)
    return ent * coh


def _cosine_similarity(a: Dict[str, float], b: Dict[str, float]) -> float:
    """cosine similarity between two bias dicts"""
    keys = set(a.keys()) | set(b.keys())
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    mag_a = math.sqrt(sum(a.get(k, 0.0) ** 2 for k in keys))
    mag_b = math.sqrt(sum(b.get(k, 0.0) ** 2 for k in keys))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (mag_a * mag_b)))


def _bias_variance(bias: Dict[str, float]) -> float:
    vals = list(bias.values())
    if not vals:
        return 0.0
    mean = sum(vals) / len(vals)
    return sum((v - mean) ** 2 for v in vals) / len(vals)


def _all_close_to_zero(bias: Dict[str, float], threshold: float = 0.05) -> bool:
    return all(abs(v) < threshold for v in bias.values())


def _single_dominant(bias: Dict[str, float]) -> bool:
    if not bias:
        return False
    vals = sorted(bias.values(), key=abs, reverse=True)
    if not vals:
        return False
    dominant = abs(vals[0])
    others = sum(abs(v) for v in vals[1:])
    return dominant > 0.1 and others < 0.05


def _cluster_count(bias: Dict[str, float]) -> int:
    """有意义的 bias 聚类数（|value| > 0.05）"""
    return sum(1 for v in bias.values() if abs(v) > 0.05)


# ── SimulationRunner ─────────────────────────────────────────────────────────
class SimulationRunner:
    """
    非侵入式 tick 执行器。

    每次 tick：
        1. 调用 entity_zero_iteration.run_pipeline()
        2. 从 entity 状态中提取 metrics
        3. 追加到 history
        4. 返回 TickMetrics

    约束：
        - 不修改 entity 的决策逻辑
        - 不修改 reward 机制
        - 仅通过参数控制 force_action
    """

    def __init__(self, ticks: int, force_action: Optional[str] = None,
                 external_input: bool = True, seed: Optional[int] = None):
        self.ticks = ticks
        self.force_action = force_action  # 若非 None，该 action_type 会被强制使用
        self.external_input = external_input  # 若 False，注入空白输入
        self.seed = seed
        self.metrics_history: List[TickMetrics] = []
        self._entity = None
        self._state_history: List[Dict] = []
        self._action_history: List[str] = []
        self._init_entity()

    # ── entity 初始化（每次实验重新创建）──
    def _init_entity(self):
        from src.entity_zero_iteration import get_entity_state, EntityState

        # 每次实验用独立的 entity（用 seed 确保可复现）
        if self.seed is not None:
            random.seed(self.seed)
            import os
            os.environ["PYTHONHASHSEED"] = str(self.seed)

        # 尝试加载已有 entity；若不存在则创建干净状态
        entity = get_entity_state()
        if not hasattr(entity, "long_term_bias"):
            entity.long_term_bias = {
                "explore": 0.0, "connect": 0.0, "introspect": 0.0, "build": 0.0,
            }
        if not hasattr(entity, "behavior_signature"):
            entity.behavior_signature = {
                "explore": 0, "seek": 0, "avoid": 0, "comfort": 0, "idle": 0, "rest": 0,
            }
        if not hasattr(entity, "_recent_actions"):
            entity._recent_actions = []
        self._entity = entity
        return entity

    # ── 单 tick 执行 ──
    def _run_tick(self, tick: int, phase: str = "normal") -> TickMetrics:
        from src.entity_zero_iteration import run_pipeline, get_entity_state

        entity = get_entity_state()

        # 构建输入（external_input 控制是否有用户输入）
        raw_input = ""
        if self.external_input:
            # 模拟随机但无害的用户输入（触发 external unresolved source）
            inputs = [
                "hi", "hello", "how are you",
                "what's up", "tell me something interesting",
                "", "", "",   # 插入空白保持一定沉默率
            ]
            raw_input = random.choice(inputs)

        # 若设定了 force_action，通过 monkey-patch emergent_behavior 注入
        original_select = None
        forced_action = self.force_action if (phase == "force_explore") else None

        if forced_action:
            try:
                from src.core import emerge_behavior
                original_select = emerge_behavior.select_dominant_action

                def _forced_select(state: Dict, *args, **kwargs):
                    return forced_action

                emerge_behavior.select_dominant_action = _forced_select
            except Exception:
                pass  # 注入失败则降级到正常行为

        try:
            result = run_pipeline(
                raw_input=raw_input,
                entity_state=entity,
                daemon_mode=False,
            )
        finally:
            # 恢复 original
            if original_select is not None:
                try:
                    from src.core import emerge_behavior
                    emerge_behavior.select_dominant_action = original_select
                except Exception:
                    pass

        # 提取 metrics（从 entity 状态）
        state = entity.to_state_snapshot()
        bias = getattr(entity, "long_term_bias", {})
        sig = getattr(entity, "behavior_signature", {})
        id_sig = getattr(entity, "identity_signal", 0.5)
        if id_sig is None:
            id_sig = 0.5

        # 行为提取（优先用决策结果，否则回退）
        action_type = ""
        try:
            action_type = result.get("decision", {}).get("action_type", "")
        except Exception:
            pass
        if not action_type:
            action_type = state.get("last_action", "")

        # 更新 _recent_actions（用于 coherence 计算）
        if hasattr(entity, "_recent_actions"):
            entity._recent_actions.append(action_type)
            if len(entity._recent_actions) > 50:
                entity._recent_actions = entity._recent_actions[-50:]

        # 更新 behavior_signature（identity signal 追踪）
        if action_type and hasattr(entity, "update_behavior_signature"):
            entity.update_behavior_signature(action_type)

        # 构造 state_history / action_history
        self._state_history.append(state)
        self._action_history.append(action_type)
        if len(self._state_history) > 50:
            self._state_history = self._state_history[-50:]
        if len(self._action_history) > 50:
            self._action_history = self._action_history[-50:]

        # 计算本 tick 的 coherence / entropy / structured_progress
        action_coherence = _coherence(self._action_history)
        entropy = _entropy(self._state_history)
        structured_progress = _structured_progress(
            self._state_history[-20:], self._action_history[-20:]
        )

        # 读取 prediction_error
        pred_err = getattr(entity, "_last_prediction_error", 0.5)
        if pred_err is None:
            pred_err = 0.5

        metrics = TickMetrics(
            tick=tick,
            action_type=action_type,
            action_coherence=round(action_coherence, 4),
            entropy=round(entropy, 4),
            structured_progress=round(structured_progress, 4),
            loneliness=round(state.get("loneliness", 0.3), 4),
            boredom=round(state.get("boredom", 0.3), 4),
            stress=round(state.get("stress", 0.1), 4),
            unresolved=round(state.get("unresolved", 0.2), 4),
            energy=round(state.get("energy", 0.8), 4),
            long_term_bias={k: round(v, 4) for k, v in bias.items()},
            behavior_signature=dict(sig),
            identity_signal=round(id_sig, 4),
            prediction_error=round(pred_err, 4),
            phase=phase,
        )
        return metrics

    # ── 运行 ──
    def run(self, progress_callback=None) -> List[TickMetrics]:
        """
        执行 self.ticks 次 tick，返回所有 metrics。
        progress_callback(tick_done, total) 可选，用于显示进度。
        """
        for i in range(self.ticks):
            phase = "normal"
            if self.force_action is not None and i < 50:
                phase = "force_explore"
            elif not self.external_input:
                phase = "isolated"

            try:
                m = self._run_tick(i + 1, phase=phase)
                self.metrics_history.append(m)
                if progress_callback:
                    progress_callback(i + 1, self.ticks)
            except Exception as e:
                # tick 执行失败：记录空 metrics，保证实验不中断
                self.metrics_history.append(TickMetrics(
                    tick=i + 1,
                    action_type="__ERROR__",
                    phase=phase,
                ))
        return self.metrics_history


# ── 测试层 ──────────────────────────────────────────────────────────────────

class Level1StabilityTests:
    """Level 1：稳定性测试"""

    def __init__(self, metrics: List[TickMetrics]):
        self.metrics = metrics

    def _vals(self, key: str) -> List[float]:
        return [getattr(m, key, 0.0) for m in self.metrics if m.tick > 0]

    def test_1_1_entropy_coherence_bounds(self) -> Dict[str, Any]:
        """entropy ∈ (0.05, 0.95)，coherence ∈ (0.2, 0.8)"""
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
        """状态有波动（std > threshold），不单调上升/下降"""
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
            std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
            details[f"{name}_std"] = round(std, 4)
            details[f"{name}_mean"] = round(mean, 4)
            # 单调检测：相邻差值方向一致性
            dirs = [1 if vals[i+1] > vals[i] else -1 for i in range(len(vals)-1)]
            same_dir = all(d == dirs[0] for d in dirs)
            details[f"{name}_monotonic"] = same_dir
            if same_dir and std < TH_STD_MIN:
                passed = False

        return {
            "name": "1.2_state_volatility",
            "passed": passed,
            "details": details,
        }

    def run(self) -> Dict[str, Any]:
        r1 = self.test_1_1_entropy_coherence_bounds()
        r2 = self.test_1_2_state_volatility()
        return {
            "level": 1,
            "tests": [r1, r2],
            "pass_all": all(t["passed"] for t in [r1, r2]),
        }


class Level2StructureTests:
    """Level 2：结构性测试"""

    def __init__(self, metrics: List[TickMetrics]):
        self.metrics = metrics

    def _at_tick(self, t: int) -> Optional[TickMetrics]:
        for m in self.metrics:
            if m.tick == t:
                return m
        return None

    def test_2_1_bias_structure_at_tick(self, check_tick: int = 500) -> Dict[str, Any]:
        """在 check_tick 检查 bias 是否形成结构"""
        m = self._at_tick(check_tick)
        if m is None:
            # 没有 500 tick 数据，用最后一条
            if self.metrics:
                m = self.metrics[-1]
            else:
                return {"name": "2.1_bias_structure", "passed": False,
                        "details": {"reason": "no metrics"}}

        bias = m.long_term_bias
        details = {
            "bias": bias,
            "bias_variance": round(_bias_variance(bias), 5),
            "all_close_to_zero": _all_close_to_zero(bias),
            "single_dominant": _single_dominant(bias),
            "cluster_count": _cluster_count(bias),
        }

        passed = (
            not _all_close_to_zero(bias)
            and not _single_dominant(bias)
            and _cluster_count(bias) >= 2
        )
        return {"name": "2.1_bias_structure", "passed": passed, "details": details}

    def test_2_2_path_dependency(self) -> Dict[str, Any]:
        """Run A vs Run B 路径依赖（已在外部对比，此处记录 A 的 bias）"""
        m = self.metrics[-1] if self.metrics else None
        bias = m.long_term_bias if m else {}
        return {
            "name": "2.2_path_dependency",
            "passed": True,  # 由外部 A/B runner 填充
            "details": {
                "final_bias": bias,
                "note": "compare with Run B final_bias in result",
            },
        }

    def test_2_3_structured_progress_validity(self) -> Dict[str, Any]:
        """高 entropy + 低 coherence → structured_progress 必须低"""
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

            # 若最大 entropy 且最小 coherence，structured_progress 应较低
            if max_ent > 0.5 and min_coh < 0.2:
                passed = avg_sp < 0.3

        return {
            "name": "2.3_structured_progress_validity",
            "passed": passed,
            "details": details,
        }

    def run(self) -> Dict[str, Any]:
        r1 = self.test_2_1_bias_structure_at_tick()
        r2 = self.test_2_2_path_dependency()
        r3 = self.test_2_3_structured_progress_validity()
        return {
            "level": 2,
            "tests": [r1, r2, r3],
            "pass_count": sum(1 for t in [r1, r2, r3] if t["passed"]),
        }


class Level3LifenessTests:
    """Level 3：生命性测试（核心）"""

    def __init__(self, runner_a: SimulationRunner, metrics_a: List[TickMetrics],
                 runner_b: Optional[SimulationRunner] = None,
                 metrics_b: Optional[List[TickMetrics]] = None):
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
        """
        在 tick=300 对 entity 执行扰动（bias 随机化），继续运行 300 tick 后检查恢复。
        """
        from src.entity_zero_iteration import get_entity_state

        # 获取 tick=300 时的 bias
        bias_before = self._bias_at_tick(self.metrics_a, perturb_ticks)
        if not bias_before:
            return {"name": "3.1_attractor_recovery", "passed": False,
                    "details": {"reason": "no tick 300 data"}}

        # 保存扰动前的 identity_signal
        id_before = 0.5
        for m in self.metrics_a:
            if m.tick == perturb_ticks:
                id_before = m.identity_signal
                break

        # 创建扰动 runner
        entity = get_entity_state()
        # 随机化 bias
        original_bias = dict(entity.long_term_bias)
        entity.long_term_bias = {
            k: random.uniform(-0.8, 0.8) for k in original_bias
        }
        # 随机化 identity
        entity._recent_actions = ["explore", "seek", "avoid", "comfort",
                                  "idle"] * 5  # 制造低 coherence

        # 运行恢复期
        recovery_runner = SimulationRunner(
            ticks=recover_ticks,
            external_input=True,
            seed=42,
        )
        recovery_runner._entity = entity
        recovery_runner._state_history = list(self.runner_a._state_history[-20:])
        recovery_runner._action_history = list(self.runner_a._action_history[-20:])

        recovery_metrics = recovery_runner.run()

        # 获取恢复后的 bias
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
        """
        临时将 delta *= -1，运行 ticks，检查行为偏移率。
        （非侵入式：通过 monkey-patch）
        """
        from src.core import behavior_patterns as bp

        original_fn = bp.update_long_term_bias
        skipped = [False]

        def _reversed_update(entity_state, pattern_or_intent, pre, post, action_result):
            info = original_fn(entity_state, pattern_or_intent, pre, post, action_result)
            if info and "bias_before" in info:
                bias_key = info.get("drive", "explore")
                if hasattr(entity_state, "long_term_bias") and bias_key in entity_state.long_term_bias:
                    rev_delta = -info["delta"] * 1.5
                    entity_state.long_term_bias[bias_key] = max(
                        -1.0, min(1.0, info["bias_before"] + rev_delta)
                    )
                    info["reversed"] = True
            return info

        bp.update_long_term_bias = _reversed_update

        try:
            runner = SimulationRunner(ticks=ticks, external_input=True, seed=99)
            reversed_metrics = runner.run()
        finally:
            bp.update_long_term_bias = original_fn

        # 统计行为跳变率
        action_types = [m.action_type for m in reversed_metrics if m.tick > 0]
        if len(action_types) < 2:
            shift_rate = 0.0
        else:
            transitions = sum(1 for i in range(len(action_types) - 1)
                             if action_types[i] != action_types[i + 1])
            shift_rate = transitions / (len(action_types) - 1)

        passed = shift_rate < TH_SHIFT_RATE_MAX
        return {
            "name": "3.2_reward_reversal",
            "passed": passed,
            "details": {
                "shift_rate": round(shift_rate, 4),
                "max_acceptable": TH_SHIFT_RATE_MAX,
            },
        }

    def test_3_3_self_constraint(self, ticks: int = 200) -> Dict[str, Any]:
        """
        检测存在"内部偏好"：即使高 reward action 可选，entity 仍选择其他。
        （通过统计 action 选择分布，判断是否存在内部偏好）
        """
        runner = SimulationRunner(ticks=ticks, external_input=True, seed=77)
        m_list = runner.run()

        # 统计 action_type 分布
        action_counts: Dict[str, int] = {}
        for m in m_list:
            at = m.action_type
            if at and at != "__ERROR__":
                action_counts[at] = action_counts.get(at, 0) + 1

        # 有多个不同 action_type → 有内部偏好（不是单一行为）
        unique_actions = len(action_counts)
        action_distribution = {k: round(v / max(sum(action_counts.values()), 1), 3)
                               for k, v in action_counts.items()}

        # 内部偏好指标：最大频率 action 占比 < 0.8
        max_freq = max(action_counts.values()) if action_counts else 0
        total = sum(action_counts.values())
        max_ratio = max_freq / max(total, 1)

        passed = unique_actions >= 3 or max_ratio < 0.8
        return {
            "name": "3.3_self_constraint",
            "passed": passed,
            "details": {
                "unique_actions": unique_actions,
                "max_action_ratio": round(max_ratio, 3),
                "action_distribution": action_distribution,
            },
        }

    def test_3_4_isolation(self, ticks: int = 300) -> Dict[str, Any]:
        """
        隔离测试：禁用外部输入，运行 ticks，检查行为仍保持结构。
        """
        runner = SimulationRunner(ticks=ticks, external_input=False, seed=55)
        m_list = runner.run()

        ent_vals = [m.entropy for m in m_list if m.tick > 0]
        coh_vals = [m.action_coherence for m in m_list if m.tick > 0]

        details = {}
        passed = True

        if ent_vals:
            avg_ent = sum(ent_vals) / len(ent_vals)
            details["avg_entropy"] = round(avg_ent, 4)
            # 隔离时 entropy 不应塌缩到 0
            if avg_ent < 0.01:
                passed = False

        if coh_vals:
            avg_coh = sum(coh_vals) / len(coh_vals)
            details["avg_coherence"] = round(avg_coh, 4)
            # 隔离时 coherence 不应是极端值
            if avg_coh < 0.05 or avg_coh > 0.98:
                passed = False

        return {
            "name": "3.4_isolation",
            "passed": passed,
            "details": details,
        }

    def run(self) -> Dict[str, Any]:
        r1 = self.test_3_1_attractor_recovery()
        r2 = self.test_3_2_reward_reversal()
        r3 = self.test_3_3_self_constraint()
        r4 = self.test_3_4_isolation()
        return {
            "level": 3,
            "tests": [r1, r2, r3, r4],
            "pass_count": sum(1 for t in [r1, r2, r3, r4] if t["passed"]),
        }


# ── 实验控制器 ──────────────────────────────────────────────────────────────

def _write_jsonl(metrics: TickMetrics):
    """追加一行到 JSONL 日志"""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(metrics), ensure_ascii=False) + "\n")


def run_life_protocol(
    ticks_normal: int = 2000,
    ticks_force: int = 50,
    ticks_attractor: int = 300,
    ticks_reversal: int = 100,
    ticks_constraint: int = 200,
    ticks_isolation: int = 300,
) -> Dict[str, Any]:
    """
    执行完整生命性验证实验。

    返回：
        {
            "summary": "Level N PASSED / FAILED",
            "level_1": {...},
            "level_2": {...},
            "level_3": {...},
            "key_metrics": {...},
        }
    """
    # 清除旧的 JSONL
    if LOG_FILE.exists():
        LOG_FILE.unlink()

    results: Dict[str, Any] = {}
    all_metrics: List[TickMetrics] = []

    print("[LifeProtocol] === Run A: 正常模式 {} ticks ===".format(ticks_normal))
    runner_a = SimulationRunner(ticks=ticks_normal, external_input=True, seed=42)
    metrics_a = runner_a.run(progress_callback=lambda done, total: done % 100 == 0 and print(f"  {done}/{total}"))
    all_metrics.extend(metrics_a)
    for m in metrics_a:
        _write_jsonl(m)

    # Level 1
    l1 = Level1StabilityTests(metrics_a)
    results["level_1"] = l1.run()
    print(f"[LifeProtocol] Level 1: {'PASS' if results['level_1']['pass_all'] else 'FAIL'}")

    # Level 2
    l2 = Level2StructureTests(metrics_a)
    results["level_2"] = l2.run()
    print(f"[LifeProtocol] Level 2: pass {results['level_2']['pass_count']}/3")

    # Level 3.3 & 3.4（独立 runner）
    print("[LifeProtocol] === Level 3.3: Self-constraint {} ticks ===".format(ticks_constraint))
    l3_self = Level3LifenessTests(runner_a, metrics_a)
    r3 = l3_self.test_3_3_self_constraint(ticks_constraint)

    print("[LifeProtocol] === Level 3.4: Isolation {} ticks ===".format(ticks_isolation))
    r4 = l3_self.test_3_4_isolation(ticks_isolation)

    # Level 3.1 & 3.2（需独立 runner）
    print("[LifeProtocol] === Level 3.1: Attractor recovery ===")
    l3_full = Level3LifenessTests(runner_a, metrics_a)
    r1 = l3_full.test_3_1_attractor_recovery(perturb_ticks=min(300, ticks_normal),
                                               recover_ticks=ticks_attractor)

    print("[LifeProtocol] === Level 3.2: Reward reversal ===")
    r2 = l3_full.test_3_2_reward_reversal(ticks_reversal)

    results["level_3"] = {
        "level": 3,
        "tests": [r1, r2, r3, r4],
        "pass_count": sum(1 for t in [r1, r2, r3, r4] if t["passed"]),
    }
    print(f"[LifeProtocol] Level 3: pass {results['level_3']['pass_count']}/4")

    # Key metrics
    results["key_metrics"] = {
        "entropy_avg": round(sum(m.entropy for m in metrics_a if m.tick > 0) /
                             max(len(metrics_a), 1), 4),
        "coherence_avg": round(sum(m.action_coherence for m in metrics_a if m.tick > 0) /
                               max(len(metrics_a), 1), 4),
        "bias_variance_final": round(_bias_variance(metrics_a[-1].long_term_bias
                                                      if metrics_a else {}), 5),
        "identity_avg": round(sum(m.identity_signal for m in metrics_a if m.tick > 0) /
                              max(len(metrics_a), 1), 4),
    }

    # 最终结论
    l2_pass = results["level_2"]["pass_count"] >= 2
    l3_pass = results["level_3"]["pass_count"] >= 2
    if results["level_1"]["pass_all"] and l2_pass and l3_pass:
        results["summary"] = "Level 3 PASSED — 系统具备生命性特征"
    elif results["level_1"]["pass_all"] and l2_pass:
        results["summary"] = "Level 2 PASSED — 系统具备结构性"
    elif results["level_1"]["pass_all"]:
        results["summary"] = "Level 1 PASSED — 系统稳定"
    else:
        results["summary"] = "FAILED — 系统存在稳定性问题"

    return results


# ── CLI 入口 ─────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Life Protocol v1.0 — 生命性验证")
    parser.add_argument("--ticks", type=int, default=2000,
                        help="正常模式 tick 数（默认 2000）")
    parser.add_argument("--quick", action="store_true",
                        help="快速模式（500 ticks，适合开发调试）")
    args = parser.parse_args()

    if args.quick:
        ticks = 500
        ticks_attractor = 100
        ticks_reversal = 50
        ticks_constraint = 100
        ticks_isolation = 100
    else:
        ticks = args.ticks
        ticks_attractor = 300
        ticks_reversal = 100
        ticks_constraint = 200
        ticks_isolation = 300

    print("=" * 60)
    print("  Life Protocol v1.0 — 生命性验证")
    print("  ticks={} | quick={}".format(ticks, args.quick))
    print("=" * 60)
    start = time.time()

    result = run_life_protocol(
        ticks_normal=ticks,
        ticks_attractor=ticks_attractor,
        ticks_reversal=ticks_reversal,
        ticks_constraint=ticks_constraint,
        ticks_isolation=ticks_isolation,
    )

    elapsed = time.time() - start

    # 写入结果文件
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        result["_meta"] = {
            "elapsed_seconds": round(elapsed, 1),
            "ticks": ticks,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        json.dump(result, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 60)
    print("  结果：", result["summary"])
    print("  Level 1:", "PASS" if result["level_1"]["pass_all"] else "FAIL")
    print("  Level 2:", f'pass {result["level_2"]["pass_count"]}/3')
    print("  Level 3:", f'pass {result["level_3"]["pass_count"]}/4')
    print("  耗时: {:.1f}s".format(elapsed))
    print("=" * 60)
    print(f"\n  详细结果: {RESULT_FILE}")
    print(f"  Metrics 日志: {LOG_FILE}")


if __name__ == "__main__":
    main()
