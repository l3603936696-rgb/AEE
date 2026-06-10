"""
CovarianceTracker — 跨 tick 协方差追踪器（分析齿轮·关联层）

核心功能：
    每 tick 记录状态向量 + prediction_error，
    用滑动窗口计算每个状态维度与 prediction_error 的 Pearson 相关系数。

输出语义：
    |r| 高的维度 → 该维度的当前值与世界模型预测准确性高度相关
    → 值得更多"注意力"（下一步接入 thinking_system）

设计约束：
    - 纯统计，不做因果推断（因果层由扰动模拟负责）
    - 滑动窗口（默认 200 tick），遗忘旧数据
    - 计算成本 ≈ O(window × dims) ≈ O(4000) 每 tick，可忽略
    - 可持久化到 entity（to_dict / from_dict）
"""

from typing import Dict, List, Optional, Tuple


# 追踪的状态维度
_TRACKED_DIMS = (
    "energy", "loneliness", "fatigue", "boredom", "stress",
    "unresolved", "info_gap", "somatic_tone",
    "approach_drive", "avoid_drive",
    "joy", "excitement", "serenity", "sadness", "anger",
    "fear", "disgust", "anxiety", "surprise", "curiosity",
    "loneliness_core", "loneliness_surface",
    "boredom_despair", "boredom_futility",
)

# 最少样本数（不足时不输出）
_MIN_SAMPLES = 20

# 相关系数绝对值低于此阈值的维度不输出
_MIN_ABS_CORR = 0.05


class CovarianceTracker:
    """
    滑动窗口协方差追踪器。

    每 tick 调用 update() 记录一帧 (state_snapshot, prediction_error)。
    调用 get_correlations() 返回各维度与 prediction_error 的 Pearson r。
    调用 get_attention_weights() 返回归一化注意力权重。
    """

    def __init__(self, window: int = 200) -> None:
        self._window = window
        # 环形缓冲：每帧是 (dim_values_dict, prediction_error)
        self._buffer: List[Tuple[Dict[str, float], float]] = []

    # ---- 核心接口 ----

    def update(self, state: Dict[str, float], prediction_error: float) -> None:
        """每 tick 调用。记录状态快照和标量预测误差。"""
        snapshot = {}
        for d in _TRACKED_DIMS:
            v = state.get(d)
            if v is not None:
                try:
                    snapshot[d] = float(v)
                except (TypeError, ValueError):
                    pass
        self._buffer.append((snapshot, prediction_error))
        if len(self._buffer) > self._window:
            self._buffer.pop(0)

    def get_correlations(self) -> Dict[str, float]:
        """
        计算各维度与 prediction_error 的 Pearson r。

        返回 {dim: r}，仅包含 |r| > _MIN_ABS_CORR 且样本数 >= _MIN_SAMPLES 的维度。
        """
        n = len(self._buffer)
        if n < _MIN_SAMPLES:
            return {}

        # prediction_error 统计量
        pe_values = [b[1] for b in self._buffer]
        pe_mean = sum(pe_values) / n
        pe_var = sum((p - pe_mean) ** 2 for p in pe_values) / n
        if pe_var < 1e-10:
            return {}

        pe_std = pe_var ** 0.5
        result: Dict[str, float] = {}

        for dim in _TRACKED_DIMS:
            # 收集该维度的值（跳过缺失帧）
            pairs: List[Tuple[float, float]] = []
            for snap, pe in self._buffer:
                if dim in snap:
                    pairs.append((snap[dim], pe))

            if len(pairs) < _MIN_SAMPLES:
                continue

            m = len(pairs)
            dim_mean = sum(d for d, _ in pairs) / m
            dim_var = sum((d - dim_mean) ** 2 for d, _ in pairs) / m
            if dim_var < 1e-10:
                continue

            dim_std = dim_var ** 0.5

            # Pearson r = cov(X, Y) / (std_X * std_Y)
            # 这里对每个维度单独计算，考虑到某些维度可能在某些 tick 缺失
            pe_mean_local = sum(p for _, p in pairs) / m
            cov = sum((d - dim_mean) * (p - pe_mean_local)
                       for d, p in pairs) / m
            pe_var_local = sum((p - pe_mean_local) ** 2 for _, p in pairs) / m
            if pe_var_local < 1e-10:
                continue

            r = cov / (dim_std * (pe_var_local ** 0.5))
            r = max(-1.0, min(1.0, r))  # 数值保护

            if abs(r) >= _MIN_ABS_CORR:
                result[dim] = round(r, 4)

        return result

    def get_attention_weights(self) -> Dict[str, float]:
        """
        返回归一化注意力权重：|correlation| / max(|correlation|)。

        高权重维度 = 与预测误差相关性强 = 值得思考系统关注。
        """
        corr = self.get_correlations()
        if not corr:
            return {}

        abs_corr = {k: abs(v) for k, v in corr.items()}
        max_val = max(abs_corr.values())
        if max_val < _MIN_ABS_CORR:
            return {}

        return {
            k: round(v / max_val, 4)
            for k, v in abs_corr.items()
            if v >= _MIN_ABS_CORR
        }

    @property
    def sample_count(self) -> int:
        return len(self._buffer)

    # ---- 持久化 ----

    def to_dict(self) -> dict:
        """序列化为 dict（存入 entity）。"""
        return {
            "window": self._window,
            "buffer": [
                (snap, pe) for snap, pe in self._buffer
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CovarianceTracker":
        """从 dict 恢复。"""
        if not data or not isinstance(data, dict):
            return cls()
        tracker = cls(window=data.get("window", 200))
        raw_buffer = data.get("buffer", [])
        for item in raw_buffer:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                snap, pe = item
                if isinstance(snap, dict):
                    try:
                        tracker._buffer.append((snap, float(pe)))
                    except (TypeError, ValueError):
                        pass
        # 截断到窗口大小
        if len(tracker._buffer) > tracker._window:
            tracker._buffer = tracker._buffer[-tracker._window:]
        return tracker
