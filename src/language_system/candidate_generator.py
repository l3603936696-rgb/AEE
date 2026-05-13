"""
CandidateGenerator — 候选生成（v7.0）

职责：
    - 基于当前驱动力场，从策略地图快速查表获取候选
    - 若无命中，用 LLM 生成候选（宽度由 thermal.get_exploration_window() 控制）
    - 六大主权过滤：自闭权（防御性退行）、厌烦权（候选窗口收窄）
    - 最终返回打过分并排序的候选列表

设计原则：
    - 快速路径：策略地图命中时直接返回，不调用 LLM
    - 参数外置：候选数量从 thermal.exploration_window 读取
    - 降级兜底：LLM 不可用时返回空列表（管线不阻断）
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CandidateGenerator:
    """
    候选生成器。

    流程：
        1. 检查六大主权（自闭权）
        2. 查策略地图（快速路径）
        3. LLM 生成候选（慢速路径）
        4. 语义分析打分
        5. 六大主权过滤（厌烦权窗口收窄）
        6. 返回排序候选列表
    """

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

        # Step 2: 策略地图查表（快速路径，v11.1: 用自己的分，不用 BGE）
        candidates: List[Tuple[str, float]] = []
        if self._strategy_map:
            entries = self._strategy_map.get_all_for_state(drive_state)
            if entries:
                # 用策略地图自己的效率分，BGE 不参与
                for entry in entries[:5]:
                    if entry.expression:
                        # 效率 × 命中次数加权
                        _map_score = min(1.0, entry.quenching_efficiency * (1.0 + entry.hit_count * 0.05))
                        candidates.append((entry.expression, _map_score))
                candidates.sort(key=lambda x: x[1], reverse=True)
                logger.debug(f"[CandidateGenerator] 策略地图命中: {len(candidates)}条 (自主选词)")
                return candidates  # 不降级，不调 BGE

        # Step 3: 策略地图未命中 → 返回空，由管线降级到 BGE
        return []

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
            from ..llm import create_llm_callable
            llm = create_llm_callable()

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
