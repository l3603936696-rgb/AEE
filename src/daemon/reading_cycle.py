"""Reading intake helpers for daemon ticks."""

from __future__ import annotations

from pathlib import Path


def run_reading_intake(entity, logger) -> None:
    """Read library text and inject harvested vocabulary candidates."""
    try:
        from .reading_source import pick_and_read
        from ..language_system.reading_acquisition import (
            harvest_from_reading,
            inject_reading_candidates,
        )

        data_dir = Path(__file__).parent.parent.parent / "data"
        reading = pick_and_read(data_dir, entity_state=entity)
        if reading:
            candidates = harvest_from_reading(
                text=reading["text"],
                entity_state=entity,
                max_candidates=3,
                min_similarity=0.35,
            )
            if candidates:
                injected = inject_reading_candidates(entity, candidates)
                if injected > 0:
                    logger.info(
                        f"[TickEngine] Reading intake: "
                        f"{injected} words from "
                        f"{reading['source']}/{reading['file']}"
                    )
                    try:
                        from .reading_taste import (
                            compute_fingerprint,
                            record_reading,
                        )

                        fingerprint = compute_fingerprint(reading["text"])
                        words = [candidate["word"] for candidate in candidates]
                        record_reading(entity, fingerprint, words)
                    except Exception:
                        pass
    except Exception as read_err:
        logger.debug(f"[TickEngine] Reading intake skipped: {read_err}")


def extract_sentence_patterns_from_reading(entity, result: dict, logger) -> None:
    """Extract construction schemas from reading history for rest/comfort ticks."""
    try:
        from ..language_system.sentence_extraction import _extract_sentence_patterns

        action_type = result.get("decision", {}).get("action_type", "")
        extracted = _extract_sentence_patterns(entity, action_type)
        if extracted > 0:
            logger.info(f"[TickEngine] Sentence extraction: {extracted} schemas from reading")
    except Exception as sentence_err:
        logger.debug(f"[TickEngine] Sentence extraction skip: {sentence_err}")
