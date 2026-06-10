"""
Stereotype Tree Helpers — internal helpers extracted from StereotypeTree.

Extracted to keep stereotype_tree.py below 400 lines.
"""

from typing import TYPE_CHECKING

from .stereotype_tree_schema import (
    DEFAULT_FEATURE_WEIGHTS,
    FEATURE_DIMS,
    infer_cognitive_tags,
)

if TYPE_CHECKING:
    from .stereotype_tree_nodes import StereotypeNode, StereotypeContext


# ─── Core math ──────────────────────────────────────────────────────────────

def cosine_similarity(a, b):
    """Cosine similarity between two feature vectors."""
    common = set(a.keys()) & set(b.keys())
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    norm_a = sum(a[k] ** 2 for k in a) ** 0.5
    norm_b = sum(b[k] ** 2 for k in b) ** 0.5
    return dot / (norm_a * norm_b) if (norm_a and norm_b) else 0.0


def compute_features_from_samples(samples):
    """Compute averaged features from conversation samples."""
    if not samples:
        return dict(DEFAULT_FEATURE_WEIGHTS)
    n = len(samples)
    texts = [s.get("text", "") for s in samples]
    text_lengths = [len(t) for t in texts]
    emotions = [abs(s.get("emotion", 0.0)) for s in samples]
    total_chars = max(1, sum(text_lengths))
    avg_len = sum(text_lengths) / n
    philosophical_markers = ["可能", "也许", "但是", "其实", "我觉得"]
    analytical_markers = ["因为", "所以", "如果", "但是"]
    philosophical_count = sum(1 for t in texts if any(m in t for m in philosophical_markers))
    analytical_count = sum(1 for t in texts if any(m in t for m in analytical_markers))
    question_count = sum(1 for t in texts if "？" in t or "?" in t)
    return {
        "avg_sentence_len": min(1.0, avg_len / 50.0),
        "question_ratio": question_count / n,
        "philosophical_ratio": philosophical_count / n,
        "emotional_variance": min(1.0, (max(emotions) - min(emotions)) if len(emotions) > 1 else abs(emotions[0]) if emotions else 0.0),
        "metacognitive_ratio": philosophical_count / n,
        "first_person_ratio": 0.5,
        "analytical_marker_ratio": analytical_count / n,
        "concrete_vs_abstract": 0.5 if avg_len < 30 else (0.8 if avg_len > 60 else 0.5),
    }


# ─── Tree traversal ────────────────────────────────────────────────────────

def walk_leaves(node, depth_limit=4):
    """Generator: yield all leaf nodes at depth_limit."""
    if depth_limit == 0:
        yield node
    else:
        if not getattr(node, "children", None):
            yield node
        for child in getattr(node, "children", {}).values():
            yield from walk_leaves(child, depth_limit - 1)


# ─── Node operations ──────────────────────────────────────────────────────

def get_node(tree, path):
    """Get a node by path."""
    current = tree._root
    if path in ("/", ""):
        return current
    for part in [p for p in path.strip("/").split("/") if p]:
        if part not in current.children:
            return None
        current = current.children[part]
    return current


def ensure_path(tree, path):
    """Ensure a path exists, creating nodes as needed."""
    parts = [p for p in path.strip("/").split("/") if p]
    node = tree._root
    current_path = "/"
    for depth, part in enumerate(parts, start=1):
        if part not in node.children:
            new_node = tree._node_factory(path=current_path + part, depth=depth)
            node.children[part] = new_node
        node = node.children[part]
        current_path = node.path.rstrip("/") + "/"
    return node


def find_node_by_path(tree, path):
    """Find a node by path."""
    return get_node(tree, path)


# ─── Context building ────────────────────────────────────────────────────

def build_context_from_node(tree, node, speaker_id, input_features):
    """Build StereotypeContext from a node, walking up the tree."""
    active_tags = []
    parent_contexts = []
    feature_weights_accum = {}
    depth_weight = 1.0

    ancestors = []
    path_parts = [p for p in node.path.rstrip("/").split("/") if p]
    for depth in range(len(path_parts) - 1, -1, -1):
        ancestor_path = "/" + "/".join(path_parts[:depth]) if depth > 0 else "/"
        ancestor_node = find_node_by_path(tree, ancestor_path)
        if ancestor_node:
            ancestors.append(ancestor_node)

    for ancestor in reversed(ancestors):
        active_tags.extend(ancestor.tags)
        for k, v in ancestor.feature_weights.items():
            feature_weights_accum[k] = feature_weights_accum.get(k, 0.0) + v * depth_weight
        depth_weight *= 1.2
        parent_contexts.append({
            "path": ancestor.path,
            "depth": ancestor.depth,
            "tags": list(ancestor.tags),
            "confidence": ancestor.confidence,
        })

    if input_features:
        for k, v in input_features.items():
            if k in FEATURE_DIMS:
                feature_weights_accum[k] = feature_weights_accum.get(k, 0.5) * 0.7 + v * 0.3

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


# ─── Fuzzy matching ──────────────────────────────────────────────────────

def fuzzy_match(tree, features):
    """Find best-matching leaf node for given features."""
    best_node = None
    best_score = -1.0
    for node in walk_leaves(tree._root):
        nf = getattr(node, "feature_weights", {})
        if not nf:
            continue
        score = cosine_similarity(features, nf)
        if score > best_score and score > 0.6:
            best_score = score
            best_node = node
    return best_node


# ─── Rebuild ─────────────────────────────────────────────────────────────

def rebuild_individuals_index(tree):
    """Rebuild _individuals from tree structure."""
    tree._individuals.clear()
    _collect_leaves(tree, tree._root, [])


def _collect_leaves(tree, node, path_parts):
    """Recursively collect leaf nodes into tree._individuals."""
    if node.depth == 4:
        leaf_id = path_parts[-1] if path_parts else node.tags[-1] if node.tags else "unknown"
        tree._individuals[leaf_id] = node
    for child_name, child_node in node.children.items():
        _collect_leaves(tree, child_node, path_parts + [child_name])


def add_individual(tree, speaker_id, initial_tags=None, initial_features=None, path_layers=None):
    """Add a new individual leaf node to the stereotype tree."""
    from .stereotype_tree_schema import DEFAULT_FEATURE_WEIGHTS, FEATURE_DIMS
    from .stereotype_tree import StereotypeNode

    if speaker_id in tree._individuals:
        leaf_node = tree._individuals[speaker_id]
        if initial_features:
            for k, v in initial_features.items():
                if k in FEATURE_DIMS:
                    old_v = leaf_node.feature_weights.get(k, 0.5)
                    leaf_node.feature_weights[k] = 0.7 * old_v + 0.3 * float(v)
        seen = set(leaf_node.tags)
        for t in (initial_tags or []):
            if t and t != speaker_id and t not in seen:
                leaf_node.tags.append(t)
                seen.add(t)
        leaf_node.confidence = min(1.0, leaf_node.confidence + 0.05)
        return leaf_node

    flat_tags = [t for t in (initial_tags or []) if t != speaker_id]
    if path_layers:
        path = tree._build_path_from_layers(path_layers, speaker_id)
    else:
        path = tree._build_path_from_tags(flat_tags, speaker_id)

    merged_features = dict(DEFAULT_FEATURE_WEIGHTS)
    if initial_features:
        for k, v in initial_features.items():
            if k in FEATURE_DIMS:
                merged_features[k] = 0.7 * merged_features.get(k, 0.5) + 0.3 * float(v)

    parent_node = ensure_path(tree, path)
    seen_parent = set(parent_node.tags)
    for t in flat_tags:
        if t not in seen_parent:
            parent_node.tags.append(t)
            seen_parent.add(t)

    leaf_node = StereotypeNode(
        path=path.rstrip("/") + f"/{speaker_id}",
        depth=4,
        tags=[speaker_id],
        feature_weights=merged_features,
        confidence=0.6,
    )
    parent_node.children[speaker_id] = leaf_node
    tree._individuals[speaker_id] = leaf_node
    return leaf_node
