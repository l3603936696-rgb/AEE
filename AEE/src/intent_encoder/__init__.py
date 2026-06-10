"""意图编码器 (Intent Encoder)

接收裁决系统输出的 decision，将其翻译为生成层能直接消费的 intent_repr。
纯翻译层，不做决策、不调用LLM、不修改输入。
"""

from .intent_encoder import encode_intent

__all__ = ["encode_intent"]
