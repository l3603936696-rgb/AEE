"""
Stereotype Tree — 刻板印象树：分层级说话者认知结构（v1.0）

职责：
    - 存储对说话者的层级认知结构（从粗粒度类别到个体特征）
    - 在理解输入时提供先验约束，实现"自顶向下剪枝"
    - 树的生长：从对话历史中自动推断并细化说话者标签

层级结构（自顶向下）：
    root → 基础类别（学生/工程师/医生）→ 地区/文化 → 社会情境 → 个体

每个节点存储：
    - tags：标签集（用于快速匹配）
    - feature_weights：特征权重 {feature_name: weight}
    - confidence：该节点对应说话者的置信度
    - conversation_samples：对话样本（用于后续推断）
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from .stereotype_tree_schema import (
    DEPTH_NAMES,
    TREE_DEPTH,
    FEATURE_DIMS,
    COGNITIVE_STYLE_OPPOSITES,
    DEFAULT_FEATURE_WEIGHTS,
    infer_cognitive_tags,
    find_opposite_pairs,
)
from .stereotype_tree_nodes import StereotypeNode, StereotypeContext


# ============================================================================
# 核心树类
# ============================================================================

class StereotypeTree:
    """
    刻板印象树。

    使用路径式存储，路径格式："/<L1>/<L2>/<L3>/<L4>"
    - L1: 基础类别（学生/工程师/医生/白领...）
    - L2: 地区/文化（东亚/中国大陆/二线城市...）
    - L3: 社会情境（机械专业/民办本科/一人公司...）
    - L4: 个体ID（bcyq/knuonuo/...）

    每个节点可以有标签（tags）和特征权重（feature_weights）。
    叶子节点的特征权重是最精确的，向上合并时做加权平均。
    """

    def __init__(self, owner_id: Optional[str] = None):
        self._owner_id = owner_id  # 拥有者（XIA 自己的 ID）
        self._root = StereotypeNode(path="/", depth=0, tags=["root"])
        # 快速访问个体叶子节点
        self._individuals: Dict[str, StereotypeNode] = {}

    # -------------------------------------------------------------------------
    # 公开 API
    # -------------------------------------------------------------------------

    def match(self, speaker_id: str, input_features: Optional[Dict[str, float]] = None) -> StereotypeContext:
        """
        匹配说话者，返回刻板印象上下文。

        匹配逻辑：
        1. 如果 speaker_id 有对应的叶子节点，从叶子向上收集标签和特征
        2. 否则尝试用 input_features 做模糊匹配，找最近的祖先节点
        3. 如果都没有，返回空上下文（使用默认权重）

        参数：
            speaker_id    : 说话者 ID
            input_features: 当前输入的特征（可选，用于模糊匹配）

        返回：
            StereotypeContext：说话者的刻板印象上下文
        """
        # 路径一：精确匹配（说话者已有叶子节点）
        if speaker_id in self._individuals:
            return self._build_context_from_leaf(speaker_id)

        # 路径二：模糊匹配（用输入特征找最近的节点）
        if input_features:
            matched_node = self._fuzzy_match(input_features)
            if matched_node:
                return self._build_context_from_node(matched_node, speaker_id, input_features)

        # 路径三：返回空上下文（使用默认权重）
        return StereotypeContext(
            speaker_id=speaker_id,
            active_tags=["unknown"],
            feature_weights=dict(DEFAULT_FEATURE_WEIGHTS),
            confidence=0.1,
            depth=0,
            path="/",
            parent_contexts=[],
        )

    def add_individual(
        self,
        speaker_id: str,
        initial_tags: Optional[List[str]] = None,
        initial_features: Optional[Dict[str, float]] = None,
        path_layers: Optional[List[str]] = None,
    ) -> StereotypeNode:
        return add_individual(self, speaker_id, initial_tags, initial_features, path_layers)


    def add_conversation_sample(self, speaker_id: str, sample: Dict[str, Any]) -> None:
        """
        添加对话样本到说话者的叶子节点。

        参数：
            speaker_id : 说话者 ID
            sample     : 对话样本 {"text": str, "emotion": float, "timestamp": float, ...}
        """
        # 不为新说话者创建节点——注册由 register_with_similarity 负责
        if speaker_id not in self._individuals:
            return

        node = self._individuals[speaker_id]
        node.conversation_samples.append(sample)
        # 最多保留 50 条
        if len(node.conversation_samples) > 50:
            node.conversation_samples = node.conversation_samples[-50:]

    def update_features_from_samples(self, speaker_id: str) -> Dict[str, float]:
        """
        从对话样本中更新说话者的特征权重。

        返回：
            更新后的特征权重
        """
        if speaker_id not in self._individuals:
            return dict(DEFAULT_FEATURE_WEIGHTS)

        node = self._individuals[speaker_id]
        samples = node.conversation_samples

        if len(samples) < 3:
            return node.feature_weights

        # 简单统计：从样本中提取特征
        new_features = self._compute_features_from_samples(samples)

        # EMA 更新（保留 70% 旧权重）
        for k in FEATURE_DIMS:
            old_v = node.feature_weights.get(k, 0.5)
            new_v = new_features.get(k, 0.5)
            node.feature_weights[k] = 0.7 * old_v + 0.3 * new_v

        # 置信度随样本增加而上升
        node.confidence = min(0.95, 0.5 + len(samples) * 0.01)

        logger.debug(f"[StereotypeTree] update_features: {speaker_id}, samples={len(samples)}")
        return node.feature_weights

    def infer_tags_from_features(self, features: Dict[str, float]) -> List[str]:
        """
        根据特征向量推断说话者的高层标签。

        这是树的"自底向上"能力——从行为特征推断其社会类别。

        参数：
            features: 特征权重

        返回：
            推断出的标签列表
        """
        inferred_tags = []

        # 句式分析推断
        if features.get("philosophical_ratio", 0) > 0.6:
            inferred_tags.append("思考者")
        if features.get("question_ratio", 0) > 0.4:
            inferred_tags.append("好奇型")
        if features.get("metacognitive_ratio", 0) > 0.3:
            inferred_tags.append("反思型")

        # 情感分析推断
        if features.get("emotional_variance", 0) > 0.6:
            inferred_tags.append("高情感表达")
        elif features.get("emotional_variance", 0) < 0.2:
            inferred_tags.append("低情感表达")

        # 语言风格推断
        if features.get("concrete_vs_abstract", 0) > 0.5:
            inferred_tags.append("抽象思维")
        else:
            inferred_tags.append("具体思维")

        # 分析性标记推断
        if features.get("analytical_marker_ratio", 0) > 0.3:
            inferred_tags.append("逻辑型")

        return inferred_tags

    # -------------------------------------------------------------------------
    # 内部方法
    # -------------------------------------------------------------------------

    def _build_context_from_leaf(self, speaker_id: str) -> StereotypeContext:
        leaf = self._individuals[speaker_id]
        return self._build_context_from_node(leaf, speaker_id, None)

    def _build_context_from_node(
        self,
        node: StereotypeNode,
        speaker_id: str,
        input_features: Optional[Dict[str, float]],
    ) -> StereotypeContext:
        return build_context_from_node(self, node, speaker_id, input_features)

    def _fuzzy_match(self, features: Dict[str, float]) -> Optional[StereotypeNode]:
        return fuzzy_match(self, features)

    @staticmethod
    def _cosine_similarity(a: Dict[str, float], b: Dict[str, float]) -> float:
        return cosine_similarity(a, b)

    def _get_node(self, path: str) -> Optional["StereotypeNode"]:
        return get_node(self, path)

    def _node_factory(self, path: str = "/", depth: int = 0) -> StereotypeNode:
        return StereotypeNode(path=path, depth=depth)

    def _ensure_path(self, path: str) -> StereotypeNode:
        return ensure_path(self, path)

    def _find_node_by_path(self, path: str) -> Optional[StereotypeNode]:
        return get_node(self, path)

    def _build_path_from_tags(self, tags: List[str], speaker_id: str) -> str:
        if not tags:
            return "/" + speaker_id
        selected = tags[:3]
        while len(selected) < 3:
            selected.append("general")
        return "/" + "/".join(selected) + "/" + speaker_id

    def _build_path_from_layers(self, layers: List[str], speaker_id: str) -> str:
        selected = (list(layers) + ["general", "general", "general"])[:3]
        return "/" + "/".join(selected) + "/" + speaker_id

    @staticmethod
    def _compute_features_from_samples(samples: List[Dict[str, Any]]) -> Dict[str, float]:
        return compute_features_from_samples(samples)

    # -------------------------------------------------------------------------
    # 序列化
    # -------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "owner_id": self._owner_id,
            "root": self._root.to_dict(),
            "individual_keys": list(self._individuals.keys()),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StereotypeTree":
        tree = cls(owner_id=data.get("owner_id"))
        if "root" in data:
            tree._root = StereotypeNode.from_dict(data["root"])
            tree._rebuild_individuals_index()
        return tree

    def _rebuild_individuals_index(self) -> None:
        rebuild_individuals_index(self)

    def _collect_leaves(self, node: StereotypeNode, path_parts: List[str]) -> None:
        if node.depth == TREE_DEPTH:
            leaf_id = path_parts[-1] if path_parts else node.tags[-1] if node.tags else "unknown"
            self._individuals[leaf_id] = node
        for child_name, child_node in node.children.items():
            self._collect_leaves(child_node, path_parts + [child_name])




from .stereotype_forks import StereotypeForks
from .stereotype_tree_helpers import (
    cosine_similarity,
    compute_features_from_samples,
    get_node,
    ensure_path,
    build_context_from_node,
    fuzzy_match,
    rebuild_individuals_index,
    add_individual,
)
from .stereotype_tree_api import get_speaker_context, ensure_tree, apply_stereotype_bias
from .stereotype_tree_stage3 import StereotypeTreeStage3


# Inject StereotypeTreeStage3 methods into StereotypeTree (avoids circular import)
StereotypeTree.find_similar_individuals = StereotypeTreeStage3.find_similar_individuals.__get__(
    None, StereotypeTree
)
StereotypeTree.register_with_similarity = StereotypeTreeStage3.register_with_similarity.__get__(
    None, StereotypeTree
)
StereotypeTree.check_and_fork = StereotypeTreeStage3.check_and_fork.__get__(
    None, StereotypeTree
)
StereotypeTree._cosine_sim = staticmethod(StereotypeTreeStage3._cosine_sim)
