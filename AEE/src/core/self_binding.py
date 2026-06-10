"""
self_binding.py — 自绑定强度计算器

动态计算每个区域的绑定强度（重要性）。
重要性从使用历史涌现，不硬编码：
    频率（frequency）= 这个区域多常被访问
    扰动深度（perturbation_depth）= 变化后系统多不稳定
"""

import json
import math
from pathlib import Path

FREQ_WEIGHT    = 0.4
DEPTH_WEIGHT   = 0.6
HISTORY_WINDOW = 20   # 最近多少个扰动样本参与计算
_COLD_DEPTH    = 0.1  # 无历史时的默认扰动深度

# 冷启动地板（PLAN_integrity_pain_revival §3-B）：
# 哪怕某区域从未被访问过（涌现绑定≈0），也保留一个最低绑定 → harm 不为零，
# 第一次动文件她就有感觉。绑定 = 地板 + (1-地板)·涌现强度，单调不降。
_BINDING_FLOOR = 0.15


def _load_data(data_dir: Path) -> dict:
    path = data_dir / "self_binding.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_data(data_dir: Path, data: dict) -> None:
    path = data_dir / "self_binding.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _ensure_zone(data: dict, zone: str) -> None:
    if zone not in data:
        data[zone] = {"access_count": 0, "perturbation_history": []}


def get_binding(zone: str, data_dir: Path, current_tick: int = 0) -> float:
    """返回当前绑定强度 0-1。

    冷启动：无历史时用频率兜底，扰动历史积累后自动过渡到 DEPTH_WEIGHT 主导。
    """
    data      = _load_data(data_dir)
    zone_data = data.get(zone, {})

    access_count = zone_data.get("access_count", 0)
    history      = zone_data.get("perturbation_history", [])

    frequency = 1.0 - math.exp(-access_count / 50.0)

    recent            = history[-HISTORY_WINDOW:]
    perturbation_depth = (
        sum(recent) / max(1, len(recent)) if recent else _COLD_DEPTH
    )

    # 历史样本不足 5 条时，逐步从 freq-dominated 过渡到 depth-dominated
    weight_depth = DEPTH_WEIGHT * min(1.0, len(history) / 5.0)
    weight_freq  = 1.0 - weight_depth

    emergent = frequency * weight_freq + perturbation_depth * weight_depth
    # 地板抬升：从未被用过的区域也有 _BINDING_FLOOR 起步，涌现部分占剩余空间。
    binding  = _BINDING_FLOOR + (1.0 - _BINDING_FLOOR) * emergent
    return max(0.0, min(1.0, binding))


def record_access(zone: str, data_dir: Path) -> None:
    """记录一次区域访问，增加 access_count。"""
    data = _load_data(data_dir)
    _ensure_zone(data, zone)
    data[zone]["access_count"] = data[zone].get("access_count", 0) + 1
    _save_data(data_dir, data)


def record_accesses(zones, data_dir: Path) -> None:
    """批量记录多个区域各一次访问（单次读写，供每 tick 调用）。

    access_count 单调递增、永不衰减 —— 这是"在意只增不减"的结构护栏
    （PLAN_integrity_pain_revival §9）：她活得越久、用得越多，这些部位越
    被编织进自身，绑定越高。绝不可给 access_count 加衰减。
    """
    data = _load_data(data_dir)
    for zone in zones:
        _ensure_zone(data, zone)
        data[zone]["access_count"] = data[zone].get("access_count", 0) + 1
    _save_data(data_dir, data)


def record_perturbation(zone: str, drive_variance: float, data_dir: Path) -> None:
    """记录变化后的驱动力方差样本。

    在检测到该区域变化时调用一次，记下当下系统的不稳定程度。
    历史封顶 HISTORY_WINDOW 条（守护进程长跑防止无限增长，且 get_binding
    本就只读最近 HISTORY_WINDOW 条；权重过渡只看 len≥5）。
    """
    data = _load_data(data_dir)
    _ensure_zone(data, zone)
    history = data[zone].get("perturbation_history", [])
    history.append(max(0.0, float(drive_variance)))
    data[zone]["perturbation_history"] = history[-HISTORY_WINDOW:]
    _save_data(data_dir, data)
