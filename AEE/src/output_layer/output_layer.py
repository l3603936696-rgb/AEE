"""
Output Layer — V3 改造。

职责：接收 EntityCore 状态快照 + emergent_behavior + somatic_signals，
调用 state_to_context 生成 system_prompt，调用 LLM 生成最终回应。

使用：
    from AEE.src.output_layer import generate_response
    result = generate_response(state_snapshot={...}, semantic_packet_biased={...}, params={...})

降级策略：任何 LLM 故障返回策略默认回复，不抛异常。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from .output_layer_schema import (
    DEFAULT_PARAMS,
    FALLBACK_RESPONSES,
    DEFAULT_FALLBACK,
    _safe_get,
    _get_param,
    _recall_similar_episodes,
    _build_system_prompt,
    _apply_emotion_particle_modulation,
    _build_user_prompt,
    _post_process,
    _get_fallback_response,
    _build_system_prompt_fallback,
    _build_rendering_instruction,
    _TONE_INSTRUCTIONS,
    _LENGTH_INSTRUCTIONS,
)


_state_to_context = None
_derive_rendering_params = None


def _get_state_to_context():
    global _state_to_context
    if _state_to_context is None:
        try:
            from ..core.state_to_context import build_system_prompt as _f
            _state_to_context = _f
        except Exception:
            _state_to_context = None
    return _state_to_context


def _get_derive_rendering_params():
    global _derive_rendering_params
    if _derive_rendering_params is None:
        try:
            from ..core.emergent_behavior import derive_rendering_params as _f
            _derive_rendering_params = _f
        except Exception:
            _derive_rendering_params = None
    return _derive_rendering_params


def generate_response(
    state_snapshot: dict,
    semantic_packet_biased: Optional[dict],
    params: Optional[dict] = None,
    llm_callable: Optional[Any] = None,
    emergent_behavior: Optional[dict] = None,
    somatic_signals: Optional[dict] = None,
    intent_repr: Optional[dict] = None,
    previous_state: Optional[dict] = None,
    drive_vector: Optional[dict] = None,
    entity_state: Optional[Any] = None,
    mainline_result: Optional[Dict[str, Any]] = None,
    thought_packet: Optional[dict] = None,
) -> dict:
    """
    输出层主入口（V3 版）。

    从 EntityCore 状态直接生成语言，省略意图编码层。

    参数：
        state_snapshot: EntityCore 状态快照
        semantic_packet_biased: 偏置后语义包（对话上下文）
        params: 输出层参数表
        llm_callable: 测试用 Mock LLM
        emergent_behavior: 行为涌现结果
        somatic_signals: 感质信号
        intent_repr: 意图编码结果（向后兼容）
        previous_state: 上一轮状态快照
        drive_vector: 驱动力向量
        entity_state: EntityCore 实例
        mainline_result: 主线检索结果
        thought_packet: 思考包（含 branch_memories）

    返回：
        {"text": str, "confidence": float, "generation_time_ms": int}
    """
    start_time = time.time()
    merged = {**DEFAULT_PARAMS, **(params or {})}

    temperature = _get_param(merged, "temperature", DEFAULT_PARAMS["temperature"])
    max_tokens = int(_get_param(merged, "max_tokens", DEFAULT_PARAMS["max_tokens"]))
    timeout_ms = _get_param(merged, "output_llm_timeout_ms", DEFAULT_PARAMS["output_llm_timeout_ms"])

    tone_constraint = None
    length_constraint = None
    must_not = []
    if intent_repr and isinstance(intent_repr, dict):
        tone_constraint = intent_repr.get("tone")
        constraints = intent_repr.get("constraints", {})
        if isinstance(constraints, dict):
            length_constraint = constraints.get("length")
            must_not = constraints.get("must_not", [])
        else:
            must_not = []

    stc = _get_state_to_context()
    if stc is not None:
        system_prompt = stc(
            state_snapshot, emergent_behavior, somatic_signals,
            tone_constraint, length_constraint,
            previous_state=previous_state, drive_vector=drive_vector,
        )
    else:
        system_prompt = _build_system_prompt_fallback(intent_repr, state_snapshot, emergent_behavior)

    if stc is not None and emergent_behavior is not None and entity_state is not None:
        drp_fn = _get_derive_rendering_params()
        if drp_fn is not None:
            try:
                rp = drp_fn(emergent_behavior, entity_state)
                system_prompt = system_prompt.rstrip() + "\n\n" + _build_rendering_instruction(rp)
            except Exception:
                pass

    particle_modulation = _apply_emotion_particle_modulation(state_snapshot)
    if particle_modulation:
        system_prompt = system_prompt.rstrip() + "\n\n" + particle_modulation

    recalled_episodes = []
    if semantic_packet_biased:
        raw_input_text = _safe_get(semantic_packet_biased, "raw_input", "") or ""
        if raw_input_text and len(raw_input_text.strip()) >= 3:
            recalled_episodes = _recall_similar_episodes(raw_input_text, None)

    branch_memories_text = ""
    if thought_packet and isinstance(thought_packet, dict):
        branch_memories = thought_packet.get("branch_memories", [])
        if branch_memories and isinstance(branch_memories, list):
            lines = []
            for item in branch_memories[:2]:
                ep = item.get("episode")
                if ep:
                    inp = getattr(ep, "raw_input", "") or ""
                    out = getattr(ep, "output_text", "") or ""
                    snippet = inp[:60] if inp else (out[:60] if out else "")
                    if snippet:
                        lines.append(f"- 想起了「{snippet}」")
            if lines:
                branch_memories_text = "你联想到了：" + "，".join(lines)

    user_prompt = _build_user_prompt(
        semantic_packet_biased, recalled_episodes,
        mainline_result=mainline_result, branch_memories_text=branch_memories_text,
    )

    if llm_callable is not None:
        text, error = llm_callable(
            system_prompt=system_prompt, user_prompt=user_prompt,
            temperature=temperature, max_tokens=max_tokens, timeout_ms=timeout_ms,
        )
    else:
        try:
            from ..observability import create_wrapped_llm
            llm_fn = create_wrapped_llm("output_layer")
            text, error = llm_fn(
                system_prompt=system_prompt, user_prompt=user_prompt,
                temperature=temperature, max_tokens=max_tokens, timeout_ms=timeout_ms,
            )
        except Exception as e:
            text = None
            error = str(e)

    if error or not text:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {"text": _get_fallback_response(tone_constraint), "confidence": 0.0, "generation_time_ms": elapsed_ms}

    elapsed_ms = int((time.time() - start_time) * 1000)
    return {"text": text, "confidence": 1.0, "generation_time_ms": elapsed_ms}


# ============================================================================
# Self-test
# ============================================================================

if __name__ == "__main__":
    from .output_layer_schema import _post_process

    print("=" * 64)
    print("输出层测试")
    print("=" * 64)

    print("\n【_build_system_prompt 测试】")
    cases_system = [
        {"name": "完整参数", "intent_repr": {"tone": "empathetic", "goal": "clarify",
             "constraints": {"length": "short", "must_not": ["分析", "展开"]}},
         "state_snapshot": {"energy": 0.2, "fatigue": 0.8}},
        {"name": "reflect_state=true", "intent_repr": {"tone": "neutral", "goal": "share",
             "constraints": {"length": "tiny", "must_not": []}},
         "state_snapshot": {"energy": 0.7}},
        {"name": "空参数", "intent_repr": {}, "state_snapshot": {}},
    ]
    for tc in cases_system:
        prompt = _build_system_prompt(tc["intent_repr"], tc["state_snapshot"])
        print(f"\n  【{tc['name']}】")
        print(f"  {prompt[:100]}...")

    print("\n【_build_user_prompt 测试】")
    cases_user = [
        {"name": "完整上下文", "sp": {"intent": "求助", "emotion": -0.5, "intensity": 0.8, "anchors": ["求助:怎么办"]}},
        {"name": "仅intent", "sp": {"intent": "分享"}},
        {"name": "空输入", "sp": None},
        {"name": "空字典", "sp": {}},
    ]
    for tc in cases_user:
        prompt = _build_user_prompt(tc["sp"])
        print(f"  {tc['name']}: {prompt}")

    print("\n【_post_process 测试】")
    must_not = ["分析", "展开", "你觉得呢", "你怎么看"]
    cases_post = [
        ("我觉得这个可以", True),
        ("让我来分析一下", False),
        ("你怎么看这个问题", False),
        ("嗯，就是这样", True),
    ]
    for text, expected_pass in cases_post:
        result_text, passed = _post_process(text, must_not)
        status = "OK" if passed == expected_pass else "FAIL"
        print(f"  {status} '{text}' -> passed={passed} (期望 {expected_pass})")

    print("\n【降级话术测试】")
    for tone in ["empathetic", "curious", "supportive", "cautious", "unknown"]:
        fallback = _get_fallback_response(tone)
        print(f"  tone={tone}: {fallback}")

    print("\n【generate_response 主流程测试（Mock Callable）】")
    cases_response = [
        {"name": "正常生成", "llm_callable": lambda **kw: ("嗯，我明白了，让我想想看。", None),
         "expect_confidence": 1.0, "expect_contains": "明白了"},
        {"name": "LLM 超时降级", "llm_callable": lambda **kw: (None, "LLM 调用超时（30000ms）"),
         "expect_confidence": 0.0, "expect_goal_fallback": "share"},
        {"name": "LLM 返回空降级", "llm_callable": lambda **kw: ("", None),
         "expect_confidence": 0.0, "expect_goal_fallback": "share"},
        {"name": "goal=answer 降级话术", "llm_callable": lambda **kw: (None, "connection error"),
         "expect_confidence": 0.0, "expect_goal_fallback": "answer",
         "intent_repr": {"tone": "neutral", "goal": "answer", "constraints": {"length": "tiny", "must_not": []}}},
    ]

    params = {"temperature": 0.7, "max_tokens": 300, "output_llm_timeout_ms": 30000}

    for tc in cases_response:
        intent_repr = tc.get("intent_repr", {"tone": "neutral", "goal": "share",
                                              "constraints": {"length": "tiny", "must_not": ["分析", "展开", "你觉得呢", "你怎么看"]}})
        result = generate_response(intent_repr, {}, None, params, llm_callable=tc["llm_callable"])

        ok_conf = abs(result["confidence"] - tc["expect_confidence"]) < 0.01
        if result["confidence"] >= 0.5:
            ok_text = tc.get("expect_contains") is None or tc["expect_contains"] in result["text"]
        else:
            ok_text = (tc.get("expect_goal_fallback") is None
                       or result["text"] == FALLBACK_RESPONSES.get(tc["expect_goal_fallback"], DEFAULT_FALLBACK)
                       or result["text"] == _get_fallback_response(tc.get("intent_repr", {}).get("tone")))

        ok = ok_conf and ok_text
        print(f"\n  {'OK' if ok else 'FAIL'} 【{tc['name']}】")
        print(f"      confidence: {result['confidence']} (期望 {tc['expect_confidence']})")
        print(f"      text: {result['text']}")
        print(f"      time_ms: {result['generation_time_ms']}")

    print("\n" + "=" * 64)
    print("测试完成")
    print("=" * 64)
