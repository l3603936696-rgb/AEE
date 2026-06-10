"""
Insights — 显性知识持久化层

第三层：结构化知识存储 (Insights) —— 本地 SQLite

来源：世界模型归纳出的高置信规律升级而来。
不属于推理生成，不走 LLM。

子模块：
    insights_db.py    — DB 初始化与路径管理
    insights_schema.py — 数据结构（Insight dataclass）与字段提取
    insights_api.py   — 公开读写 API
"""

from .insights_api import (
    write_insight,
    write_insight_batch,
    recall_insights,
    sync_decay,
    get_all_insights,
    get_insight_count,
)
from .insights_schema import Insight

__all__ = [
    "write_insight",
    "write_insight_batch",
    "recall_insights",
    "sync_decay",
    "get_all_insights",
    "get_insight_count",
    "Insight",
]
