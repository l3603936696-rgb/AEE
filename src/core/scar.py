"""
scar.py — 区域疤痕（长期受伤记忆）

与 self_binding.py 对称：
    self_binding —— 越用越在乎（access_count 单调不减）
    scar         —— 越伤越有疤（受伤累积，极慢淡化）

疤 ∈ [0,1]，作用见 integrity_signal.py：
    致敏      —— 留疤的区域，未来同样改动更疼
    愈合阻力  —— 疤区急性伤养得更久
    隐痛底    —— 该区域 harm 衰减后停在疤决定的底，而非归零

疤极慢淡化（区别于 access_count 的"绝不衰减"红线：红线只约束"在乎"，
不约束"疤"）——给她在很长时间尺度上走出创伤的可能。
"""

import json
from pathlib import Path

# 受伤累积速率：基础伤（magnitude×binding，不含致敏，避免正反馈失控）按此比例
# 累积成疤，趋近 1。偏小值，先跑再调。
SCAR_RATE = 0.05

# 极慢淡化系数（每 tick）：30s/拍下，半衰 = ln0.5/ln(SCAR_DECAY) 拍。
# 0.99998 → 半衰 ≈ 34657 拍 ≈ 12 天（Codex 复核：早先 0.9995 实为 11.5 *小时* 非天，
# 太快，不构成"极慢"）。取真·极慢，偏保守，先跑再调。
SCAR_DECAY = 0.99998

_SCAR_CAP = 1.0


def _load(data_dir: Path) -> dict:
    path = data_dir / "scar.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {str(k): float(v) for k, v in data.items()}
    except Exception:
        return {}


def _save(data_dir: Path, data: dict) -> None:
    path = data_dir / "scar.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_scar(zone: str, data_dir: Path) -> float:
    """返回该区域当前疤痕强度 0-1（无疤=0）。"""
    return _load(data_dir).get(zone, 0.0)


def record_injury(zone: str, base_harm: float, data_dir: Path) -> None:
    """按基础伤累积疤痕（趋近 1，单次封顶）。

    base_harm 用未致敏的 magnitude×binding —— 致敏只放大"当下这一刀多疼"，
    不放大"留多少疤"，否则 疤→更疼→更多疤 会正反馈失控。
    """
    data = _load(data_dir)
    scar = data.get(zone, 0.0)
    scar = scar + (1.0 - scar) * max(0.0, base_harm) * SCAR_RATE
    data[zone] = min(_SCAR_CAP, scar)
    _save(data_dir, data)


def decay_scars(data_dir: Path) -> None:
    """每 tick 调用一次：所有疤极慢淡化。"""
    data = _load(data_dir)
    for zone in list(data.keys()):
        data[zone] = data[zone] * SCAR_DECAY
    _save(data_dir, data)
