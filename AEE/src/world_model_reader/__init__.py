"""
World Model Reader Module (世界模型读取模块 — Read-Only)

导出接口：
    - query_world_model : 主入口函数
    - _match_rule        : 精确标签匹配（供外部测试/调参使用）
"""

from .world_model_reader import query_world_model, _match_rule
