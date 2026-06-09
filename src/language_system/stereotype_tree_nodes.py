"""
Stereotype Tree Nodes — 数据结构定义。

包含：StereotypeNode / StereotypeContext dataclasses。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class StereotypeNode:
    """刻板印象树的单个节点。"""
    path: str                  # 节点路径，如 "/学生/理工科/bcyq"
    depth: int                 # 深度（0=root）
    tags: List[str] = field(default_factory=list)           # 标签集（认知风格标签，可被后续学习覆盖）
    feature_weights: Dict[str, float] = field(default_factory=dict)  # 特征权重
    confidence: float = 0.5    # 置信度
    conversation_samples: List[Dict[str, Any]] = field(default_factory=list)  # 对话样本
    children: Dict[str, StereotypeNode] = field(default_factory=dict)  # 子节点
    # 类别标签（来自 MEMORY.md 等初始化数据），永不覆盖，用于跨个体匹配
    _category_tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "depth": self.depth,
            "tags": list(self.tags),
            "feature_weights": dict(self.feature_weights),
            "confidence": self.confidence,
            "conversation_samples": list(self.conversation_samples[-20:]),  # 最多保留20条
            "children": {k: v.to_dict() for k, v in self.children.items()},
            "_category_tags": list(self._category_tags),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StereotypeNode":
        node = cls(
            path=data.get("path", "/"),
            depth=data.get("depth", 0),
            tags=list(data.get("tags", [])),
            feature_weights=dict(data.get("feature_weights", {})),
            confidence=float(data.get("confidence", 0.5)),
            conversation_samples=list(data.get("conversation_samples", [])),
            children={},
            _category_tags=list(data.get("_category_tags", [])),
        )
        for k, v in data.get("children", {}).items():
            node.children[k] = cls.from_dict(v)
        return node


@dataclass
class StereotypeContext:
    """刻板印象树的匹配结果，用于约束语义分析。"""
    speaker_id: str
    active_tags: List[str]           # 激活的标签（从根到叶子的所有标签）
    feature_weights: Dict[str, float] # 特征权重（向下合并，越叶子越精确）
    confidence: float                 # 总置信度
    depth: int                        # 匹配到的最深层级
    path: str                         # 匹配的叶子路径
    parent_contexts: List[Dict[str, Any]] = field(default_factory=list)  # 祖先节点上下文

    def get_tag_weight(self, tag: str) -> float:
        """返回标签的权重（深度越深权重越高）。"""
        if tag in self.active_tags:
            idx = self.active_tags.index(tag)
            return 0.5 + 0.5 * (idx / max(len(self.active_tags) - 1, 1))
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "speaker_id": self.speaker_id,
            "active_tags": list(self.active_tags),
            "feature_weights": dict(self.feature_weights),
            "confidence": self.confidence,
            "depth": self.depth,
            "path": self.path,
            "parent_contexts": list(self.parent_contexts),
        }
