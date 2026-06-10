"""
test_persistence_language.py — 语言系统持久化链路测试

覆盖范围：
  1. _warm_words        写入→读取 完整往返（Fix: 之前断链）
  2. _quenching_data   写入→读取 完整往返（已知 OK，回归测试）
  3. _strategy_map_data 写入→读取 完整往返（已知 OK，回归测试）
  4. QuenchingTracker  from_dict 重建后 record+get_efficiency 功能正常
  5. StrategyMap       from_dict 重建后 record_path+get_best_path 功能正常
  6. s01_init 恢复链   从 entity._quenching_data 重建 QuenchingTracker 实例

设计原则：
  - 使用临时文件，不污染 data/entity_core.json
  - 不启动 daemon / pipeline，只测持久化模块本身
"""

import sys as _sys
import os as _os
import tempfile
import json

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import pytest

from AEE.src.entity_persistence import persist_entity_to_file, load_entity_from_file
from AEE.src.language_system import QuenchingTracker
from AEE.src.language_system.strategy_map import StrategyMap


# ============================================================================
# Helpers
# ============================================================================

class MockEntity:
    """Minimal mock matching EntityState persistence interface."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _make_entity_with_language_state(**overrides):
    """创建带语言系统状态的 MockEntity，模拟一轮运行后的 entity。"""
    # QuenchingTracker with some history
    qt = QuenchingTracker(history_maxlen=500)
    for i in range(10):
        qt.record(
            drive_state={"unresolved": 0.5, "loneliness": 0.3, "curiosity": 0.4},
            expression="嗯",
            delta_unresolved_before=0.5,
            delta_unresolved_after=0.35,
            tick=i,
            template_idx=i % 3,
        )

    # StrategyMap with some paths
    sm = StrategyMap()
    sm.record_path(
        {"unresolved": 0.5}, {"unresolved": 0.3},
        "哦", 0.6, "daemon_tick",
    )
    sm.record_path(
        {"loneliness": 0.6}, {"loneliness": 0.3},
        "……", 0.55, "daemon_tick",
    )

    defaults = {
        "tick": 123,
        "energy": 0.7,
        "loneliness": 0.35,
        "loneliness_core": 0.25,
        "loneliness_surface": 0.10,
        "unresolved": 0.4,
        "boredom": 0.2,
        "fatigue": 0.15,
        "stress": 0.1,
        "relief_debt": 0.0,
        "pain": 0.0,
        "info_gap": 0.5,
        "curiosity": 0.5,
        "time_since_last_info": 0.0,
        "time_since_last_social": 0.0,
        "external_change_rate": 0.0,
        "somatic_tone": 0.0,
        "danger_level": 0.0,
        "approach_drive": 0.3,
        "avoid_drive": 0.2,
        "approach_social": 0.3,
        "approach_explore": 0.3,
        "approach_urgency": 0.2,
        "quenching_eff_rolling": 0.55,
        "_training_randomize": False,
        "wm_rules": [],
        "snapshots": [],
        "memory_context": [],
        "last_update_time": 1234567890.0,
        "last_shutdown_time": 1234567800.0,
        "last_shutdown_tick": 120,
        "last_interaction_timestamp": 1234567890.0,
        "last_interaction_context": {},
        "pending_surprises": [],
        "long_term_bias": {"explore": 0.0, "connect": 0.0, "introspect": 0.0, "build": 0.0},
        "behavior_signature": {"explore": 0, "seek": 0, "avoid": 0, "comfort": 0, "idle": 0, "rest": 0},
        "unresolved_source": "internal",
        "_unresolved_sources": [],
        "pending_failures": [],
        "_pending_tool_gaps": [],
        "failure_metabolite": 0.0,
        "behavior_rules": [],
        "last_action_timestamp": 0.0,
        "consecutive_reaches_without_response": 0,
        # Language system fields
        "_umbilical_detached": True,
        "_unlocked_vocabulary": ["嗯", "哦", "好", "累", "困"],
        "_warm_words": {"嗯": {"hits": 5, "avg_eff": 0.62}, "哦": {"hits": 3, "avg_eff": 0.55}},
        "_cluster_weights": {"cluster_a": 0.4, "cluster_b": 0.6},
        "_state_pattern_data": {},
        "_approach_synthesis_weights": {"social": 0.4, "explore": 0.35, "urgency": 0.25},
        "_quench_feedback_weights": {"quench_rate": 0.25, "approach_release": 0.3},
        "_failure_metabolite_weights": {"approach_suppress": 0.15},
        "_conflict_to_unresolved_weights": {"conflict_rate": 0.04},
        "_emotion_drive_modulation": {},
        "_vocab_acquisition_params": {"min_comprehension": 0.3},
        "_word_exposure_tracker": {"啊": 2.0},
        "_repetition_decay_params": {"decay_per_use": 0.15},
        "_response_pressure_params": {"coefficient": 0.03},
        "_sibling_channel": {"enabled": True},
        "_source_profiles": {},
        "_stereotype_trees": [],
        "_stereotype_conversation_history": {},
        "_recent_speaker_features": {},
        "_environment_vector": {},
        "_pending_questions": [],
        "_feedback_params": {},
        "_chronic_feedback_tracker": {},
        "_causal_observations": [],
        "_causal_associations": {},
        "_input_theme_data": {},
        # Runtime learner data (dicts that s01_init uses to reconstruct runtime objects)
        "_quenching_data": qt.to_dict(),
        "_strategy_map_data": sm.to_dict(),
        "_thermal_data": {},
        "_mirror_data": {},
        "_five_rights_data": {},
        "_semantic_analyzer_data": {},
        "_candidate_gen_data": {},
        "_behavior_profiler_data": {},
        "_decay_engine_data": {},
        "_cxg_data": {},
        "_rcxg_data": {},
        "_template_learner_data": {},
        "_clarification_memory_data": {},
        "_clarification_hints_data": {},
        "boredom_despair": 0.2,
        "boredom_futility": 0.1,
        "dopamine_tone": 0.5,
        "oxytocin_tone": 0.5,
        "emotion_particle_field": {},
        "emotion_accumulators": {},
        "last_emotion_tick": 1234567890.0,
        "joy": 0.0,
        "excitement": 0.0,
        "serenity": 0.0,
        "anger": 0.0,
        "fear": 0.0,
        "sadness": 0.0,
        "disgust": 0.0,
        "anxiety": 0.0,
        "surprise": 0.0,
        "_reading_taste_log": [],
        "_taste_evidence": [],
        "_concept_exposure_log": {},
        "_concept_learned_bias": {},
        "_preoccupations": [],
        "_last_reflection_tick": -10,
        "_self_narrative": "",
        "_reflection_log": [],
        "_narrative_bias": {},
        "_last_vjepa_tick": -201,
        "_jepa_surprise_density": 0.0,
        "_jepa_transition_indices": [],
    }
    defaults.update(overrides)
    return MockEntity(**defaults)


def _make_blank_entity():
    """空白 entity，模拟首次启动。"""
    return _make_entity_with_language_state(
        _warm_words={},
        _quenching_data={},
        _strategy_map_data={},
        _unlocked_vocabulary=[],
    )


# ============================================================================
# Test 1 — _warm_words 写入→读取往返（Fix 验证）
# ============================================================================

class TestWarmWordsPersistence:
    """验证 _warm_words 写入和读取的完整性。"""

    def test_warm_words_roundtrip(self, tmp_path):
        """写入后读出，_warm_words 内容一致。"""
        entity = _make_entity_with_language_state()
        path = tmp_path / "warm.json"

        persist_entity_to_file(entity, path)
        loaded = _make_blank_entity()
        ok = load_entity_from_file(loaded, path)

        assert ok, "load_entity_from_file 应返回 True"
        assert loaded._warm_words == entity._warm_words, (
            f"_warm_words 往返后不一致。"
            f"  原始: {entity._warm_words}"
            f"  读出: {loaded._warm_words}"
        )

    def test_warm_words_empty_roundtrip(self, tmp_path):
        """空 _warm_words 也能正常往返。"""
        entity = _make_entity_with_language_state(_warm_words={})
        path = tmp_path / "warm_empty.json"

        persist_entity_to_file(entity, path)
        loaded = _make_blank_entity()
        ok = load_entity_from_file(loaded, path)

        assert ok
        assert loaded._warm_words == {}

    def test_warm_words_json_direct(self, tmp_path):
        """直接读 JSON，确认字段名和结构正确。"""
        entity = _make_entity_with_language_state()
        path = tmp_path / "warm_direct.json"

        persist_entity_to_file(entity, path)
        raw = json.loads(path.read_text(encoding="utf-8"))

        assert "_warm_words" in raw, "_warm_words 应出现在 JSON 中"
        assert isinstance(raw["_warm_words"], dict), "_warm_words 应为 dict"
        assert "嗯" in raw["_warm_words"], "已知词应出现在 _warm_words"
        entry = raw["_warm_words"]["嗯"]
        assert "hits" in entry, "暖词条目应有 hits 字段"
        assert "avg_eff" in entry, "暖词条目应有 avg_eff 字段"


# ============================================================================
# Test 2 — _quenching_data 往返（回归测试）
# ============================================================================

class TestQuenchingDataPersistence:
    """验证 _quenching_data 往返（已知 OK，防止回归）。"""

    def test_quenching_data_roundtrip(self, tmp_path):
        """写入后读出，_quenching_data 内容一致。"""
        entity = _make_entity_with_language_state()
        path = tmp_path / "quench.json"

        persist_entity_to_file(entity, path)
        loaded = _make_blank_entity()
        ok = load_entity_from_file(loaded, path)

        assert ok
        assert loaded._quenching_data == entity._quenching_data, (
            f"_quenching_data 往返不一致。"
            f"  原始 records: {len(entity._quenching_data.get('records', []))}"
            f"  读出 records: {len(loaded._quenching_data.get('records', []))}"
        )

    def test_quenching_tracker_reconstructed_functional(self, tmp_path):
        """从 _quenching_data 重建 QuenchingTracker 后功能正常。"""
        entity = _make_entity_with_language_state()
        path = tmp_path / "quench_func.json"

        persist_entity_to_file(entity, path)
        loaded = _make_blank_entity()
        load_entity_from_file(loaded, path)

        # 重建 QuenchingTracker（模拟 s01_init 恢复）
        qt = QuenchingTracker.from_dict(loaded._quenching_data)
        assert qt is not None

        # 新增记录应追加到历史（非覆盖）
        initial_len = len(qt._history)
        qt.record(
            drive_state={"unresolved": 0.6},
            expression="新词",
            delta_unresolved_before=0.6,
            delta_unresolved_after=0.45,
            tick=999,
            template_idx=0,
        )
        assert len(qt._history) == initial_len + 1, "record 应追加到历史"

        # get_template_stats 应返回有效统计
        stats = qt.get_template_stats(seed_count=0)
        assert isinstance(stats, dict), f"get_template_stats 应返回 dict，实际: {type(stats)}"
        assert len(stats) > 0, "应有至少一个模板的统计"


# ============================================================================
# Test 3 — _strategy_map_data 往返（回归测试）
# ============================================================================

class TestStrategyMapPersistence:
    """验证 _strategy_map_data 往返（已知 OK，防止回归）。"""

    def test_strategy_map_roundtrip(self, tmp_path):
        """写入后读出，_strategy_map_data 内容一致。"""
        entity = _make_entity_with_language_state()
        path = tmp_path / "strmap.json"

        persist_entity_to_file(entity, path)
        loaded = _make_blank_entity()
        ok = load_entity_from_file(loaded, path)

        assert ok
        assert loaded._strategy_map_data == entity._strategy_map_data

    def test_strategy_map_reconstructed_functional(self, tmp_path):
        """从 _strategy_map_data 重建 StrategyMap 后功能正常。"""
        entity = _make_entity_with_language_state()
        path = tmp_path / "strmap_func.json"

        persist_entity_to_file(entity, path)
        loaded = _make_blank_entity()
        load_entity_from_file(loaded, path)

        sm = StrategyMap.from_dict(loaded._strategy_map_data)
        assert sm is not None

        # 新路径应可追加
        sm.record_path(
            {"fatigue": 0.7}, {"fatigue": 0.4},
            "休息", 0.7, "test_context",
        )
        assert len(sm._map) > 0


# ============================================================================
# Test 4 — s01_init 恢复链（QuenchingTracker.from_dict）
# ============================================================================

class TestS01InitRecoveryChain:
    """模拟 s01_init 的恢复逻辑，验证 QuenchingTracker.from_dict 正确重建。"""

    def test_quenching_from_quenching_data(self):
        """entity._quenching_data → QuenchingTracker.from_dict → 功能正常。"""
        qt_original = QuenchingTracker(history_maxlen=500)
        for i in range(5):
            qt_original.record(
                drive_state={"unresolved": 0.5 + i * 0.05},
                expression=["嗯", "哦", "好"][i % 3],
                delta_unresolved_before=0.5 + i * 0.05,
                delta_unresolved_after=0.35 + i * 0.05,
                tick=i,
                template_idx=i,
            )

        # 模拟 entity 存储
        class FakeEntity:
            _quenching_data = qt_original.to_dict()

        # 模拟 s01_init 恢复
        qt_restored = QuenchingTracker.from_dict(FakeEntity._quenching_data)
        assert len(qt_restored._history) == 5, (
            f"应重建 5 条记录，实际: {len(qt_restored._history)}"
        )

        # 验证效率查询可用（返回 Dict[int, float]）
        eff = qt_restored.get_template_efficiency(seed_count=0)
        assert isinstance(eff, dict), f"get_template_efficiency 应返回 dict，实际: {type(eff)}"
        assert len(eff) > 0, "应有至少一个模板的效率统计"

    def test_strategy_map_from_strategy_map_data(self):
        """entity._strategy_map_data → StrategyMap.from_dict → 功能正常。"""
        sm_original = StrategyMap()
        sm_original.record_path(
            {"loneliness": 0.6}, {"loneliness": 0.2}, "……", 0.55, "daemon",
        )
        sm_original.record_path(
            {"boredom": 0.8}, {"boredom": 0.4}, "无聊", 0.65, "daemon",
        )

        class FakeEntity:
            _strategy_map_data = sm_original.to_dict()

        sm_restored = StrategyMap.from_dict(FakeEntity._strategy_map_data)
        assert len(sm_restored._map) == 2


# ============================================================================
# Test 5 — 完整性：所有语言子系统字段往返一致
# ============================================================================

class TestAllLanguageFieldsRoundtrip:
    """验证所有语言系统相关字段的完整往返。"""

    def test_language_fields_complete_roundtrip(self, tmp_path):
        """所有语言系统字段写入后读出完全一致。"""
        entity = _make_entity_with_language_state()
        path = tmp_path / "lang_all.json"

        persist_entity_to_file(entity, path)
        loaded = _make_blank_entity()
        ok = load_entity_from_file(loaded, path)

        assert ok

        lang_fields = [
            "_unlocked_vocabulary",
            "_warm_words",
            "_quenching_data",
            "_strategy_map_data",
            "_thermal_data",
            "_mirror_data",
            "_five_rights_data",
            "_semantic_analyzer_data",
            "_candidate_gen_data",
            "_behavior_profiler_data",
            "_decay_engine_data",
            "_cxg_data",
            "_rcxg_data",
            "_template_learner_data",
            "_clarification_memory_data",
            "_clarification_hints_data",
        ]

        mismatches = []
        for field in lang_fields:
            orig = getattr(entity, field, None)
            rest = getattr(loaded, field, None)
            if orig != rest:
                mismatches.append(f"  {field}: 原始={orig!r}, 读出={rest!r}")

        assert not mismatches, "以下字段往返不一致:\n" + "\n".join(mismatches)


# ============================================================================
# 运行入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
