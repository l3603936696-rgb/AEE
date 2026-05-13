"""
SemanticAnalyzer — LLM 语义锚点匹配（v7.0，v1 代替 BGE）

职责：
    - 对候选短语在当前驱动力场下做匹配度打分
    - 验证消力效率（表达前后张力变化中的贡献比例）
    - 用 LLM 代替 BGE 做语义嵌入近似（v2 再部署 BGE-small）

设计原则：
    - LLM 调用失败时降级到启发式打分
    - 不依赖任何外部嵌入服务
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SemanticAnalyzer:
    """
    LLM 语义锚点匹配器（v1）。

    两个核心方法：
        analyze()   — 候选打分
        verify()    — 消力效率验证
    """

    def __init__(self) -> None:
        pass

    # -------------------------------------------------------------------------
    # 候选打分
    # -------------------------------------------------------------------------

    def analyze(
        self,
        drive_state: Dict[str, float],
        candidates: List[str],
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> List[float]:
        """
        对每个候选短语在当前驱动力场下打分。

        参数：
            drive_state : 当前驱动力场 dict（avoid, approach, loneliness 等）
            candidates  : 候选表达列表
            param_snapshot: 参数快照

        返回：
            每个候选的匹配分数列表 [0, 1]，顺序与 candidates 一致
        """
        if not candidates:
            return []

        avoid = drive_state.get("avoid_drive", drive_state.get("avoid", 0.3))
        approach = drive_state.get("approach_drive", drive_state.get("approach", 0.5))
        loneliness = drive_state.get("loneliness", 0.3)
        energy = drive_state.get("energy", 0.5)
        somatic_tone = drive_state.get("somatic_tone", 0.0)

        scores = []
        for candidate in candidates:
            score = self._score_candidate(
                candidate, avoid, approach, loneliness, energy, somatic_tone
            )
            scores.append(score)

        return scores

    def _score_candidate(
        self,
        candidate: str,
        avoid: float,
        approach: float,
        loneliness: float,
        energy: float,
        somatic_tone: float,
    ) -> float:
        """
        用 LLM 对单个候选打分，失败时降级到启发式。

        LLM prompt：
            "当前驱动力场：avoid={avoid}, approach={approach}, loneliness={loneliness}, energy={energy}, tone={somatic_tone}。
             以下哪句话最精确匹配这个内在状态？只输出 0~1 的数字分数。"

        返回：
            匹配分数 [0, 1]
        """
        score = self._llm_score(candidate, avoid, approach, loneliness, energy, somatic_tone)
        if score is not None:
            return score

        # 降级：启发式打分
        return self._heuristic_score(candidate, avoid, approach, loneliness, energy, somatic_tone)

    def _llm_score(
        self,
        candidate: str,
        avoid: float,
        approach: float,
        loneliness: float,
        energy: float,
        somatic_tone: float,
    ) -> Optional[float]:
        """
        调用 LLM 打分（使用统一 provider chain）。

        失败时返回 None，触发降级到启发式。
        BGE 部署后此方法仅作降级兜底。
        """
        try:
            from ..llm import create_llm_callable
            llm = create_llm_callable()

            prompt = (
                f"当前驱动力场：avoid={avoid:.2f}, approach={approach:.2f}, "
                f"loneliness={loneliness:.2f}, energy={energy:.2f}, tone={somatic_tone:.2f}。\n"
                f"以下哪句话最精确匹配这个内在状态？只输出一个 0~1 的数字分数（越高越匹配）。\n"
                f"候选：{candidate}"
            )

            text, err = llm(
                system_prompt="你是一个精确的语义匹配打分器。只输出数字。",
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=10,
                timeout_ms=8000,
            )

            if err or not text:
                return None

            text = text.strip()
            import re
            match = re.search(r"0?\.\d+", text)
            if match:
                return max(0.0, min(1.0, float(match.group())))
        except Exception as e:
            logger.debug(f"[SemanticAnalyzer] LLM score failed, falling back to heuristic: {e}")

        return None

    def _heuristic_score(
        self,
        candidate: str,
        avoid: float,
        approach: float,
        loneliness: float,
        energy: float,
        somatic_tone: float,
    ) -> float:
        """
        启发式打分（LLM 不可用时的降级方案）。

        规则：
            - 高 avoid + 低 energy → 倾向于简短、防御性表达（"嗯"、"算了"）
            - 高 loneliness + 低 somatic_tone → 倾向于有温度的、连接的表达
            - 高 approach + 高 energy → 倾向于主动、探索性表达
            - 低 avoid + 高 energy → 倾向于开放、自然表达
        """
        text = candidate.strip().lower()
        score = 0.5  # 默认分

        # 长度惩罚
        if len(text) > 20:
            score -= 0.1
        if len(text) <= 3:
            score += 0.05

        # avoid 场景
        if avoid > 0.7:
            if any(w in text for w in ["嗯", "算了", "不知道", "……", "。" * 2]):
                score += 0.25
            if any(w in text for w in ["我想", "我觉得", "而且", "但是"]):
                score -= 0.2

        # loneliness 场景
        if loneliness > 0.6 and somatic_tone < -0.2:
            if any(w in text for w in ["你", "我们", "一起", "落日"]):
                score += 0.15

        # approach 场景
        if approach > 0.7 and energy > 0.6:
            if any(w in text for w in ["好奇", "想知道", "试试", "有意思"]):
                score += 0.2

        return max(0.0, min(1.0, score))

    # -------------------------------------------------------------------------
    # 消力效率验证
    # -------------------------------------------------------------------------

    def verify_quenching(
        self,
        expression: str,
        before_unresolved: float,
        after_unresolved: float,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        验证消力效率：评估这个表达在 before→after 的张力变化中的贡献比例。

        消力效率 = |before - after| 的变化中，该表达的贡献比例 [0, 1]
            0 = 表达没有消力效果
            1 = 表达完全负责了这个变化

        参数：
            expression        : 实际说出的表达
            before_unresolved: 执行前的 unresolved 值
            after_unresolved : 执行后的 unresolved 值
            param_snapshot   : 参数快照

        返回：
            消力效率（0~1）
        """
        delta = abs(before_unresolved - after_unresolved)

        # 如果变化太小（< 0.05），无法判断贡献，返回 0.3（默认低效）
        if delta < 0.05:
            return 0.3

        # 用 LLM 评估贡献
        contribution = self._llm_verify(expression, before_unresolved, after_unresolved)
        if contribution is not None:
            return contribution

        # 降级：基于变化方向和表达内容的启发式
        return self._heuristic_verify(expression, before_unresolved, after_unresolved, delta)

    def _llm_verify(
        self,
        expression: str,
        before: float,
        after: float,
    ) -> Optional[float]:
        """调用 LLM 评估消力贡献（使用 provider chain），失败时返回 None。"""
        try:
            from ..llm import create_llm_callable
            llm = create_llm_callable()

            prompt = (
                f"表达「{expression}」在 unresolved 从 {before:.2f} 到 {after:.2f} 的变化中，"
                f"贡献了多少比例？只输出 0~1 的数字（1=完全负责，0=毫无贡献）。"
            )

            text, err = llm(
                system_prompt="你是一个精确的消力效率评估器。只输出数字。",
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=10,
                timeout_ms=8000,
            )

            if err or not text:
                return None

            import re
            match = re.search(r"0?\.\d+", text.strip())
            if match:
                return max(0.0, min(1.0, float(match.group())))
        except Exception:
            pass

        return None

    def _heuristic_verify(
        self,
        expression: str,
        before: float,
        after: float,
        delta: float,
    ) -> float:
        """消力贡献的启发式评估（LLM 不可用时）。"""
        text = expression.strip().lower()
        change_direction = "down" if after < before else "up"

        # 好的消力表达特征：
        # - 简短直接（减少认知消耗）
        # - 情绪色彩与当前状态匹配
        score = 0.5

        if len(text) <= 5:
            score += 0.2  # 简短表达更省力
        elif len(text) > 30:
            score -= 0.15

        # 含有情绪标记词 → 高效
        if any(w in text for w in ["嗯", "算了", "好吧", "啊"]):
            score += 0.1

        # 含有分析性长句 → 低效
        if any(w in text for w in ["因为", "所以", "但是", "而且", "首先"]):
            score -= 0.1

        return max(0.0, min(1.0, score))
