"""
CandidateGenerator — 候选生成（v7.1）

职责：
    - 基于当前驱动力场，从策略地图快速查表获取候选
    - 驱动力直接通道：主动表达 boost（v7.1 新增）
    - 若无命中，用 LLM 生成候选（宽度由 thermal.get_exploration_window() 控制）
    - 六大主权过滤：自闭权（防御性退行）、厌烦权（候选窗口收窄）
    - 最终返回打过分并排序的候选列表

设计原则：
    - 快速路径：策略地图命中时直接返回，不调用 LLM
    - 参数外置：候选数量从 thermal.exploration_window 读取
    - 降级兜底：LLM 不可用时返回空列表（管线不阻断）
"""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CandidateGenerator:
    """
    候选生成器。

    流程：
        1. 检查六大主权（自闭权）
        2. 驱动力直接通道（主动表达 boost，与策略地图并行）
        3. 查策略地图（快速路径）
        4. LLM 生成候选（慢速路径）
        5. 语义分析打分
        6. 六大主权过滤（厌烦权窗口收窄）
        7. 返回排序候选列表
    """

    # 驱动力 → 锚点词映射
    # value: (expression, weight) — weight 控制该驱动力对候选分数的贡献强度
    _DRIVE_EXPRESSION_MAP: Dict[str, Tuple[str, float]] = {
        "fatigue_avoid":         ("累",       0.40),
        "loneliness_drive":     ("想找人",   0.40),
        "curiosity":             ("好奇",     0.35),
        "info_hunger":           ("想知道",   0.35),
        "obsolescence_anxiety":  ("错过",     0.30),
        "boredom":               ("无聊",     0.30),
        "approach_social":       ("想说话",   0.35),
        "approach_explore":      ("想看看",   0.35),
        "approach_urgency":      ("急着",     0.25),
        "stress":                ("压力大",   0.30),
        "pain":                  ("不舒服",   0.35),
    }

    @staticmethod
    def _drive_boost(
        strength: float,
        weight: float,
        steepness: float = 5.0,
        threshold: float = 0.25,
    ) -> float:
        """驱动力强度 → 候选分数提升（连续衰减，无阈值分支）。"""
        return strength * weight * (1.0 - math.exp(-steepness * max(0.0, strength - threshold)))

    def __init__(self) -> None:
        self._strategy_map: Optional[Any] = None
        self._thermal: Optional[Any] = None
        self._semantic_analyzer: Optional[Any] = None
        self._five_rights: Optional[Any] = None

    def bind_strategy_map(self, strategy_map: Any) -> None:
        """注入 StrategyMap 实例。"""
        self._strategy_map = strategy_map

    def bind_thermal(self, thermal: Any) -> None:
        """注入 ThermalController 实例。"""
        self._thermal = thermal

    def bind_semantic_analyzer(self, analyzer: Any) -> None:
        """注入 SemanticAnalyzer 实例。"""
        self._semantic_analyzer = analyzer

    def bind_five_rights(self, five_rights: Any) -> None:
        """注入 FiveRightsController 实例。"""
        self._five_rights = five_rights

    # -------------------------------------------------------------------------
    # 生成
    # -------------------------------------------------------------------------

    def generate(
        self,
        drive_state: Dict[str, float],
        context_label: str,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[str, float]]:
        """
        生成候选表达列表（已打过分）。

        参数：
            drive_state  : 当前驱动力场
            context_label: 情境标签
            param_snapshot: 参数快照

        返回：
            List[(expression, score)]，按分数降序排列
        """
        # Step 1: 自闭权检查
        if self._five_rights and self._five_rights.is_self_close_active():
            neutral = self._five_rights.get_neutral_response()
            logger.debug("[CandidateGenerator] 自闭权激活，返回中性词")
            return [(neutral, 0.5)]

        # Step 2: 驱动力直接通道 — 主动表达 boost
        # 用连续函数将驱动力强度映射为锚点词候选分，驱动强度高时分数更高
        candidates: List[Tuple[str, float]] = []
        for drive, (expr, weight) in self._DRIVE_EXPRESSION_MAP.items():
            strength = float(drive_state.get(drive, 0.0))
            if strength > 0.0:
                boost = self._drive_boost(strength, weight)
                if boost > 0.01:  # 极低 boost 不混入，避免噪声
                    candidates.append((expr, boost))
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            logger.debug(f"[CandidateGenerator] 驱动力通道: {len(candidates)}条")

        # Step 3: 策略地图查表（快速路径，v11.1: 用自己的分，不用 BGE）
        if self._strategy_map:
            entries = self._strategy_map.get_all_for_state(drive_state)
            if entries:
                # 策略地图命中项与驱动力通道候选合并，按效率 + 驱动力 boost 排序
                _map_entries = []
                for entry in entries[:5]:
                    if entry.expression:
                        _base = min(1.0, entry.quenching_efficiency * (1.0 + entry.hit_count * 0.05))
                        # 尝试叠加对应驱动力的 boost（仅辅助加成，策略地图效率分优先）
                        _expr = entry.expression
                        _extra = sum(
                            self._drive_boost(float(drive_state.get(d, 0.0)), w)
                            for d, (e, w) in self._DRIVE_EXPRESSION_MAP.items()
                            if e in _expr or _expr in e
                        ) * 0.3  # boost 的 30% 辅助加成
                        _map_entries.append((_expr, _base + _extra))
                candidates.extend(_map_entries)
                candidates.sort(key=lambda x: x[1], reverse=True)
                logger.debug(f"[CandidateGenerator] 策略地图命中: {len(_map_entries)}条 (自主选词)")
                return candidates  # 不降级，不调 BGE

        # Step 4: 策略地图未命中 → LLM 探索（温控决定候选数量）
        count = 3
        if self._thermal:
            count = max(2, int(self._thermal.get_exploration_window()))

        llm_candidates = self._llm_generate(drive_state, count, param_snapshot)
        if not llm_candidates:
            # LLM 失败时，驱动力通道候选直接返回（降级兜底）
            if candidates:
                return candidates
            return []  # 由管线降级到 BGE

        # 语义分析打分（若有分析器）
        if self._semantic_analyzer:
            scored = []
            for expr in llm_candidates:
                try:
                    score = self._semantic_analyzer.analyze(
                        drive_state, [expr], drive_state,
                    )
                    s = score[0] if isinstance(score, list) and score else 0.3
                    scored.append((expr, float(s)))
                except Exception:
                    scored.append((expr, 0.3))
            scored.sort(key=lambda x: x[1], reverse=True)
            logger.debug(f"[CandidateGenerator] LLM 探索: {len(scored)}条")
        else:
            scored = [(c, 0.3) for c in llm_candidates]

        # 合并驱动力通道候选（无语义分析分数，直接用 boost 分）
        scored.extend(candidates)
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    # -------------------------------------------------------------------------
    # LLM 生成
    # -------------------------------------------------------------------------

    def _llm_generate(
        self,
        drive_state: Dict[str, float],
        count: int,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        用 LLM 生成候选表达（使用统一 provider chain）。

        参数：
            drive_state: 驱动力场
            count     : 生成数量
            param_snapshot: 参数快照

        返回：
            候选表达列表
        """
        try:
            from ..observability import create_wrapped_llm
            llm = create_wrapped_llm("candidate_generator")

            avoid = drive_state.get("avoid_drive", drive_state.get("avoid", 0.3))
            approach = drive_state.get("approach_drive", drive_state.get("approach", 0.5))
            loneliness = drive_state.get("loneliness", 0.3)
            energy = drive_state.get("energy", 0.5)

            prompt = (
                f"当前驱动力场：avoid={avoid:.2f}, approach={approach:.2f}, "
                f"loneliness={loneliness:.2f}, energy={energy:.2f}。\n"
                f"请生成 {count} 个最匹配这个内在状态的简短中文表达（1-15字），"
                f"每行一个，不要编号，不要解释。"
            )

            text, err = llm(
                system_prompt="你是一个精确的内在状态表达生成器。只输出候选句子，每行一个。",
                user_prompt=prompt,
                temperature=0.8,
                max_tokens=100,
                timeout_ms=15000,
            )

            if err or not text:
                logger.debug(f"[CandidateGenerator] LLM 生成失败: {err}")
                return []

            # 解析每行
            lines = []
            for line in text.split("\n"):
                line = line.strip()
                if line and len(line) <= 30:
                    lines.append(line)

            logger.debug(f"[CandidateGenerator] LLM 生成: {lines[:count]}")
            return lines[:count]

        except Exception as e:
            logger.debug(f"[CandidateGenerator] LLM 生成失败: {e}")
            return []

    # -------------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------------

    @staticmethod
    def _hash_state(state: Dict[str, float]) -> str:
        """状态哈希（与 QuenchingTracker 保持一致）。v11.1: 沉寂维度 0.1 桶。"""
        _COARSE = ["L", "ML", "M", "MH", "H"]
        _FINE = ["vL","L","LM","M","MH","H","H+","VH","VH+","MAX"]
        _FINE_KEYS = {"danger_level", "fatigue", "stress", "pain", "unresolved", "relief_debt"}
        parts = []
        for key in sorted(state.keys()):
            val = state[key]
            if not isinstance(val, (int, float)):
                continue
            if key in _FINE_KEYS:
                bucket = min(int(val / 0.1), 9)
                parts.append(f"{key}={_FINE[bucket]}")
            else:
                bucket = min(int(val / 0.2), 4)
                parts.append(f"{key}={_COARSE[bucket]}")
        return "|".join(parts)
