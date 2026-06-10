"""
Somatic Concept Map Helpers — BGE propagation + clustering helpers.

Extracted from somatic_concept_map.py to keep the main module below 400 lines.
All these functions are re-exported by somatic_concept_map.py for backward compatibility.
"""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from .somatic_anchors import SOMATIC_ANCHORS

# Module-level cache for BGE embeddings
_anchor_embeddings: Optional[Dict[str, "numpy.ndarray"]] = None  # type: ignore
_anchor_words: List[str] = []


# =============================================================================
# BGE Propagation Layer
# =============================================================================

def _ensure_anchor_embeddings():
    """Lazy-load: compute BGE embeddings for all anchor words."""
    global _anchor_embeddings, _anchor_words
    if _anchor_embeddings is not None:
        return

    from .bge_analyzer import _get_bge_model

    model = _get_bge_model()
    if model is None:
        logger.warning("[SomaticMap] BGE not available, propagation disabled")
        _anchor_embeddings = {}
        return

    _anchor_words = list(SOMATIC_ANCHORS.keys())
    try:
        import numpy as np
        embeddings = model.encode(_anchor_words, normalize_embeddings=True)
        _anchor_embeddings = {
            word: emb for word, emb in zip(_anchor_words, embeddings)
        }
        logger.info(
            f"[SomaticMap] {len(_anchor_embeddings)} anchors embedded "
            f"(dim={embeddings.shape[1]})"
        )
    except Exception as e:
        logger.warning(f"[SomaticMap] Embedding failed: {e}")
        _anchor_embeddings = {}


def get_somatic_delta(
    word: str,
    top_k: int = 3,
    min_similarity: float = 0.35,
    propagation_weight: float = 0.60,
) -> Dict[str, float]:
    """
    Compute the drive-field somatic mapping for any word.

    Algorithm:
        1. If word is directly an anchor, return its mapping (weight 1.0)
        2. Compute cosine similarity via BGE with all anchors
        3. Take top-k most similar anchors
        4. Weighted-average deltas, weight = sim × propagation_weight
        5. Anchors below min_similarity don't participate

    Args:
        word: The word to look up
        top_k: Number of nearest anchors participating in propagation
        min_similarity: Minimum similarity threshold
        propagation_weight: Propagation decay coefficient

    Returns:
        {dimension: delta} dict, empty dict when word cannot be mapped
    """
    if word in SOMATIC_ANCHORS:
        return dict(SOMATIC_ANCHORS[word])

    _ensure_anchor_embeddings()

    if not _anchor_embeddings or not _anchor_words:
        return {}

    from .bge_analyzer import _get_bge_model

    model = _get_bge_model()
    if model is None:
        return {}

    try:
        import numpy as np
        word_emb = model.encode([word], normalize_embeddings=True)[0]

        similarities = []
        for anchor_word in _anchor_words:
            anchor_emb = _anchor_embeddings[anchor_word]
            sim = float(word_emb @ anchor_emb)  # normalized → dot = cosine
            similarities.append((anchor_word, sim))

        similarities.sort(key=lambda x: x[1], reverse=True)
        top = [(w, s) for w, s in similarities[:top_k] if s >= min_similarity]

        if not top:
            return {}

        total_weight = sum(s for _, s in top)
        merged: Dict[str, float] = {}

        for anchor_word, sim in top:
            weight = (sim / total_weight) * propagation_weight
            anchor_delta = SOMATIC_ANCHORS[anchor_word]
            for dim, delta in anchor_delta.items():
                merged[dim] = merged.get(dim, 0.0) + delta * weight

        return merged

    except Exception as e:
        logger.warning(f"[SomaticMap] get_delta('{word}') failed: {e}")
        return {}


# =============================================================================
# Exploration & Clustering Helpers
# =============================================================================

_NEUTRAL_ANCHOR = {
    "energy": 0.5, "loneliness": 0.3, "unresolved": 0.2,
    "boredom": 0.2, "fatigue": 0.1, "stress": 0.1,
    "approach_drive": 0.5, "avoid_drive": 0.5,
    "danger_level": 0.0, "curiosity": 0.5,
    "somatic_tone": 0.0,
}


def training_exploration_nudge(
    entity,
    drive_state: Dict[str, float],
    stuck_threshold: float = 0.35,
    nudge_strength: float = 0.015,
) -> Dict[str, float]:
    """
    Training exploration nudge — applies weak homeostatic force to dimensions
    locked at extreme values.

    Design:
        Early training may trap her in one state region (e.g. high stress +
        high approach → can only say "好/嗯"). A weak homeostatic force lets
        her naturally drift to new states and encounter more seed words.

        This is not a hard threshold — force is continuous and each tick's
        nudge is small (0.015), insufficient to jump-state, only accelerating
        natural drift.

    Args:
        entity: EntityCore instance
        drive_state: Current drive field
        stuck_threshold: Deviation from neutral considered "locked" (default 0.35)
        nudge_strength: Homeostatic force strength per tick

    Returns:
        {dim: nudge_applied} dict
    """
    applied = {}
    for dim, neutral in _NEUTRAL_ANCHOR.items():
        if not hasattr(entity, dim):
            continue
        current = float(getattr(entity, dim, neutral))
        deviation = current - neutral

        if abs(deviation) > stuck_threshold:
            nudge = -deviation * nudge_strength

            if dim in ("somatic_tone", "prediction_error"):
                lo, hi = -1.0, 1.0
            else:
                lo, hi = 0.0, 1.0
            setattr(entity, dim, max(lo, min(hi, current + nudge)))
            applied[dim] = round(nudge, 4)

    if applied:
        logger.debug(
            f"[SomaticMap] exploration nudge: "
            f"{', '.join(f'{k}{v:+.3f}' for k, v in applied.items())}"
        )

    return applied


def get_top_matches(
    drive_state: Dict[str, float],
    top_k: int = 5,
    min_score: float = 0.2,
    cluster_weights: Optional[Dict[str, float]] = None,
) -> List[Tuple[str, float]]:
    """
    Score all 29 anchor words, return top-K.

    Used for candidate word selection: not just the top-1, several top
    candidates are injected into the candidate pool for vocabulary diversity.

    v11.3: cluster_weights from long-word training accumulation; high-weight
    clusters get micro-upward adjustment.

    Args:
        drive_state: Current drive field
        top_k: Return top-K results
        min_score: Minimum precision threshold
        cluster_weights: {anchor_word: weight} cluster weight dict

    Returns:
        [(word, match_score), ...] sorted descending
    """
    results = []
    for word in SOMATIC_ANCHORS:
        try:
            score = _get_state_match_score_impl(word, drive_state)
            if cluster_weights and word in cluster_weights:
                w = cluster_weights[word]
                bias = math.tanh(w * 0.5) * 0.15
                score = max(0.0, min(1.0, score + bias))
            if score >= min_score:
                results.append((word, score))
        except Exception:
            pass

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]


def get_cluster_peers(
    word: str,
    min_similarity: float = 0.6,
) -> List[str]:
    """
    Return anchor words in the same cluster as the given word (semantically similar).

    Used for discovery reward: when a word has high match precision,
    inject same-cluster words into the discovery pool.
    """
    if not _anchor_embeddings or not _anchor_words or word not in _anchor_words:
        return []

    try:
        import numpy as np
        word_emb = _anchor_embeddings[word]

        peers = []
        for anchor in _anchor_words:
            if anchor == word:
                continue
            sim = float(np.dot(word_emb, _anchor_embeddings[anchor]))
            if sim >= min_similarity:
                peers.append((anchor, sim))

        peers.sort(key=lambda x: x[1], reverse=True)
        return [p[0] for p in peers[:5]]
    except Exception as e:
        logger.debug(f"[SomaticMap] get_cluster_peers('{word}') failed: {e}")
        return []


def find_closest_anchor(word: str, min_score: float = 0.3) -> Optional[Tuple[str, float]]:
    """
    Find the nearest somatic anchor for a word using BGE.

    v11.3: when a long word (3+ chars) is selected, find its somatic cluster
    to adjust cluster weights — let "useful" clusters be weighted higher.

    Returns:
        (anchor_word, similarity) or None (no anchor close enough)
    """
    _ensure_anchor_embeddings()
    if not _anchor_embeddings or not _anchor_words:
        return None

    try:
        import numpy as np
        from .bge_analyzer import _get_bge_model
        model = _get_bge_model()
        if model is None:
            return None
        word_emb = model.encode([word], normalize_embeddings=True)[0]

        best_anchor = None
        best_sim = -1.0
        for anchor_word in _anchor_words:
            anchor_emb = _anchor_embeddings[anchor_word]
            sim = float(np.dot(word_emb, anchor_emb))
            if sim > best_sim:
                best_sim = sim
                best_anchor = anchor_word

        if best_sim >= min_score and best_anchor is not None:
            return (best_anchor, best_sim)
        return None
    except Exception as e:
        logger.debug(f"[SomaticMap] find_closest_anchor('{word}') failed: {e}")
        return None


def list_anchors() -> List[Tuple[str, int]]:
    """List all anchor words and the number of dimensions they cover."""
    return [(word, len(deltas)) for word, deltas in SOMATIC_ANCHORS.items()]


# =============================================================================
# Internal scoring implementation (shared with main module)
# =============================================================================

_NEUTRAL_ZONE = 0.25  # |current - 0.5| < 0.25 → neutral zone, not scored


def _get_state_match_score_impl(
    candidate_word: str,
    drive_state: Dict[str, float],
    top_k: int = 3,
    min_similarity: float = 0.35,
) -> float:
    """
    Diagnostic precision score — how accurately does this word describe
    the current body state?

    Algorithm:
        1. Get somatic delta for candidate_word
        2. For each dimension, compare delta sign vs. current state deviation
        3. Weighted-average match quality by |delta|
        4. Normalize to [0, 1]

    Neutral dimensions (near 0.5) don't participate in scoring.

    Returns:
        Diagnostic precision [0, 1]; 0.5 (neutral) when word cannot be mapped
    """
    delta = get_somatic_delta(
        candidate_word,
        top_k=top_k,
        min_similarity=min_similarity,
        propagation_weight=0.60,
    )

    if not delta:
        return 0.5

    match_sum = 0.0
    weight_sum = 0.0

    for dim, d in delta.items():
        if abs(d) < 1e-6:
            continue

        current = drive_state.get(dim, 0.5)
        if dim in ("somatic_tone", "prediction_error"):
            mapped = (current + 1.0) / 2.0
        else:
            mapped = current

        deviation = mapped - 0.5
        if abs(deviation) < _NEUTRAL_ZONE:
            continue

        dim_weight = abs(d)
        word_expects_high = d > 0
        state_is_high = mapped > 0.5

        if word_expects_high == state_is_high:
            match_quality = abs(deviation) * 2.0
            match_sum += dim_weight * match_quality
        else:
            match_sum -= dim_weight * abs(deviation) * 1.5

        weight_sum += dim_weight

    if weight_sum < 1e-6:
        return 0.5

    raw = match_sum / weight_sum
    normalized = 1.0 / (1.0 + math.exp(-raw * 3.0))
    return max(0.0, min(1.0, normalized))
