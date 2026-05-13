"""
Memory Update — 记忆写入编排模块

子模块：
    write_engine : 统一出口，负责分类、打标签、权重计算，委托 tetramem_adapter 写入。
"""

from .write_engine import write_experience_log

__all__ = ["write_experience_log"]
