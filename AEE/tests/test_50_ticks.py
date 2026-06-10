"""
50-tick end-to-end test: verify the full signal chain.

Checks:
  1. wm_rules count goes from 0 to > 0
  2. _pending_questions gets populated
  3. unresolved rises from 0
"""

import sys, os, time, random, logging

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test_50_ticks")

from AEE.src.entity_state import get_entity_state, reset_entity_state, ENTITY_CORE_PATH
from AEE.src.pipeline_runner import run_pipeline

# Reset singleton so we get a fresh load
reset_entity_state()
entity = get_entity_state()

print(f"=== INITIAL STATE ===")
print(f"  tick:              {entity.tick}")
print(f"  snapshots:         {len(entity.snapshots)}")
print(f"  wm_rules:          {len(getattr(entity, 'wm_rules', []))}")
print(f"  unresolved:        {entity.unresolved}")
print(f"  info_gap:          {entity.info_gap}")
print(f"  _pending_questions:{len(getattr(entity, '_pending_questions', []))}")
print(f"  energy:            {entity.energy:.3f}")
print(f"  fatigue:           {entity.fatigue:.3f}")
print()

tick_count = 0
N_TICKS = 50

# Somatic driver (same as tick_engine)
_somatic_dims = {
    "somatic_tone": (-1.0, 1.0),
    "energy": (0.0, 1.0),
    "fatigue": (0.0, 1.0),
    "stress": (0.0, 1.0),
    "anxiety": (0.0, 1.0),
    "avoid_drive": (0.0, 1.0),
    "approach_drive": (0.0, 1.0),
    "fear": (0.0, 1.0),
    "joy": (0.0, 1.0),
    "sadness": (0.0, 1.0),
}

for i in range(N_TICKS):
    t0 = time.time()
    tick_count += 1

    # Somatic driver: every 7 ticks push a random dimension
    if entity.tick % 7 == 0:
        _dim = random.choice(list(_somatic_dims.keys()))
        _lo, _hi = _somatic_dims[_dim]
        _target = _lo + random.random() * (_hi - _lo)
        setattr(entity, _dim, _target)

    # Run the pipeline (daemon mode, no LLM)
    try:
        result = run_pipeline(
            raw_input=None,
            entity_state=entity,
            daemon_mode=True,
        )
        ok = True
    except Exception as e:
        logger.error(f"Tick {tick_count} pipeline error: {e}")
        ok = False

    # WM induction (every 10 ticks, snapshots >= 5)
    if tick_count % 10 == 0:
        _snaps = getattr(entity, "snapshots", [])
        if len(_snaps) >= 5:
            try:
                from AEE.src.world_model_update.core import run_update_cycle
                _state_snap = entity.to_state_snapshot()
                _old_rules = getattr(entity, "wm_rules", [])
                _new_rules, _wm_stats = run_update_cycle(
                    old_rules=_old_rules,
                    snaps=_snaps,
                    dialogue_log=[],
                    state_snapshot=_state_snap,
                    param_snapshot=None,
                )
                if isinstance(_new_rules, list):
                    entity.wm_rules = [
                        r.to_dict() if hasattr(r, "to_dict") else dict(r)
                        for r in _new_rules
                    ]
                    entity.snapshots = _snaps[-5:]
                    logger.info(
                        f"[WM] {len(_old_rules)} -> {len(entity.wm_rules)} rules "
                        f"(inducted={_wm_stats.inducted})"
                    )
            except Exception as e:
                logger.warning(f"[WM] induction failed: {e}")
        else:
            logger.info(f"[WM] tick {tick_count}: only {len(_snaps)} snapshots, need 5")

    dt = time.time() - t0

    # Progress every 10 ticks
    if tick_count % 10 == 0 or tick_count == 1:
        thought = getattr(entity, "_last_thought_packet", {})
        q_count = len(thought.get("questions", [])) if thought else 0
        s_count = len(thought.get("suggestions", [])) if thought else 0
        print(
            f"  tick {tick_count:3d} | "
            f"ok={ok} | "
            f"snap={len(entity.snapshots)} | "
            f"rules={len(getattr(entity, 'wm_rules', []))} | "
            f"Qs={q_count} Ss={s_count} | "
            f"unresolved={entity.unresolved:.3f} | "
            f"info_gap={entity.info_gap:.3f} | "
            f"pending_q={len(getattr(entity, '_pending_questions', []))} | "
            f"{dt*1000:.0f}ms"
        )

print()
print(f"=== FINAL STATE (after {N_TICKS} ticks) ===")
print(f"  tick:              {entity.tick}")
print(f"  snapshots:         {len(entity.snapshots)}")
print(f"  wm_rules:          {len(getattr(entity, 'wm_rules', []))}")
print(f"  unresolved:        {entity.unresolved:.4f}")
print(f"  info_gap:          {entity.info_gap:.4f}")
print(f"  _pending_questions:{len(getattr(entity, '_pending_questions', []))}")
print(f"  energy:            {entity.energy:.3f}")
print(f"  fatigue:           {entity.fatigue:.3f}")

# Verification
wm_ok = len(getattr(entity, "wm_rules", [])) > 0
pq_ok = len(getattr(entity, "_pending_questions", [])) > 0
ur_ok = entity.unresolved > 0.001

print()
print(f"=== VERIFICATION ===")
print(f"  wm_rules > 0:          {'PASS' if wm_ok else 'FAIL'} ({len(getattr(entity, 'wm_rules', []))})")
print(f"  _pending_questions > 0: {'PASS' if pq_ok else 'FAIL'} ({len(getattr(entity, '_pending_questions', []))})")
print(f"  unresolved > 0:         {'PASS' if ur_ok else 'FAIL'} ({entity.unresolved:.4f})")

if wm_ok and pq_ok and ur_ok:
    print("\n  >>> ALL CHECKS PASSED <<<")
else:
    print("\n  >>> SOME CHECKS FAILED <<<")

# Don't persist — this is a test
print("\n(Entity NOT persisted — test only)")
