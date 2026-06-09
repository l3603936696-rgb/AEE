"""
Somatic Anchors — anchor table and clustering constants.

Re-exports from somatic_anchors_data.py.
Actual data lives in src.language_system.somatic_anchors_data.
"""

from .somatic_anchors_data import (
    SOMATIC_ANCHORS,
    ANCHOR_CLUSTERS,
    ALL_DIMENSIONS,
)

__all__ = ["SOMATIC_ANCHORS", "ANCHOR_CLUSTERS", "ALL_DIMENSIONS"]
