"""
Stereotype Forks — fork detection and registration for stereotype trees.

Extracted from stereotype_tree.py to keep the main module below 400 lines.
"""

from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from .stereotype_tree_schema import (
    COGNITIVE_STYLE_OPPOSITES,
    DEFAULT_FEATURE_WEIGHTS,
    find_opposite_pairs,
    _SIMILARITY_THRESHOLD,
    _FORK_DIFF_THRESHOLD,
    _FORK_WINDOW,
)

if TYPE_CHECKING:
    from .stereotype_tree import StereotypeNode


def cosine_sim(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Cosine similarity."""
    common = set(a.keys()) & set(b.keys())
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    norm_a = sum(a[k] ** 2 for k in a) ** 0.5
    norm_b = sum(b[k] ** 2 for k in b) ** 0.5
    return dot / (norm_a * norm_b) if (norm_a and norm_b) else 0.0


class StereotypeForks:
    """
    跨个体分叉记录。

    当两个个体在相似父节点下积累足够差异后，触发分叉，
    同时修正该父节点的刻板印象。
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
        """获取需要从父节点删除的错误共性标签。"""
        corrections = []
        for fork in self.forks:
            if fork["parent_tag"] == parent_tag:
                if fork["diff_features"]:
                    max_diff_key = max(
                        fork["diff_features"],
                        key=fork["diff_features"].get,
                    )
                    opp_pairs = [
                        (a, b) for a, b in COGNITIVE_STYLE_OPPOSITES
                        if max_diff_key in a or max_diff_key in b
                    ]
                    if opp_pairs:
                        corrections.append(opp_pairs[0][0])
                    else:
                        corrections.append(max_diff_key)
        return list(dict.fromkeys(corrections))

    def find_similar_individuals(
        self,
        individual_features: Dict[str, float],
        individuals: Dict[str, "StereotypeNode"],
        threshold: float = _SIMILARITY_THRESHOLD,
    ) -> List[Tuple[str, float]]:
        """找到与给定特征最相似的已有说话者。"""
        similar = []
        for existing_id, existing_node in individuals.items():
            if not getattr(existing_node, "feature_weights", None):
                continue
            sim = cosine_sim(individual_features, getattr(existing_node, "feature_weights", {}))
            if sim >= threshold:
                similar.append((existing_id, sim))
        similar.sort(key=lambda x: x[1], reverse=True)
        return similar

    def register_with_similarity(
        self,
        speaker_id: str,
        features: Dict[str, float],
        tags: List[str],
        individuals: Dict[str, "StereotypeNode"],
        tree,
        node_factory,
        similarity_threshold: float = _SIMILARITY_THRESHOLD,
    ) -> Dict[str, Any]:
        """注册说话者，若存在相似者则触发分叉。"""
        # 找最相似的已有说话者
        similar = self.find_similar_individuals(features, individuals, similarity_threshold)

        # 强制分叉（force_register）
        parent_path = "/" + "/".join(tags[:min(3, len(tags))]) if tags else "/"

        # 尝试找共同祖先节点
        existing_similar = [sid for sid, _ in similar]
        common_ancestor_tag = None
        if existing_similar:
            for tag in reversed(tags):
                tag_node_path = parent_path + "/" + tag
                for existing_id in existing_similar:
                    ex_node = individuals.get(existing_id)
                    if ex_node:
                        ex_path = getattr(ex_node, "path", "")
                        if tag in ex_path:
                            common_ancestor_tag = tag
                            break
                if common_ancestor_tag:
                    break

        result = {
            "action": "new",
            "similar_to": None,
            "similarity": 0.0,
            "parent_tag": common_ancestor_tag,
            "parent_path": parent_path,
        }

        if similar:
            best_id, best_sim = similar[0]
            result["action"] = "fork"
            result["similar_to"] = best_id
            result["similarity"] = best_sim
            result["parent_tag"] = common_ancestor_tag
            result["parent_path"] = parent_path

            # 检查是否真的应该分叉（差异够大）
            best_node = individuals.get(best_id)
            if best_node:
                diff_features = {}
                for key in set(list(features.keys()) + list(getattr(best_node, "feature_weights", {}).keys())):
                    fv = features.get(key, DEFAULT_FEATURE_WEIGHTS.get(key, 0.5))
                    ev = getattr(best_node, "feature_weights", {}).get(key, DEFAULT_FEATURE_WEIGHTS.get(key, 0.5))
                    diff_features[key] = abs(fv - ev)
                max_diff = max(diff_features.values()) if diff_features else 0.0

                if max_diff < _FORK_DIFF_THRESHOLD:
                    result["action"] = "new"

            if result["action"] == "fork":
                self.record_fork(common_ancestor_tag or parent_path, speaker_id, best_id, diff_features)

        return result

    def check_and_fork(
        self,
        individuals: Dict[str, "StereotypeNode"],
        node_factory,
        diff_threshold: float = _FORK_DIFF_THRESHOLD,
    ) -> None:
        """检查所有个体对，触发必要的分叉。"""
        individual_list = list(individuals.items())

        for i in range(len(individual_list)):
            for j in range(i + 1, len(individual_list)):
                id_a, node_a = individual_list[i]
                id_b, node_b = individual_list[j]

                feats_a = getattr(node_a, "feature_weights", {})
                feats_b = getattr(node_b, "feature_weights", {})

                if not (feats_a and feats_b):
                    continue

                path_a = getattr(node_a, "path", "")
                path_b = getattr(node_b, "path", "")

                if not (path_a and path_b):
                    continue

                # 找共同祖先
                parts_a = [p for p in path_a.strip("/").split("/") if p]
                parts_b = [p for p in path_b.strip("/").split("/") if p]
                common = set(parts_a) & set(parts_b)

                if not common:
                    continue

                parent_tag = sorted(common, key=lambda x: len(x), reverse=True)[0]
                parent_path = "/" + parent_tag

                sim = cosine_sim(feats_a, feats_b)

                if sim < 1.0 - diff_threshold:
                    diff_features = {
                        k: abs(feats_a.get(k, 0) - feats_b.get(k, 0))
                        for k in set(list(feats_a.keys()) + list(feats_b.keys()))
                    }
                    self.record_fork(parent_tag, id_a, id_b, diff_features)

                    # 执行分叉
                    opp_pairs = find_opposite_pairs(
                        getattr(node_a, "tags", []),
                        getattr(node_b, "tags", []),
                    )

                    for op_a, op_b in opp_pairs:
                        node_a.tags = [t for t in node_a.tags if t != op_a]
                        node_b.tags = [t for t in node_b.tags if t != op_b]

                    # 添加对立标签
                    for tag_a, tag_b in opp_pairs:
                        new_a = node_factory()
                        new_a.path = path_a + "/" + op_a
                        new_a.depth = len([p for p in new_a.path.strip("/").split("/") if p])
                        new_a.tags = list(node_a.tags) + [op_a]
                        new_a.confidence = node_a.confidence
                        new_a.feature_weights = dict(feats_a)
                        new_a.children = {}

                        new_b = node_factory()
                        new_b.path = path_b + "/" + op_b
                        new_b.depth = len([p for p in new_b.path.strip("/").split("/") if p])
                        new_b.tags = list(node_b.tags) + [op_b]
                        new_b.confidence = node_b.confidence
                        new_b.feature_weights = dict(feats_b)
                        new_b.children = {}
