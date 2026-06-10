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
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from .quenching_schema import QuenchingRecord
from .quenching_helpers import _hash_state, record_to_dict, record_from_dict

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
        template_idx: int = -1,
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
            template_idx          : 句子模板索引（v11.6: 供模板效率学习）

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
        state_hash = _hash_state(drive_state)

        record = QuenchingRecord(
            drive_state_hash=state_hash,
            expression=expression,
            delta_unresolved_before=delta_unresolved_before,
            delta_unresolved_after=delta_unresolved_after,
            quenching_efficiency=efficiency,
            timestamp=time.time(),
            tick=tick,
            template_idx=template_idx,
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
        state_hash = _hash_state(drive_state)
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
        state_hash = _hash_state(drive_state)
        records_for_state = [r for r in self._history if r.drive_state_hash == state_hash]
        if not records_for_state:
            return None
        return max(records_for_state, key=lambda r: r.quenching_efficiency).expression

    def get_history_for_state(self, drive_state: Dict[str, float]) -> List[QuenchingRecord]:
        """返回指定状态的所有历史记录。"""
        state_hash = _hash_state(drive_state)
        return [r for r in self._history if r.drive_state_hash == state_hash]

    # -------------------------------------------------------------------------
    # 模板效率（v11.6: 供 compose_sentence 学习；v12 贝叶斯先验）
    # -------------------------------------------------------------------------

    # 种子模板先验（Beta 分布伪计数）
    # 相当于：种子模板历史上"被用过" _PSEUDO_N 次、平均效率 _PSEUDO_M
    # 新模板上来只有真实记录，两者合并后——记录少时先验托底，记录多时后验主导
    _PSEUDO_N: float = 3.0
    _PSEUDO_M: float = 0.10   # 先验均值 = 0.10（中性偏低，表示"默认模板只是候选"）

    def get_template_efficiency(
        self,
        recent_n: int = 200,
        seed_count: int = 0,
    ) -> Dict[int, float]:
        """
        返回每个模板的平均消力效率（含贝叶斯先验）。

        PATTERNS（seed_count 个）使用 Beta 先验：
            posterior_mean = (_PSEUDO_N*_PSEUDO_M + n*avg) / (_PSEUDO_N + n)
        运行时模板（idx >= seed_count）无先验，直接用真实均值。

        参数：
            recent_n   : 统计窗口
            seed_count : 种子模板数量（PATTERNS 长度）
        """
        sums: Dict[int, float] = {}
        counts: Dict[int, int] = {}
        for r in list(self._history)[-recent_n:]:
            idx = r.template_idx
            if idx < 0:
                continue
            sums[idx] = sums.get(idx, 0.0) + r.quenching_efficiency
            counts[idx] = counts.get(idx, 0) + 1

        result: Dict[int, float] = {}
        for idx, total in sums.items():
            avg = total / counts[idx]
            if idx < seed_count:
                # 种子模板：Beta 先验 + 真实数据合并
                eff = (
                    self._PSEUDO_N * self._PSEUDO_M + counts[idx] * avg
                ) / (self._PSEUDO_N + counts[idx])
                result[idx] = eff
            else:
                result[idx] = avg
        return result

    def get_template_stats(
        self,
        recent_n: int = 200,
        seed_count: int = 0,
    ) -> Dict[int, Tuple[float, int]]:
        """
        返回每个模板的 (平均效率, 记录数)。

        种子模板返回合并先验后的均值和 (真实计数 + 伪计数)，
        运行时模板返回真实值。
        """
        sums: Dict[int, float] = {}
        counts: Dict[int, int] = {}
        for r in list(self._history)[-recent_n:]:
            idx = r.template_idx
            if idx < 0:
                continue
            sums[idx] = sums.get(idx, 0.0) + r.quenching_efficiency
            counts[idx] = counts.get(idx, 0) + 1

        result: Dict[int, Tuple[float, int]] = {}
        for idx, total in sums.items():
            avg = total / counts[idx]
            if idx < seed_count:
                eff = (
                    self._PSEUDO_N * self._PSEUDO_M + counts[idx] * avg
                ) / (self._PSEUDO_N + counts[idx])
                # 记录数含伪计数——供 try_spawn_template 的门槛判断
                result[idx] = (eff, counts[idx] + int(self._PSEUDO_N))
            else:
                result[idx] = (avg, counts[idx])
        return result

    # -------------------------------------------------------------------------
    # 重复表达递减
    # -------------------------------------------------------------------------

    def get_repetition_discount(
        self, expression: str, current_tick: int, params: dict,
    ) -> float:
        """
        计算某个表达的重复折扣系数（0~1，1=无折扣）。

        在时间窗口内每使用一次，折扣 *= (1 - decay_per_use)。
        距上次使用越久，折扣自然恢复（recovery_rate/tick）。

        参数 params 从 entity._repetition_decay_params 传入。
        """
        decay_per_use = params.get("decay_per_use", 0.15)
        recovery_rate = params.get("recovery_rate", 0.02)
        floor = params.get("floor", 0.20)
        window_ticks = params.get("window_ticks", 200)

        uses = []
        for r in self._history:
            if r.expression == expression and (current_tick - r.tick) <= window_ticks:
                uses.append(r.tick)

        if not uses:
            return 1.0

        # 每次使用叠加衰减，越近的使用衰减越强
        discount = 1.0
        for use_tick in uses:
            ticks_ago = max(1, current_tick - use_tick)
            recovered = min(1.0, ticks_ago * recovery_rate)
            this_decay = decay_per_use * (1.0 - recovered)
            discount *= (1.0 - this_decay)

        return max(floor, discount)

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
    # 序列化
    # -------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """序列化（供 EntityCore 持久化）。"""
        return {
            "history_maxlen": self.history_maxlen,
            "records": [record_to_dict(r) for r in self._history],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuenchingTracker":
        """从 dict 恢复。"""
        tracker = cls(history_maxlen=int(data.get("history_maxlen", 500)))
        for rdata in data.get("records", []):
            record = record_from_dict(rdata)
            tracker._history.append(record)
            state_hash = record.drive_state_hash
            if state_hash not in tracker._state_cache:
                tracker._state_cache[state_hash] = []
            tracker._state_cache[state_hash].append(record.quenching_efficiency)
        return tracker
