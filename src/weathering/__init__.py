"""风化系统 — 长期参数漂移与崩塌。"""

from .registry import (
    DriftableParam,
    register,
    get_driftable,
    list_all,
    TIER_WINDOWS,
    TIER_DRIFT_RATES,
)
from .baseline import get_store, BaselineStore
from .drift import apply_normal_drift, apply_acute_drift, apply_drift_cycle
from .shattering import (
    compute_shattering_force,
    compute_update_resistance,
    detect_and_process_shattering,
    load_suppressed_tension,
)
from .signal_bridge import (
    correlations_to_drift_signals,
    dimensions_to_param_paths,
    make_emotion_weight_fn,
    make_contradiction_fn,
)
from .param_writer import write_drifted_params, read_current_params
from .domain_map import get_allowed_params, DOMAIN_PARAM_SCOPE

__all__ = [
    "DriftableParam", "register", "get_driftable", "list_all",
    "TIER_WINDOWS", "TIER_DRIFT_RATES",
    "get_store", "BaselineStore",
    "apply_normal_drift", "apply_acute_drift", "apply_drift_cycle",
    "compute_shattering_force", "compute_update_resistance",
    "detect_and_process_shattering", "load_suppressed_tension",
    "correlations_to_drift_signals", "dimensions_to_param_paths",
    "make_emotion_weight_fn", "make_contradiction_fn",
    "write_drifted_params", "read_current_params",
    "get_allowed_params", "DOMAIN_PARAM_SCOPE",
]
