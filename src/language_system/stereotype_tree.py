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

import copy
import hashlib
import logging
from dataclasses import dataclass, field
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

# ============================================================================
# 数据结构
# ============================================================================

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
            # 越靠近叶子（索引越大）权重越高
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
        """
        添加一个新的个体叶子节点。

        如果说话者已存在，**只更新标签和特征，不重建路径**——防止重复节点爆炸。

        参数：
            speaker_id    : 说话者 ID
            initial_tags  : 初始标签（可为空）
            initial_features: 初始特征权重（可为空）
            path_layers   : 有序语义层级 [category, region, situation]，
                            传入时用 _build_path_from_layers（确定性路径）；
                            不传时退化为 _build_path_from_tags（向后兼容）。
        返回：
            新建或更新的节点
        """
        # ── 已存在：只更新，绝不重建路径 ──────────────────────────────────────
        if speaker_id in self._individuals:
            leaf_node = self._individuals[speaker_id]
            # 特征 EMA 更新
            if initial_features:
                for k, v in initial_features.items():
                    if k in FEATURE_DIMS:
                        old_v = leaf_node.feature_weights.get(k, 0.5)
                        leaf_node.feature_weights[k] = 0.7 * old_v + 0.3 * float(v)
            # 标签有序去重追加
            seen = set(leaf_node.tags)
            for t in (initial_tags or []):
                if t and t != speaker_id and t not in seen:
                    leaf_node.tags.append(t)
                    seen.add(t)
            leaf_node.confidence = min(1.0, leaf_node.confidence + 0.05)
            logger.debug(f"[StereotypeTree] update_individual: {speaker_id}")
            return leaf_node

        # ── 新建：构建确定性路径 ───────────────────────────────────────────────
        # 过滤掉 speaker_id 自身（叶子节点名，不混入路径标签）
        flat_tags = [t for t in (initial_tags or []) if t != speaker_id]

        if path_layers:
            path = self._build_path_from_layers(path_layers, speaker_id)
        else:
            path = self._build_path_from_tags(flat_tags, speaker_id)

        # 初始特征
        merged_features = dict(DEFAULT_FEATURE_WEIGHTS)
        if initial_features:
            for k, v in initial_features.items():
                if k in FEATURE_DIMS:
                    merged_features[k] = 0.7 * merged_features.get(k, 0.5) + 0.3 * float(v)

        parent_node = self._ensure_path(path)
        # 有序去重更新父节点标签
        seen_parent = set(parent_node.tags)
        for t in flat_tags:
            if t not in seen_parent:
                parent_node.tags.append(t)
                seen_parent.add(t)

        leaf_node = StereotypeNode(
            path=path.rstrip("/") + f"/{speaker_id}",
            depth=TREE_DEPTH,
            tags=[speaker_id],
            feature_weights=merged_features,
            confidence=0.6,
        )
        parent_node.children[speaker_id] = leaf_node
        self._individuals[speaker_id] = leaf_node

        logger.debug(f"[StereotypeTree] add_individual: {speaker_id}, path={path}")
        return leaf_node

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
        """从叶子节点构建上下文。"""
        leaf = self._individuals[speaker_id]
        return self._build_context_from_node(leaf, speaker_id, None)

    def _build_context_from_node(
        self,
        node: StereotypeNode,
        speaker_id: str,
        input_features: Optional[Dict[str, float]],
    ) -> StereotypeContext:
        """从任意节点向上收集上下文。"""
        # 向上回溯收集标签和祖先节点
        active_tags: List[str] = []
        parent_contexts: List[Dict[str, Any]] = []
        feature_weights_accum: Dict[str, float] = {}
        depth_weight = 1.0

        # 从当前节点向上走
        current: Optional[StereotypeNode] = node
        ancestors: List[StereotypeNode] = []

        # 找到从 root 到 current 的路径
        current_path = node.path.rstrip("/")
        path_parts = [p for p in current_path.split("/") if p]
        # path_parts[-1] 应该是 speaker_id 或最后一个标签

        # 向上回溯：用 path 找到每个祖先节点
        for depth in range(len(path_parts) - 1, -1, -1):
            ancestor_path = "/" + "/".join(path_parts[:depth]) if depth > 0 else "/"
            ancestor_node = self._find_node_by_path(ancestor_path)
            if ancestor_node:
                ancestors.append(ancestor_node)

        # 从根到叶子，收集标签和特征
        for ancestor in reversed(ancestors):
            active_tags.extend(ancestor.tags)
            # 越靠近叶子，权重越高
            for k, v in ancestor.feature_weights.items():
                if k not in feature_weights_accum:
                    feature_weights_accum[k] = 0.0
                feature_weights_accum[k] += v * depth_weight
            depth_weight *= 1.2  # 每上升一层，权重衰减 1.2 倍（但累积）

            parent_contexts.append({
                "path": ancestor.path,
                "depth": ancestor.depth,
                "tags": list(ancestor.tags),
                "confidence": ancestor.confidence,
            })

        # 合并 input_features（如果有）
        if input_features:
            for k, v in input_features.items():
                if k in FEATURE_DIMS:
                    feature_weights_accum[k] = feature_weights_accum.get(k, 0.5) * 0.7 + v * 0.3

        # 归一化
        if feature_weights_accum:
            avg = sum(feature_weights_accum.values()) / len(feature_weights_accum)
            for k in feature_weights_accum:
                feature_weights_accum[k] = 0.5 * feature_weights_accum[k] + 0.5 * avg

        return StereotypeContext(
            speaker_id=speaker_id,
            active_tags=active_tags,
            feature_weights=feature_weights_accum or dict(DEFAULT_FEATURE_WEIGHTS),
            confidence=node.confidence,
            depth=node.depth,
            path=node.path,
            parent_contexts=parent_contexts,
        )

    def _fuzzy_match(self, features: Dict[str, float]) -> Optional[StereotypeNode]:
        """用输入特征做模糊匹配，找最近的节点。"""
        best_node: Optional[StereotypeNode] = None
        best_score = -1.0

        # 在所有个体节点中找最相似的
        for node in self._individuals.values():
            score = self._cosine_similarity(features, node.feature_weights)
            if score > best_score and score > 0.6:  # 阈值 0.6
                best_score = score
                best_node = node

        return best_node

    @staticmethod
    def _cosine_similarity(a: Dict[str, float], b: Dict[str, float]) -> float:
        """余弦相似度。"""
        common_keys = set(a.keys()) & set(b.keys())
        if not common_keys:
            return 0.0

        dot = sum(a[k] * b[k] for k in common_keys)
        norm_a = sum(a[k] ** 2 for k in a.keys()) ** 0.5
        norm_b = sum(b[k] ** 2 for k in b.keys()) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _get_node(self, path: str) -> Optional["StereotypeNode"]:
        """根据路径获取节点，不存在则返回 None。"""
        parts = [p for p in path.strip("/").split("/") if p]
        current = self._root
        for part in parts:
            if part not in current.children:
                return None
            current = current.children[part]
        return current

    def _ensure_path(self, path: str) -> StereotypeNode:
        """确保路径存在，返回末端节点。"""
        parts = [p for p in path.strip("/").split("/") if p]
        current = self._root
        current_path = "/"

        for i, part in enumerate(parts):
            if part not in current.children:
                child = StereotypeNode(
                    path=current_path + part,
                    depth=i + 1,
                    tags=[part],
                    feature_weights=dict(DEFAULT_FEATURE_WEIGHTS),
                )
                current.children[part] = child
            current = current.children[part]
            current_path = current.path + "/"

        return current

    def _find_node_by_path(self, path: str) -> Optional[StereotypeNode]:
        """按路径查找节点。"""
        if path == "/" or path == "":
            return self._root

        parts = [p for p in path.strip("/").split("/") if p]
        current = self._root

        for part in parts:
            if part not in current.children:
                return None
            current = current.children[part]

        return current

    def _build_path_from_tags(self, tags: List[str], speaker_id: str) -> str:
        """从标签构建路径（向后兼容，取前 3 个标签）。"""
        selected = tags[:3]
        while len(selected) < 3:
            selected.append("general")
        return "/" + "/".join(selected) + "/" + speaker_id

    def _build_path_from_layers(self, layers: List[str], speaker_id: str) -> str:
        """从有序的语义层级列表构建确定性路径。

        layers 应按 [category, region, situation] 顺序传入，
        由调用方保证顺序（不依赖 set 的迭代序）。
        """
        selected = (list(layers) + ["general", "general", "general"])[:3]
        return "/" + "/".join(selected) + "/" + speaker_id

    @staticmethod
    def _compute_features_from_samples(samples: List[Dict[str, Any]]) -> Dict[str, float]:
        """从对话样本中计算特征向量。"""
        if not samples:
            return dict(DEFAULT_FEATURE_WEIGHTS)

        # 统计字段计算
        text_lengths = [len(s.get("text", "")) for s in samples]
        emotions = [abs(s.get("emotion", 0.0)) for s in samples]

        # 问号比例（简化）
        question_count = sum(1 for s in samples if "？" in s.get("text", "") or "?" in s.get("text", ""))
        philosophical_markers = ["可能", "也许", "但是", "其实", "我觉得"]
        philosophical_count = sum(1 for s in samples if any(m in s.get("text", "") for m in philosophical_markers))
        analytical_markers = ["因为", "所以", "如果", "但是"]
        analytical_count = sum(1 for s in samples if any(m in s.get("text", "") for m in analytical_markers))

        n = len(samples)
        return {
            "avg_sentence_len": min(1.0, (sum(text_lengths) / n) / 50.0),
            "question_ratio": question_count / n,
            "philosophical_ratio": philosophical_count / n,
            "emotional_variance": min(1.0, (max(emotions) - min(emotions)) if emotions else 0.0),
            "metacognitive_ratio": philosophical_count / n,
            "first_person_ratio": 0.5,  # 简化
            "analytical_marker_ratio": analytical_count / n,
            "concrete_vs_abstract": 0.5,  # 简化
        }

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
            # 重建 _individuals 索引
            tree._rebuild_individuals_index()

        return tree

    def _rebuild_individuals_index(self) -> None:
        """从树结构重建个体索引。"""
        self._individuals.clear()
        self._collect_leaves(self._root, [])

    def _collect_leaves(self, node: StereotypeNode, path_parts: List[str]) -> None:
        """递归收集所有叶子节点。"""
        if node.depth == TREE_DEPTH:
            # 叶子节点
            leaf_id = path_parts[-1] if path_parts else node.tags[-1] if node.tags else "unknown"
            self._individuals[leaf_id] = node
        for child_name, child_node in node.children.items():
            self._collect_leaves(child_node, path_parts + [child_name])


# ============================================================================
# 便捷函数
# ============================================================================

def get_speaker_context(
    entity,
    speaker_id: str,
    input_features: Optional[Dict[str, float]] = None,
) -> Optional[StereotypeContext]:
    """
    从 entity._stereotype_trees 获取说话者的刻板印象上下文。

    参数：
        entity        : EntityState 实例
        speaker_id    : 说话者 ID
        input_features: 当前输入的特征（可选）

    返回：
        StereotypeContext 或 None
    """
    trees = getattr(entity, "_stereotype_trees", None)
    if trees is None:
        return None

    # 获取 XIA 自己的树
    tree = trees.get("default")
    if tree is None:
        return None

    return tree.match(speaker_id, input_features)


def ensure_tree(entity, name: str = "default") -> StereotypeTree:
    """
    确保 entity 有刻板印象树，没有则创建。

    参数：
        entity: EntityState 实例
        name  : 树名称

    返回：
        StereotypeTree
    """
    trees = getattr(entity, "_stereotype_trees", None)
    if trees is None:
        entity._stereotype_trees = {}
        trees = entity._stereotype_trees

    if name not in trees:
        trees[name] = StereotypeTree(owner_id=name)

    return trees[name]


# ============================================================================
# 阶段三：跨个体相似度与分叉
# ============================================================================

# 相似度阈值：高于此值认为是"相似个体"
_SIMILARITY_THRESHOLD = 0.72

# 分叉阈值：差异积累到多少触发分叉
_FORK_DIFF_THRESHOLD = 0.40

# 积累窗口：取最近 N 个样本计算差异
_FORK_WINDOW = 5


class StereotypeForks:
    """
    跨个体分叉记录。

    当两个个体在相似父节点下积累足够差异后，触发分叉，
    同时修正该父节点的刻板印象（删除错误的共性标签）。
    """

    def __init__(self):
        self.forks: List[Dict[str, Any]] = []

    def record_fork(
        self,
        parent_tag: str,
        speaker_a: str,
        speaker_b: str,
        diff_features: Dict[str, float],
    ) -> None:
        """记录一次分叉事件。"""
        self.forks.append({
            "parent_tag": parent_tag,
            "speaker_a": speaker_a,
            "speaker_b": speaker_b,
            "diff_features": diff_features,
        })

    def get_parent_stereotype_corrections(self, parent_tag: str) -> List[str]:
        """
        获取需要从父节点刻板印象中删除的标签（错误共性）。

        例如：两个"机械专业"学生 A 和 B 其实思维风格截然不同，
        则"机械专业→思维风格相似"这个推断是错误的。
        """
        corrections = []
        for fork in self.forks:
            if fork["parent_tag"] == parent_tag:
                # 差异最大的特征维度 → 推断为错误的共性
                if fork["diff_features"]:
                    max_diff_key = max(
                        fork["diff_features"],
                        key=fork["diff_features"].get,
                    )
                    corrections.append(max_diff_key)
        return list(dict.fromkeys(corrections))


class StereotypeTreeStage3:
    """阶段三增强方法，混入 StereotypeTree。"""

    @staticmethod
    def _cosine_sim(a: Dict[str, float], b: Dict[str, float]) -> float:
        """余弦相似度。"""
        keys = set(a.keys()) & set(b.keys())
        if not keys:
            return 0.0
        dot = sum(a[k] * b[k] for k in keys)
        norm_a = (sum(a[k] ** 2 for k in keys)) ** 0.5
        norm_b = (sum(b[k] ** 2 for k in keys)) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def find_similar_individuals(
        self,
        speaker_id: str,
        features: Dict[str, float],
    ) -> List[tuple[str, float]]:
        """
        找到与新说话者特征最相似的现有个体。

        返回：[(speaker_id, similarity_score), ...]，按相似度降序
        """
        similar = []
        for existing_id, node in self._individuals.items():
            if existing_id == speaker_id:
                continue
            if not node.feature_weights:
                continue
            sim = self._cosine_sim(features, node.feature_weights)
            if sim >= _SIMILARITY_THRESHOLD:
                similar.append((existing_id, sim))

        similar.sort(key=lambda x: x[1], reverse=True)
        return similar

    def register_with_similarity(
        self,
        speaker_id: str,
        features: Dict[str, float],
        tags: List[str],
        force_similar_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        注册新说话者，基于相似度决定挂载位置。

        策略：
            1. 有 force_similar_to → 强制挂到指定个体所在节点
            2. 否则找相似个体 → 挂到共同父节点
            3. 无相似个体 → 新建独立分支

        返回注册结果描述。
        """
        if speaker_id in self._individuals:
            return {"action": "exists", "speaker_id": speaker_id}

        similar = self.find_similar_individuals(speaker_id, features)
        result = {
            "action": "new_branch",
            "speaker_id": speaker_id,
            "similar_to": None,
            "parent_tag": None,
        }

        if force_similar_to and force_similar_to in self._individuals:
            # 强制挂到指定个体所在路径
            target = self._individuals[force_similar_to]
            target_parts = target.path.strip("/").split("/")
            if len(target_parts) >= 3:
                parent_path = "/" + "/".join(target_parts[:-2])
            else:
                parent_path = "/" + "/".join(target_parts[:-1]) if len(target_parts) > 1 else "/"
            new_path = f"{parent_path}/{speaker_id}"
            self._ensure_path(new_path)
            new_node = self._get_node(new_path)
            if new_node:
                new_node.tags = tags + [force_similar_to]
                new_node.confidence = 0.6
            self._individuals[speaker_id] = new_node
            result["action"] = "forced_similar"
            result["similar_to"] = force_similar_to
            result["parent_tag"] = force_similar_to
            result["parent_path"] = parent_path

        elif similar:
            # 找到最相似的个体，挂在同一父节点下
            best_match, best_sim = similar[0]
            target = self._individuals[best_match]
            # 直接从目标个体的路径继承父路径，不从标签重建
            # 路径格式: /L1/L2/L3/.../speaker_id，取 L1...L(N-2) 作为父路径
            target_parts = target.path.strip("/").split("/")
            if len(target_parts) >= 3:
                # 去掉最后两个部分（speaker_id 和可能的重复个体名）
                parent_path = "/" + "/".join(target_parts[:-2])
            else:
                parent_path = "/" + "/".join(target_parts[:-1]) if len(target_parts) > 1 else "/"
            new_path = f"{parent_path}/{speaker_id}"
            self._ensure_path(new_path)
            new_node = self._get_node(new_path)
            if new_node:
                new_node.tags = tags + [best_match]
                new_node.confidence = best_sim * 0.8
            self._individuals[speaker_id] = new_node
            result["action"] = "similar_branch"
            result["similar_to"] = best_match
            result["similarity"] = round(best_sim, 3)
            result["parent_tag"] = best_match
            result["parent_path"] = parent_path

        else:
            # 无相似个体，新建独立分支
            path = self._build_path_from_tags(tags, speaker_id)
            self._ensure_path(path)
            new_node = self._get_node(path)
            if new_node:
                new_node.tags = tags
                new_node.confidence = 0.5
            self._individuals[speaker_id] = new_node
            result["action"] = "new_branch"

        return result

    def check_and_fork(
        self,
        speaker_a: str,
        speaker_b: str,
        recent_features_a: Dict[str, float],
        recent_features_b: Dict[str, float],
    ) -> Optional[Dict[str, Any]]:
        """
        检查两个个体是否应该分叉。

        当两者在相似个体注册后积累了足够差异，触发分叉：
        1. 从两个个体的认知风格标签中找互斥对立对
        2. 从父节点删除被证明错误的泛化标签
        3. 创建分叉节点并移动两人

        返回分叉结果或 None（未达到阈值或无法找到互斥标签）。
        """
        if speaker_a not in self._individuals or speaker_b not in self._individuals:
            return None

        # 计算差异特征
        diff_features = {}
        keys = set(recent_features_a.keys()) & set(recent_features_b.keys())
        for k in keys:
            diff_features[k] = abs(recent_features_a[k] - recent_features_b[k])

        max_diff = max(diff_features.values()) if diff_features else 0.0
        if max_diff < _FORK_DIFF_THRESHOLD:
            return None

        # 获取两人的现有节点和父节点
        node_a = self._individuals[speaker_a]
        node_b = self._individuals[speaker_b]

        parent_path_a = "/".join(node_a.path.strip("/").split("/")[:-1])
        parent_path_b = "/".join(node_b.path.strip("/").split("/")[:-1])

        # 必须是同一父节点下才能分叉
        if parent_path_a != parent_path_b:
            return None

        parent_node = self._get_node(parent_path_a)
        if parent_node is None:
            return None

        parent_tag = parent_node.tags[0] if parent_node.tags else "shared"

        # 从两个个体的特征推断认知风格标签
        tags_a = infer_cognitive_tags(recent_features_a)
        tags_b = infer_cognitive_tags(recent_features_b)

        # 找互斥对立对
        opposites = find_opposite_pairs(tags_a, tags_b)
        if not opposites:
            return None  # 没有找到互斥标签，不触发分叉

        # 使用第一个互斥对作为分叉标签
        op_a, op_b = opposites[0]
        # 分叉节点标签：使用互斥标签的组合
        fork_label = f"{op_a}_vs_{op_b}"

        # 从父节点删除被证明不成立的泛化标签
        removed_tags = []
        for op_a_item, op_b_item in opposites:
            if op_a_item in parent_node.tags:
                parent_node.tags.remove(op_a_item)
                removed_tags.append(op_a_item)
            if op_b_item in parent_node.tags:
                parent_node.tags.remove(op_b_item)
                removed_tags.append(op_b_item)

        # 创建分叉节点
        fork_path_a = f"{parent_node.path}/{fork_label}_{speaker_a}"
        fork_path_b = f"{parent_node.path}/{fork_label}_{speaker_b}"

        self._ensure_path(fork_path_a)
        self._ensure_path(fork_path_b)

        # 移动节点
        new_node_a = self._get_node(fork_path_a)
        new_node_b = self._get_node(fork_path_b)

        if new_node_a and new_node_b:
            new_node_a.feature_weights = dict(node_a.feature_weights)
            new_node_a.tags = list(node_a.tags) + [op_a]
            new_node_a.confidence = node_a.confidence

            new_node_b.feature_weights = dict(node_b.feature_weights)
            new_node_b.tags = list(node_b.tags) + [op_b]
            new_node_b.confidence = node_b.confidence

            self._individuals[speaker_a] = new_node_a
            self._individuals[speaker_b] = new_node_b

        # 增加分叉计数
        parent_node.feature_weights["_fork_count"] = parent_node.feature_weights.get(
            "_fork_count", 0
        ) + 1

        return {
            "parent_tag": parent_tag,
            "fork_label": fork_label,
            "opposites": opposites,
            "removed_tags": removed_tags,
            "speaker_a": speaker_a,
            "speaker_b": speaker_b,
            "diff_features": diff_features,
            "inferred_tags_a": tags_a,
            "inferred_tags_b": tags_b,
        }


# 混入阶段三方法
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


# ============================================================================
# 偏置应用
# ============================================================================

def apply_stereotype_bias(
    semantic_packet: dict,
    context: "StereotypeContext",
) -> dict:
    """
    用刻板印象上下文偏置语义包。

    偏置是概率性的、叠加的——它调整可能性分布，而不是硬编码结果。
    偏置强度 = context.confidence（树对说话者的置信度）。

    偏置维度：
        - emotion: 高情感表达者放大 emotion，绝对值向 ±1 移动
        - intensity: 长句型说话者轻微增加 intensity
        - intent: 哲学型说话者轻微提升 "求助" 和 "分享" 意图得分
        - anchors: 加入说话者风格的标记

    参数：
        semantic_packet: 原始语义包
        context        : 刻板印象上下文

    返回：
        偏置后的语义包（新的 dict，不修改原对象）
    """
    if context is None or context.confidence < 0.3:
        # 置信度太低，不应用偏置
        return semantic_packet

    weights = context.feature_weights
    confidence = context.confidence

    # 深拷贝
    biased = dict(semantic_packet)

    # ---- emotion 偏置 ----
    emotional_variance = weights.get("emotional_variance", 0.5)
    # 高情感表达者：emotion 向极值移动
    if emotional_variance > 0.6:
        bias_strength = (emotional_variance - 0.6) * 2.5 * confidence
        old_emotion = biased.get("emotion", 0.0)
        # 向 ±1 方向拉伸
        biased["emotion"] = old_emotion + bias_strength * old_emotion
        biased["emotion"] = max(-1.0, min(1.0, biased["emotion"]))
    elif emotional_variance < 0.3:
        bias_strength = (0.3 - emotional_variance) * 1.5 * confidence
        old_emotion = biased.get("emotion", 0.0)
        # 向中性收缩
        biased["emotion"] = old_emotion * (1.0 - bias_strength * 0.5)

    # ---- intensity 偏置 ----
    avg_sentence_len = weights.get("avg_sentence_len", 0.5)
    if avg_sentence_len > 0.6:
        # 长句型说话者轻微增加 intensity
        bias_delta = (avg_sentence_len - 0.6) * 0.15 * confidence
        biased["intensity"] = min(1.0, biased.get("intensity", 0.5) + bias_delta)
    elif avg_sentence_len < 0.3:
        # 短句型说话者轻微降低 intensity
        bias_delta = (0.3 - avg_sentence_len) * 0.1 * confidence
        biased["intensity"] = max(0.1, biased.get("intensity", 0.5) - bias_delta)

    # ---- intent 偏置 ----
    philosophical_ratio = weights.get("philosophical_ratio", 0.5)
    question_ratio = weights.get("question_ratio", 0.5)
    analytical_ratio = weights.get("analytical_marker_ratio", 0.5)

    intent_bias = confidence * 0.3  # 偏置幅度上限

    # 哲学型说话者：轻微偏向 "求助" 或 "分享"
    if philosophical_ratio > 0.5:
        current_intent = biased.get("intent", "闲聊")
        if current_intent == "闲聊" and question_ratio > 0.4:
            biased["intent"] = "求助"
            if "求助" not in str(biased.get("anchors", [])):
                biased.setdefault("anchors", []).insert(0, "stereotype:哲学型")

    # 逻辑型说话者：轻微提升 "指令" 意图权重
    if analytical_ratio > 0.4:
        biased.setdefault("anchors", []).append("stereotype:逻辑型")

    # ---- anchors 注入 ----
    anchors = biased.setdefault("anchors", [])
    # 加入说话者置信度标记
    if confidence > 0.7:
        anchors.append(f"stereotype:confidence_high")
    elif confidence > 0.5:
        anchors.append(f"stereotype:confidence_medium")
    else:
        anchors.append(f"stereotype:confidence_low")

    # 加入说话者推断的标签（如果有）
    for tag in context.active_tags[:2]:
        if tag not in ["unknown", "root"]:
            safe_tag = f"speaker:{tag}"
            if safe_tag not in anchors:
                anchors.append(safe_tag)

    return biased
