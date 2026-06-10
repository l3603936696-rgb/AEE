"""
Stereotype Memory — MEMORY.md tag extraction and tree initialization.

Submodules of src.language_system.stereotype_learner:
    stereotype_markers.py — linguistic marker constants
    stereotype_memory.py  — MEMORY.md extraction and tree init
    stereotype_learner.py — FeatureExtractor + TagInferrer + StereotypeLearner
"""

import os
from typing import Dict, List


def extract_tags_from_memory(
    memory_path: str = "MEMORY.md",
) -> Dict[str, List[str]]:
    """
    从 MEMORY.md 提取说话者的基础标签。

    提取维度：
        - category   : 基础类别（大二学生）
        - region     : 地区/文化（UTC+8）
        - situation  : 社会情境（机械专业、民办本科、一人工公司）
        - individual : 个体标识（bcyq）
    """
    if not os.path.exists(memory_path):
        return {}

    try:
        with open(memory_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return {}

    tags = {
        "category": [],
        "region": [],
        "situation": [],
        "individual": [],
    }

    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if "bcyq" in line.lower():
            tags["individual"].append("bcyq")

        if "背景" in line or "专业" in line:
            if "机械" in line:
                tags["situation"].append("理工科")
                tags["situation"].append("机械专业")
            if "大二" in line:
                tags["category"].append("大学生")
                tags["category"].append("大二学生")
            if "民办" in line:
                tags["situation"].append("民办本科")
            if "二本" in line:
                tags["situation"].append("二本")

        if "UTC" in line or "时区" in line:
            if "UTC+8" in line:
                tags["region"].append("亚洲东部")
                tags["region"].append("UTC+8")

        if "项目" in line or "XIA" in line:
            tags["situation"].append("AI项目")
            if "一人公司" in line:
                tags["situation"].append("一人公司")

        if "工作区" in line:
            if "Windows" in line:
                tags["region"].append("Windows用户")
            if "WSL" in line:
                tags["region"].append("WSL2用户")

    for key in tags:
        tags[key] = list(dict.fromkeys(tags[key]))

    return tags


def init_tree_from_memory(
    entity,
    memory_path: str = "MEMORY.md",
    speaker_id: str = "bcyq",
) -> None:
    """
    从 MEMORY.md 提取标签，初始化说话者在刻板印象树中的位置。
    """
    from .stereotype_tree import ensure_tree

    tags = extract_tags_from_memory(memory_path)
    if not tags or not any(tags.values()):
        return

    tree = ensure_tree(entity)

    def _first(lst: list, fallback: str = "general") -> str:
        return lst[0] if lst else fallback

    path_layers = [
        _first(tags.get("category", [])),
        _first(tags.get("region",   [])),
        _first(tags.get("situation",[])),
    ]

    seen: set = set()
    filtered_tags: list = []
    for layer_tags in tags.values():
        for t in layer_tags:
            if t != speaker_id and t not in seen:
                filtered_tags.append(t)
                seen.add(t)

    node = tree.add_individual(
        speaker_id=speaker_id,
        initial_tags=filtered_tags,
        initial_features=None,
        path_layers=path_layers,
    )
    if node and filtered_tags and not getattr(node, "_category_tags", None):
        node._category_tags = list(filtered_tags)
