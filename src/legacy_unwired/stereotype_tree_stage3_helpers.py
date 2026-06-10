"""Stereotype Tree Shared Constants & Math — shared between StereotypeForks and StereotypeTreeStage3."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .stereotype_tree import StereotypeNode

# ─── Shared constants ─────────────────────────────────────────────────────────

_SIMILARITY_THRESHOLD = 0.72
_FORK_DIFF_THRESHOLD = 0.40
_FORK_WINDOW = 5


# ─── Shared math ──────────────────────────────────────────────────────────────

def cosine_sim(a, b):
    """Cosine similarity between two feature vectors."""
    common = set(a.keys()) & set(b.keys())
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    norm_a = sum(a[k] ** 2 for k in a) ** 0.5
    norm_b = sum(b[k] ** 2 for k in b) ** 0.5
    return dot / (norm_a * norm_b) if (norm_a and norm_b) else 0.0


def find_similar_individuals(stage3_self, speaker_id, features):
    """Find similar individuals. Stage3.register_with_similarity helper."""
    from .stereotype_tree_schema import DEFAULT_FEATURE_WEIGHTS
    similar = []
    for existing_id, node in stage3_self._individuals.items():
        if existing_id == speaker_id:
            continue
        nf = getattr(node, "feature_weights", None)
        if not nf:
            continue
        sim = cosine_sim(features, nf)
        if sim >= _SIMILARITY_THRESHOLD:
            similar.append((existing_id, sim))
    similar.sort(key=lambda x: x[1], reverse=True)
    return similar


def register_with_similarity(stage3_self, speaker_id, features, tags, force_similar_to=None):
    """Register speaker with similarity-based placement. Stage3.register_with_similarity helper."""
    from .stereotype_tree_schema import DEFAULT_FEATURE_WEIGHTS, infer_cognitive_tags, find_opposite_pairs

    if speaker_id in stage3_self._individuals:
        return {"action": "exists", "speaker_id": speaker_id}

    similar = find_similar_individuals(stage3_self, speaker_id, features)
    result = {
        "action": "new_branch",
        "speaker_id": speaker_id,
        "similar_to": None,
        "parent_tag": None,
    }

    parent_path = "/" + "/".join(tags[:3]) if tags else "/"

    # Force similar path
    if force_similar_to and force_similar_to in stage3_self._individuals:
        target = stage3_self._individuals[force_similar_to]
        tp = target.path.strip("/").split("/")
        parent_path = "/" + "/".join(tp[:-2]) if len(tp) >= 3 else "/" + "/".join(tp[:-1]) if len(tp) > 1 else "/"
        new_path = f"{parent_path}/{speaker_id}"
        stage3_self._ensure_path(new_path)
        new_node = stage3_self._get_node(new_path)
        if new_node:
            new_node.tags = tags + [force_similar_to]
            new_node.confidence = 0.6
        stage3_self._individuals[speaker_id] = new_node
        result.update({
            "action": "forced_similar",
            "similar_to": force_similar_to,
            "parent_tag": force_similar_to,
            "parent_path": parent_path,
        })
        return result

    if similar:
        best_id, best_sim = similar[0]
        result["action"] = "fork"
        result["similar_to"] = best_id

        # Try to find common ancestor
        best_node = stage3_self._individuals.get(best_id)
        common_ancestor_tag = None
        if best_node:
            ex_path = best_node.path.strip("/").split("/")
            for tag in reversed(tags):
                if tag in ex_path:
                    common_ancestor_tag = tag
                    break

        # Check if actually should fork
        if best_node:
            feats_a = features
            feats_b = getattr(best_node, "feature_weights", {})
            diff_features = {}
            for key in set(list(feats_a.keys()) + list(feats_b.keys())):
                fv = feats_a.get(key, DEFAULT_FEATURE_WEIGHTS.get(key, 0.5))
                ev = feats_b.get(key, DEFAULT_FEATURE_WEIGHTS.get(key, 0.5))
                diff_features[key] = abs(fv - ev)
            max_diff = max(diff_features.values()) if diff_features else 0.0
            if max_diff < _FORK_DIFF_THRESHOLD:
                result["action"] = "new"

        # Record fork if needed
        if stage3_self._forks is not None and result["action"] == "fork":
            stage3_self._forks.record_fork(
                common_ancestor_tag or parent_path,
                speaker_id, best_id, diff_features,
            )

        # Add new node
        stage3_self.add_individual(speaker_id, initial_tags=tags + [common_ancestor_tag or best_id] if common_ancestor_tag else tags)

    return result


def check_and_fork(stage3_self, speaker_a, speaker_b, recent_a, recent_b):
    """Check if two individuals should fork. Stage3.check_and_fork helper."""
    from .stereotype_tree_schema import infer_cognitive_tags, find_opposite_pairs

    if speaker_a not in stage3_self._individuals or speaker_b not in stage3_self._individuals:
        return None

    diff_features = {}
    keys = set(recent_a.keys()) & set(recent_b.keys())
    for k in keys:
        diff_features[k] = abs(recent_a[k] - recent_b[k])
    max_diff = max(diff_features.values()) if diff_features else 0.0
    if max_diff < _FORK_DIFF_THRESHOLD:
        return None

    node_a = stage3_self._individuals[speaker_a]
    node_b = stage3_self._individuals[speaker_b]
    pa = "/".join(node_a.path.strip("/").split("/")[:-1])
    pb = "/".join(node_b.path.strip("/").split("/")[:-1])
    if pa != pb:
        return None

    parent_node = stage3_self._get_node(pa)
    if parent_node is None:
        return None
    parent_tag = parent_node.tags[0] if parent_node.tags else "shared"

    tags_a = infer_cognitive_tags(recent_a)
    tags_b = infer_cognitive_tags(recent_b)
    opposites = find_opposite_pairs(tags_a, tags_b)
    if not opposites:
        return None

    op_a, op_b = opposites[0]
    fork_label = f"{op_a}_vs_{op_b}"

    new_node_a = stage3_self._node_factory()
    new_node_a.path = node_a.path + "/" + op_a
    new_node_a.depth = len([p for p in new_node_a.path.strip("/").split("/") if p])
    new_node_a.tags = list(node_a.tags) + [op_a]
    new_node_a.confidence = node_a.confidence
    new_node_a.feature_weights = dict(getattr(node_a, "feature_weights", {}))
    new_node_a.children = {}

    new_node_b = stage3_self._node_factory()
    new_node_b.path = node_b.path + "/" + op_b
    new_node_b.depth = len([p for p in new_node_b.path.strip("/").split("/") if p])
    new_node_b.tags = list(node_b.tags) + [op_b]
    new_node_b.confidence = node_b.confidence
    new_node_b.feature_weights = dict(getattr(node_b, "feature_weights", {}))
    new_node_b.children = {}

    parent_node.children[fork_label + "_A"] = new_node_a
    parent_node.children[fork_label + "_B"] = new_node_b

    return {
        "speaker_a": speaker_a, "speaker_b": speaker_b,
        "fork_label": fork_label, "opposites": opposites,
        "parent_tag": parent_tag, "diff_features": diff_features,
    }
