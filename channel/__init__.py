"""
Channel Module — 对话通道模块

职责：提供与 XIA 通信的统一入口，封装认知管线的调用接口。

设计原则：
    - 所有输入走同一管线（run_pipeline），保证行为一致
    - 支持多种通道（CLI / API / 文件监听等），后续可扩展
    - 通道本身无状态，状态由实体内核管理
"""

from .chat import chat, chat_turn

__all__ = ["chat", "chat_turn"]
