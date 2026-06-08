"""Sibling-channel and stereotype maintenance helpers for daemon ticks."""

from __future__ import annotations

SIBLING_QUENCH_WEIGHT = 0.4
SIBLING_COMPREHENSION_MIN = 0.3
STEREOTYPE_FORK_INTERVAL_TICKS = 10


def apply_sibling_social_credit(entity, result: dict, input_source: str, logger) -> None:
    """Apply social comprehension credit when the tick input came from a sibling."""
    if input_source == "sibling":
        try:
            from ..language_system.word_warmup import add_social_comprehension

            recognized_words = result.get("cx_recognized_words", [])
            comprehension = float(result.get("cx_comprehension", 0.0))
            if recognized_words and comprehension > SIBLING_COMPREHENSION_MIN:
                from ..language_system.word_warmup import resonate_with_word

                for word, _score in recognized_words:
                    add_social_comprehension(
                        entity,
                        word,
                        comprehension * SIBLING_QUENCH_WEIGHT,
                    )
                    resonate_with_word(entity, word, comprehension)
                logger.info(
                    f"[SiblingChannel] social credit+resonance: comp={comprehension:.2f} "
                    f"words={[word for word, _score in recognized_words]}"
                )
        except Exception as social_credit_err:
            logger.debug(f"[SiblingChannel] social credit skipped: {social_credit_err}")


def run_stereotype_fork_check(entity, tick_count: int, logger) -> None:
    """Run periodic stereotype-tree fork checks."""
    if tick_count % STEREOTYPE_FORK_INTERVAL_TICKS == 0:
        try:
            from ..language_system.stereotype_tree import ensure_tree

            tree = ensure_tree(entity)
            checked_pairs = set()
            for speaker_id, node in list(tree._individuals.items()):
                parent_path = "/".join(node.path.strip("/").split("/")[:-1])
                for other_id, other_node in tree._individuals.items():
                    if other_id == speaker_id:
                        continue
                    other_parent = "/".join(other_node.path.strip("/").split("/")[:-1])
                    if other_parent != parent_path:
                        continue
                    pair = tuple(sorted([speaker_id, other_id]))
                    if pair in checked_pairs:
                        continue
                    checked_pairs.add(pair)
                    feat_a = entity._recent_speaker_features.get(speaker_id, {})
                    feat_b = entity._recent_speaker_features.get(other_id, {})
                    if not feat_a or not feat_b:
                        continue
                    fork_result = tree.check_and_fork(speaker_id, other_id, feat_a, feat_b)
                    if fork_result:
                        logger.info(
                            f"[StereotypeFork] forked {speaker_id} vs {other_id}: "
                            f"label={fork_result['fork_label']}, "
                            f"removed={fork_result['removed_tags']}"
                        )
        except Exception as fork_err:
            logger.debug(f"[StereotypeFork] async check skipped: {fork_err}")


def post_sibling_anchor(sibling_channel, entity, result: dict, logger) -> None:
    """Post short anchor output to the sibling channel when anchor weighting selects it."""
    pipeline_text = result.get("response", {}).get("text", "")
    if pipeline_text and sibling_channel:
        response = result.get("response", {})
        anchor_weight = float(response.get("anchor_weight", 0.0))
        for _ in range(int(round(anchor_weight))):
            try:
                sibling_channel.post(pipeline_text, tick=entity.tick)
            except Exception as err:
                logger.debug(f"[SiblingChannel] post failed: {err}")
                break
