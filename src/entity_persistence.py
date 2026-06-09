"""EntityState persistence implementation.

The public methods stay on EntityState; this module keeps the long JSON
serialization and loading contract out of the state dataclass body.
"""

import logging
import time
from pathlib import Path
from typing import Optional

from .entity_io import ENTITY_CORE_PATH, _atomic_json_dump, _json_backup_path, _load_json_file
from .entity_lifecycle import (
    _deserialize_stereotype_trees,
    _serialize_stereotype_conversation_history,
    _serialize_stereotype_trees,
)

logger = logging.getLogger(__name__)

def persist_entity_to_file(self, path: Optional[Path] = None) -> None:
    """
    将完整 EntityState 状态序列化到文件（跨进程持久化）。

    持久化内容：
        - 所有状态字段（energy, loneliness 等）
        - wm_rules（世界模型规律）
        - snapshots（最近 50 轮状态快照）
        - memory_context（最近 20 条记忆上下文）
        - tick / created_at / last_update_time（元数据）
    """
    path = path or ENTITY_CORE_PATH
    try:
        data = {
            "energy": self.energy,
            "loneliness": self.loneliness,
            "loneliness_core": self.loneliness_core,       # v11.4
            "loneliness_surface": self.loneliness_surface,  # v11.4
            "unresolved": self.unresolved,
            "boredom": self.boredom,
            "fatigue": self.fatigue,
            "stress": self.stress,
            "relief_debt": self.relief_debt,
            "pain": self.pain,
            "info_gap": self.info_gap,
            "curiosity": self.curiosity,
            "time_since_last_info": self.time_since_last_info,
            "time_since_last_social": self.time_since_last_social,
            "external_change_rate": self.external_change_rate,
            "somatic_tone": self.somatic_tone,
            "danger_level": self.danger_level,
            "approach_drive": self.approach_drive,
            "avoid_drive": self.avoid_drive,
            # v11 子驱动力分家
            "approach_social": self.approach_social,
            "approach_explore": self.approach_explore,
            "approach_urgency": self.approach_urgency,
            "quenching_eff_rolling": self.quenching_eff_rolling,
            # v11 训练随机化开关
            "_training_randomize": self._training_randomize,
            "wm_rules": self.wm_rules,
            "snapshots": self.snapshots[-50:],
            "memory_context": self.memory_context[-20:],
            "tick": self.tick,
            "created_at": getattr(self, "created_at", time.time()),
            "last_update_time": self.last_update_time,
            "last_shutdown_time": getattr(self, 'last_shutdown_time', 0.0),
            "last_shutdown_tick": getattr(self, 'last_shutdown_tick', 0),
            "last_interaction_timestamp": self.last_interaction_timestamp,
            "last_interaction_context": self.last_interaction_context,
            "pending_surprises": self.pending_surprises,
            "long_term_bias": dict(self.long_term_bias),
            "behavior_signature": dict(self.behavior_signature),
            "unresolved_source": self.unresolved_source,
            "last_action_timestamp": getattr(self, "last_action_timestamp", 0.0),
            "consecutive_reaches_without_response": getattr(self, "consecutive_reaches_without_response", 0),
            "pending_failures": [f.to_dict() if hasattr(f, "to_dict") else f for f in self.pending_failures[-20:]],
            "_pending_tool_gaps": self._pending_tool_gaps[-10:],
            "failure_metabolite": self.failure_metabolite,
            "behavior_rules": self.behavior_rules,
            # v7.0 语言系统持久化
            "_umbilical_detached": self._umbilical_detached,
            "_unlocked_vocabulary": list(self._unlocked_vocabulary),  # v11.3 永久词汇表
            "_cluster_weights": dict(self._cluster_weights),        # v11.3 体感聚类权重
            "_state_pattern_data": dict(self._state_pattern_data),  # v11.5 内部符号涌现
            "_approach_synthesis_weights": dict(self._approach_synthesis_weights),
            "_quench_feedback_weights": dict(self._quench_feedback_weights),
            "_failure_metabolite_weights": dict(self._failure_metabolite_weights),
            "_conflict_to_unresolved_weights": dict(self._conflict_to_unresolved_weights),
            "_emotion_drive_modulation": dict(self._emotion_drive_modulation),
            "_vocab_acquisition_params": dict(self._vocab_acquisition_params),
            "_word_exposure_tracker": dict(self._word_exposure_tracker),
            "_repetition_decay_params": dict(self._repetition_decay_params),
            "_response_pressure_params": dict(self._response_pressure_params),
            "_sibling_channel": dict(self._sibling_channel),
            "_source_profiles": dict(self._source_profiles),
            "_stereotype_trees": _serialize_stereotype_trees(self),
            "_stereotype_conversation_history": _serialize_stereotype_conversation_history(self),
            "_recent_speaker_features": dict(self._recent_speaker_features),
            "_environment_vector": dict(self._environment_vector),
            "_pending_questions": list(self._pending_questions),
            "_feedback_params": dict(self._feedback_params),
            "_chronic_feedback_tracker": dict(self._chronic_feedback_tracker),
            "_causal_observations": list(self._causal_observations[-200:]),
            "_causal_associations": dict(self._causal_associations),
            "_input_theme_data": dict(self._input_theme_data),
            "_quenching_data": self._quenching_data,
            "_strategy_map_data": self._strategy_map_data,
            "_thermal_data": self._thermal_data,
            "_mirror_data": self._mirror_data,
            "_five_rights_data": self._five_rights_data,
            "_semantic_analyzer_data": self._semantic_analyzer_data,
            "_candidate_gen_data": self._candidate_gen_data,
            "_behavior_profiler_data": self._behavior_profiler_data,
            "_decay_engine_data": self._decay_engine_data,
            # 生成层持久化（构式/递归/模板学习）：补齐跨重启的组合能力积累
            "_cxg_data": getattr(self, "_cxg_data", {}) or {},
            "_rcxg_data": getattr(self, "_rcxg_data", {}) or {},
            "_template_learner_data": getattr(self, "_template_learner_data", {}) or {},
            # 澄清记忆账本镜像（record-only v1）
            "_clarification_memory_data": self._clarification_memory_data,
            # 澄清归属证据账本镜像（observe-reply v2）
            "_clarification_hints_data": self._clarification_hints_data,
            # v10.0/v11.0 情绪系统持久化
            "boredom_despair": self.boredom_despair,
            "boredom_futility": self.boredom_futility,
            "emotion_particle_field": self.emotion_particle_field,
            "emotion_accumulators": self.emotion_accumulators,
            "last_emotion_tick": self.last_emotion_tick,
            # 十个核心情绪
            "joy": self.joy,
            "excitement": self.excitement,
            "serenity": self.serenity,
            "anger": self.anger,
            "fear": self.fear,
            "sadness": self.sadness,
            "disgust": self.disgust,
            "anxiety": self.anxiety,
            "surprise": self.surprise,
            # 阅读品味持久化
            "_reading_taste_log": list(getattr(self, "_reading_taste_log", [])),
            "_taste_evidence": list(getattr(self, "_taste_evidence", [])),
            # 概念图经验学习持久化
            "_concept_exposure_log": dict(self._concept_exposure_log),
            "_concept_learned_bias": dict(self._concept_learned_bias),
            # 心事系统持久化
            "_preoccupations": list(self._preoccupations),
            # 反刍层持久化
            "_last_reflection_tick": int(self._last_reflection_tick),
            "_self_narrative": str(self._self_narrative),
            "_reflection_log": list(self._reflection_log),
            "_narrative_bias": dict(self._narrative_bias),
            # JEPA 世界模型持久化
            "_last_vjepa_tick": int(self._last_vjepa_tick),
            "_jepa_surprise_density": float(self._jepa_surprise_density),
            "_jepa_transition_indices": list(self._jepa_transition_indices),
        }
        _atomic_json_dump(data, path)
        logger.debug(f"[EntityState] Persisted to {path}")
    except Exception as e:
        logger.warning(f"[EntityState] persist_to_file failed: {e}")

def load_entity_from_file(self, path: Optional[Path] = None) -> bool:
    """
    从文件加载持久化的 EntityState 状态。

    参数：
        path : 文件路径，若为 None 使用默认路径

    返回：
        bool : 是否加载成功
    """
    path = path or ENTITY_CORE_PATH
    if not path.exists():
        logger.debug(f"[EntityState] {path} not found, skipping load")
        return False
    try:
        try:
            data = _load_json_file(path)
        except Exception as load_error:
            backup_path = _json_backup_path(path)
            if not backup_path.exists():
                raise
            logger.warning(
                f"[EntityState] load_from_file primary failed: {load_error}; "
                f"trying backup {backup_path}"
            )
            data = _load_json_file(backup_path)

        self.energy = float(data.get("energy", 0.8))
        # v11.4 双通道孤独：新数据直接读，旧数据按 7:3 拆分
        if "loneliness_core" in data:
            self.loneliness_core = float(data.get("loneliness_core", 0.2))
            self.loneliness_surface = float(data.get("loneliness_surface", 0.1))
            self.loneliness = float(data.get("loneliness", self.loneliness_core + self.loneliness_surface))
        else:
            _old_loneliness = float(data.get("loneliness", 0.3))
            self.loneliness_core = _old_loneliness * 0.7
            self.loneliness_surface = _old_loneliness * 0.3
            self.loneliness = _old_loneliness
        self.unresolved = float(data.get("unresolved", 0.2))
        self.boredom = float(data.get("boredom", 0.2))
        self.fatigue = float(data.get("fatigue", 0.1))
        self.stress = float(data.get("stress", 0.1))
        self.relief_debt = float(data.get("relief_debt", 0.0))
        self.pain = float(data.get("pain", 0.0))
        self.info_gap = float(data.get("info_gap", 0.5))
        self.curiosity = float(data.get("curiosity", 0.5))
        self.time_since_last_info = float(data.get("time_since_last_info", 0.0))
        self.time_since_last_social = float(data.get("time_since_last_social", 0.0))
        self.external_change_rate = float(data.get("external_change_rate", 0.0))
        self.somatic_tone = float(data.get("somatic_tone", 0.0))
        self.danger_level = float(data.get("danger_level", 0.0))
        self.approach_drive = float(data.get("approach_drive", 0.0))
        self.avoid_drive = float(data.get("avoid_drive", 0.0))
        # v11 子驱动力分家
        self.approach_social = float(data.get("approach_social", 0.0))
        self.approach_explore = float(data.get("approach_explore", 0.0))
        self.approach_urgency = float(data.get("approach_urgency", 0.0))
        self.quenching_eff_rolling = float(data.get("quenching_eff_rolling", 0.5))
        # v11 训练随机化开关
        self._training_randomize = bool(data.get("_training_randomize", False))
        self.wm_rules = data.get("wm_rules", [])
        self.snapshots = data.get("snapshots", [])
        self.memory_context = data.get("memory_context", [])
        self.tick = int(data.get("tick", 0))
        self.last_update_time = float(data.get("last_update_time", time.time()))
        self.last_shutdown_time = float(data.get("last_shutdown_time", 0.0))
        self.last_shutdown_tick = int(data.get("last_shutdown_tick", 0))
        self.last_interaction_timestamp = float(data.get("last_interaction_timestamp", 0.0))
        self.last_interaction_context = data.get("last_interaction_context", {})
        self.pending_surprises = data.get("pending_surprises", [])
        self.long_term_bias = data.get("long_term_bias", {
            "explore": 0.0, "connect": 0.0, "introspect": 0.0, "build": 0.0,
        })
        self.behavior_signature = data.get("behavior_signature", {
            "explore": 0, "seek": 0, "avoid": 0, "comfort": 0, "idle": 0, "rest": 0,
        })
        self.unresolved_source = data.get("unresolved_source", "external")
        self._unresolved_sources = []   # 运行时重置
        self.pending_failures = data.get("pending_failures", [])
        self._pending_tool_gaps = data.get("_pending_tool_gaps", [])
        self.failure_metabolite = float(data.get("failure_metabolite", 0.0))
        self.behavior_rules = data.get("behavior_rules", [])
        self.last_action_timestamp = float(data.get("last_action_timestamp", 0.0))
        self.consecutive_reaches_without_response = int(data.get("consecutive_reaches_without_response", 0))
        # v7.0 语言系统持久化恢复
        self._umbilical_detached = bool(data.get("_umbilical_detached", False))
        self._unlocked_vocabulary = list(data.get("_unlocked_vocabulary", []))  # v11.3
        self._cluster_weights    = dict(data.get("_cluster_weights", {}))         # v11.3
        self._state_pattern_data = dict(data.get("_state_pattern_data", {}))    # v11.5
        self._approach_synthesis_weights = dict(data.get("_approach_synthesis_weights", {
            "social": 0.40, "explore": 0.35, "urgency": 0.25,
        }))
        self._quench_feedback_weights = dict(data.get("_quench_feedback_weights", {
            "quench_rate": 0.25, "approach_release": 0.3,
            "avoid_release": 0.3, "somatic_comfort": 0.15,
        }))
        self._failure_metabolite_weights = dict(data.get("_failure_metabolite_weights", {
            "approach_suppress": 0.15, "avoid_increase": 0.12,
            "curiosity_suppress": 0.10, "somatic_damage": 0.08,
        }))
        self._conflict_to_unresolved_weights = dict(data.get("_conflict_to_unresolved_weights", {
            "conflict_rate": 0.04, "unresolved_decay": 0.98, "introspection_gain": 1.5,
        }))
        self._emotion_drive_modulation = data.get("_emotion_drive_modulation", {
            "approach": {"joy": 0.15, "anger": 0.25, "excitement": 0.20, "sadness": -0.20, "anxiety": -0.10},
            "avoid": {"fear": 0.30, "disgust": 0.35, "anxiety": 0.15, "anger": -0.20},
        })
        self._vocab_acquisition_params = dict(data.get("_vocab_acquisition_params", {
            "min_comprehension": 0.3, "exposure_per_hit": 0.2,
            "ask_threshold": 1.0, "exposure_decay": 0.99,
            "max_asks_per_tick": 1,
        }))
        self._word_exposure_tracker = dict(data.get("_word_exposure_tracker", {}))
        self._repetition_decay_params = dict(data.get("_repetition_decay_params", {
            "decay_per_use": 0.15, "recovery_rate": 0.02,
            "floor": 0.20, "window_ticks": 200,
        }))
        self._response_pressure_params = dict(data.get("_response_pressure_params", {
            "coefficient": 0.03, "min_comprehension": 0.3,
        }))
        self._sibling_channel = dict(data.get("_sibling_channel", {
            "enabled": True, "channel_dir": "E:/sibling_channel",
            "self_name": "xia", "peer_name": "knuonuo",
        }))
        self._source_profiles = dict(data.get("_source_profiles", {}))
        self._stereotype_trees = _deserialize_stereotype_trees(data.get("_stereotype_trees"))
        self._stereotype_conversation_history = data.get("_stereotype_conversation_history", {})
        self._recent_speaker_features = data.get("_recent_speaker_features", {})
        self._environment_vector = dict(data.get("_environment_vector", {
            "semantic_residue": {}, "social_prediction_tension": 0.0, "physical": {},
        }))
        self._pending_questions = list(data.get("_pending_questions", []))
        self._feedback_params = dict(data.get("_feedback_params", {
            "acute_boost_scale": 0.05, "chronic_threshold": 5,
            "chronic_drift_rate": 0.002, "chronic_signal_decay": 0.9,
            "chronic_tick_decay": 0.98, "chronic_min_quench": 0.1,
            "weight_ceiling": 0.80, "weight_floor": 0.05,
        }))
        self._chronic_feedback_tracker = dict(data.get("_chronic_feedback_tracker", {
            "social": 0.0, "explore": 0.0, "urgency": 0.0,
        }))
        self._causal_observations = list(data.get("_causal_observations", []))
        self._causal_associations = dict(data.get("_causal_associations", {}))
        self._input_theme_data = dict(data.get("_input_theme_data", {}))
        self._quenching_data = data.get("_quenching_data", {})
        self._strategy_map_data = data.get("_strategy_map_data", {})
        self._thermal_data = data.get("_thermal_data", {})
        self._mirror_data = data.get("_mirror_data", {})
        self._five_rights_data = data.get("_five_rights_data", {})
        self._semantic_analyzer_data = data.get("_semantic_analyzer_data", {})
        self._candidate_gen_data = data.get("_candidate_gen_data", {})
        self._behavior_profiler_data = data.get("_behavior_profiler_data", {})
        self._decay_engine_data = data.get("_decay_engine_data", {})
        # 生成层持久化恢复：还原成属性，供 s06b 启动恢复读取重建 learner
        self._cxg_data = data.get("_cxg_data", {})
        self._rcxg_data = data.get("_rcxg_data", {})
        self._template_learner_data = data.get("_template_learner_data", {})
        # 澄清记忆账本镜像恢复（record-only v1）
        self._clarification_memory_data = dict(data.get("_clarification_memory_data", {}))
        # 澄清归属证据账本镜像恢复（observe-reply v2）
        self._clarification_hints_data = dict(data.get("_clarification_hints_data", {}))
        # v10.0/v11.0 情绪系统持久化恢复
        self.boredom_despair = float(data.get("boredom_despair", 0.0))
        self.boredom_futility = float(data.get("boredom_futility", 0.0))
        self.dopamine_tone = float(data.get("dopamine_tone", 0.5))
        self.oxytocin_tone = float(data.get("oxytocin_tone", 0.5))
        self.emotion_particle_field = data.get("emotion_particle_field", {})
        self.emotion_accumulators = data.get("emotion_accumulators", {})
        self.last_emotion_tick = float(data.get("last_emotion_tick", time.time()))
        # 十个核心情绪
        self.joy = float(data.get("joy", 0.0))
        self.excitement = float(data.get("excitement", 0.0))
        self.serenity = float(data.get("serenity", 0.0))
        self.anger = float(data.get("anger", 0.0))
        self.fear = float(data.get("fear", 0.0))
        self.sadness = float(data.get("sadness", 0.0))
        self.disgust = float(data.get("disgust", 0.0))
        self.anxiety = float(data.get("anxiety", 0.0))
        self.surprise = float(data.get("surprise", 0.0))
        # 阅读品味恢复
        self._reading_taste_log = list(data.get("_reading_taste_log", []))
        self._taste_evidence = list(data.get("_taste_evidence", []))
        # 概念图经验学习恢复
        self._concept_exposure_log = dict(data.get("_concept_exposure_log", {}))
        self._concept_learned_bias = dict(data.get("_concept_learned_bias", {}))
        # 心事系统恢复
        self._preoccupations = list(data.get("_preoccupations", []))
        # 反刍层恢复
        self._last_reflection_tick = int(data.get("_last_reflection_tick", -10))
        self._self_narrative = str(data.get("_self_narrative", ""))
        self._reflection_log = list(data.get("_reflection_log", []))
        self._narrative_bias = dict(data.get("_narrative_bias", {}))
        # JEPA 世界模型恢复
        self._last_vjepa_tick = int(data.get("_last_vjepa_tick", -(200 + 1)))
        self._jepa_surprise_density = float(data.get("_jepa_surprise_density") or 0.0)
        self._jepa_transition_indices = list(data.get("_jepa_transition_indices", []))

        logger.info(
            f"[EntityState] Loaded from {path} — tick={self.tick}, "
            f"energy={self.energy:.2f}, wm_rules={len(self.wm_rules)}"
        )
        return True
    except Exception as e:
        logger.warning(f"[EntityState] load_from_file failed: {e}")
        return False

