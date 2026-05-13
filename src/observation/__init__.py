"""
src/observation/__init__.py — 观测层导出
"""

from .behavior_trace import (
    build_connection_trace,
    build_loneliness_trace,
    compute_trend,
    compute_profile,
    get_observation_summary,
)
from .counterfactual_probe import run_counterfactual_probe, _generate_counterfactual_analysis
from .probe_logger import ProbeLogger

__all__ = [
    "build_connection_trace",
    "build_loneliness_trace",
    "compute_trend",
    "compute_profile",
    "get_observation_summary",
    "run_counterfactual_probe",
    "_generate_counterfactual_analysis",
    "ProbeLogger",
]
