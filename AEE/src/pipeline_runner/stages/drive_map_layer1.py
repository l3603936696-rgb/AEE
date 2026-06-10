"""drive_map 层1 — somatic keyword 直击 drive 维度

职责（一句话）：从输入文本中提取体感词典关键词，直接映射到 5维 drive 空间，
不经过 BGE 或语言模型，是三层中最直接、权重最高的层。
"""
import logging
from typing import Dict, List

from .drive_map_utils import _DIMS, _SOMATIC_TO_DRIVE

logger = logging.getLogger(__name__)


def _load_somatic_dictionary() -> Dict:
    """懒加载体感词典。"""
    try:
        from ...language_system.somatic_dictionary import SOMATIC_DICTIONARY
        return SOMATIC_DICTIONARY
    except Exception:
        return {}


def extract_drive_from_somatic(input_text: str) -> Dict[str, float]:
    """
    层1核心：从输入文本中提取体感词典关键词，直接映射到 5维 drive 空间。

    流程：
        输入文本 → 字符匹配 → 找 SOMATIC_DICTIONARY 关键词
        → 提取关键词的 drive profile → 汇总到 5维 drive 空间

    多关键词命中时，各维度取绝对值最强的方向（不叠加，只取最强信号）。
    返回空 dict 代表无关键词命中。
    """
    somatic = _load_somatic_dictionary()
    if not somatic:
        return {}

    text = str(input_text)
    text_lower = text.lower()

    hit_dims: Dict[str, List[float]] = {d: [] for d in _DIMS}

    for category, entries in somatic.items():
        if not isinstance(entries, dict):
            continue
        for word, profile in entries.items():
            if not word or not isinstance(profile, dict):
                continue
            if word in text_lower or word in text:
                for somatic_dim, drive_mapping in _SOMATIC_TO_DRIVE.items():
                    somatic_val = float(profile.get(somatic_dim, 0.0))
                    if abs(somatic_val) < 0.05:
                        continue
                    for spm_dim, weight in drive_mapping.items():
                        hit_dims[spm_dim].append(somatic_val * weight)

    if not any(hit_dims[d] for d in _DIMS):
        return {}

    drive_vector: Dict[str, float] = {}
    for dim, values in hit_dims.items():
        if not values:
            continue
        pos = max((v for v in values if v > 0), default=0.0)
        neg = min((v for v in values if v < 0), default=0.0)
        # 取绝对值最强的方向
        dominant = pos if abs(pos) >= abs(neg) else abs(neg)
        drive_vector[dim] = max(0.0, min(1.0, dominant))

    return drive_vector


def collect_somatic_hits(input_text: str) -> List[str]:
    """返回输入文本中命中的体感词典关键词列表（去重，用于日志和解释）。"""
    somatic = _load_somatic_dictionary()
    if not somatic:
        return []

    text = str(input_text)
    text_lower = text.lower()
    hits: List[str] = []

    for category, entries in somatic.items():
        if not isinstance(entries, dict):
            continue
        for word in entries.keys():
            if (word in text_lower or word in text) and word not in hits:
                hits.append(word)

    return hits
