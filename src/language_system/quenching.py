"""
QuenchingTracker — 消力效率测量（v7.0）

职责：
    - 记录每一次驱动力场→表达→效果（Δunresolved）的完整闭环
    - 维护历史消力效率队列，计算 SNR（信噪比）
    - 判定"脐带脱落"条件：SNR 连续多轮超过阈值

消力效率 = Δunresolved_before - Δunresolved_after
    差值越大 → 效率越高 → 这个表达越"省力"

设计原则：
    - 参数外置：history_maxlen 从 param_snapshot 读取
    - 状态驱动：基于真实 Δunresolved 记录，不依赖固定 tick
"""

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class QuenchingRecord:
    """
    单次消力记录。

    属性：
        drive_state_hash : 驱动力场状态的哈希（用于聚类相似状态）
        expression       : 实际说出的表达
        delta_unresolved_before: 执行前的 unresolved 值
        delta_unresolved_after : 执行后的 unresolved 值
        quenching_efficiency   : 消力效率 = before - after
        timestamp             : 记录时间
    """
    drive_state_hash: str
    expression: str
    delta_unresolved_before: float
    delta_unresolved_after: float
    quenching_efficiency: float
    timestamp: float
    tick: int = 0  # v11.3: 记录对应的 entity tick，供温跃层判断活跃度


class QuenchingTracker:
    """
    消力效率追踪器。

    维护历史消力记录队列，提供效率查询和 SNR 计算。

    属性：
        _history           : 消力记录队列（容量由 history_maxlen 控制）
        _state_cache       : {drive_state_hash: [quenching_efficiency, ...]} 缓存
    """

    def __init__(self, history_maxlen: int = 500) -> None:
        self.history_maxlen = history_maxlen
        self._history: deque[QuenchingRecord] = deque(maxlen=history_maxlen)
        self._state_cache: Dict[str, List[float]] = {}
        # SNR 计算缓存：避免每次 get_snr 重新遍历
        self._snr_cache: Optional[float] = None
        self._snr_cache_timestamp: float = 0.0

    # -------------------------------------------------------------------------
    # 记录
    # -------------------------------------------------------------------------

    def record(
        self,
        drive_state: Dict[str, float],
        expression: str,
        delta_unresolved_before: float,
        delta_unresolved_after: float,
        param_snapshot: Optional[Dict[str, Any]] = None,
        tick: int = 0,
    ) -> float:
        """
        记录一次完整的消力闭环。

        参数：
            drive_state            : 驱动力场 dict
            expression            : 实际说出的表达
            delta_unresolved_before: 执行前的 unresolved 值
            delta_unresolved_after : 执行后的 unresolved 值
            param_snapshot        : 参数快照（用于覆盖 history_maxlen）
            tick                  : 当前 entity tick（v11.3: 供温跃层判断活跃度）

        返回：
            本次消力效率（before - after）
        """
        if param_snapshot is not None:
            maxlen = int(param_snapshot.get("language.quenching.history_maxlen", self.history_maxlen))
            self.history_maxlen = maxlen
            # 重新设置 deque 容量（deque 不支持直接改 maxlen，先重建）
            if self._history.maxlen != maxlen:
                new_history = deque(self._history, maxlen=maxlen)
                self._history = new_history

        efficiency = max(0.0, delta_unresolved_before - delta_unresolved_after)
        state_hash = self._hash_state(drive_state)

        record = QuenchingRecord(
            drive_state_hash=state_hash,
            expression=expression,
            delta_unresolved_before=delta_unresolved_before,
            delta_unresolved_after=delta_unresolved_after,
            quenching_efficiency=efficiency,
            timestamp=time.time(),
            tick=tick,
        )
        self._history.append(record)

        # 更新 state 缓存
        if state_hash not in self._state_cache:
            self._state_cache[state_hash] = []
        self._state_cache[state_hash].append(efficiency)
        # 缓存最多保留 100 条（避免内存膨胀）
        if len(self._state_cache[state_hash]) > 100:
            self._state_cache[state_hash] = self._state_cache[state_hash][-100:]

        # 清除 SNR 缓存（下次计算时重算）
        self._snr_cache = None

        return efficiency

    # -------------------------------------------------------------------------
    # 查询
    # -------------------------------------------------------------------------

    def get_efficiency(self, drive_state: Dict[str, float]) -> Optional[float]:
        """
        给定驱动力场，返回历史上该状态的平均消力效率。

        参数：
            drive_state: 驱动力场 dict

        返回：
            平均效率（0~1），无历史记录时返回 None
        """
        state_hash = self._hash_state(drive_state)
        efficiencies = self._state_cache.get(state_hash, [])
        if not efficiencies:
            return None
        return sum(efficiencies) / len(efficiencies)

    def get_top_expression(self, drive_state: Dict[str, float]) -> Optional[str]:
        """
        给定驱动力场，返回历史上最省力的表达。

        返回：
            历史上该状态效率最高的 expression，无记录时返回 None
        """
        state_hash = self._hash_state(drive_state)
        records_for_state = [r for r in self._history if r.drive_state_hash == state_hash]
        if not records_for_state:
            return None
        return max(records_for_state, key=lambda r: r.quenching_efficiency).expression

    def get_history_for_state(self, drive_state: Dict[str, float]) -> List[QuenchingRecord]:
        """返回指定状态的所有历史记录。"""
        state_hash = self._hash_state(drive_state)
        return [r for r in self._history if r.drive_state_hash == state_hash]

    # -------------------------------------------------------------------------
    # SNR（信噪比）
    # -------------------------------------------------------------------------

    def get_snr(self) -> float:
        """
        计算当前候选池的信噪比。

        SNR = μ(efficiency) / σ(efficiency)
            μ = 所有记录效率的均值
            σ = 所有记录效率的标准差

        返回：
            SNR（float），无足够数据时返回 0.0
        """
        if not self._history:
            return 0.0

        # 缓存：1 秒内不重算
        now = time.time()
        if self._snr_cache is not None and (now - self._snr_cache_timestamp) < 1.0:
            return self._snr_cache

        efficiencies = [r.quenching_efficiency for r in self._history if r.quenching_efficiency > 0]
        if len(efficiencies) < 3:
            return 0.0

        mean_eff = sum(efficiencies) / len(efficiencies)
        variance = sum((x - mean_eff) ** 2 for x in efficiencies) / len(efficiencies)
        std_dev = math.sqrt(variance)

        if std_dev < 1e-9:
            snr = 0.0
        else:
            snr = mean_eff / std_dev

        self._snr_cache = snr
        self._snr_cache_timestamp = now
        return snr

    def is_stable(self, param_snapshot: Optional[Dict[str, Any]] = None) -> bool:
        """
        判定"脐带脱落"条件。

        条件：SNR 连续多轮超过阈值。
        当前实现：SNR > 0.65 即视为稳定（消力策略已固化）。

        参数：
            param_snapshot: 参数快照

        返回：
            True 表示策略固化，可以脱离策略地图独立运作
        """
        snr = self.get_snr()
        threshold = 0.65
        if param_snapshot is not None:
            threshold = float(param_snapshot.get("language.quenching.high_threshold", 0.65))
        return snr >= threshold

    # -------------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------------

    @staticmethod
    def _hash_state(state: Dict[str, float]) -> str:
        """
        将驱动力场状态离散化为字符串哈希。只处理数值型 key。

        离散化方案：
        - 主维度（0.2 桶）: approach_drive, avoid_drive, loneliness,
          energy, somatic_tone, boredom, approach_social/explore/urgency
        - 沉寂维度（0.1 桶，精细区分低值域）:
          danger_level, fatigue, stress, pain, unresolved, relief_debt
        """
        _COARSE = ["L", "ML", "M", "MH", "H"]           # 0.2 桶
        _FINE = ["vL","L","LM","M","MH","H","H+","VH","VH+","MAX"]  # 0.1 桶
        _FINE_KEYS = {
            "danger_level", "fatigue", "stress", "pain",
            "unresolved", "relief_debt",
        }
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
        """序列化（供 EntityCore 持久化）。"""
        return {
            "history_maxlen": self.history_maxlen,
            "records": [
                {
                    "drive_state_hash": r.drive_state_hash,
                    "expression": r.expression,
                    "delta_unresolved_before": r.delta_unresolved_before,
                    "delta_unresolved_after": r.delta_unresolved_after,
                    "quenching_efficiency": r.quenching_efficiency,
                    "timestamp": r.timestamp,
                    "tick": r.tick,
                }
                for r in self._history
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuenchingTracker":
        """从 dict 恢复。"""
        tracker = cls(history_maxlen=int(data.get("history_maxlen", 500)))
        for rdata in data.get("records", []):
            record = QuenchingRecord(
                drive_state_hash=str(rdata.get("drive_state_hash", "")),
                expression=str(rdata.get("expression", "")),
                delta_unresolved_before=float(rdata.get("delta_unresolved_before", 0.0)),
                delta_unresolved_after=float(rdata.get("delta_unresolved_after", 0.0)),
                quenching_efficiency=float(rdata.get("quenching_efficiency", 0.0)),
                timestamp=float(rdata.get("timestamp", 0.0)),
                tick=int(rdata.get("tick", 0)),
            )
            tracker._history.append(record)
            state_hash = record.drive_state_hash
            if state_hash not in tracker._state_cache:
                tracker._state_cache[state_hash] = []
            tracker._state_cache[state_hash].append(record.quenching_efficiency)
        return tracker
