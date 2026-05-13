"""
XIA 主动行动系统

我们只决定一件事：她什么时候"有权"行动。
她想做什么、说什么，由她自己决定。

架构：
    TickEngine.tick_now()
        → run_pipeline(daemon_mode=True)   状态推进
        → evaluate_triggers(entity)         评估：她现在有资格行动吗？
        → if triggered:
              ask_xia_what_to_do()          问她：你现在想做什么？
              execute_xia_choice(choice)    她说写哪就写哪，我们执行

触发条件（状态驱动，无硬编码阈值，可配置）：
    - loneliness 持续高位
    - 沉默时长超过阈值
    - boredom 高位
    - info_gap 高位
    - stress 高位

出口目录：data/xia_voice/
    她想写什么都行——独白、笔记、疑问、给用户的留言、对世界的好奇……
    所有行动都记录在 xia_voice/manifest.jsonl
"""

from .triggers import evaluate_triggers
from .executor import execute_xia_choice
from . import tools

__all__ = [
    "evaluate_triggers",
    "execute_xia_choice",
    "tools",
]
