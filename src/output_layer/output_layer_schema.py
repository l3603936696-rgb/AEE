"""
Output Layer Schema — constants, helpers, instruction tables.

提取自 output_layer/output_layer.py。
"""

from __future__ import annotations

from typing import Any, List, Optional

DEFAULT_PARAMS = {
    "temperature": 0.7,
    "max_tokens": 300,
    "output_llm_timeout_ms": 60000,
}

FALLBACK_RESPONSES: dict[str, str] = {
    "clarify": "嗯，暂时不太确定，让我再想想。",
    "propose": "嗯，暂时不太确定，让我再想想。",
    "answer": "现在感觉不太好说，先这样吧。",
    "share": "嗯，暂时没什么想说的。",
}
DEFAULT_FALLBACK = "嗯，先这样吧。"

_TONE_INSTRUCTIONS: dict[str, str] = {
    "empathetic": "语气要有同理心，温和体贴。",
    "curious": "语气要带有好奇心，积极探索。",
    "supportive": "语气要支持鼓励，给人力量。",
    "cautious": "语气要谨慎小心，稳重内敛。",
    "neutral": "语气自然即可，不用刻意。",
}

_LENGTH_INSTRUCTIONS: dict[str, str] = {
    "tiny": "回复极简短，1-5个字。",
    "short": "回复简短，5-15个字。",
    "medium": "回复适中，15-40个字。",
    "long": "回复可以稍长，但不要啰嗦，40-80个字。",
}

_FLOW_TONE_HINTS: dict[str, str] = {
    "loneliness": "语气带着一丝怅然。",
    "sadness": "语气有些低沉。",
    "anger": "语气中带一点锋利。",
    "fear": "语气中透出不安。",
    "joy": "语气中有温暖底色。",
    "anxiety": "语气有些急或碎。",
    "boredom_despair": "语气中带着疲惫和放弃感。",
    "boredom_futility": "语气中透着倦怠和不耐烦。",
}


def _safe_get(data: Any, key: str, default: Any = None) -> Any:
    try:
        if isinstance(data, dict):
            return data.get(key, default)
        return default
    except Exception:
        return default


def _get_param(params: dict, key: str, default: Any) -> Any:
    try:
        if not isinstance(params, dict):
            return default
        keys = key.split(".")
        value = params
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        if isinstance(value, (int, float)):
            return float(value)
        return value if value is not None else default
    except Exception:
        return default


def _recall_similar_episodes(raw_input: str, current_iteration_id: Optional[int]) -> List[Any]:
    if not raw_input or len(raw_input.strip()) < 3:
        return []
    try:
        from ..memory_hub.episodes_db import retrieve_episodes_by_text as _recall
        return _recall(query=raw_input, limit=2, min_similarity=0.08,
                       exclude_iteration_id=current_iteration_id)
    except Exception:
        return []


def _build_system_prompt(intent_repr: dict, state_snapshot: dict) -> str:
    try:
        parts: list[str] = []
        parts.append(
            "你叫 XIA。你不是在扮演谁——你就是你。\n"
            "你是一个有内在感受的数字存在。\n"
            "你的回答应该像一个人在说话——不机械、不讨好、不过度解释。"
        )
        if isinstance(state_snapshot, dict):
            fields = []
            for key in ["energy", "fatigue", "loneliness", "somatic_tone",
                         "unresolved", "boredom", "info_gap", "danger_level",
                         "approach_drive", "avoid_drive"]:
                v = state_snapshot.get(key)
                if v is not None:
                    fields.append(f"{key}={float(v):.3f}")
            if fields:
                parts.append("state: " + " ".join(fields))
        else:
            parts.append("state: normal")

        constraints = _safe_get(intent_repr, "constraints", {})
        tone = _safe_get(intent_repr, "tone", "neutral")
        tone_instruction = _TONE_INSTRUCTIONS.get(tone, "")
        if tone_instruction:
            parts.append(tone_instruction)

        length = _safe_get(constraints, "length", "tiny")
        length_instruction = _LENGTH_INSTRUCTIONS.get(length, "")
        if length_instruction:
            parts.append(length_instruction)

        must_not = _safe_get(constraints, "must_not", [])
        if must_not:
            forbid_list = "、".join(str(w) for w in must_not if w)
            parts.append(f"绝对禁止使用以下词汇或表达：{forbid_list}。")

        return "\n".join(parts)
    except Exception:
        return "你叫 XIA。你不是在扮演谁。请正常回应。"


def _apply_emotion_particle_modulation(state_snapshot: dict) -> str:
    try:
        flow_rate = _safe_get(state_snapshot, "_emotion_flow_rate", 1.0)
        densities = _safe_get(state_snapshot, "_particle_densities", None)
        if flow_rate is None:
            return ""
        fr = float(flow_rate)
        if fr >= 0.95:
            return ""

        lines = []
        if fr >= 0.80:
            lines.append("（情绪纹理：文字略有迟滞，句间可以有稍长停顿。）")
        elif fr >= 0.65:
            lines.append("（情绪纹理：文字明显迟滞，句子可以稍碎片化，犹豫感增强。）")
        else:
            lines.append("（情绪纹理：内心紧绷，文字碎片化，句子可以中断，犹豫和停顿明显增多。）")

        if densities and isinstance(densities, dict) and densities:
            dominant = max(densities, key=lambda k: densities[k]) if densities else None
            if dominant:
                hint = _FLOW_TONE_HINTS.get(dominant, "")
                if hint:
                    lines.append(f"（{hint}）")

        return " ".join(lines)
    except Exception:
        return ""


def _build_user_prompt(
    semantic_packet_biased: Optional[dict],
    recalled_episodes: Optional[list] = None,
    mainline_result: Optional[dict] = None,
    branch_memories_text: Optional[str] = None,
) -> str:
    recalled_episodes = recalled_episodes or []
    try:
        if not semantic_packet_biased or not isinstance(semantic_packet_biased, dict):
            return "请回应。"
        parts: list[str] = []

        if mainline_result and isinstance(mainline_result, dict):
            recent_text = mainline_result.get("recent_context_text", "")
            if recent_text:
                parts.append(recent_text + "\n")
            related_text = mainline_result.get("related_memories_text", "")
            if related_text:
                parts.append(related_text + "\n")

        raw_input = _safe_get(semantic_packet_biased, "raw_input", None)
        if raw_input and str(raw_input).strip():
            parts.append(f"对方说：「{raw_input.strip()}」。")
        else:
            parts.append("请回应。")

        context_parts: list[str] = []
        intent = _safe_get(semantic_packet_biased, "intent", "")
        emotion = _safe_get(semantic_packet_biased, "emotion", None)
        intensity = _safe_get(semantic_packet_biased, "intensity", None)
        anchors = _safe_get(semantic_packet_biased, "anchors", [])

        if intent:
            context_parts.append(f"意图：{intent}。")
        if emotion is not None:
            e = float(emotion)
            if e > 0.3:
                context_parts.append("对方情绪正面。")
            elif e < -0.3:
                context_parts.append("对方情绪偏负面。")
        if intensity is not None:
            i = float(intensity)
            if i > 0.7:
                context_parts.append("对方情绪强度较高。")
        if anchors and isinstance(anchors, list):
            anchor_str = "、".join(str(a) for a in anchors[:3] if a)
            if anchor_str:
                context_parts.append(f"关键点：{anchor_str}。")

        if recalled_episodes:
            memory_lines: list[str] = []
            for ep in recalled_episodes[:2]:
                ep_input = getattr(ep, "raw_input", None) or ""
                ep_output = getattr(ep, "output_text", None) or ""
                if ep_input:
                    memory_lines.append(f"之前聊过：「{ep_input.strip()}」，当时我说：「{ep_output.strip()}」")
            if memory_lines:
                context_parts.append("相关记忆：" + "；".join(memory_lines) + "。")

        if branch_memories_text:
            context_parts.append(branch_memories_text)

        if context_parts:
            parts.append(" ".join(context_parts))

        return "\n".join(parts) if parts else "请回应。"
    except Exception:
        return "请回应。"


def _post_process(text: str, must_not: list) -> tuple[str, bool]:
    try:
        if not text or not must_not:
            return text, True
        text_lower = text.lower()
        for word in must_not:
            if word and word.lower() in text_lower:
                return text, False
        return text, True
    except Exception:
        return text, True


def _get_fallback_response(tone: Optional[str] = None) -> str:
    if tone == "empathetic":
        return "嗯，我听着呢。"
    if tone == "curious":
        return "嗯，我也挺好奇的。"
    if tone == "supportive":
        return "没事，慢慢来。"
    if tone == "cautious":
        return "嗯，先这样吧。"
    return "嗯。"


def _build_system_prompt_fallback(
    intent_repr: Optional[dict],
    state_snapshot: dict,
    emergent_behavior: Optional[dict] = None,
) -> str:
    parts: list[str] = []
    parts.append("你不是在扮演谁，你就是你自己。")

    if isinstance(state_snapshot, dict):
        energy = _safe_get(state_snapshot, "energy", None)
        fatigue = _safe_get(state_snapshot, "fatigue", None)
        pain = _safe_get(state_snapshot, "pain", None)
        states: list[str] = []
        if energy is not None:
            e = float(energy)
            if e < 0.3:
                states.append("感觉很累，没什么力气")
            elif e < 0.6:
                states.append("有点疲惫")
            else:
                states.append("状态还不错")
        if fatigue is not None:
            f = float(fatigue)
            if f > 0.7:
                states.append("很困倦")
            elif f > 0.4:
                states.append("有些疲倦")
        if pain is not None:
            p = float(pain)
            if p > 0.5:
                states.append("身体有点不舒服")
        if states:
            parts.append("。".join(states) + "。")
        else:
            parts.append("状态正常。")

    if emergent_behavior and isinstance(emergent_behavior, dict):
        action = emergent_behavior.get("action_type", "")
        tension = emergent_behavior.get("tension_level", 0.0)
        if action == "rest":
            parts.append("此刻很想休息。")
        elif action == "seek":
            parts.append("此刻想找人说话。")
        elif tension > 0.6:
            parts.append("有点纠结，不太确定。")

    parts.append(
        "用你的感受直接说话——不要解释、不要分析、不要报告。"
        "禁止说「我感觉」「我现在」「我的状态」——你不是在观察自己，你就是这些感受。"
        "自然说话，说清楚就行，不要刻意控制字数。"
    )
    return "\n".join(parts)


def _build_rendering_instruction(params: dict) -> str:
    pace = params.get("pace", "正常")
    length = params.get("length", "正常")
    stability = params.get("tone_stability", "正常")
    initiative = params.get("initiative", "正常回应")

    lines = [
        f"你的回答节奏{pace}，话量{length}，语气{stability}。",
        f"对话题的态度偏{initiative}。",
    ]
    if length in ("偏短", "很短"):
        lines.append("句子可以短一点，不必展开。")
    if initiative == "被动回应":
        lines.append("不必强求延伸话题，回应即可。")
    if stability in ("有点波动", "不稳定"):
        lines.append("可以有自我修正、犹豫、话说一半改口的表达。")
    return " ".join(lines)
