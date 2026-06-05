"""
Rules — 规律和快照数据结构

核心类型：
    - Predicts : 规律预测字段（trigger / expect）
    - Evidence : 单条证据（discrimination / effect / baseline_delta）
    - Rule     : 完整规律记录
    - Snap     : 经验快照（一次决策循环的全部状态）
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List


# ============================================================================
# Predicts — 预测字段
# ============================================================================

@dataclass
class Predicts:
    """
    规律预测字段。

    字段：
        trigger : 由通用状态差分法自动生成的字符串，
                 描述触发动作（如 "action_seek_in_high_energy"）
        expect  : 由通用状态差分法自动生成的字符串，
                 描述预期效果（如 "info_gap_decrease"）
    """
    trigger: str = ""
    expect: str = ""

    def to_dict(self) -> dict:
        return {
            "trigger": self.trigger,
            "expect": self.expect,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Predicts":
        if isinstance(data, dict):
            return cls(
                trigger=str(data.get("trigger", "")),
                expect=str(data.get("expect", "")),
            )
        if isinstance(data, Predicts):
            return data
        return cls()


# ============================================================================
# Evidence — 单条证据
# ============================================================================

@dataclass
class Evidence:
    """
    归纳证据。

    字段：
        discrimination      : 区分度 = abs(mean_effect_action - mean_effect_baseline)
        effect_action_mean  : 动作组的平均状态变化
        effect_baseline_mean: 对照组的平均状态变化
        action_sample_count : 动作组样本量
        counterfactual_count: 对照组样本量（反事实样本）
        state_field        : 发生显著变化的字段名
        snap_indices       : 涉及的快照索引列表
    """
    discrimination: float = 0.0
    effect_action_mean: float = 0.0
    effect_baseline_mean: float = 0.0
    action_sample_count: int = 0
    counterfactual_count: int = 0
    state_field: str = ""
    snap_indices: List[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "discrimination": round(self.discrimination, 5),
            "effect_action_mean": round(self.effect_action_mean, 5),
            "effect_baseline_mean": round(self.effect_baseline_mean, 5),
            "action_sample_count": self.action_sample_count,
            "counterfactual_count": self.counterfactual_count,
            "state_field": self.state_field,
            "snap_indices": list(self.snap_indices),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Evidence":
        if isinstance(data, Evidence):
            return data
        if isinstance(data, dict):
            return cls(
                discrimination=float(data.get("discrimination", 0.0)),
                effect_action_mean=float(data.get("effect_action_mean", 0.0)),
                effect_baseline_mean=float(data.get("effect_baseline_mean", 0.0)),
                action_sample_count=int(data.get("action_sample_count", 0)),
                counterfactual_count=int(data.get("counterfactual_count", 0)),
                state_field=str(data.get("state_field", "")),
                snap_indices=list(data.get("snap_indices", [])),
            )
        return cls()


# ============================================================================
# Rule — 规律记录
# ============================================================================

@dataclass
class Rule:
    """
    完整规律记录。

    字段：
        id                        : 规律唯一标识符（UUID 或自增）
        content                   : 可读描述文本
        confidence                : 置信度 [0, 1]
        source_experience_count   : 来源经验计数
        stability_score           : 稳定性得分 [0, 1]
        stability_band            : 稳定性置信区间半宽度
        created_at                : 创建时间戳（Unix 秒）
        last_verified_at          : 上次验证时间戳
        last_decay_at             : 上次衰减时间戳
        status                    : "active" | "pending" | "decayed"
        context                   : 规律适用上下文标签
        predicts                  : Predicts 对象
        evidence                  : Evidence 对象列表
        _debug_meta               : 调试元数据（供测试/审计用）
    """
    id: str = ""
    content: str = ""
    confidence: float = 0.5
    source_experience_count: int = 1
    stability_score: float = 0.5
    stability_band: float = 0.1
    created_at: float = 0.0
    last_verified_at: float = 0.0
    last_decay_at: float = 0.0
    status: str = "active"
    domain: str = "general"      # 规律所属认知域，例 "social.intimate", "work", "creative"
    context: str = ""
    predicts: Predicts = field(default_factory=Predicts)
    evidence: List[Evidence] = field(default_factory=list)
    expected_deltas: Dict[str, float] = field(default_factory=dict)
    _debug_meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "confidence": round(self.confidence, 4),
            "source_experience_count": self.source_experience_count,
            "stability_score": round(self.stability_score, 4),
            "stability_band": round(self.stability_band, 4),
            "created_at": round(self.created_at, 2),
            "last_verified_at": round(self.last_verified_at, 2),
            "last_decay_at": round(self.last_decay_at, 2),
            "status": self.status,
            "domain": self.domain,
            "context": self.context,
            "predicts": self.predicts.to_dict(),
            "evidence": [e.to_dict() for e in self.evidence],
            "expected_deltas": {k: round(v, 5) for k, v in self.expected_deltas.items()},
            "_debug_meta": dict(self._debug_meta),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Rule":
        """从字典构造 Rule"""
        try:
            if isinstance(data, Rule):
                return data

            if not isinstance(data, dict):
                return cls()

            predicts_data = data.get("predicts", {})
            predicts = Predicts.from_dict(predicts_data)

            evidence_list = []
            for ev in data.get("evidence", []):
                evidence_list.append(Evidence.from_dict(ev))

            now = time.time()
            return cls(
                id=str(data.get("id", "")),
                content=str(data.get("content", "")),
                confidence=float(data.get("confidence", 0.5)),
                source_experience_count=int(data.get("source_experience_count", 1)),
                stability_score=float(data.get("stability_score", 0.5)),
                stability_band=float(data.get("stability_band", 0.1)),
                created_at=float(data.get("created_at", now)),
                last_verified_at=float(data.get("last_verified_at", now)),
                last_decay_at=float(data.get("last_decay_at", now)),
                status=str(data.get("status", "active")),
                domain=str(data.get("domain", "general")),
                context=str(data.get("context", "")),
                predicts=predicts,
                evidence=evidence_list,
                expected_deltas={str(k): float(v) for k, v in data.get("expected_deltas", {}).items()},
                _debug_meta=dict(data.get("_debug_meta", {})),
            )
        except Exception:
            return cls()


# ============================================================================
# Snap — 经验快照
# ============================================================================

@dataclass
class Snap:
    """
    一次决策循环的经验快照。

    字段：
        snap_index   : 快照序号（自增）
        timestamp     : 快照时间戳
        action_type   : 裁决结果动作类型（seek / avoid / comfort）
        target        : 动作目标
        priority      : 决策优先级
        pre_state     : 动作执行前的状态向量（dict）
        post_state    : 动作执行后的状态向量（dict）
        wm_context    : 快照时的世界模型上下文（供调试/分析用）
        decision      : 完整决策包（供调试/分析用）
    """
    snap_index: int = 0
    timestamp: float = 0.0
    action_type: str = ""
    target: str = ""
    priority: float = 0.0
    pre_state: Dict[str, float] = field(default_factory=dict)
    post_state: Dict[str, float] = field(default_factory=dict)
    wm_context: Dict[str, Any] = field(default_factory=dict)
    decision: Dict[str, Any] = field(default_factory=dict)
    prediction_error_map: Dict[str, float] = field(default_factory=dict)
    input_class: str = ""  # ②a：输入事件主题标签（"" = 非输入触发，走既有 action 归纳）

    def to_dict(self) -> dict:
        return {
            "snap_index": self.snap_index,
            "timestamp": round(self.timestamp, 2),
            "action_type": self.action_type,
            "target": self.target,
            "priority": round(self.priority, 3),
            "pre_state": {k: round(float(v), 4) for k, v in self.pre_state.items()},
            "post_state": {k: round(float(v), 4) for k, v in self.post_state.items()},
            "wm_context": dict(self.wm_context),
            "decision": dict(self.decision),
            "prediction_error_map": {k: round(float(v), 5) for k, v in self.prediction_error_map.items()},
            "input_class": self.input_class,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Snap":
        """从字典构造 Snap"""
        try:
            if isinstance(data, Snap):
                return data
            if not isinstance(data, dict):
                return cls()

            def _floats_only(d: dict) -> Dict[str, float]:
                """提取 dict 中可转 float 的条目，跳过嵌套结构"""
                out = {}
                for k, v in d.items():
                    try:
                        out[str(k)] = float(v)
                    except (TypeError, ValueError):
                        pass
                return out

            return cls(
                snap_index=int(data.get("snap_index", 0)),
                timestamp=float(data.get("timestamp", 0.0)),
                action_type=str(data.get("action_type", "")),
                target=str(data.get("target", "")),
                priority=float(data.get("priority", 0.0)),
                pre_state=_floats_only(data.get("pre_state", {})),
                post_state=_floats_only(data.get("post_state", {})),
                wm_context=dict(data.get("wm_context", {})),
                decision=dict(data.get("decision", {})),
                prediction_error_map=_floats_only(data.get("prediction_error_map", {})),
                input_class=str(data.get("input_class", "")),
            )
        except Exception:
            return cls()


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    import time

    print("=" * 64)
    print("Rules — 数据结构测试")
    print("=" * 64)

    now = time.time()

    # 测试 1: Rule round-trip
    print("\n【测试 1】Rule Round-trip")
    original = Rule(
        id="test_rule_1",
        content="高能量时执行seek，info_gap下降",
        confidence=0.75,
        source_experience_count=3,
        stability_score=0.6,
        stability_band=0.12,
        created_at=now,
        last_verified_at=now,
        last_decay_at=now,
        status="active",
        context="高energy",
        predicts=Predicts(trigger="action_seek_in_high_energy", expect="info_gap_decrease"),
        evidence=[
            Evidence(
                discrimination=0.04,
                effect_action_mean=-0.10,
                effect_baseline_mean=-0.01,
                action_sample_count=2,
                counterfactual_count=2,
                state_field="info_gap",
                snap_indices=[0, 1],
            )
        ],
        _debug_meta={"source": "test"},
    )
    d = original.to_dict()
    restored = Rule.from_dict(d)
    ok1 = (
        restored.id == original.id
        and abs(restored.confidence - original.confidence) < 1e-4
        and len(restored.evidence) == 1
        and restored.predicts.trigger == "action_seek_in_high_energy"
    )
    print(f"  {'✓' if ok1 else '✗'} Rule round-trip: id={restored.id}, conf={restored.confidence}")

    # 测试 2: Snap round-trip
    print("\n【测试 2】Snap Round-trip")
    snap = Snap(
        snap_index=5,
        timestamp=now,
        action_type="seek",
        target="topic_abc",
        priority=0.82,
        pre_state={"energy": 0.8, "info_gap": 0.7},
        post_state={"energy": 0.75, "info_gap": 0.6},
        wm_context={"rule_hit": 1},
        decision={"action": "seek"},
    )
    snap_d = snap.to_dict()
    snap_restored = Snap.from_dict(snap_d)
    ok2 = (
        snap_restored.snap_index == snap.snap_index
        and snap_restored.action_type == "seek"
        and abs(snap_restored.priority - 0.82) < 1e-4
    )
    print(f"  {'✓' if ok2 else '✗'} Snap round-trip: index={snap_restored.snap_index}, action={snap_restored.action_type}")

    # 测试 3: Dict 输入兼容
    print("\n【测试 3】Dict 输入兼容")
    rule_dict = {
        "id": "dict_rule",
        "content": "从字典构造",
        "confidence": 0.6,
        "status": "pending",
        "predicts": {"trigger": "test_trigger", "expect": "info_gap_decrease"},
    }
    rule_from_dict = Rule.from_dict(rule_dict)
    ok3 = rule_from_dict.id == "dict_rule" and rule_from_dict.status == "pending"
    print(f"  {'✓' if ok3 else '✗'} Dict 输入 → Rule: id={rule_from_dict.id}, status={rule_from_dict.status}")

    # 测试 4: Evidence round-trip
    print("\n【测试 4】Evidence Round-trip")
    ev = Evidence(
        discrimination=0.05,
        effect_action_mean=-0.12,
        effect_baseline_mean=-0.02,
        action_sample_count=3,
        counterfactual_count=2,
        state_field="loneliness",
        snap_indices=[1, 2, 3],
    )
    ev_d = ev.to_dict()
    ev_r = Evidence.from_dict(ev_d)
    ok4 = (
        abs(ev_r.discrimination - 0.05) < 1e-9
        and len(ev_r.snap_indices) == 3
    )
    print(f"  {'✓' if ok4 else '✗'} Evidence round-trip: discr={ev_r.discrimination}, indices={ev_r.snap_indices}")

    print("\n" + "=" * 64)
    print("Rules 测试完成")
    print("=" * 64)
