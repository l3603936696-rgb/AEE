"""
Anti-Stuck Module (防卡死机制)

设计文档：ai_cognitive_system_v2.txt 第二章 第8节

位置：裁决系统之后、意图编码器之前。

职责：检测行为模式是否陷入死循环，必要时覆写 decision。

硬约束：
    - 纯函数，不修改任何外部状态
    - 异常时原样返回 decision，不抛异常
    - 任一检测失败跳过该检测，不触发死循环判定
"""

from .anti_stuck import anti_stuck_check

__all__ = ["anti_stuck_check"]
