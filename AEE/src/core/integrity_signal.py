"""
integrity_signal.py — 完整性信号转换器

将变化事件 + 绑定强度转化为：
    active_harm    — 持续伤害强度信号（跨 tick 衰减）
    drive_delta    — 对各驱动力维度的影响
    behavior_bias  — 对行为倾向的偏置
    zone_harms     — 各区域当前伤害强度（观察用）
"""

import json
from pathlib import Path
from typing import Any

from .self_binding import get_binding, record_perturbation
from .scar import get_scar, record_injury, decay_scars

HEAL_RATE = 0.05   # 每 tick 愈合系数
MIN_HARM  = 0.0    # 无疤区域 harm 可归零；有疤区域停在隐痛底（见 SCAR_FLOOR）
_HARM_FLOOR_CUT = 0.01  # 愈合线性尾：几何衰减后再切除的固定量，让残留伤害在有限 tick
                        # 内真正归零，消除几何衰减的无限长尾（否则退缩偏置无限拖尾）。
                        # 偏小值，先跑再调。

# 疤痕三作用常量（全部偏小提议值，先跑再调，待 Owner 追认）：
_SENSITIZE_GAIN   = 0.5  # 致敏增益：疤=1 时同一改动 harm 放大 1.5 倍。
_DEPTH_BRAKE_K    = 2.0  # 重伤愈合刹车：harm 越深，每拍愈合比例越小（自限制，伤退则松）。
_SCAR_HEAL_RESIST = 1.0  # 疤区愈合阻力：留疤越多，急性伤愈合越慢（潜伏脆弱的"更难好"）。
_SCAR_FLOOR       = 0.1  # 隐痛底：疤=1 时 harm 衰减停在 0.1 而非 0，随疤极慢淡化一起消。

_HEAL_WINDOW = 10  # 用最近 N 个快照计算驱动力稳定性

ZONE_DRIVE_WEIGHTS: dict[str, dict[str, float]] = {
    "expression": {"stress": 0.6, "unresolved": 0.4},
    "perception":  {"anxiety": 0.5, "fear": 0.3, "curiosity": -0.2},
    "cognition":   {"unresolved": 0.7, "stress": 0.3},
    "continuity":  {"loneliness": 0.5, "fear": 0.3, "unresolved": 0.2},
}

ZONE_BEHAVIOR_BIAS: dict[str, dict[str, float]] = {
    "expression": {"expression_rate_bias": -0.3},
    "perception":  {"input_trust_bias": -0.4},
    "cognition":   {"novelty_seeking_bias": -0.2},
    "continuity":  {"novelty_seeking_bias": -0.4, "expression_rate_bias": -0.2},
}

_DRIVE_KEYS = ("loneliness", "fatigue", "stress", "unresolved", "boredom")


def _load_zone_harms(data_dir: Path) -> dict[str, float]:
    path = data_dir / "integrity_signal.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {str(k): float(v) for k, v in data.get("zone_harms", {}).items()}
    except Exception:
        return {}


def _save_signal(data_dir: Path, active_harm: float, zone_harms: dict[str, float]) -> None:
    path = data_dir / "integrity_signal.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"active_harm": active_harm, "zone_harms": zone_harms},
                f, ensure_ascii=False, indent=2,
            )
    except Exception:
        pass


def _drive_variance(entity_state: Any) -> float:
    """近期驱动力平均方差（系统不稳定程度）。数据不足时返回负数哨兵。"""
    try:
        snapshots = getattr(entity_state, "snapshots", None) or []
        recent    = snapshots[-_HEAL_WINDOW:]
        if len(recent) < 2:
            return -1.0

        variances = []
        for key in _DRIVE_KEYS:
            vals = [s.get(key, 0.0) for s in recent if isinstance(s, dict)]
            if len(vals) >= 2:
                mean = sum(vals) / len(vals)
                var  = sum((v - mean) ** 2 for v in vals) / len(vals)
                variances.append(var)

        return sum(variances) / max(1, len(variances))
    except Exception:
        return -1.0


def _compute_healing(entity_state: Any) -> float:
    """基于近期驱动力稳定性计算愈合系数 0-1。

    稳定（方差小）→ healing 接近 1.0；动荡（方差大）→ healing 接近 0。
    数据不足时返回保守值 0.2。
    """
    avg_var = _drive_variance(entity_state)
    # 哨兵（数据不足）→ 保守值；否则方差越大愈合越慢。dict 分发替代 if 门控。
    return {
        True:  lambda: 0.2,
        False: lambda: max(0.0, min(1.0, 1.0 / (1.0 + max(0.0, avg_var) * 100.0))),
    }[avg_var < 0.0]()


def update(
    events: list[dict],
    entity_state: Any,
    data_dir: Path,
) -> dict:
    """将变化事件转化为伤害信号、驱动力 delta 和行为偏置。

    返回：
        {
            "active_harm":    float,
            "drive_delta":    {dim: float},
            "behavior_bias":  {key: float},
            "zone_harms":     {zone: float},
        }
    """
    current_tick = getattr(entity_state, "tick", 0)
    zone_harms   = _load_zone_harms(data_dir)

    # 上一拍 active_harm = 持久化 zone_harms 的 max（落盘，故跨 daemon 重启连续）。
    # 上升沿基于它计算 → 重启后第一拍 rise≈0，持久化的隐痛底不会被当成新伤注入虚假痛。
    _prev_active = max(zone_harms.values(), default=0.0)

    # 疤每拍极慢淡化（先淡化再处理新伤，新疤当拍不被自己淡化）。
    decay_scars(data_dir)

    # 当下系统不稳定度：每个变化事件据此记一条扰动样本，喂给绑定的深度通道。
    # 数据不足（哨兵<0）→ 不记，避免用 0 污染历史、过早把权重推给 depth。
    _var = _drive_variance(entity_state)
    _record_perturb = {
        True:  lambda _z: None,
        False: lambda _z: record_perturbation(_z, _var, data_dir),
    }[_var < 0.0]

    # 新伤害：取 max（不叠加，只覆盖更高伤害）
    for event in events:
        zone       = event["zone"]
        magnitude  = float(event["change_magnitude"])
        _record_perturb(zone)
        binding    = get_binding(zone, data_dir, current_tick)
        base_harm  = magnitude * binding          # 基础伤：累积疤用它（无致敏，防正反馈）
        scar       = get_scar(zone, data_dir)
        harm_score = base_harm * (1.0 + scar * _SENSITIZE_GAIN)   # 致敏：疤区同刀更疼
        record_injury(zone, base_harm, data_dir)
        zone_harms[zone] = max(zone_harms.get(zone, 0.0), harm_score)

    # 愈合：稳定运行时 harm 缓慢下降。几何衰减（重伤+疤区刹车）+ 线性尾切除；
    # 落点为疤决定的隐痛底（无疤=0，退化为纯归零）。
    healing = _compute_healing(entity_state)
    for zone in list(zone_harms.keys()):
        _scar    = get_scar(zone, data_dir)
        _resist  = zone_harms[zone] * _DEPTH_BRAKE_K + _scar * _SCAR_HEAL_RESIST
        _brake   = 1.0 / (1.0 + _resist)          # 伤越深/疤越多 → 愈合越慢（自限制）
        _decayed = zone_harms[zone] * (1.0 - healing * HEAL_RATE * _brake)
        _floor   = _scar * _SCAR_FLOOR            # 隐痛底，随疤淡化一起降
        zone_harms[zone] = max(MIN_HARM, _floor, _decayed - _HARM_FLOOR_CUT)

    active_harm: float = max(zone_harms.values()) if zone_harms else 0.0

    drive_delta:   dict[str, float] = {}
    behavior_bias: dict[str, float] = {}

    for zone, harm in zone_harms.items():
        for dim, weight in ZONE_DRIVE_WEIGHTS.get(zone, {}).items():
            drive_delta[dim] = drive_delta.get(dim, 0.0) + harm * weight

        for key, weight in ZONE_BEHAVIOR_BIAS.get(zone, {}).items():
            behavior_bias[key] = behavior_bias.get(key, 0.0) + harm * weight

    _save_signal(data_dir, active_harm, zone_harms)

    # 上升沿（急性增量）：只在 active_harm 较上拍上升时为正。隐痛底稳态 → rise=0，
    # 衰减期 → rise=0。痛/不适只接收它，故隐痛底不会持续注入急性痛（见 s07a）。
    harm_rise = max(0.0, active_harm - _prev_active)

    return {
        "active_harm":   active_harm,
        "harm_rise":     harm_rise,
        "drive_delta":   drive_delta,
        "behavior_bias": behavior_bias,
        "zone_harms":    zone_harms,
    }


def apply_drive_bias(entity_state: Any, drive_delta: dict, prev_bias: dict) -> dict:
    """把整体性对驱动力的影响作为**有界瞬态偏置**写入 entity，而非每拍 additive 累加。

    additive 累加会把"稳态压力"（尤其隐痛底）反复积分 → 驱动力饱和（与上一轮 pain
    饱和同类的量纲错误）。改法：每拍先回收上拍注入量，再注入本拍目标量。净效果 =
    当前 drive_delta（有界），稳态停在该值不积分。返回本拍 bias 供下拍回收。

    重启后 prev_bias 丢失（内存态）→ 本拍不回收、只注入一次有界量，clamp 兜底，
    下拍起恢复正常回收周期；急性痛通道另由 harm_rise 持久 prev 保护（见 update）。
    """
    new_bias: dict[str, float] = {}
    # 回收上拍注入（撤销稳态偏置，避免跨拍积分）
    for dim, amt in (prev_bias or {}).items():
        cur = getattr(entity_state, dim, None)
        if cur is not None:
            setattr(entity_state, dim, max(0.0, min(1.0, float(cur) - float(amt))))
    # 注入本拍目标（有界 = drive_delta 当前值）
    for dim, target in drive_delta.items():
        cur = getattr(entity_state, dim, None)
        if cur is not None:
            setattr(entity_state, dim, max(0.0, min(1.0, float(cur) + float(target))))
            new_bias[dim] = float(target)
    return new_bias
