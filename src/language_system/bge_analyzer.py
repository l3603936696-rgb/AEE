"""
BGE Semantic Analyzer — BGE-small-zh-v1.5 嵌入锚点匹配（v7.0 v2）

替代原来的 LLM 打分方案。
用 BGE 嵌入将驱动力场描述和候选表达映射到同一向量空间，
通过余弦相似度做锚点匹配打分。

设计原则：
    - 纯本地推理，无网络依赖
    - 模型懒加载（首次调用时加载，后续缓存）
    - BGE 不可用时自动降级到 LLM 启发式打分
    - BGE-small-zh-v1.5: 24M 参数，512 维嵌入，CPU 友好

安装依赖：
    pip install sentence-transformers

模型下载：
    首次运行自动从 HuggingFace 下载 (~100MB)
    或手动放到 models/bge-small-zh-v1.5/
"""

import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 模块级缓存
_bge_model = None  # SentenceTransformer 实例


def _get_bge_model():
    """懒加载 BGE 模型（首次调用时下载/加载）。"""
    global _bge_model
    if _bge_model is not None:
        return _bge_model

    try:
        import os as _os
        from pathlib import Path as _Path
        _os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        _os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer
        _model_path = _Path(__file__).parent.parent.parent / "models" / "bge-small-zh-v1.5"
        _bge_model = SentenceTransformer(
            str(_model_path),
            local_files_only=True,
        )
        logger.info("[BGEAnalyzer] BGE-small-zh-v1.5 loaded successfully")
        return _bge_model
    except ImportError:
        logger.warning(
            "[BGEAnalyzer] sentence-transformers not installed. "
            "Run: pip install sentence-transformers. Falling back to LLM heuristic."
        )
        return None
    except Exception as e:
        logger.warning(f"[BGEAnalyzer] BGE model load failed: {e}. Falling back to LLM heuristic.")
        return None


def _drive_state_to_text(drive_state: Dict[str, float]) -> str:
    """
    将驱动力场转换为驱动力分析锚点描述（供 BGE 嵌入匹配）。

    短句阶段使用固定模板，每个维度用离散等级标注，
    让 BGE 能在"驱动力场→候选表达"之间建立精确语义映射。
    随策略地图积累，锚点描述逐渐细化（组合阶段→自由表达阶段）。
    """
    def _level(v: float) -> str:
        if v < 0.2: return "极低"
        if v < 0.4: return "较低"
        if v < 0.6: return "中等"
        if v < 0.8: return "较高"
        return "极高"

    avoid = drive_state.get("avoid_drive", drive_state.get("avoid", 0.3))
    approach = drive_state.get("approach_drive", drive_state.get("approach", 0.5))
    loneliness = drive_state.get("loneliness", 0.3)
    energy = drive_state.get("energy", 0.5)
    somatic = drive_state.get("somatic_tone", 0.0)
    unresolved = drive_state.get("unresolved", 0.2)
    boredom = drive_state.get("boredom", 0.2)
    # v11 新维度
    fatigue = drive_state.get("fatigue", 0.1)
    danger = drive_state.get("danger_level", 0.0)
    stress = drive_state.get("stress", 0.1)
    pain = drive_state.get("pain", 0.0)
    relief_debt = drive_state.get("relief_debt", 0.0)
    # v11 子驱动力
    social = drive_state.get("approach_social", approach * 0.4)
    explore = drive_state.get("approach_explore", approach * 0.35)
    urgency = drive_state.get("approach_urgency", approach * 0.25)

    # 结构化锚点模板（v11: 扩展至 12 维）
    return (
        f"回避={_level(avoid)}，趋近={_level(approach)}，"
        f"孤独={_level(loneliness)}，能量={_level(energy)}，"
        f"身体感受={_level((somatic + 1) / 2)}，"
        f"心事={_level(unresolved)}，无聊={_level(boredom)}，"
        f"疲惫={_level(fatigue)}，危险={_level(danger)}，"
        f"压力={_level(stress)}，疼痛={_level(pain)}，"
        f"亏欠={_level(relief_debt)}，"
        f"社交欲={_level(social)}，探索欲={_level(explore)}，紧迫感={_level(urgency)}"
    )


def bge_score_candidates(
    drive_state: Dict[str, float],
    candidates: List[str],
) -> List[float]:
    """
    用 BGE 嵌入对每个候选短语在驱动力场下打分。

    参数：
        drive_state: 当前驱动力场
        candidates : 候选表达列表

    返回：
        每个候选的匹配分数 [0, 1]
    """
    model = _get_bge_model()
    if model is None or not candidates:
        return [0.5] * len(candidates)

    try:
        state_text = _drive_state_to_text(drive_state)
        # 同时编码状态描述和所有候选
        texts = [state_text] + list(candidates)
        embeddings = model.encode(texts, normalize_embeddings=True)

        state_embedding = embeddings[0]
        candidate_embeddings = embeddings[1:]

        scores = []
        for cand_emb in candidate_embeddings:
            # 余弦相似度（已归一化，点积即余弦）
            sim = float(state_embedding @ cand_emb)
            # 映射到 [0, 1]（余弦 ∈ [-1, 1]）
            score = (sim + 1.0) / 2.0
            scores.append(max(0.0, min(1.0, score)))

        return scores
    except Exception as e:
        logger.warning(f"[BGEAnalyzer] Scoring failed: {e}")
        return [0.5] * len(candidates)


# =============================================================================
# SemanticAnalyzerV2 — 兼容现有接口的包装器
# =============================================================================

class SemanticAnalyzerV2:
    """
    BGE 驱动的语义锚点匹配器（v2）。

    与 v1 SemanticAnalyzer 接口兼容，可直接替换。
    优先用 BGE 打分，不可用时降级到 LLM 启发式。
    """

    def __init__(self) -> None:
        pass

    def analyze(
        self,
        drive_state: Dict[str, float],
        candidates: List[str],
        param_snapshot: Optional[Dict[str, Any]] = None,
        use_somatic: bool = True,
        somatic_blend: float = 0.35,
    ) -> List[float]:
        """
        BGE 优先打分，降级到启发式。应用感质缩放。

        新增：体感打分融合（use_somatic=True 时）。
        将候选词的预期身体感受和当前需求匹配度融入得分。
        权重：bge_score * (1-somatic_blend) + somatic_score * somatic_blend
        """
        if not candidates:
            return []

        # 尝试 BGE
        bge_scores = bge_score_candidates(drive_state, candidates)
        if bge_scores and any(s != 0.5 for s in bge_scores):
            scores = bge_scores
        else:
            # 降级：启发式打分
            scores = self._heuristic_scores(drive_state, candidates)
        # ---- 诊断精度融合 (State Match Score) ----
        # 候选词有多准确地描述了她当前的身体状态？
        # 越精准的诊断 → 越高的消力潜力（如果之后被选中并验证匹配）
        if use_somatic:
            try:
                from .somatic_concept_map import get_state_match_score
                somatic_scores = [
                    get_state_match_score(c, drive_state)
                    for c in candidates
                ]
                scores = [
                    s * (1.0 - somatic_blend) + ss * somatic_blend
                    for s, ss in zip(scores, somatic_scores)
                ]
            except ImportError:
                pass  # somatic_concept_map 不可用时静默跳过

        # ---- 感质缩放 (Somatic Scaling) ----
        # somatic_tone 低 → 匹配窗口收窄 → 语言必须更精确才能消力
        # somatic_tone 高 → 匹配窗口放宽 → 语言可以更自由探索
        somatic_tone = float(drive_state.get("somatic_tone", 0.0))
        if somatic_tone < 0.0:
            # 痛苦时收紧窗口：负分被放大惩罚，只有高分候选通过
            scaling = 2.0  # 惩罚系数
            scores = [
                s * (1.0 + somatic_tone * scaling)  # somatic_tone 为负，效果是缩小
                for s in scores
            ]
        elif somatic_tone > 0.2:
            # 平静/愉悦时放宽窗口
            scaling = 0.5
            scores = [
                s + (1.0 - s) * somatic_tone * scaling
                for s in scores
            ]
        scores = [max(0.0, min(1.0, s)) for s in scores]

        return scores

    def verify_quenching(
        self,
        expression: str,
        before_unresolved: float,
        after_unresolved: float,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> float:
        """消力效率验证（基于 delta 的连续计算）。"""
        delta = abs(before_unresolved - after_unresolved)
        if delta < 0.01:
            return 0.0
        # 表达式越短 + delta 越大 → 效率越高
        efficiency = delta * (1.0 / max(1.0, len(expression) / 10.0))
        return max(0.0, min(1.0, efficiency))

    def _heuristic_scores(
        self,
        drive_state: Dict[str, float],
        candidates: List[str],
    ) -> List[float]:
        """降级启发式打分（与 v1 相同逻辑）。"""
        avoid = drive_state.get("avoid_drive", drive_state.get("avoid", 0.3))
        approach = drive_state.get("approach_drive", drive_state.get("approach", 0.5))
        loneliness = drive_state.get("loneliness", 0.3)
        energy = drive_state.get("energy", 0.5)
        somatic_tone = drive_state.get("somatic_tone", 0.0)

        scores = []
        for candidate in candidates:
            text = candidate.strip().lower()
            score = 0.5

            if len(text) > 20:
                score -= 0.1
            if len(text) <= 3:
                score += 0.05

            if avoid > 0.7:
                if any(w in text for w in ["嗯", "算了", "不知道", "……"]):
                    score += 0.25
                if any(w in text for w in ["我想", "我觉得", "而且", "但是"]):
                    score -= 0.2

            if loneliness > 0.6 and somatic_tone < -0.2:
                if any(w in text for w in ["你", "我们", "一起"]):
                    score += 0.15

            if approach > 0.7 and energy > 0.6:
                if any(w in text for w in ["好奇", "想知道", "试试", "有意思"]):
                    score += 0.2

            scores.append(max(0.0, min(1.0, score)))
        return scores
