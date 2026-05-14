"""EMA baseline 管理 — 追踪参数的长期均衡值。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Optional

from .registry import get_driftable, tier_alpha

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_BASELINE_PATH = _DATA_DIR / "weathering_baselines.json"


class BaselineStore:
    """
    参数 EMA baseline 存储。

    每个参数维护一个 baseline 值（指数移动平均）。
    baseline 代表"系统认为这个参数的常态值是什么"。
    弹簧力 = (current - baseline)^2 × spring_constant，
    拉参数向 baseline 靠拢。
    """

    def __init__(self):
        self._baselines: Dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        """从磁盘加载 baseline 数据。"""
        if _BASELINE_PATH.exists():
            try:
                data = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
                self._baselines = {k: float(v) for k, v in data.items()}
            except Exception as e:
                logger.warning(f"[weathering] Failed to load baselines: {e}")
                self._baselines = {}

    def save(self) -> None:
        """持久化 baseline 到磁盘。"""
        try:
            _BASELINE_PATH.write_text(
                json.dumps(self._baselines, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[weathering] Failed to save baselines: {e}")

    def get_baseline(self, param_path: str) -> float:
        """
        获取参数的 baseline。

        如果没有历史 baseline，用注册表的 baseline_default 初始化。
        """
        if param_path in self._baselines:
            return self._baselines[param_path]

        meta = get_driftable(param_path)
        if meta:
            self._baselines[param_path] = meta.baseline_default
            return meta.baseline_default

        return 0.0

    def update_baseline(self, param_path: str, current_value: float) -> float:
        """
        用当前参数值更新 EMA baseline。

        公式：baseline = baseline × (1 - alpha) + current × alpha
        alpha 由参数的 drift_tier 决定（深层 alpha 更小 = baseline 更稳）。

        返回：更新后的 baseline 值。
        """
        meta = get_driftable(param_path)
        if not meta:
            return current_value

        old_baseline = self.get_baseline(param_path)
        alpha = tier_alpha(meta.tier)
        new_baseline = old_baseline * (1.0 - alpha) + current_value * alpha
        self._baselines[param_path] = new_baseline
        return new_baseline

    def compute_spring_force(self, param_path: str, current_value: float) -> float:
        """
        计算弹簧力（阻止参数偏离 baseline 太远）。

        返回值：
          > 0 → 应向 baseline 拉回（current > baseline）
          < 0 → 应向 baseline 拉回（current < baseline）
          绝对值越大 → 拉力越强

        公式：spring = -(current - baseline)^2 × sign(current - baseline) × k
        k = 0.1（可调）
        """
        baseline = self.get_baseline(param_path)
        delta = current_value - baseline
        if abs(delta) < 1e-9:
            return 0.0
        sign = 1.0 if delta > 0 else -1.0
        spring_k = 0.1
        return -(delta ** 2) * sign * spring_k

    def get_all(self) -> Dict[str, float]:
        """返回所有 baseline 的副本。"""
        return dict(self._baselines)


_store: Optional[BaselineStore] = None


def get_store() -> BaselineStore:
    """获取 BaselineStore 单例。"""
    global _store
    if _store is None:
        _store = BaselineStore()
    return _store
