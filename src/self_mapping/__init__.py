"""
SelfMapping — XIA 的内部本体感觉模块

内部本体感觉（interoception + proprioception）：XIA 知道自己的部位是哪些、
它们之间是什么关系、它们当前是什么状态。

核心设计：
    - SelfBodyMap：从 wm_rules 归纳内部因果关系图（relations）
    - NarrativeGenerator：生成预测性内部叙事（纯内部，不上报 LLM）
    - CoherenceMeta：测量叙事预测是否被实际状态变化验证
    - 所有输出不参与决策，只供内部 coherence 计算使用
"""

from .self_body_map import SelfBodyMap, Relation
from .relations_builder import build_relations_from_wm
from .narrative_generator import NarrativeGenerator

__all__ = [
    "SelfBodyMap",
    "Relation",
    "build_relations_from_wm",
    "NarrativeGenerator",
]
