"""Entity experience helpers used by persistence and pipeline compatibility layers."""

from typing import Any, Dict, List, Optional

from .memory_hub import ExperienceLog

# ---- v11.2 逐字段预测误差计算 ----

def _compute_prediction_error_map(entity: Any, pre_state: Dict[str, float]) -> Dict[str, float]:
    """
    计算逐字段预测误差 = actual_delta - predicted_delta。

    在 Step 12 快照记录时调用，post_state 来自 entity.to_state_snapshot()，
    prediction 来自 Step 8.3b 写入 entity._last_prediction。

    返回 {field: error}，错误=0 的字段不包含在结果中（节省空间）。
    """
    try:
        prediction = getattr(entity, "_last_prediction", {})
        if not prediction:
            return {}

        post_state = entity.to_state_snapshot() if hasattr(entity, "to_state_snapshot") else {}
        if not post_state:
            return {}

        error_map: Dict[str, float] = {}
        for field, predicted in prediction.items():
            pre_val = float(pre_state.get(field, 0.0))
            post_val = float(post_state.get(field, pre_val))
            actual = post_val - pre_val
            error = round(actual - predicted, 5)
            if abs(error) > 0.0001:  # 过滤纯零
                error_map[field] = error

        return error_map
    except Exception:
        return {}


def _build_experience_log(
    output_text: Optional[str],
    decision: Dict[str, Any],
    semantic_packet_biased: Dict[str, Any],
    concept_tags: List[Any],
) -> ExperienceLog:
    """
    从管线输出构造 ExperienceLog（供异步经验沉淀使用）。

    参数：
        output_text          : 生成的回复文本
        decision             : 裁决输出
        semantic_packet_biased : 偏置后的语义包
        concept_tags         : 概念标签列表

    返回：
        ExperienceLog : TetraMem 适配器所需的经验日志结构
    """
    content = output_text or ""
    tags = [t.get("tag", "") for t in concept_tags if isinstance(t, dict)]
    # 从决策添加标签
    action = decision.get("action_type", "")
    if action:
        tags.append(f"action:{action}")
    # 高情绪标记
    emotion = semantic_packet_biased.get("emotion", 0.0)
    if abs(emotion) > 0.5:
        tags.append("high_emotion")
    # 失败决策标记
    if decision.get("was_override"):
        tags.append("failed_decision")

    weight = float(decision.get("priority", 0.5))
    if abs(emotion) > 0.7:
        weight *= 1.2

    return ExperienceLog(content=content, tags=tags, weight=min(weight, 1.0))

