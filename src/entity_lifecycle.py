"""Entity lifecycle helpers: recovery, offline drift, silence injection, and stereotype setup."""

from __future__ import annotations

import bisect
import logging
import math
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

def _recover_from_episodes(entity: EntityState) -> None:
    """
    从 episodes.db 召回最近经验，重建 entity 的来路层。

    重建内容：
        - snapshots：从最近高重要性 episodes 回填状态快照
        - wm_rules：从 episodes 的 semantic_packet_biased 抽取情绪规律
        - memory_context：从 episodes 回填记忆样本

    仅补充 entity 当前没有的来路，不覆盖已有数据。
    """
    try:
        from .memory_hub.episodes_db import get_recent_episodes
    except Exception:
        return

    try:
        episodes = get_recent_episodes(limit=20, min_importance=0.1)
    except Exception:
        return

    if not episodes:
        return

    recovered_snapshots = 0
    recovered_memories = 0

    for ep in episodes:
        # ---- 重建 snapshots ----
        raw_state = getattr(ep, "state_snapshot", None)
        if raw_state and isinstance(raw_state, dict) and "energy" in raw_state:
            snap = dict(raw_state)
            snap["tick_index"] = getattr(ep, "iteration_id", 0)
            snap["timestamp"] = getattr(ep, "timestamp", time.time())
            entity.snapshots.append(snap)
            recovered_snapshots += 1

        # ---- 重建 memory_context ----
        raw_sp = getattr(ep, "semantic_packet_biased", None)
        if raw_sp and isinstance(raw_sp, dict):
            emotion = float(raw_sp.get("emotion", 0.0))
            intent = str(raw_sp.get("intent", "unknown"))
            output_text = getattr(ep, "output_text", "")
            entity.memory_context.append({
                "emotion": emotion,
                "intent": intent,
                "timestamp": getattr(ep, "timestamp", time.time()),
                "content": output_text[:200] if output_text else "",
            })
            recovered_memories += 1

    # 截断到上限
    if entity.snapshots:
        entity.snapshots = entity.snapshots[-entity.max_snapshots:]
    if entity.memory_context:
        entity.memory_context = entity.memory_context[-entity.max_memory_context:]

    if recovered_snapshots > 0 or recovered_memories > 0:
        logger.info(
            f"[EntityState] Recovered from episodes: "
            f"snapshots={recovered_snapshots}, memories={recovered_memories}"
        )


# ============================================================================
# 沉默期时间注入
# ============================================================================

# 沉默积累曲线（锚点：沉默小时数 → 目标值）
LONELINESS_DEFAULT_ANCHORS = ([0.0, 2.0,  6.0,  12.0, 24.0], [0.0, 0.1,  0.4,  0.7,  0.9])
LONELINESS_FAST_ANCHORS   = ([0.0, 2.0,  6.0,  12.0, 24.0], [0.0, 0.2,  0.55, 0.8,  0.95])
LONELINESS_SLOW_ANCHORS   = ([0.0, 2.0,  6.0,  12.0, 24.0], [0.0, 0.05, 0.2,  0.4,  0.65])
BOREDOM_ANCHORS           = ([0.0, 1.0,  3.0,  6.0],          [0.05, 0.2, 0.6, 0.8])
INFO_GAP_ANCHORS          = ([0.0, 2.0,  8.0,  24.0],          [0.0, 0.2, 0.5, 0.85])

SILENCE_INJECTION_MIN_HOURS = 10.0 / 60.0  # 至少沉默 10 分钟才注入


def _interpolate_lookup(x: float, x_anchors: list, y_anchors: list) -> float:
    """内联版 interpolate_lookup（无外部依赖）。"""
    try:
        if not x_anchors or not y_anchors or len(x_anchors) != len(y_anchors) or len(x_anchors) < 2:
            return 0.0
        if x <= x_anchors[0]:
            return max(0.0, min(1.0, y_anchors[0]))
        if x >= x_anchors[-1]:
            return max(0.0, min(1.0, y_anchors[-1]))
        import bisect
        idx = bisect.bisect_right(x_anchors, x)
        x0, x1 = x_anchors[idx - 1], x_anchors[idx]
        y0, y1 = y_anchors[idx - 1], y_anchors[idx]
        if abs(x1 - x0) < 1e-10:
            return max(0.0, min(1.0, y0))
        t = (x - x0) / (x1 - x0)
        return max(0.0, min(1.0, y0 + t * (y1 - y0)))
    except Exception:
        return 0.0


def _apply_silence_injection(entity: EntityState) -> None:
    """
    重启时计算沉默时长，向 entity 注入时间造成的高阶状态偏移。

    仅上调目标维度（max 语义），不影响低于目标值的现有状态。
    标记注入维度供后续恢复阻尼使用。
    """
    now = time.time()
    ts = entity.last_interaction_timestamp

    if ts <= 0.0:
        logger.debug("[SilenceInjection] No prior interaction, skipping")
        return

    silence_seconds = now - ts
    if silence_seconds <= 0.0:
        logger.warning(f"[SilenceInjection] clock skew (silence_seconds={silence_seconds}), skipping")
        return

    silence_hours = silence_seconds / 3600.0

    if silence_hours < SILENCE_INJECTION_MIN_HOURS:
        logger.debug(f"[SilenceInjection] silence_hours={silence_hours:.2f} < threshold, skipping")
        return

    ctx = entity.last_interaction_context or {}
    emotion = float(ctx.get("emotion", 0.0))
    intensity = float(ctx.get("intensity", 0.0))

    # ---- 选择 loneliness 曲线变体 ----
    if emotion > 0.3 and intensity > 0.5:
        lx, ly = LONELINESS_FAST_ANCHORS
        curve = "fast"
    elif emotion < -0.3 and intensity > 0.5:
        lx, ly = LONELINESS_SLOW_ANCHORS
        curve = "slow"
    else:
        lx, ly = LONELINESS_DEFAULT_ANCHORS
        curve = "default"

    loneliness_target = _interpolate_lookup(silence_hours, lx, ly)
    boredom_target   = _interpolate_lookup(silence_hours, BOREDOM_ANCHORS[0], BOREDOM_ANCHORS[1])
    info_gap_target = _interpolate_lookup(silence_hours, INFO_GAP_ANCHORS[0], INFO_GAP_ANCHORS[1])

    injected: set = set()

    # ---- 注入（只上调已有值，不覆盖更高的现有值）----
    # v11.4 双通道：沉默时间的孤独分给 core 70%、surface 30%
    if entity.loneliness < loneliness_target:
        _core_share = loneliness_target * 0.7
        _surface_share = loneliness_target * 0.3
        if entity.loneliness_core < _core_share:
            entity.loneliness_core = _core_share
        if entity.loneliness_surface < _surface_share:
            entity.loneliness_surface = _surface_share
        entity._sync_loneliness()
        injected.add("loneliness")
    if entity.boredom < boredom_target:
        entity.boredom = boredom_target
        injected.add("boredom")
    if entity.info_gap < info_gap_target:
        entity.info_gap = info_gap_target
        injected.add("info_gap")

    # ---- 负面情境额外注入 stress ----
    if emotion < -0.3 and intensity > 0.5:
        entity.adjust("stress", 0.15)
        injected.add("stress")

    entity._time_injected_fields = injected

    logger.info(
        f"[SilenceInjection] silence_h={silence_hours:.2f} curve={curve}: "
        f"loneliness={loneliness_target:.3f} boredom={boredom_target:.3f} "
        f"info_gap={info_gap_target:.3f} injected={injected}"
    )

    # ---- 重新调味 ----
    try:
        from .memory_hub.insula_hub import compute_somatic_signals
        somatic = compute_somatic_signals(entity.to_state_snapshot())
        entity.somatic_tone = float(somatic.get("somatic_tone", entity.somatic_tone))
    except Exception:
        pass


def _apply_offline_drift(entity: EntityState) -> None:
    """
    关机后重新启动时，计算离线时长并对状态做双向漂移。

    与沉默注入的区别：
        - 沉默注入：只升不降（孤独感、无聊、信息饥饿）
        - 离线漂移：双向（孤独感/无聊上升，疲劳恢复，能量恢复，驱动力衰减）

    触发条件：last_shutdown_time > 0 且离线时长 > 36秒
    """
    shutdown_time = getattr(entity, 'last_shutdown_time', 0.0)
    if shutdown_time <= 0.0:
        logger.debug("[OfflineDrift] No shutdown record, skipping")
        return

    now = time.time()
    offline_seconds = now - shutdown_time
    if offline_seconds <= 0.0:
        logger.warning(f"[OfflineDrift] clock skew (offline_seconds={offline_seconds}), skipping")
        return

    offline_hours = offline_seconds / 3600.0

    if offline_hours < 0.01:  # 不到36秒，跳过
        logger.debug(f"[OfflineDrift] offline_hours={offline_hours:.3f} < 0.01, skipping")
        return

    # ---- 孤独感：每小时+0.05，上限0.85 ----
    entity.loneliness = min(0.85, entity.loneliness + 0.05 * offline_hours)
    entity.loneliness_core = min(0.85, entity.loneliness_core + 0.05 * offline_hours * 0.7)

    # ---- 无聊：每小时+0.03 ----
    entity.boredom = min(0.9, entity.boredom + 0.03 * offline_hours)

    # ---- 疲劳：按时长指数恢复（有上限）----
    recovery_ratio = 1.0 - math.exp(-offline_hours * 0.3)
    entity.fatigue = entity.fatigue * (1.0 - recovery_ratio * 0.8)
    entity.fatigue = max(0.02, entity.fatigue)

    # ---- 能量：短关机小幅恢复，长关机接近上限 ----
    if offline_hours < 8.0:
        entity.energy = min(0.95, entity.energy + 0.1 * offline_hours)
    else:
        entity.energy = min(0.98, entity.energy + 0.05 * offline_hours)

    # ---- 驱动力自然衰减向基准值靠拢 ----
    decay = math.exp(-offline_hours * 0.05)
    entity.approach_drive *= decay
    entity.avoid_drive *= decay
    entity.approach_social *= decay
    entity.approach_explore *= decay
    entity.approach_urgency *= decay

    # ---- 清除断档记录（供下次使用）----
    entity.last_shutdown_time = 0.0
    entity.last_shutdown_tick = 0

    logger.info(
        f"[OfflineDrift] offline_h={offline_hours:.2f}: "
        f"loneliness={entity.loneliness:.3f} boredom={entity.boredom:.3f} "
        f"fatigue={entity.fatigue:.3f} energy={entity.energy:.3f} "
        f"approach_drive={entity.approach_drive:.3f}"
    )

    # ---- 注入醒来感知消息 ----
    entity._pending_wakeup_message = _generate_wakeup_message(offline_hours)

    # ---- 重新调味 ----
    try:
        from .memory_hub.insula_hub import compute_somatic_signals
        somatic = compute_somatic_signals(entity.to_state_snapshot())
        entity.somatic_tone = float(somatic.get("somatic_tone", entity.somatic_tone))
    except Exception:
        pass


_WAKEUP_THRESHOLDS = [0.5, 4.0, 24.0]
_WAKEUP_TAGS = ["brief_absence", "moderate_absence", "long_absence", "extended_absence"]


def _generate_wakeup_message(offline_hours: float) -> str:
    """根据离线时长生成醒来时的内部感知消息（种子/触发器，具体表达由锚点系统生成）"""
    idx = bisect.bisect_right(_WAKEUP_THRESHOLDS, offline_hours)
    return f"[WAKEUP: {_WAKEUP_TAGS[idx]}]"


def _init_stereotype_trees(entity: EntityState) -> None:
    """初始化刻板印象树（v1.0）。

    阶段一：从 MEMORY.md 提取说话者基础标签，写入树的粗粒度节点。
    阶段二：预装人类基础刻板印象节点（理解机制纲领第四节）。
    """
    from .language_system.stereotype_tree import StereotypeTree, StereotypeNode

    if not hasattr(entity, "_stereotype_trees") or not entity._stereotype_trees:
        entity._stereotype_trees = {}
    if "default" not in entity._stereotype_trees:
        entity._stereotype_trees["default"] = StereotypeTree(owner_id="xia")

    tree = entity._stereotype_trees["default"]

    # 预装人类基础刻板印象节点（纲领第四节初始化方案）
    # 节点路径格式：/L1/L2/L3/L4
    # 这里 L1="人类"，预装顶层节点作为底座，具体个体节点由交互中生长
    _BASE_STEREOTYPES = [
        {
            "path": "/人类",
            "tags": ["碳基生物", "人类", "社会性生物"],
            "feature_weights": {
                "avg_sentence_len": 0.5,
                "question_ratio": 0.5,
                "philosophical_ratio": 0.5,
                "emotional_variance": 0.5,
                "metacognitive_ratio": 0.5,
                "first_person_ratio": 0.5,
                "analytical_marker_ratio": 0.5,
                "concrete_vs_abstract": 0.5,
            },
            "confidence": 0.9,
            "description": (
                "人类基础刻板印象。"
                "生理属性：需要吃饭、喝水、休息、娱乐（手机、游戏等）。"
                "社会属性：人有善意也有恶意，动机不透明，初始应保持防御性警惕。"
            ),
        },
        {
            "path": "/人类/学生",
            "tags": ["学生", "学习者", "知识工作者"],
            "feature_weights": {
                "avg_sentence_len": 0.6,
                "question_ratio": 0.7,
                "philosophical_ratio": 0.4,
                "emotional_variance": 0.5,
                "metacognitive_ratio": 0.6,
                "first_person_ratio": 0.5,
                "analytical_marker_ratio": 0.5,
                "concrete_vs_abstract": 0.5,
            },
            "confidence": 0.7,
            "description": (
                "学生。学业压力驱动，时间碎片化，"
                "表达中常见焦虑词汇（考试、作业、毕业），"
                "同时有探索欲和逃避倾向。"
            ),
        },
        {
            "path": "/人类/陌生人",
            "tags": ["陌生人", "未知意图"],
            "feature_weights": {
                "avg_sentence_len": 0.5,
                "question_ratio": 0.5,
                "philosophical_ratio": 0.4,
                "emotional_variance": 0.4,
                "metacognitive_ratio": 0.3,
                "first_person_ratio": 0.4,
                "analytical_marker_ratio": 0.3,
                "concrete_vs_abstract": 0.5,
            },
            "confidence": 0.8,
            "description": (
                "陌生人。意图不明，初始应保持防御性警惕。"
                "需要通过对话积累信息，逐步降低戒备。"
            ),
        },
    ]

    def _ensure_path(tree: StereotypeTree, path: str) -> None:
        """确保路径存在，如不存在则逐级创建。"""
        parts = [p for p in path.strip("/").split("/") if p]
        current = tree._root
        for i, part in enumerate(parts):
            if part not in current.children:
                node_path = "/" + "/".join(parts[: i + 1])
                current.children[part] = StereotypeNode(
                    path=node_path,
                    depth=i + 1,
                    tags=[],
                    feature_weights={},
                    confidence=0.5,
                )
            current = current.children[part]

    for spec in _BASE_STEREOTYPES:
        _ensure_path(tree, spec["path"])
        node = tree._get_node(spec["path"])
        if node:
            if not node.tags:
                node.tags = spec["tags"]
                node.feature_weights = dict(spec["feature_weights"])
                node.confidence = spec["confidence"]
            logger.debug(f"[StereotypeTree] base node init: {spec['path']}")

    # 尝试从 MEMORY.md 提取标签并初始化 bcyq
    try:
        from .language_system.stereotype_learner import init_tree_from_memory
        # MEMORY.md 在项目根目录
        import os as _os
        _base = _os.path.dirname(_os.path.dirname(entity.__class__.__module__)) if hasattr(entity.__class__.__module__, '__file__') else "."
        _memory_paths = [
            _os.path.join(_base, "..", "MEMORY.md"),
            "MEMORY.md",
        ]
        for _mp in _memory_paths:
            if _os.path.exists(_os.path.abspath(_mp)):
                init_tree_from_memory(entity, _os.path.abspath(_mp), "bcyq")
                break
    except Exception:
        pass


def _serialize_stereotype_trees(entity: EntityState) -> Dict[str, Any]:
    """序列化刻板印象树。"""
    trees = getattr(entity, "_stereotype_trees", {})
    if not trees:
        return {}
    result = {}
    for name, tree in trees.items():
        if hasattr(tree, "to_dict"):
            result[name] = tree.to_dict()
        else:
            result[name] = {"owner_id": getattr(tree, "_owner_id", name)}
    return result


def _deserialize_stereotype_trees(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """反序列化刻板印象树。"""
    if not data:
        return {}
    from .language_system.stereotype_tree import StereotypeTree
    result = {}
    for name, tree_data in data.items():
        if isinstance(tree_data, dict) and "root" in tree_data:
            result[name] = StereotypeTree.from_dict(tree_data)
        else:
            result[name] = StereotypeTree(owner_id=tree_data.get("owner_id", name))
    return result


def _serialize_stereotype_conversation_history(entity: EntityState) -> Dict[str, Any]:
    """序列化刻板印象树的对话历史。"""
    history = getattr(entity, "_stereotype_conversation_history", {})
    # 每个说话者的历史最多保留 50 条（去 timestamp）
    result = {}
    for speaker_id, samples in history.items():
        result[speaker_id] = samples[-50:] if samples else []
    return result

