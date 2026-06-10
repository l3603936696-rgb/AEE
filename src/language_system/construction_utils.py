"""
Construction Utilities — standalone helper functions for construction grammar.

Submodules of src.language_system.construction_grammar:
    construction_schema.py — hyperparameters + class definitions
    construction_grammar.py — ConstructionLearner class
    construction_utils.py — standalone helper functions
"""

from typing import Dict


def _infer_anchor_pos(template_str: str) -> str:
    """
    Infer anchor position from template string.

    Returns: "head" (first 1/3) | "tail" (last 1/3) | "adj" (middle) | "none"
    """
    if "{anchor}" not in template_str:
        return "none"
    idx = template_str.index("{anchor}")
    total = len(template_str)
    ratio = idx / max(total, 1)
    if ratio < 0.3:
        return "head"
    elif ratio > 0.65:
        return "tail"
    else:
        return "adj"
