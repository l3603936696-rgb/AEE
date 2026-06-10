"""
LLM — 大语言模型调用抽象层

功能：
    封装 LLM 调用逻辑，支持多后端 fallback。
    当前实现：DeepSeek API（优先）→ Ollama（备选）

核心函数：
    create_llm_callable()
        → 返回 LLM 调用函数
        → 自动读取 .env 中的 DEEPSEEK_API_KEY

配置：
    XIA_LLM_CHAIN=deepseek,ollama
    DEEPSEEK_API_KEY=sk-...
    OLLAMA_BASE_URL=http://localhost:11434

设计原则：
    - 纯 urllib，无 SDK 依赖
    - Provider chain 模式，failover 自动切换
"""

from .providers import (
    DeepSeekProvider,
    create_llm_callable,
)

__all__ = [
    "DeepSeekProvider",
    "create_llm_callable",
]
