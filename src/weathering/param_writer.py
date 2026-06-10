"""
Parameter Writer — 将风化漂移结果写回参数持久化文件

直接读写 param_store.json，不走 governance（风化是自主内部过程）。
所有变更已通过 observability 的 DriftEvent 记录。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _get_nested(d: dict, key_path: str, default: Any = None) -> Any:
    """按点分路径读取嵌套 dict 值。"""
    parts = key_path.split(".")
    for p in parts:
        if not isinstance(d, dict) or p not in d:
            return default
        d = d[p]
    return d


def _set_nested(d: dict, key_path: str, value: Any) -> None:
    """按点分路径设置嵌套 dict 值，自动创建中间层。"""
    parts = key_path.split(".")
    for p in parts[:-1]:
        if p not in d or not isinstance(d[p], dict):
            d[p] = {}
        d = d[p]
    d[parts[-1]] = value


def read_current_param(key_path: str, default: float = 0.0) -> float:
    """从参数文件读取单个参数的当前值。"""
    try:
        from ..parameter_system.access import load_params_from_file
        params = load_params_from_file()
        val = _get_nested(params, key_path, default)
        return float(val) if not isinstance(val, dict) else default
    except Exception:
        return default


def read_current_params(paths: list, defaults: Dict[str, float] = None) -> Dict[str, float]:
    """
    批量读取参数当前值。

    参数：
        paths: 参数路径列表
        defaults: {path: default_value}，缺失时的默认值

    返回：
        {path: value}
    """
    if defaults is None:
        defaults = {}
    try:
        from ..parameter_system.access import load_params_from_file
        params = load_params_from_file()
        result = {}
        for path in paths:
            val = _get_nested(params, path, defaults.get(path, 0.0))
            result[path] = float(val) if not isinstance(val, dict) else defaults.get(path, 0.0)
        return result
    except Exception:
        return {p: defaults.get(p, 0.0) for p in paths}


def write_drifted_params(drifted: Dict[str, float]) -> bool:
    """
    将漂移后的参数值写入参数持久化文件。

    参数：
        drifted: {param_path: new_value}

    返回：
        bool — 写入成功
    """
    if not drifted:
        return True

    try:
        from ..parameter_system.access import load_params_from_file, save_params_to_file

        params = load_params_from_file()
        for path, value in drifted.items():
            _set_nested(params, path, round(value, 8))

        return save_params_to_file(params)

    except Exception as e:
        logger.warning(f"[weathering] Failed to write drifted params: {e}")
        return False
