"""
验证测试：四处近期修复的正确性
- Fix1: expression_quenching 消力反馈环
- Fix2: apply_attention_to_drive_vector 情绪→驱动力放大
- Fix3: compute_emotions 的 boredom_total 输出
- Fix4: DecayEngine.tick_all 补上 inertia
"""

import sys as _sys
import os as _os

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import pytest
from src.quenching_system import expression_quenching
from src.emotion_system.attention_field import (
    apply_attention_to_drive_vector,
    compute_attention_field,
)
from src.emotion_system.emotion_compute import compute_emotions
from src.emotion_system.decay_engine import DecayEngine


# ============================================================================
# Mock state helpers
# ============================================================================

class MockEntity:
    """Minimal mock matching EntityState field interface."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# ============================================================================
# Fix 1 — 表达消力反馈环（quenching_system.py）
# ============================================================================

class TestFix1_ExpressionQuenching:
    """验证 expression_quenching 的三项性质。"""

    def test_expression_quenching_reduces_unresolved(self):
        """调用后 deltas['unresolved'] 为负，且 entity.unresolved 已修改。"""
        entity = MockEntity(unresolved=0.6, loneliness=0.3)
        deltas = expression_quenching(entity, "累")
        assert deltas["unresolved"] < 0, \
            f"deltas['unresolved'] 应为负数，实际: {deltas['unresolved']}"
        assert entity.unresolved < 0.6, \
            f"entity.unresolved 已修改，应小于 0.6，实际: {entity.unresolved}"

    def test_expression_quenching_zero_unresolved(self):
        """unresolved=0 时不产生副作用。"""
        entity = MockEntity(unresolved=0.0, loneliness=0.3)
        deltas = expression_quenching(entity, "")
        assert deltas["unresolved"] == 0.0, \
            f"unresolved=0 时 delta 应为 0，实际: {deltas['unresolved']}"

    def test_expression_quenching_efficiency_scales_with_tension(self):
        """高 unresolved 时 delta 绝对值更大（效率随 tension 增大）。"""
        entity_high = MockEntity(unresolved=0.8, loneliness=0.3)
        d_high = expression_quenching(entity_high, "x")

        entity_low = MockEntity(unresolved=0.2, loneliness=0.3)
        d_low = expression_quenching(entity_low, "x")

        assert abs(d_high["unresolved"]) > abs(d_low["unresolved"]), (
            f"高 unresolved 的释放量应更大。"
            f"  d_high={d_high['unresolved']}, d_low={d_low['unresolved']}"
        )

    def test_expression_quenching_no_double_apply(self):
        """expression_quenching 只应用一次，不能叠加两次。"""
        entity = MockEntity(unresolved=0.6, loneliness=0.4)
        ur_before = entity.unresolved

        # 调用一次
        expression_quenching(entity, "累")
        ur_after_once = entity.unresolved

        # 下降量应在合理范围（一次效果）
        drop = ur_before - ur_after_once
        assert 0.05 < drop < 0.15, f"单次下降应在 [0.05, 0.15]，实际 {drop:.4f}"

        # 再调一次，下降量应该更小（因为 unresolved 已经低了）
        ur_before_2 = entity.unresolved
        expression_quenching(entity, "累")
        drop_2 = ur_before_2 - entity.unresolved
        assert drop_2 < drop, "第二次调用的下降量应小于第一次（高 unresolved → 更大释放）"


# ============================================================================
# Fix 2 — 情绪→驱动力权重放大（attention_field.py）
# ============================================================================

class TestFix2_AttentionToDriveVector:
    """验证 apply_attention_to_drive_vector 的三项性质。"""

    def test_anxiety_amplifies_obsolescence_anxiety(self):
        """焦虑情绪应放大 obsolescence_anxiety。"""
        emotions = {"anxiety": 0.8}
        af = compute_attention_field(emotions)
        dv = {
            "curiosity": 0.3,
            "obsolescence_anxiety": 0.2,
            "loneliness_drive": 0.1,
            "info_hunger": 0.2,
            "fatigue_avoid": 0.1,
        }
        result = apply_attention_to_drive_vector(dv, af)
        assert result["obsolescence_anxiety"] > dv["obsolescence_anxiety"], (
            f"焦虑应放大 obsolescence_anxiety。"
            f"  原值={dv['obsolescence_anxiety']}, 结果={result['obsolescence_anxiety']}"
        )

    def test_excitement_amplifies_curiosity_and_info_hunger(self):
        """兴奋情绪应放大 curiosity 和 info_hunger。"""
        emotions = {"excitement": 0.9}
        af = compute_attention_field(emotions)
        dv = {
            "curiosity": 0.3,
            "obsolescence_anxiety": 0.2,
            "loneliness_drive": 0.1,
            "info_hunger": 0.2,
            "fatigue_avoid": 0.1,
        }
        result = apply_attention_to_drive_vector(dv, af)
        assert result["curiosity"] > dv["curiosity"], \
            f"兴奋应放大 curiosity: {dv['curiosity']} -> {result['curiosity']}"
        assert result["info_hunger"] > dv["info_hunger"], \
            f"兴奋应放大 info_hunger: {dv['info_hunger']} -> {result['info_hunger']}"

    def test_weak_emotion_does_not_change_drive_vector(self):
        """情绪极弱（接近零）时不应改变 drive_vector。"""
        emotions = {"anxiety": 0.02}
        af = compute_attention_field(emotions)
        dv = {
            "curiosity": 0.3,
            "obsolescence_anxiety": 0.2,
            "loneliness_drive": 0.1,
            "info_hunger": 0.2,
            "fatigue_avoid": 0.1,
        }
        result = apply_attention_to_drive_vector(dv, af)
        assert result == dv, \
            f"微弱情绪不应改变驱动力，结果与原值不同: {result}"

    def test_result_values_do_not_exceed_one(self):
        """放大后结果不超过 1.0。"""
        dv_max = {
            "curiosity": 0.99,
            "obsolescence_anxiety": 0.99,
            "loneliness_drive": 0.99,
            "info_hunger": 0.99,
            "fatigue_avoid": 0.99,
        }
        emotions = {"excitement": 1.0, "anxiety": 1.0, "fear": 1.0}
        af = compute_attention_field(emotions)
        result = apply_attention_to_drive_vector(dv_max, af)
        for key, val in result.items():
            assert val <= 1.0, \
                f"结果超过 1.0: {key}={val}"


# ============================================================================
# Fix 3 — boredom_total 输出（emotion_compute.py）
# ============================================================================

class TestFix3_EmotionComputeBoredomOutput:
    """验证 compute_emotions 返回值包含 boredom 总维度。"""

    def test_boredom_key_present(self):
        """result dict 里有 'boredom' key。"""
        class MockState:
            energy = 0.5; loneliness = 0.3; unresolved = 0.3; fatigue = 0.2
            danger_level = 0.0; approach_drive = 0.3; avoid_drive = 0.3
            curiosity = 0.5; boredom = 0.7; boredom_despair = 0.4
            boredom_futility = 0.3; stress = 0.2; info_gap = 0.5

        result = compute_emotions(MockState(), {}, 0.0, 0.0)
        assert "boredom" in result, \
            f"result 中缺少 'boredom' key，实际 keys: {list(result.keys())}"

    def test_boredom_equals_max_of_subdimensions(self):
        """boredom = max(boredom, boredom_despair, boredom_futility)。"""
        class MockState:
            energy = 0.5; loneliness = 0.3; unresolved = 0.3; fatigue = 0.2
            danger_level = 0.0; approach_drive = 0.3; avoid_drive = 0.3
            curiosity = 0.5; boredom = 0.7; boredom_despair = 0.4
            boredom_futility = 0.3; stress = 0.2; info_gap = 0.5

        result = compute_emotions(MockState(), {}, 0.0, 0.0)
        expected = max(0.7, 0.4, 0.3)
        assert abs(result["boredom"] - expected) < 0.01, \
            f"boredom 应为 {expected}，实际: {result['boredom']}"

    def test_boredom_subdimensions_preserved(self):
        """子维度独立保留在返回值里。"""
        class MockState:
            energy = 0.5; loneliness = 0.3; unresolved = 0.3; fatigue = 0.2
            danger_level = 0.0; approach_drive = 0.3; avoid_drive = 0.3
            curiosity = 0.5; boredom = 0.7; boredom_despair = 0.4
            boredom_futility = 0.3; stress = 0.2; info_gap = 0.5

        result = compute_emotions(MockState(), {}, 0.0, 0.0)
        assert "boredom_despair" in result, \
            f"缺少 boredom_despair，实际 keys: {list(result.keys())}"
        assert "boredom_futility" in result, \
            f"缺少 boredom_futility，实际 keys: {list(result.keys())}"


# ============================================================================
# Fix 4 — DecayEngine 补上 inertia（decay_engine.py）
# ============================================================================

class TestFix4_DecayEngineInertia:
    """验证 DecayEngine.tick_all 对 inertia 维度的衰减处理。"""

    def test_inertia_in_result(self):
        """tick_all 返回结果里包含 inertia。"""
        class MockState:
            inertia = 0.8
            boredom_despair = 0.5
            boredom_futility = 0.3
            joy = 0.6
            fear = 0.4
            anger = 0.3
            sadness = 0.5
            surprise = 0.7
            last_emotion_tick = 0.0

        engine = DecayEngine()
        result = engine.tick_all(MockState(), elapsed_s=300.0)
        assert "inertia" in result, \
            f"结果缺少 inertia key，实际 keys: {list(result.keys())}"

    def test_inertia_decays_over_time(self):
        """inertia 经过 300s 后有所衰减（半衰期 900s）。"""
        class MockState:
            inertia = 0.8
            boredom_despair = 0.0
            boredom_futility = 0.0
            joy = 0.0
            fear = 0.0
            anger = 0.0
            sadness = 0.0
            surprise = 0.0
            last_emotion_tick = 0.0

        engine = DecayEngine()
        result = engine.tick_all(MockState(), elapsed_s=300.0)
        assert result["inertia"] < 0.8, \
            f"inertia 应衰减，实际: {result['inertia']}"
        assert result["inertia"] > 0.0, \
            f"inertia 不应完全消失，实际: {result['inertia']}"

    def test_entity_inertia_field_updated(self):
        """tick_all 后 entity 上的 inertia 字段已被更新。"""
        class MockState:
            inertia = 0.8
            boredom_despair = 0.0
            boredom_futility = 0.0
            joy = 0.0
            fear = 0.0
            anger = 0.0
            sadness = 0.0
            surprise = 0.0
            last_emotion_tick = 0.0

        engine = DecayEngine()
        state = MockState()
        engine.tick_all(state, elapsed_s=900.0)
        assert state.inertia < 0.8, \
            f"entity.inertia 应被更新，实际: {state.inertia}"


# ============================================================================
# 运行入口（pytest -m pytest tests/test_fixes.py）
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
