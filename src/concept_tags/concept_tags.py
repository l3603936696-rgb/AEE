"""
Concept Tags Module (轻量标签映射层)

接收记忆偏置层输出的 semantic_packet_biased，将意图、情绪、强度、锚点
映射为结构化的概念标签。

输入：
    semantic_packet_biased: dict，来自记忆偏置层
        - intent: str
        - emotion: float [-1, 1]
        - intensity: float (0, 1]
        - anchors: list
        - intent_confidence: float (可选，默认0.8)

输出：
    list[dict] — 概念标签列表，如：
        [
            {"tag": "求助", "category": "intent", "confidence": 0.9},
            {"tag": "负面情绪", "category": "emotion", "confidence": 0.75, "raw_emotion": -0.75},
            {"tag": "高强度", "category": "intensity", "confidence": 0.88}
        ]

约束：
    - 纯函数，不访问内部状态/记忆/世界模型
    - 不调用LLM
    - 任一环节失败返回空列表[]
    - 不生成规则之外的新标签
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# 意图标签映射
# ============================================================================

# intent → tag 直接映射表（可按需扩展）
INTENT_TAG_MAP: Dict[str, str] = {
    "求助": "求助",
    "分享": "分享",
    "挑战": "挑战",
    "闲聊": "闲聊",
    "抱怨": "抱怨",
    "指令": "指令",
}


def _map_intent(semantic_packet: dict) -> List[dict]:
    """
    intent → intent标签

    规则：
    - 直接映射，confidence取 semantic_packet["intent_confidence"]，无此字段默认0.8
    """
    intent = semantic_packet.get("intent", "")
    confidence = semantic_packet.get("intent_confidence", 0.8)

    if intent in INTENT_TAG_MAP:
        tag = INTENT_TAG_MAP[intent]
        return [{"tag": tag, "category": "intent", "confidence": confidence}]
    return []


# ============================================================================
# 情绪标签映射
# ============================================================================

# emotion → emotion标签映射
EMOTION_THRESHOLD_NEG = -0.3
EMOTION_THRESHOLD_POS = 0.3


def _map_emotion(semantic_packet: dict) -> List[dict]:
    """
    emotion → emotion标签

    规则：
    - emotion < -0.3 → "负面情绪"
    - emotion > 0.3  → "正面情绪"
    - -0.3 ≤ emotion ≤ 0.3 → "中性情绪"

    置信度修正（GLM5缺陷一修正）：
    - 中性情绪：confidence = 1.0 - abs(emotion) * 2.5（越平静置信度越高）
    - 非中性情绪：confidence = min(1.0, abs(emotion) * 1.2)

    每个标签必须携带 raw_emotion 字段（GLM5缺陷二修正）
    """
    emotion = float(semantic_packet.get("emotion", 0.0))
    emotion = max(-1.0, min(1.0, emotion))

    # 确定标签
    if emotion < EMOTION_THRESHOLD_NEG:
        tag = "负面情绪"
    elif emotion > EMOTION_THRESHOLD_POS:
        tag = "正面情绪"
    else:
        tag = "中性情绪"

    # 置信度修正
    abs_emotion = abs(emotion)
    if abs_emotion <= EMOTION_THRESHOLD_POS:
        confidence = 1.0 - abs_emotion * 2.5
    else:
        confidence = min(1.0, abs_emotion * 1.2)
    confidence = max(0.0, min(1.0, confidence))

    return [{
        "tag": tag,
        "category": "emotion",
        "confidence": round(confidence, 3),
        "raw_emotion": round(emotion, 3)
    }]


# ============================================================================
# 强度标签映射
# ============================================================================

INTENSITY_THRESHOLD_HIGH = 0.7
INTENSITY_THRESHOLD_LOW = 0.3


def _map_intensity(semantic_packet: dict) -> List[dict]:
    """
    intensity → intensity标签

    规则：
    - intensity > 0.7 → "高强度"
    - 0.3 < intensity ≤ 0.7 → "中等强度"
    - intensity ≤ 0.3 → "低强度"

    confidence = intensity
    """
    intensity = float(semantic_packet.get("intensity", 0.5))
    intensity = max(0.0, min(1.0, intensity))

    # 确定标签
    if intensity > INTENSITY_THRESHOLD_HIGH:
        tag = "高强度"
    elif intensity > INTENSITY_THRESHOLD_LOW:
        tag = "中等强度"
    else:
        tag = "低强度"

    return [{
        "tag": tag,
        "category": "intensity",
        "confidence": round(intensity, 3)
    }]


# ============================================================================
# 锚点标签映射
# ============================================================================

def _map_anchors(semantic_packet: dict) -> List[dict]:
    """
    anchors → anchor标签

    规则（GLM5缺陷四修正）：
    - 每个anchor直接映射为一个标签
    - 若anchor是带confidence字段的字典，直接取用
    - 若anchor是字符串，默认confidence=0.5（从0.8下调）
    """
    anchors = semantic_packet.get("anchors", [])

    if not anchors:
        return []

    tags = []
    for anchor in anchors:
        if isinstance(anchor, dict):
            tag_str = anchor.get("tag", str(anchor))
            confidence = float(anchor.get("confidence", 0.5))
        elif isinstance(anchor, str):
            tag_str = anchor
            confidence = 0.5
        else:
            tag_str = str(anchor)
            confidence = 0.5

        tags.append({
            "tag": tag_str,
            "category": "anchor",
            "confidence": round(min(1.0, max(0.0, confidence)), 3)
        })

    return tags


# ============================================================================
# 主入口函数
# ============================================================================

def generate_concept_tags(semantic_packet_biased: dict) -> List[dict]:
    """
    概念标签映射层主入口

    接收 semantic_packet_biased，输出结构化标签列表

    约束：
        - 若 semantic_packet_biased 中无 intent_confidence 字段，
          显式使用默认值0.8并在日志记录警告
        - 任一环节失败返回空列表[]
        - 纯函数，不访问内部状态
    """
    result: List[dict] = []

    try:
        # 边界检查
        if not semantic_packet_biased or not isinstance(semantic_packet_biased, dict):
            logger.warning("[concept_tags] 输入为空或非字典，返回空列表")
            return []

        # 显式处理 intent_confidence 默认值并记录警告
        if "intent_confidence" not in semantic_packet_biased:
            logger.warning(
                "[concept_tags] semantic_packet_biased 缺少 'intent_confidence' 字段，"
                "使用默认值 0.8"
            )

        # 意图标签
        try:
            result.extend(_map_intent(semantic_packet_biased))
        except Exception as e:
            logger.warning(f"[concept_tags] intent映射失败: {e}，跳过")

        # 情绪标签
        try:
            result.extend(_map_emotion(semantic_packet_biased))
        except Exception as e:
            logger.warning(f"[concept_tags] emotion映射失败: {e}，跳过")

        # 强度标签
        try:
            result.extend(_map_intensity(semantic_packet_biased))
        except Exception as e:
            logger.warning(f"[concept_tags] intensity映射失败: {e}，跳过")

        # 锚点标签
        try:
            result.extend(_map_anchors(semantic_packet_biased))
        except Exception as e:
            logger.warning(f"[concept_tags] anchors映射失败: {e}，跳过")

        return result

    except Exception as e:
        logger.warning(f"[concept_tags] 主入口异常: {e}，返回空列表")
        return []


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    print("=" * 60)
    print("概念标签映射层测试")
    print("=" * 60)

    test_cases = [
        {
            "name": "完整输入-求助负面高强度",
            "input": {
                "intent": "求助",
                "intent_confidence": 0.9,
                "emotion": -0.75,
                "intensity": 0.88,
                "anchors": ["求助:问句", "求助:怎么办"]
            },
            "expect_tags": ["求助", "负面情绪", "高强度"]
        },
        {
            "name": "正面情绪中等强度-有intent_confidence",
            "input": {
                "intent": "分享",
                "intent_confidence": 0.85,
                "emotion": 0.6,
                "intensity": 0.5,
                "anchors": [{"tag": "分享:开心", "confidence": 0.7}]
            },
            "expect_tags": ["分享", "正面情绪", "中等强度"]
        },
        {
            "name": "中性情绪-无intent_confidence（应记录警告）",
            "input": {
                "intent": "闲聊",
                "emotion": 0.0,
                "intensity": 0.4,
                "anchors": ["闲聊:默认"]
            },
            "expect_tags": ["闲聊", "中性情绪", "中等强度"]
        },
        {
            "name": "边界值测试-emotion=0.3",
            "input": {
                "intent": "指令",
                "intent_confidence": 0.9,
                "emotion": 0.3,
                "intensity": 0.3,
                "anchors": []
            },
            "expect_tags": ["指令", "中性情绪", "低强度"]
        },
        {
            "name": "边界值测试-intensity=0.7为中等强度",
            "input": {
                "intent": "抱怨",
                "intent_confidence": 0.9,
                "emotion": -0.3,
                "intensity": 0.7,
                "anchors": []
            },
            "expect_tags": ["抱怨", "中性情绪", "中等强度"]
        },
        {
            "name": "强度边界-低强度临界",
            "input": {
                "intent": "闲聊",
                "emotion": 0.0,
                "intensity": 0.2,
                "anchors": []
            },
            "expect_tags": ["闲聊", "中性情绪", "低强度"]
        },
        {
            "name": "强度边界-高强度临界",
            "input": {
                "intent": "挑战",
                "intent_confidence": 0.9,
                "emotion": -0.5,
                "intensity": 0.71,
                "anchors": []
            },
            "expect_tags": ["挑战", "负面情绪", "高强度"]
        },
        {
            "name": "空anchors",
            "input": {
                "intent": "分享",
                "intent_confidence": 0.8,
                "emotion": 0.5,
                "intensity": 0.6,
                "anchors": []
            },
            "expect_tags": ["分享", "正面情绪", "中等强度"]
        },
        {
            "name": "anchors为字符串列表",
            "input": {
                "intent": "求助",
                "emotion": -0.4,
                "intensity": 0.8,
                "anchors": ["求助:问号结尾", "求助:怎么办"]
            },
            "expect_tags": ["求助", "负面情绪", "高强度"]
        },
        {
            "name": "raw_emotion字段验证",
            "input": {
                "intent": "分享",
                "intent_confidence": 0.9,
                "emotion": 0.75,
                "intensity": 0.6,
                "anchors": []
            },
            "expect_raw_emotion": 0.75
        },
        {
            "name": "空输入-应返回空列表",
            "input": {},
            "expect_result": []
        },
    ]

    for i, tc in enumerate(test_cases, 1):
        print(f"\n【测试 {i}】{tc['name']}")
        print(f"  输入: {tc['input']}")

        result = generate_concept_tags(tc['input'])

        print(f"  输出标签数: {len(result)}")
        for tag_obj in result:
            extras = ""
            if "raw_emotion" in tag_obj:
                extras = f", raw_emotion={tag_obj['raw_emotion']}"
            print(f"    - {tag_obj['tag']} ({tag_obj['category']}) confidence={tag_obj['confidence']}{extras}")

        # 验证
        if "expect_result" in tc:
            status = "✓" if result == [] else "✗"
        elif "expect_tags" in tc:
            result_tags = [t["tag"] for t in result]
            status = "✓" if set(tc["expect_tags"]).issubset(set(result_tags)) else "✗"
        elif "expect_raw_emotion" in tc:
            emotion_tag = next((t for t in result if t.get("category") == "emotion"), None)
            raw_ok = emotion_tag and abs(emotion_tag.get("raw_emotion", 0) - tc["expect_raw_emotion"]) < 0.001
            status = "✓" if raw_ok else "✗"

        print(f"  结果: {status}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
