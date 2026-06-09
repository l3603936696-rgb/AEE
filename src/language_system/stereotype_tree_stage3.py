"""Stereotype Tree Stage 3 - stage-3 enhancement for StereotypeTree."""

from typing import Any, Dict, List, Tuple
from .stereotype_tree_schema import (
    DEFAULT_FEATURE_WEIGHTS, find_opposite_pairs, infer_cognitive_tags,
    _SIMILARITY_THRESHOLD, _FORK_DIFF_THRESHOLD,
)


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


# Mixin note: the three methods (find_similar_individuals, register_with_similarity,
# check_and_fork) are injected into StereotypeTree in stereotype_tree.py,
# after the StereotypeTree class definition, to avoid circular imports.


# ============================================================================
# 偏置应用
# ============================================================================

