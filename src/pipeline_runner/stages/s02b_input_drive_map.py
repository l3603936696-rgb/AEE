"""Input → Drive 空间映射 — 三层融合入口 (stage s02b)

职责（一句话）：编排三层映射（somatic keyword / BGE / drive 空间最近邻），
将结果加权融合后写入 PipelineContext，供后续阶段使用。

层实现分布：
    层1 somatic keyword  → drive_map_layer1.py
    层2 BGE 语义匹配     → drive_map_layer2.py
    层3 drive 空间 + 融合 → 本文件
    共用常量/工具函数     → drive_map_utils.py

三层并行架构：
    层1（somatic keyword）: 输入 → 体感词典关键词 → drive 向量直击（最高权重）
    层2（BGE 语义）       : 输入 → BGE 嵌入 → 已命名符号文本相似度
    层3（drive 空间）     : 层1/2 融合向量 → SPM 全符号（包括未命名）drive 最近邻
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from .drive_map_utils import _DIMS, _DRIVE_BASELINE, _LAYER_WEIGHTS, _drive_cosine, _weighted_combine
from .drive_map_layer1 import extract_drive_from_somatic, collect_somatic_hits
from .drive_map_layer2 import layer2_bge_match

logger = logging.getLogger(__name__)


# ============================================================================
# 层3：drive 空间最近邻（全部符号，包括未命名）
# ============================================================================

def _layer3_drive_space_match(
    query_drive: Dict[str, float],
    spm_data: Dict[str, Any],
) -> Dict[str, float]:
    """
    层3核心：query drive 向量与 SPM 中全部符号的 drive 质心做余弦相似度。

    关键设计：包括未命名符号——它们没有外部词绑定，但有 drive 质心，
    是最原始的内部体验的载体。

    返回：{symbol_name: resonance_score}，仅含 resonance > 0.01 的符号。
    """
    if not query_drive:
        return {}

    resonances: Dict[str, float] = {}
    for p in spm_data.get("patterns", []):
        symbol = p.get("symbol")
        center = p.get("center", {})
        if not symbol or not center:
            continue
        sim = _drive_cosine(query_drive, center)
        # [-1, 1] → [0, 1] 归一化
        resonance = max(0.0, min(1.0, (sim + 1.0) * 0.5))
        if resonance > 0.01:
            resonances[symbol] = resonance

    return resonances


# ============================================================================
# 三层融合
# ============================================================================

def _build_layer3_query(
    layer1_drive: Dict[str, float],
    layer2_drive: Optional[Dict[str, float]],
    current_drive_state: Optional[Dict[str, float]],
) -> Dict[str, float]:
    """构造层3 的查询向量：层1/2 结果加权，再以当前 drive 状态做微弱偏置。"""
    query: Dict[str, float] = {}

    if layer1_drive and layer2_drive:
        for dim in _DIMS:
            query[dim] = 0.6 * layer1_drive.get(dim, 0.0) + 0.4 * layer2_drive.get(dim, 0.0)
    elif layer1_drive:
        query = dict(layer1_drive)
    elif layer2_drive:
        query = dict(layer2_drive)

    if current_drive_state:
        for dim in _DIMS:
            base = query.get(dim, 0.0)
            cur = float(current_drive_state.get(dim, _DRIVE_BASELINE.get(dim, 0.3)))
            query[dim] = 0.9 * base + 0.1 * cur

    return query


def map_input_to_drive(
    input_text: str,
    spm_data: Dict[str, Any],
    current_drive_state: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    三层融合主函数：输入文本 → drive 激活向量。

    返回：
        drive_vector     — 最终融合 drive 激活向量
        layer1_drive     — 层1 somatic keyword 结果
        layer2_drive     — 层2 BGE 语义结果
        all_resonances   — 层3 全符号 drive 共鸣 {symbol: score}
        best_symbol      — 层2 最佳匹配符号名
        best_similarity  — 层2 最佳匹配相似度
        somatic_hits     — 层1 命中的关键词列表
        layers_used      — 实际使用的层名列表
        has_match        — 是否有有效匹配
    """
    if not input_text or not str(input_text).strip():
        return _empty_result()

    # 层1
    layer1_drive = extract_drive_from_somatic(input_text)
    somatic_hits = collect_somatic_hits(input_text) if layer1_drive else []

    # 层2
    layer2_drive, layer2_info = layer2_bge_match(input_text, spm_data)
    best_symbol = layer2_info["symbol"] if layer2_info else None
    best_similarity = layer2_info.get("similarity", 0.0) if layer2_info else 0.0

    # 层3
    query = _build_layer3_query(layer1_drive, layer2_drive, current_drive_state)
    all_resonances = _layer3_drive_space_match(query, spm_data)

    # 融合
    sources: List[Dict[str, float]] = []
    weights: List[float] = []

    if layer1_drive:
        sources.append(layer1_drive)
        weights.append(_LAYER_WEIGHTS["somatic_keyword"])
    if layer2_drive:
        sources.append(layer2_drive)
        weights.append(_LAYER_WEIGHTS["bge_semantic"])
    if all_resonances:
        top_symbol = max(all_resonances, key=all_resonances.get)
        top_resonance = all_resonances[top_symbol]
        if top_resonance > 0.3:
            for p in spm_data.get("patterns", []):
                if p.get("symbol") == top_symbol and p.get("center"):
                    sources.append(p["center"])
                    weights.append(_LAYER_WEIGHTS["drive_space"] * top_resonance)
                    break

    if not sources:
        return _empty_result()

    final_drive_vector = _weighted_combine(sources, weights)

    # 兜底：层1/2 无输出但层3 有结果时，用 top 符号质心
    if not final_drive_vector and all_resonances:
        top_symbol = max(all_resonances, key=all_resonances.get)
        for p in spm_data.get("patterns", []):
            if p.get("symbol") == top_symbol:
                final_drive_vector = dict(p.get("center", {}))
                break

    layers_used = (
        (["somatic_keyword"] if layer1_drive else [])
        + (["bge_semantic"] if layer2_drive else [])
        + (["drive_space"] if all_resonances else [])
    )

    return {
        "drive_vector":    final_drive_vector,
        "layer1_drive":    layer1_drive,
        "layer2_drive":    layer2_drive,
        "all_resonances":  all_resonances,
        "best_symbol":     best_symbol,
        "best_similarity": best_similarity,
        "somatic_hits":    somatic_hits,
        "layers_used":     layers_used,
        "has_match":       best_symbol is not None or bool(all_resonances),
    }


def _empty_result() -> Dict[str, Any]:
    return {
        "drive_vector": {}, "layer1_drive": {}, "layer2_drive": {},
        "all_resonances": {}, "best_symbol": None, "best_similarity": 0.0,
        "somatic_hits": [], "layers_used": [], "has_match": False,
    }


def compute_resonance_with_spm(
    activated_drive: Dict[str, float],
    spm_data: Dict[str, Any],
) -> Dict[str, float]:
    """直接用 drive 向量查 SPM 共鸣（层3 已算过时复用，未算时兜底调用）。"""
    return _layer3_drive_space_match(activated_drive, spm_data)


# ============================================================================
# Pipeline 入口
# ============================================================================

def run_input_drive_mapping(ctx, entity) -> None:
    """
    Pipeline stage：输入 → drive 空间三层映射，结果写入 ctx。

    写入：
        ctx._input_drive_map  — 完整映射结果 dict
        ctx._spm_resonance    — SPM 共鸣信号 {symbol: score}
    """
    map_result = map_input_to_drive(
        input_text=str(ctx.raw_input or ""),
        spm_data=getattr(entity, "_state_pattern_data", {}),
        current_drive_state=getattr(ctx, "drive_vector", None),
    )

    all_resonances = map_result.get("all_resonances", {})
    if not all_resonances:
        all_resonances = compute_resonance_with_spm(
            map_result.get("drive_vector", {}),
            getattr(entity, "_state_pattern_data", {}),
        )

    ctx._input_drive_map = map_result
    ctx._spm_resonance = all_resonances
    entity._last_input_drive_map = map_result
    entity._last_spm_resonance = all_resonances

    ctx.input_context = {
        "text": str(ctx.raw_input or ""),
        "spm_resonance": all_resonances,
        "best_symbol": map_result.get("best_symbol"),
        "best_similarity": float(map_result.get("best_similarity", 0.0)),
        "somatic_hits": map_result.get("somatic_hits", []),
        "layers_used": map_result.get("layers_used", []),
    }

    if entity.tick % 10 == 0 and map_result["layers_used"]:
        logger.info(
            f"[InputDriveMap] t={entity.tick} "
            f"layers={map_result['layers_used']} "
            f"somatic_hits={map_result.get('somatic_hits', [])} "
            f"best={map_result['best_symbol']} "
            f"resonances={len(all_resonances)} symbols"
        )
