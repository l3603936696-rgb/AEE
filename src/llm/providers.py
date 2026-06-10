"""
LLM Provider Module — 模块化 LLM 后端

每个 Provider 是一个可调用对象，签名统一为：

    (system_prompt, user_prompt, temperature, max_tokens, timeout_ms)
    → tuple[str | None, str | None]   # (text, error)

环境变量：
    DEEPSEEK_API_KEY      DeepSeek API Key
    DEEPSEEK_MODEL        默认 deepseek-chat
"""

import json as _json
import logging
import os
import threading
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================================
# DeepSeek Provider
# ============================================================================

class DeepSeekProvider:
    """DeepSeek API (OpenAI-compatible)"""

    BASE_URL = "https://api.deepseek.com/v1/chat/completions"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        self.base_url = base_url or os.environ.get("DEEPSEEK_BASE_URL", self.BASE_URL)

    def __call__(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.8,
        max_tokens: int = 400,
        timeout_ms: float = 30000,
    ) -> tuple[Optional[str], Optional[str]]:
        if not self.api_key:
            return None, "DeepSeek API key not set (DEEPSEEK_API_KEY)"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload = _json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")

        result_container: list = [None, None]

        def _call():
            try:
                req = urllib.request.Request(
                    self.base_url,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=timeout_ms / 1000.0) as resp:
                    data = _json.loads(resp.read().decode("utf-8"))
                text = data["choices"][0]["message"]["content"].strip()
                if text:
                    result_container[0] = text
                else:
                    result_container[1] = "DeepSeek returned empty response"
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8")[:200]
                except Exception:
                    pass
                result_container[1] = f"DeepSeek HTTP {e.code}: {body}"
            except Exception as e:
                result_container[1] = f"DeepSeek: {e}"

        thread = threading.Thread(target=_call, daemon=True)
        thread.start()
        thread.join(timeout=timeout_ms / 1000.0)

        if thread.is_alive():
            return None, f"DeepSeek timeout ({timeout_ms}ms)"

        return result_container[0], result_container[1]


# ============================================================================
# 工厂函数
# ============================================================================

def create_llm_callable():
    """
    创建 DeepSeek LLM 调用器。

    直接使用 DeepSeek API，不再 fallback 到本地模型。
    """
    provider = DeepSeekProvider()
    logger.info(f"[LLM] Provider: DeepSeekProvider ({provider.model})")
    return provider
