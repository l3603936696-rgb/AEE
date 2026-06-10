"""drive_map 层2 — BGE 语义匹配已命名符号

职责（一句话）：用 BGE 嵌入将输入文本与 SPM 中已命名符号的文本描述做相似度匹配，
BGE 不可用时自动降级到 TF-IDF，返回最佳匹配符号的 drive 质心。
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from .drive_map_utils import (
    _DIMS, _DIM_LEVEL_LABELS, _level_index,
    _cosine_sim_vec, _tfidf_sim,
)

logger = logging.getLogger(__name__)

# 模块级 BGE 模型缓存（懒加载，避免重复初始化）
_bge_model = None


def _get_bge_model():
    """懒加载 BGE 模型，失败时返回 None（触发 TF-IDF 降级）。"""
    global _bge_model
    if _bge_model is not None:
        return _bge_model
    try:
        import os as _os
        from pathlib import Path as _Path
        _os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        _os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer
        _model_path = _Path(__file__).parent.parent.parent.parent.parent / "models" / "bge-small-zh-v1.5"
        _bge_model = SentenceTransformer(str(_model_path), local_files_only=True)
        logger.info("[InputDriveMap/L2] BGE model loaded")
        return _bge_model
    except ImportError:
        logger.warning("[InputDriveMap/L2] sentence-transformers not installed, using TF-IDF")
        return None
    except Exception as e:
        logger.warning(f"[InputDriveMap/L2] BGE load failed: {e}, using TF-IDF")
        return None


def _bge_embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    """用 BGE 嵌入文本列表，返回归一化向量列表。失败返回 None。"""
    model = _get_bge_model()
    if model is None:
        return None
    try:
        embeddings = model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()
    except Exception as e:
        logger.warning(f"[InputDriveMap/L2] BGE embed failed: {e}")
        return None


def symbol_to_text_description(
    symbol: str,
    drive_center: Dict[str, float],
    named_as: Optional[str] = None,
) -> str:
    """将内部符号转换为可供 BGE 匹配的文本描述。"""
    parts = [symbol]
    if named_as:
        parts.append(f"也叫{named_as}")
    parts.append("状态：")
    dim_descs = [
        _DIM_LEVEL_LABELS[dim][_level_index(float(drive_center.get(dim, 0.0)))]
        for dim in _DIMS
    ]
    parts.append("，".join(dim_descs))
    return "".join(parts)


def layer2_bge_match(
    input_text: str,
    spm_data: Dict[str, Any],
) -> Tuple[Optional[Dict[str, float]], Optional[Dict[str, Any]]]:
    """
    层2核心：输入文本与 SPM 已命名符号做 BGE（或 TF-IDF）语义匹配。

    返回：
        (drive_center, match_info) — 最佳匹配符号的 drive 质心 + 元信息
        (None, None)               — 无有效匹配（best_score < 0.01）
    """
    patterns = spm_data.get("patterns", [])
    named_patterns = [p for p in patterns if p.get("symbol") and p.get("named_as")]
    if not named_patterns:
        return None, None

    symbol_descs = []
    for p in named_patterns:
        desc = symbol_to_text_description(
            p["symbol"],
            p.get("center", {}),
            p.get("named_as", ""),
        )
        symbol_descs.append((p["symbol"], desc, p.get("center", {})))

    descriptions = [desc for _, desc, _ in symbol_descs]

    embeddings = _bge_embed_texts([input_text] + descriptions)
    if embeddings:
        input_emb = embeddings[0]
        raw_scores = [_cosine_sim_vec(input_emb, emb) for emb in embeddings[1:]]
    else:
        raw_scores = [_tfidf_sim(input_text, desc) for desc in descriptions]

    best_idx = max(range(len(raw_scores)), key=lambda i: raw_scores[i])
    best_score = raw_scores[best_idx]
    if best_score < 0.01:
        return None, None

    best_symbol, _, best_center = symbol_descs[best_idx]
    return dict(best_center), {
        "symbol": best_symbol,
        "drive_center": dict(best_center),
        "similarity": max(0.0, min(1.0, best_score)),
        "named_as": named_patterns[best_idx].get("named_as", ""),
    }
