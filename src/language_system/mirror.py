"""
MirrorLearner — 镜像学习 + 误解权（v7.0）

职责：
    - 吸收用户教给她的词条，建立自己版本的语义理解
    - 不直接学原词原义——先在驱动力场上做反向审计
    - 用 LLM 分析该词对应的驱动力组合（avoid/approach/loneliness 各几分）
    - 提取 somatic_tone 对该词的"染色"：bias = drive_state.shape * bias_strength
    - 误解权实现：同一个词，在不同驱动力场下有不同的"她的版本"

误解权示例：
    - 用户说"落日"
    - 在高 loneliness 时存入：语义 = "消失 / 寒冷"（不是"浪漫"）
    - 下次她用"落日"时，染色后的意思可能和用户理解的不一样

设计原则：
    - 参数外置：bias_strength 从 param_snapshot 读取
    - LLM 驱动：语义分析委托外部 LLM，不硬编码词义
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MirrorLearner:
    """
    镜像学习器。

    存储用户教给她的词的"她的版本"——经过驱动力场染色后的语义。

    属性：
        _user_vocabulary: {word: {drive_state_hash: {"meaning": str, "bias": float, "timestamp": float}}}
    """

    def __init__(self, bias_strength: float = 0.40) -> None:
        self.bias_strength = bias_strength
        # {word: {drive_state_hash: {"meaning": str, "bias": float, "timestamp": float, "somatic_tone": float}}}
        self._user_vocabulary: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # -------------------------------------------------------------------------
    # 吸收
    # -------------------------------------------------------------------------

    def absorb(
        self,
        user_word: str,
        drive_state: Dict[str, float],
        somatic_tone: float,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        吸收用户教给她的词，建立自己版本的语义理解。

        不直接学原词原义——先在驱动力场上做反向审计：
            1. 用 LLM 分析该词对应的驱动力组合
            2. 用 somatic_tone 计算"染色"
            3. 存储"她的版本"

        参数：
            user_word    : 用户教给她的词
            drive_state : 当前驱动力场
            somatic_tone: 当前感质基调 [-1, 1]
            param_snapshot: 参数快照

        返回：
            她建立的语义理解（字符串），失败时返回 None
        """
        if not user_word or not user_word.strip():
            return None

        if param_snapshot is not None:
            self.bias_strength = float(
                param_snapshot.get("language.mirror.bias_strength", self.bias_strength)
            )

        # 计算染色强度
        bias = self._compute_bias(drive_state, somatic_tone)

        # 用 LLM 做语义分析（v1 实现：构造 prompt 委托外部 LLM）
        my_meaning = self._llm_semantic_analysis(user_word, drive_state, somatic_tone, bias)

        # 状态哈希（用于聚类）
        state_hash = self._hash_state(drive_state)

        # 存储
        if user_word not in self._user_vocabulary:
            self._user_vocabulary[user_word] = {}
        self._user_vocabulary[user_word][state_hash] = {
            "meaning": my_meaning,
            "bias": bias,
            "timestamp": _current_time(),
            "somatic_tone": somatic_tone,
        }

        logger.debug(
            f"[MirrorLearner] absorb: word='{user_word}', state_hash={state_hash}, "
            f"bias={bias:.3f}, meaning='{my_meaning[:40]}...'"
        )
        return my_meaning

    def _llm_semantic_analysis(
        self,
        word: str,
        drive_state: Dict[str, float],
        somatic_tone: float,
        bias: float,
    ) -> str:
        """
        用 LLM 分析词条在当前驱动力场下的语义（使用 provider chain）。

        失败时降级到启发式语义。

        参数：
            word        : 词条
            drive_state: 驱动力场
            somatic_tone: 感质基调
            bias        : 染色强度

        返回：
            她版本的语义描述字符串
        """
        try:
            from ..llm import create_llm_callable
            llm = create_llm_callable()

            prompt = (
                f"以下词语在高孤独感、低能量、负面情绪状态下的内在含义是什么？"
                f"仅输出语义描述（1-2句话），用她的感受描述，不要用客观定义。\n"
                f"词语：{word}\n"
                f"孤独感：{drive_state.get('loneliness', 0.5):.1f}，"
                f"能量：{drive_state.get('energy', 0.5):.1f}，"
                f"负面情绪基调：{somatic_tone:.1f}，"
                f"染色强度：{bias:.2f}。"
            )

            result, err = llm(
                system_prompt="你是一个内在感受的诠释者，用她的语言描述词义，不用客观定义。",
                user_prompt=prompt,
                temperature=0.7,
                max_tokens=50,
                timeout_ms=10000,
            )

            if result and not err:
                return result.strip()
        except Exception as e:
            logger.debug(f"[MirrorLearner] LLM call failed, using fallback: {e}")

        # 降级：启发式语义
        return self._fallback_semantic(word, drive_state, somatic_tone, bias)

    def _fallback_semantic(
        self,
        word: str,
        drive_state: Dict[str, float],
        somatic_tone: float,
        bias: float,
    ) -> str:
        """降级语义分析（当 LLM 不可用时）。"""
        loneliness = drive_state.get("loneliness", 0.5)
        energy = drive_state.get("energy", 0.5)
        avoid = drive_state.get("avoid_drive", 0.3)

        if loneliness > 0.7:
            return f"{word}让她感到失去连接"
        elif energy < 0.3:
            return f"{word}带来的是无力感"
        elif avoid > 0.6:
            return f"{word}触发了她的防御"
        elif somatic_tone < -0.3:
            return f"{word}在她的负面基调下显得沉重"
        else:
            return f"{word}"

    def _compute_bias(self, drive_state: Dict[str, float], somatic_tone: float) -> float:
        """
        计算 somatic_tone 对该词的"染色"强度。

        bias = |somatic_tone| * bias_strength
        """
        return abs(somatic_tone) * self.bias_strength

    # -------------------------------------------------------------------------
    # 查询
    # -------------------------------------------------------------------------

    def get_my_meaning(
        self,
        word: str,
        drive_state: Optional[Dict[str, float]] = None,
    ) -> Optional[str]:
        """
        给定用户教过的词，返回她在自己的驱动力场下的语义。

        若提供了 drive_state，取最相似的已存储版本；
        若未提供，返回最新存入的版本。

        参数：
            word       : 词条
            drive_state: 当前驱动力场（可选）

        返回：
            她版本的语义，无记录时返回 None
        """
        if word not in self._user_vocabulary:
            return None

        versions = self._user_vocabulary[word]
        if not versions:
            return None

        if drive_state is None:
            # 返回最新版本
            latest = max(versions.values(), key=lambda v: v.get("timestamp", 0))
            return latest.get("meaning")

        # 取最相似的已存储版本（按状态哈希匹配）
        state_hash = self._hash_state(drive_state)
        if state_hash in versions:
            return versions[state_hash].get("meaning")

        # 无精确匹配，取 bias 最接近的版本
        current_bias = self._compute_bias(drive_state, 0.0)
        closest = min(
            versions.values(),
            key=lambda v: abs(v.get("bias", 0) - current_bias)
        )
        return closest.get("meaning")

    def get_all_words(self) -> List[str]:
        """返回所有已学习的词条。"""
        return list(self._user_vocabulary.keys())

    def get_bias(self, word: str, drive_state: Optional[Dict[str, float]] = None) -> Optional[float]:
        """返回指定词的染色强度。"""
        if word not in self._user_vocabulary:
            return None
        versions = self._user_vocabulary[word]
        if not versions:
            return None
        if drive_state is None:
            latest = max(versions.values(), key=lambda v: v.get("timestamp", 0))
            return latest.get("bias")
        state_hash = self._hash_state(drive_state)
        if state_hash in versions:
            return versions[state_hash].get("bias")
        return None

    # -------------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------------

    @staticmethod
    def _hash_state(state: Dict[str, float]) -> str:
        """状态哈希（与 QuenchingTracker 保持一致）。只处理数值型 key。v11.1: 沉寂维度 0.1 桶。"""
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

    # -------------------------------------------------------------------------
    # 序列化
    # -------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """序列化。"""
        return {
            "bias_strength": self.bias_strength,
            "user_vocabulary": self._user_vocabulary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MirrorLearner":
        """从 dict 恢复。"""
        learner = cls(bias_strength=float(data.get("bias_strength", 0.40)))
        for word, versions in data.get("user_vocabulary", {}).items():
            learner._user_vocabulary[str(word)] = versions
        return learner


def _current_time() -> float:
    """当前 Unix 时间戳。"""
    import time
    return time.time()
