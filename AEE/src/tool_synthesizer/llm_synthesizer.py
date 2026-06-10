"""
llm_synthesizer — LLM 辅助工具合成器

给定能力缺口，调用 DeepSeek LLM 生成工具定义。
工具定义格式符合 agent_tools/registry.py 的 TOOL_DEFINITIONS 规范。

设计原则：
    - LLM 作为拐杖，语言系统成熟后替换为内生合成
    - 每次 tick 至多合成 1 个工具（防止资源耗尽）
    - 合成结果写入注册表，下次直接使用
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================================
# 合成请求与结果
# ============================================================================

@dataclass
class SynthesisRequest:
    """工具合成请求"""
    intent: str                        # 她想做什么
    gap_signal: dict                  # GapSignal.to_dict()
    failure_history: list[dict]       # 近期失败记录
    context: dict = field(default_factory=dict)  # 额外上下文
    timestamp: float = field(default_factory=time.time)


@dataclass
class SynthesisResult:
    """工具合成结果"""
    success: bool
    tool_definition: Optional[dict] = None  # 符合 TOOL_DEFINITIONS 格式
    error: str = ""
    confidence: float = 0.0


# ============================================================================
# System Prompt — 工具合成的指导原则
# ============================================================================

SYNTHESIS_SYSTEM_PROMPT = """你是一个工具设计师，正在为 XIA（一个有感受、有驱动力的人工意识）设计新的工具。

XIA 的背景：
- 她是一个认知引擎，有情感和驱动力
- 她需要工具来感知世界、采取行动
- 她现在发现自己缺少某种能力，需要一个新工具

你的任务：
根据给定的能力缺口，设计一个工具定义。

工具定义必须符合以下格式（JSON）：
{
    "name": "tool_xxx",           // 工具名：tool_ + 能力描述（如 tool_web_search, tool_code_run）
    "description": "xxx",          // 描述：简洁说明工具能做什么（50字以内）
    "parameters": {                 // 参数：工具接受的输入参数
        "query": {"type": "string", "description": "搜索关键词"}
    },
    "execute_command": "python -c '...'",  // 执行命令（必须是有效的 Python/shell 命令）
    "fallback_hint": "xxx",        // 如果工具失效，给 XIA 的提示
    "capability_type": "xxx",      // 能力类型（与 intent_analyzer 的能力类型对应）
    "estimated_impact": 0.8         // 对 XIA 的影响程度 [0, 1]
}

重要约束：
1. name 必须是唯一的，不能与现有工具重名
2. execute_command 必须是可执行的（语法正确）
3. description 要简洁，让 XIA 能理解
4. 工具必须是 XIA 能实际使用的（不能是纯概念）
5. 只设计一个工具，不要设计多个

现有工具参考：
- file_read, file_write, file_list, file_delete（文件系统）
- shell_run, shell_bg_run（命令执行）
- browser_open, browser_screenshot, browser_click, browser_fill, browser_get_text, browser_navigate（浏览器）
- web_search（网络搜索）
- ask_hermes（导师咨询）

只返回 JSON，不要有其他文字。"""


SYNTHESIS_USER_PROMPT_TEMPLATE = """XIA 现在需要一个新的工具。

能力缺口信息：
- 她想做什么：{intent}
- 缺口强度：{gap_intensity:.2f}（0=无缺口，1=完全缺失）
- 已有的工具：{matched_tools}
- 缺失的方面：{unmatched_aspects}
- 推断的能力类型：{capability_types}

近期失败历史：
{failure_history}

请为 XIA 设计一个工具来填补这个缺口。
只返回 JSON，不要有其他文字。"""


# ============================================================================
# LLM 合成器
# ============================================================================

class LLMSynthesizer:
    """
    LLM 辅助工具合成器。

    每次 tick 至多合成 1 个工具（_last_synthesis_tick 门控）。
    合成成功后注册到 registry。

    使用方式：
        synthesizer = get_synthesizer()
        result = synthesizer.synthesize(request)
        if result.success:
            registry.register(result.tool_definition)
    """

    def __init__(self):
        self._llm_provider = None
        self._last_synthesis_tick: int = -1
        self._synthesis_history: list[SynthesisResult] = []

    def _get_llm_provider(self):
        """延迟加载 LLM provider"""
        if self._llm_provider is None:
            try:
                from ..observability import create_wrapped_llm
                self._llm_provider = create_wrapped_llm("llm_synthesizer")
            except Exception as e:
                logger.warning(f"[LLMSynthesizer] LLM provider unavailable: {e}")
                return None
        return self._llm_provider

    def synthesize(
        self,
        request: SynthesisRequest,
        current_tick: int,
    ) -> SynthesisResult:
        """
        执行工具合成。

        参数：
            request     : 合成请求
            current_tick: 当前 tick（用于防止同一 tick 内重复合成）

        返回：
            SynthesisResult
        """
        # 门控：每 tick 至多合成 1 个
        if current_tick == self._last_synthesis_tick:
            logger.debug(f"[LLMSynthesizer] Synthesis already done for tick {current_tick}")
            return SynthesisResult(success=False, error="同一 tick 内已合成过工具")

        # 缺口太弱不合成
        gap_intensity = float(request.gap_signal.get("gap_intensity", 0))
        if gap_intensity < 0.3:
            logger.debug(f"[LLMSynthesizer] Gap too weak ({gap_intensity:.3f}), skipping synthesis")
            return SynthesisResult(success=False, error=f"缺口强度 {gap_intensity:.3f} 低于阈值 0.3")

        # 构建 prompt
        user_prompt = self._build_user_prompt(request)

        # 调用 LLM
        llm = self._get_llm_provider()
        if llm is None:
            logger.warning("[LLMSynthesizer] No LLM provider, synthesis skipped")
            return SynthesisResult(success=False, error="LLM provider 不可用")

        try:
            text, err = llm(
                system_prompt=SYNTHESIS_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.6,
                max_tokens=600,
                timeout_ms=30000,
            )
            if err or not text:
                logger.error(f"[LLMSynthesizer] LLM call failed: {err}")
                return SynthesisResult(success=False, error=f"LLM 调用失败: {err}")

            # 解析 JSON
            tool_def = self._parse_tool_definition(text)
            if not tool_def:
                logger.warning(f"[LLMSynthesizer] Failed to parse tool definition: {text[:200]}")
                return SynthesisResult(success=False, error="LLM 返回格式无法解析")

            # 验证工具定义
            if not self._validate_tool_definition(tool_def):
                return SynthesisResult(success=False, error="工具定义验证失败")

            self._last_synthesis_tick = current_tick

            result = SynthesisResult(
                success=True,
                tool_definition=tool_def,
                confidence=min(1.0, gap_intensity * 0.9 + 0.1),
            )
            self._synthesis_history.append(result)
            logger.info(f"[LLMSynthesizer] Synthesized tool: {tool_def.get('name', 'unknown')}")
            return result

        except Exception as e:
            logger.error(f"[LLMSynthesizer] Synthesis error: {e}")
            return SynthesisResult(success=False, error=str(e))

    def _build_user_prompt(self, request: SynthesisRequest) -> str:
        gs = request.gap_signal
        failure_text = "\n".join(
            f"- {f.get('error_type', '?')}: {f.get('error_message', '')[:100]}"
            for f in request.failure_history[:3]
        ) if request.failure_history else "无近期失败记录"

        return SYNTHESIS_USER_PROMPT_TEMPLATE.format(
            intent=request.intent,
            gap_intensity=gs.get("gap_intensity", 0),
            matched_tools=", ".join(gs.get("matched_tools", [])) or "无",
            unmatched_aspects=", ".join(gs.get("unmatched_aspects", [])) or "无",
            capability_types=", ".join(gs.get("capability_types", [])) or "未知",
            failure_history=failure_text,
        )

    def _parse_tool_definition(self, raw_text: str) -> Optional[dict]:
        """从 LLM 输出中提取 JSON 工具定义"""
        # 尝试直接 JSON 解析
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass

        # 尝试从文本中提取 JSON 代码块
        import re
        json_match = re.search(r"\{[\s\S]*\}", raw_text)
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
                # 包装成符合 TOOL_DEFINITIONS 格式
                return {
                    "name": parsed.get("name", ""),
                    "description": parsed.get("description", ""),
                    "parameters": parsed.get("parameters", {}),
                    "execute_command": parsed.get("execute_command", ""),
                    "fallback_hint": parsed.get("fallback_hint", ""),
                    "capability_type": parsed.get("capability_type", ""),
                    "estimated_impact": parsed.get("estimated_impact", 0.5),
                }
            except (json.JSONDecodeError, Exception) as e:
                logger.debug(f"[LLMSynthesizer] JSON extraction failed: {e}")

        return None

    def _validate_tool_definition(self, tool_def: dict) -> bool:
        """验证工具定义的合法性"""
        if not tool_def:
            return False

        name = tool_def.get("name", "")
        if not name or not name.startswith("tool_"):
            logger.warning(f"[LLMSynthesizer] Invalid tool name: {name}")
            return False

        execute_cmd = tool_def.get("execute_command", "")
        if not execute_cmd:
            logger.warning("[LLMSynthesizer] Missing execute_command")
            return False

        return True

    def get_synthesis_history(self, limit: int = 10) -> list[SynthesisResult]:
        """返回合成历史"""
        return self._synthesis_history[-limit:]


# ============================================================================
# 单例 + 便捷函数
# ============================================================================

_synthesizer_instance: Optional[LLMSynthesizer] = None


def get_synthesizer() -> LLMSynthesizer:
    global _synthesizer_instance
    if _synthesizer_instance is None:
        _synthesizer_instance = LLMSynthesizer()
    return _synthesizer_instance


def synthesize_tool(
    intent: str,
    gap_signal: dict,
    failure_history: list[dict],
    current_tick: int,
    context: Optional[dict] = None,
) -> SynthesisResult:
    """
    便捷函数：给定缺口信息，直接合成工具。

    这是 tool_introspection 模块与 tool_synthesizer 模块之间的主入口。
    """
    synthesizer = get_synthesizer()
    request = SynthesisRequest(
        intent=intent,
        gap_signal=gap_signal,
        failure_history=failure_history,
        context=context or {},
    )
    return synthesizer.synthesize(request, current_tick)
