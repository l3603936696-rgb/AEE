"""
Output Layer Module (输出层)

设计文档：ai_cognitive_system_v2.txt 第二章 第10节

位置：意图编码器之后。

职责：接收意图编码器输出的 intent_repr，调用本地 LLM 生成最终的自然语言回应。

硬约束：
    - 所有关键参数从 params 读取，禁止硬编码
    - 降级方案必须生效：任何 LLM 故障都返回策略默认回复，不抛异常
    - 不修改任何外部状态
"""

from .output_layer import generate_response

__all__ = ["generate_response"]
