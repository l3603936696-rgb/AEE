"""
Life Protocol Runner — SimulationRunner only.

提取自 life_protocol.py。
"""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from .life_protocol_schema import TickMetrics, _entropy, _coherence, _structured_progress

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DATA_DIR.mkdir(exist_ok=True)
LOG_FILE = DATA_DIR / "life_protocol_log.jsonl"


class SimulationRunner:
    """非侵入式 tick 执行器。"""

    def __init__(self, ticks: int, force_action: Optional[str] = None,
                 external_input: bool = True, seed: Optional[int] = None):
        self.ticks = ticks
        self.force_action = force_action
        self.external_input = external_input
        self.seed = seed
        self.metrics_history: List[TickMetrics] = []
        self._entity = None
        self._state_history: List[Dict] = []
        self._action_history: List[str] = []
        self._init_entity()

    def _init_entity(self):
        from AEE.src.entity_zero_iteration import get_entity_state
        if self.seed is not None:
            random.seed(self.seed)
            os.environ["PYTHONHASHSEED"] = str(self.seed)
        entity = get_entity_state()
        if not hasattr(entity, "long_term_bias"):
            entity.long_term_bias = {"explore": 0.0, "connect": 0.0, "introspect": 0.0, "build": 0.0}
        if not hasattr(entity, "behavior_signature"):
            entity.behavior_signature = {"explore": 0, "seek": 0, "avoid": 0, "comfort": 0, "idle": 0, "rest": 0}
        if not hasattr(entity, "_recent_actions"):
            entity._recent_actions = []
        self._entity = entity
        return entity

    def _run_tick(self, tick: int, phase: str = "normal") -> TickMetrics:
        from AEE.src.entity_zero_iteration import run_pipeline, get_entity_state
        entity = get_entity_state()
        raw_input = ""
        if self.external_input:
            raw_input = random.choice([
                "hi", "hello", "how are you", "what's up", "tell me something interesting",
                "", "", "",
            ])
        original_select = None
        forced_action = self.force_action if (phase == "force_explore") else None
        if forced_action:
            try:
                from AEE.src.core import emerge_behavior
                original_select = emerge_behavior.select_dominant_action
                emerge_behavior.select_dominant_action = lambda state, *args, **kwargs: forced_action
            except Exception:
                pass
        try:
            result = run_pipeline(raw_input=raw_input, entity_state=entity, daemon_mode=False)
        finally:
            if original_select is not None:
                try:
                    from AEE.src.core import emerge_behavior
                    emerge_behavior.select_dominant_action = original_select
                except Exception:
                    pass
        state = entity.to_state_snapshot()
        bias = getattr(entity, "long_term_bias", {})
        sig = getattr(entity, "behavior_signature", {})
        id_sig = getattr(entity, "identity_signal", 0.5) or 0.5
        action_type = ""
        try:
            action_type = result.get("decision", {}).get("action_type", "")
        except Exception:
            pass
        if not action_type:
            action_type = state.get("last_action", "")
        if hasattr(entity, "_recent_actions"):
            entity._recent_actions.append(action_type)
            if len(entity._recent_actions) > 50:
                entity._recent_actions = entity._recent_actions[-50:]
        if action_type and hasattr(entity, "update_behavior_signature"):
            entity.update_behavior_signature(action_type)
        self._state_history.append(state)
        self._action_history.append(action_type)
        if len(self._state_history) > 50:
            self._state_history = self._state_history[-50:]
        if len(self._action_history) > 50:
            self._action_history = self._action_history[-50:]
        pred_err = getattr(entity, "_last_prediction_error", 0.5) or 0.5
        return TickMetrics(
            tick=tick, action_type=action_type,
            action_coherence=round(_coherence(self._action_history), 4),
            entropy=round(_entropy(self._state_history), 4),
            structured_progress=round(_structured_progress(self._state_history[-20:], self._action_history[-20:]), 4),
            loneliness=round(state.get("loneliness", 0.3), 4),
            boredom=round(state.get("boredom", 0.3), 4),
            stress=round(state.get("stress", 0.1), 4),
            unresolved=round(state.get("unresolved", 0.2), 4),
            energy=round(state.get("energy", 0.8), 4),
            long_term_bias={k: round(v, 4) for k, v in bias.items()},
            behavior_signature=dict(sig),
            identity_signal=round(id_sig, 4),
            prediction_error=round(pred_err, 4),
            phase=phase,
        )

    def run(self, progress_callback=None) -> List[TickMetrics]:
        for i in range(self.ticks):
            phase = "normal"
            if self.force_action is not None and i < 50:
                phase = "force_explore"
            elif not self.external_input:
                phase = "isolated"
            try:
                m = self._run_tick(i + 1, phase=phase)
                self.metrics_history.append(m)
                if progress_callback:
                    progress_callback(i + 1, self.ticks)
            except Exception:
                self.metrics_history.append(TickMetrics(tick=i + 1, action_type="__ERROR__", phase=phase))
        return self.metrics_history
