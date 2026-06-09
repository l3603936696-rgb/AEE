"""
Inline tests extracted from episodes_db.py.

Run with: python -m src.memory_hub.episodes_db_test
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.memory_hub.episodes_db import (
    init_db, write_episode, write_episode_async,
    build_episode, get_recent_episodes, get_episode_by_id,
    get_episodes_for_induction, get_episode_count, compute_importance,
)
from src.memory_hub.episodes_db_helpers import Episode, _current_utc_time


def main():
    print("=" * 64)
    print("Episodes DB -- unit tests")
    print("=" * 64)

    init_db()
    print(f"\nDB path: .../data/episodes.db")
    print(f"Record count: {get_episode_count()}")

    # T1: write_episode
    print("\n[T1] write_episode")
    ep1 = Episode(
        iteration_id=1,
        timestamp=_current_utc_time(),
        raw_input="你好呀！",
        semantic_packet_biased={"emotion": 0.3, "intent": "greet", "intensity": 0.5},
        decision={"action_type": "greet", "target": "user", "priority": 0.6},
        intent_repr={"tone": "warm", "goal": "connect"},
        state_snapshot={"energy": 0.8, "fatigue": 0.1},
        drive_vector={"curiosity": 0.3},
        output_text="你好呀！有什么想聊的吗？",
        idle_seconds=0.0,
        importance=0.5,
        tags=["greet", "social"],
    )
    ok1 = write_episode(ep1)
    print(f"  {'PASS' if ok1 else 'FAIL'} write {'1' if ok1 else '0'} episode(s)")

    # T2: get_recent_episodes
    print("\n[T2] get_recent_episodes")
    recent = get_recent_episodes(limit=5)
    ok2 = len(recent) >= 1
    print(f"  {'PASS' if ok2 else 'FAIL'} query {len(recent)} episode(s)")

    # T3: get_episode_by_id
    print("\n[T3] get_episode_by_id")
    ep_found = get_episode_by_id(1)
    ok3 = ep_found is not None
    print(f"  {'PASS' if ok3 else 'FAIL'} iteration_id=1 {'found' if ok3 else 'not found'}")

    # T4: build_episode
    print("\n[T4] build_episode (importance + auto-tags)")
    built = build_episode(
        iteration_id=2,
        raw_input="我今天很开心！",
        semantic_packet_biased={"emotion": 0.8, "intent": "share", "intensity": 0.9},
        decision={"action_type": "share", "target": "user", "priority": 0.7},
        intent_repr={"tone": "warm"},
        state_snapshot={"energy": 0.8},
        drive_vector={"curiosity": 0.4},
        output_text="太棒了！",
        idle_seconds=10.0,
        was_override=False,
        tags=["positive"],
    )
    ok4 = (
        built.importance >= 0.5
        and "intent:share" in built.tags
        and "high_emotion" in built.tags
    )
    print(f"  {'PASS' if ok4 else 'FAIL'} importance={built.importance:.3f}, tags={built.tags}")

    # T5: get_episodes_for_induction
    print("\n[T5] get_episodes_for_induction")
    for_ind = get_episodes_for_induction(since_iteration=0, limit=10)
    ok5 = isinstance(for_ind, list) and len(for_ind) >= 1
    print(f"  {'PASS' if ok5 else 'FAIL'} returned {len(for_ind)} Snap-format dicts")

    # T6: async write
    print("\n[T6] write_episode_async")
    ep_async = Episode(
        iteration_id=3,
        timestamp=_current_utc_time(),
        raw_input="async test",
        semantic_packet_biased={"emotion": 0.1},
        decision={"action_type": "wait"},
        intent_repr={},
        state_snapshot={},
        drive_vector={},
        output_text="",
        idle_seconds=0.0,
    )
    write_episode_async(ep_async)
    time.sleep(0.5)
    count_after = get_episode_count()
    ok6 = count_after >= 2
    print(f"  {'PASS' if ok6 else 'FAIL'} after async write: {count_after} episodes")

    # T7: failed decision importance bonus
    print("\n[T7] compute_importance: failed decision bonus")
    normal = compute_importance(0.5, 0.3, 0.5, False)
    failed = compute_importance(0.5, 0.3, 0.5, True)
    ok7 = failed > normal
    print(f"  {'PASS' if ok7 else 'FAIL'} failed={failed:.3f} > normal={normal:.3f}")

    # T8: build_episode failed_decision tag
    print("\n[T8] build_episode: was_override=True")
    ep_override = build_episode(
        iteration_id=4, raw_input="test",
        semantic_packet_biased={"emotion": 0.2, "intensity": 0.3},
        decision={"priority": 0.3}, intent_repr={},
        state_snapshot={}, drive_vector={},
        output_text="", idle_seconds=0.0, was_override=True,
    )
    ok8 = "failed_decision" in ep_override.tags
    print(f"  {'PASS' if ok8 else 'FAIL'} failed_decision tag: {ok8}")

    # T9: internal_tick auto-tag
    print("\n[T9] build_episode: no raw_input -> internal_tick")
    ep_tick = build_episode(
        iteration_id=5, raw_input=None,
        semantic_packet_biased={"emotion": 0.1, "intensity": 0.2},
        decision={"priority": 0.1}, intent_repr={},
        state_snapshot={}, drive_vector={},
        output_text="", idle_seconds=0.0,
    )
    ok9 = "internal_tick" in ep_tick.tags
    print(f"  {'PASS' if ok9 else 'FAIL'} internal_tick tag: {ok9}")

    all_ok = ok1 and ok2 and ok3 and ok4 and ok5 and ok6 and ok7 and ok8 and ok9
    print(f"\n{'='*64}")
    print(f"Result: {'ALL PASS' if all_ok else 'SOME FAILED'}")
    print(f"Final count: {get_episode_count()}")
    print("=" * 64)


if __name__ == "__main__":
    main()
