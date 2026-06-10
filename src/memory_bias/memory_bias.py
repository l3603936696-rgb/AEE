"""
Memory Bias Module (记忆偏置层)

接收感性认识模块输出的 semantic_packet，读取记忆库中与当前情境相关的历史片段，
对原始的 emotion 和 intensity 进行微调，输出带记忆偏置的语义包。

输入：
    semantic_packet: 感性认识模块的输出
    memory_context: 历史样本列表（当前优先从外部存储预加载，降级用内存列表）

输出：
    semantic_packet_biased: 结构与输入完全一致，emotion 和 intensity 被微调

约束：
    - 纯函数，不写入任何状态
    - 任一环节失败直接透传原值
    - 不调用LLM

外部检索：
    - load_memories_to_entity() 在管线运行前异步预加载外部记忆
    - retrieve_memories() 优先查 TetraMem，降级读 memories_staged.json
"""

from dataclasses import dataclass, field
from typing import List
import math
import time


# ============================================================================
# 数据结构定义
# ============================================================================

@dataclass
class MemorySample:
    """记忆样本 — 纯情绪片段 + metadata扩展接口"""
    emotion: float                      # 情绪极性 [-1, 1]
    intent: str                         # 意图类型（主匹配维度）
    timestamp: float                    # 时间戳（Unix时间戳或秒）

    # 预留扩展字段：行为结果、来源标签等
    # 当前必须通过 metadata.get("outcome", ...) 读取，不能硬编码
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        """数值安全 clamp"""
        self.emotion = max(-1.0, min(1.0, self.emotion))


# ============================================================================
# Metadata 扩展常量（必须预定义，供调用方使用）
# ============================================================================

OUTCOME_POSITIVE = "positive"   # 正面结果：偏置放大系数 1.2
OUTCOME_NEGATIVE = "negative"  # 负面结果：偏置削弱系数 0.5
OUTCOME_NEUTRAL = "neutral"   # 中性结果：偏置系数 1.0


# ============================================================================
# 配置参数
# ============================================================================

# 基础偏置量（首条记忆的贡献上限）
BASE_BIAS = 0.15

# 边际递减率（控制后续记忆的影响力衰减速度）
DECAY_RATE = 0.5

# 时间衰减半衰期（小时）- 新鲜记忆权重更高
TIME_HALF_LIFE_HOURS = 24.0

# 启用时间衰减（可配置开关）
ENABLE_TIME_DECAY = True

# 偏置量硬上限
BIAS_CLAMP_MAX = 0.3
BIAS_CLAMP_MIN = -0.3

# 匹配样本数量上限
MAX_SAMPLES = 3

# outcome 调制系数
OUTCOME_MOD_POSITIVE = 1.2
OUTCOME_MOD_NEGATIVE = 0.5
OUTCOME_MOD_NEUTRAL = 1.0


# ============================================================================
# 核心计算函数
# ============================================================================

def _get_direction(current_emotion: float, sample_emotion: float) -> float:
    """
    计算偏置方向系数

    规则：
    - 当前情绪非零：同向返回 +1.0，反向返回 -1.0
    - 当前情绪为零：方向完全由样本决定（样本正→+1，样本负→-1，样本零→0）
    """
    if abs(current_emotion) < 1e-6:
        # 当前情绪为零，由样本决定方向
        if abs(sample_emotion) < 1e-6:
            return 0.0
        return 1.0 if sample_emotion > 0 else -1.0
    else:
        # 当前情绪非零，判断是否同向
        return 1.0 if (current_emotion * sample_emotion) > 0 else -1.0


def _get_outcome_mod(metadata: dict) -> float:
    """
    从 metadata 读取 outcome 并返回调制系数

    必须通过 metadata.get("outcome", ...) 读取，即使数据为空
    """
    outcome = metadata.get("outcome", OUTCOME_NEUTRAL)

    if outcome == OUTCOME_POSITIVE:
        return OUTCOME_MOD_POSITIVE
    elif outcome == OUTCOME_NEGATIVE:
        return OUTCOME_MOD_NEGATIVE
    else:
        return OUTCOME_MOD_NEUTRAL


def _get_time_weight(timestamp: float) -> float:
    """
    计算时间衰减权重

    使用指数衰减：weight = exp(-age_hours / half_life)
    """
    if not ENABLE_TIME_DECAY:
        return 1.0

    current_time = time.time()
    age_hours = (current_time - timestamp) / 3600.0

    if age_hours < 0:
        return 1.0

    return math.exp(-age_hours / TIME_HALF_LIFE_HOURS)


def _calculate_bias(current_emotion: float, matched_samples: List[MemorySample]) -> float:
    """
    偏置量计算

    公式：bias = Σ [ direction_i × |sample_emotion| × decay_i × time_weight_i × outcome_mod_i ]

    参数：
        current_emotion: 当前输入的情绪值
        matched_samples: 匹配的历史样本列表

    返回：
        偏置量，范围 [-0.3, 0.3]
    """
    if not matched_samples:
        return 0.0

    total_bias = 0.0

    for i, sample in enumerate(matched_samples):
        # 1. 方向系数（当前情绪为零时由样本决定）
        direction = _get_direction(current_emotion, sample.emotion)

        # 2. 历史情绪强度作为权重
        emotion_weight = abs(sample.emotion)

        # 3. 边际递减：1 / (1 + i * decay_rate)
        decay = 1.0 / (1.0 + i * DECAY_RATE)

        # 4. 时间衰减
        time_weight = _get_time_weight(sample.timestamp)

        # 5. outcome 调制系数（必须从 metadata 读取）
        outcome_mod = _get_outcome_mod(sample.metadata)

        # 计算该项贡献
        contribution = direction * emotion_weight * decay * time_weight * outcome_mod

        # 归一化到基础偏置量
        contribution *= BASE_BIAS

        total_bias += contribution

    # clamp 到硬约束范围
    return max(BIAS_CLAMP_MIN, min(BIAS_CLAMP_MAX, total_bias))


def _match_samples(semantic_packet: dict, memory_context: List) -> List[MemorySample]:
    """
    匹配历史样本

    规则：
    1. 按 intent 类型过滤（主匹配维度）
    2. 按时间倒序（最新优先）
    3. 最多取 MAX_SAMPLES 条
    """
    current_intent = semantic_packet.get("intent", "")

    # 过滤并转换
    matched = []
    for item in memory_context:
        # 支持 dict 或 MemorySample
        if isinstance(item, dict):
            if item.get("intent") == current_intent:
                matched.append(MemorySample(
                    emotion=item.get("emotion", 0.0),
                    intent=item.get("intent", ""),
                    timestamp=item.get("timestamp", 0.0),
                    metadata=item.get("metadata", {})
                ))
        elif isinstance(item, MemorySample):
            if item.intent == current_intent:
                matched.append(item)

    # 按时间倒序（最新优先）
    matched.sort(key=lambda x: x.timestamp, reverse=True)

    # 限制数量
    return matched[:MAX_SAMPLES]


def _calculate_intensity_delta(bias: float, current_intensity: float) -> float:
    """
    计算 intensity 调整量

    公式：intensity_delta = abs(bias) * 0.3 * (1.0 + (1.0 - current_intensity) * 0.5)

    当前强度越低，越容易被情绪偏置影响
    """
    modulation = 1.0 + (1.0 - current_intensity) * 0.5
    return abs(bias) * 0.3 * modulation


# ============================================================================
# 主入口函数
# ============================================================================

def apply_memory_bias(semantic_packet: dict, memory_context: list) -> dict:
    """
    记忆偏置层主入口

    唯一对外接口

    参数：
        semantic_packet: 感性认识模块输出
            {
                "emotion": float,      # [-1, 1]
                "intent": str,
                "intensity": float,    # (0, 1]
                "anchors": list
            }
        memory_context: 历史样本列表（dict 或 MemorySample）

    返回：
        semantic_packet_biased: 偏置后的语义包
            结构与输入完全一致

    约束：
        - memory_context 为空 → 直接透传
        - 任一环节失败 → 直接透传原值
        - 纯函数，不写入状态
    """
    try:
        # 边界检查
        if not semantic_packet or not isinstance(semantic_packet, dict):
            return semantic_packet

        if not memory_context or not isinstance(memory_context, list):
            return semantic_packet.copy() if isinstance(semantic_packet, dict) else semantic_packet

        # 提取当前值
        current_emotion = float(semantic_packet.get("emotion", 0.0))
        current_intensity = float(semantic_packet.get("intensity", 0.5))

        # 匹配样本
        matched_samples = _match_samples(semantic_packet, memory_context)

        if not matched_samples:
            return semantic_packet.copy() if isinstance(semantic_packet, dict) else semantic_packet

        # 计算偏置量
        bias = _calculate_bias(current_emotion, matched_samples)

        # 计算新的 emotion
        new_emotion = current_emotion + bias
        new_emotion = max(-1.0, min(1.0, new_emotion))

        # 计算 intensity 调整量
        intensity_delta = _calculate_intensity_delta(bias, current_intensity)
        new_intensity = current_intensity + intensity_delta
        new_intensity = max(0.1, min(1.0, new_intensity))

        # 构建输出（保持原始结构不变）
        result = semantic_packet.copy()
        result["emotion"] = round(new_emotion, 3)
        result["intensity"] = round(new_intensity, 3)

        # 标注偏置来源（可选，便于调试）
        # result["_bias_meta"] = {
        #     "bias": round(bias, 3),
        #     "matched_count": len(matched_samples),
        #     "sample_intents": [s.intent for s in matched_samples]
        # }

        return result

    except Exception:
        # 任一环节失败，直接透传原值
        return semantic_packet.copy() if isinstance(semantic_packet, dict) else semantic_packet


# ============================================================================
# 外部记忆预加载（供 entity_zero_iteration 调用）
# ============================================================================

async def load_memories_to_entity(
    entity,
    intent: str,
    emotion: float,
    limit: int = 5,
) -> int:
    """
    从外部存储加载相关记忆到 entity.memory_context。

    优先从 TetraMem 检索，降级读 memories_staged.json，
    同时从 episodes.db 补充最近高重要性经验。

    参数：
        entity : EntityState 实例
        intent : 当前意图类型
        emotion : 当前情绪极性
        limit  : 各来源分别取几条

    返回：
        int : 加载的记忆条数
    """
    try:
        from ..memory_hub import retrieve_memories as _retrieve_memories
        from ..memory_hub.episodes_db import get_recent_episodes
    except Exception:
        return 0

    loaded = 0

    # 路径 1: TetraMem / memories_staged.json 检索
    try:
        staged = await _retrieve_memories(intent=intent, emotion=emotion, limit=limit)
        for item in staged:
            entity.add_memory_sample({
                "emotion": float(item.get("emotion", 0.0)),
                "intent": str(item.get("intent", "")),
                "timestamp": float(item.get("timestamp", 0.0)),
                "metadata": item.get("metadata", {}),
            })
            loaded += 1
    except Exception:
        pass

    # 路径 2: episodes.db 补充最近高重要性记忆
    try:
        recent = get_recent_episodes(limit=limit, min_importance=0.3)
        for ep in recent:
            semantic = ep.semantic_packet_biased or {}
            entity.add_memory_sample({
                "emotion": float(semantic.get("emotion", 0.0)),
                "intent": str(semantic.get("intent", "")),
                "timestamp": ep.iteration_id * 3600.0,  # 用 iteration 估算时间戳
                "metadata": {
                    "content": ep.raw_input or "",
                    "outcome": "neutral",
                    "weight": ep.importance,
                    "source": "episodes",
                },
            })
            loaded += 1
    except Exception:
        pass

    return loaded

if __name__ == "__main__":
    import time

    print("=" * 60)
    print("记忆偏置层测试")
    print("=" * 60)

    # 测试用例
    test_cases = [
        {
            "name": "同向记忆放大（基础）",
            "input": {"emotion": 0.5, "intent": "分享", "intensity": 0.6, "anchors": []},
            "memory": [
                {"emotion": 0.4, "intent": "分享", "timestamp": time.time() - 3600, "metadata": {}},
            ],
            "expected_bias": "正向"
        },
        {
            "name": "反向记忆抑制",
            "input": {"emotion": 0.5, "intent": "分享", "intensity": 0.6, "anchors": []},
            "memory": [
                {"emotion": -0.4, "intent": "分享", "timestamp": time.time() - 3600, "metadata": {}},
            ],
            "expected_bias": "负向"
        },
        {
            "name": "边际递减（多条同向）",
            "input": {"emotion": 0.5, "intent": "分享", "intensity": 0.6, "anchors": []},
            "memory": [
                {"emotion": 0.8, "intent": "分享", "timestamp": time.time() - 3600, "metadata": {}},
                {"emotion": 0.6, "intent": "分享", "timestamp": time.time() - 7200, "metadata": {}},
                {"emotion": 0.4, "intent": "分享", "timestamp": time.time() - 10800, "metadata": {}},
            ],
            "expected_bias": "接近+0.3但不触顶"
        },
        {
            "name": "零值情绪由历史决定",
            "input": {"emotion": 0.0, "intent": "求助", "intensity": 0.5, "anchors": []},
            "memory": [
                {"emotion": -0.5, "intent": "求助", "timestamp": time.time() - 3600, "metadata": {}},
            ],
            "expected_bias": "负向（被历史引导）"
        },
        {
            "name": "outcome=positive 放大",
            "input": {"emotion": 0.3, "intent": "分享", "intensity": 0.5, "anchors": []},
            "memory": [
                {"emotion": 0.5, "intent": "分享", "timestamp": time.time() - 3600, "metadata": {"outcome": "positive"}},
            ],
            "expected_bias": "正向放大（1.2倍）"
        },
        {
            "name": "outcome=negative 削弱",
            "input": {"emotion": 0.3, "intent": "分享", "intensity": 0.5, "anchors": []},
            "memory": [
                {"emotion": 0.5, "intent": "分享", "timestamp": time.time() - 3600, "metadata": {"outcome": "negative"}},
            ],
            "expected_bias": "正向但被削弱（0.5倍）"
        },
        {
            "name": "空记忆透传",
            "input": {"emotion": 0.8, "intent": "分享", "intensity": 0.7, "anchors": []},
            "memory": [],
            "expected_bias": "透传不变"
        },
        {
            "name": "不同intent不匹配",
            "input": {"emotion": 0.5, "intent": "求助", "intensity": 0.6, "anchors": []},
            "memory": [
                {"emotion": 0.9, "intent": "分享", "timestamp": time.time() - 3600, "metadata": {}},
            ],
            "expected_bias": "透传不变（intent不匹配）"
        },
    ]

    for i, tc in enumerate(test_cases, 1):
        print(f"\n【测试 {i}】{tc['name']}")
        print(f"  输入: emotion={tc['input']['emotion']}, intent={tc['input']['intent']}")

        result = apply_memory_bias(tc["input"], tc["memory"])

        print(f"  输出: emotion={result['emotion']}, intensity={result['intensity']}")
        print(f"  期望: {tc['expected_bias']}")

        emotion_changed = abs(result['emotion'] - tc['input']['emotion']) > 1e-6
        intensity_changed = abs(result['intensity'] - tc['input']['intensity']) > 1e-6
        print(f"  emotion变化: {'是' if emotion_changed else '否'}, intensity变化: {'是' if intensity_changed else '否'}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
