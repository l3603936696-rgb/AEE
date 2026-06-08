"""State-pattern memory tick helper for daemon ticks."""

from __future__ import annotations


def run_state_pattern_memory_tick(entity, result: dict, logger) -> None:
    """Run the internal symbol emergence tick from the pipeline drive vector."""
    try:
        from ..language_system.state_pattern_memory import run_symbol_tick

        drive_vector = result.get("drive_vector", {})
        tick = result.get("tick", entity.tick)
        new_symbols = run_symbol_tick(entity, drive_vector, tick)
        if new_symbols:
            logger.info(f"[StatePatternMemory] internal symbols: {new_symbols}")
    except Exception as spm_err:
        logger.debug(f"[StatePatternMemory] skipped: {spm_err}")
