"""
Staging — 待生效缓冲与异步写入

核心约束：
    - 同步管线执行期间，所有参数修改写入待生效缓冲区（不落地）
    - 异步写入循环负责真正落盘（覆盖 JSON）
    - 绝对禁止在同步管线返回前应用任何修改
    - 落盘后自动清空缓冲区
"""

from __future__ import annotations

import copy
import time
import threading
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ============================================================================
# 枚举与常量
# ============================================================================

class APPLY_MODE(Enum):
    """写入模式"""
    STAGED_ONLY = "staged_only"      # 仅更新缓冲区，不落盘（同步管线内）
    PERSIST_NOW = "persist_now"      # 立即落盘（仅异步写入循环可调用）
    STAGED_AND_PERSIST = "staged_and_persist"  # 缓冲 + 落盘（仅异步写入循环）


# ============================================================================
# 变更记录
# ============================================================================

@dataclass
class ChangeRecord:
    """单条变更记录"""
    key_path: str
    value: Any
    reason: str
    staged_at: float
    applied_at: Optional[float] = None
    applied: bool = False

    def mark_applied(self) -> None:
        self.applied_at = time.time()
        self.applied = True


# ============================================================================
# 待生效缓冲区
# ============================================================================

class StagedChanges:
    """
    待生效参数修改缓冲区。

    约束：
        - 所有修改先入缓冲区，不直接影响 PARAM_DEFAULTS
        - apply_staged() 由异步写入循环调用，负责真正落盘
        - 落盘后清空缓冲区
    """

    def __init__(self, persist_path: str) -> None:
        self._lock = threading.RLock()
        self._changes: Dict[str, ChangeRecord] = {}   # key_path → ChangeRecord
        self._persist_path = persist_path
        self._pending_apply: List[Dict[str, Any]] = []   # 待落盘队列

    # ---- 公开 API ----

    def stage(
        self,
        key_path: str,
        value: Any,
        reason: str,
    ) -> ChangeRecord:
        """
        将修改写入缓冲区（不落盘）。
        """
        with self._lock:
            record = ChangeRecord(
                key_path=key_path,
                value=copy.deepcopy(value),
                reason=reason,
                staged_at=time.time(),
            )
            self._changes[key_path] = record
            return record

    def get_staged(self, key_path: str) -> Optional[Any]:
        """查询缓冲区中某个 key 的值"""
        with self._lock:
            rec = self._changes.get(key_path)
            return copy.deepcopy(rec.value) if rec else None

    def list_pending(self) -> List[ChangeRecord]:
        """列出所有待生效修改"""
        with self._lock:
            return list(self._changes.values())

    def count(self) -> int:
        """缓冲区中待生效修改数量"""
        with self._lock:
            return len(self._changes)

    def apply_staged(
        self,
        source_params: Dict[str, Any],
        mode: APPLY_MODE = APPLY_MODE.STAGED_ONLY,
    ) -> Dict[str, Any]:
        """
        应用缓冲区中的所有修改。

        参数：
            source_params : 当前持久化的参数表（从 JSON 加载）
            mode          : 写入模式

        返回：
            应用后的完整参数表

        约束：
            - STAGED_ONLY：仅更新 source_params（供测试/验证用）
            - PERSIST_NOW：落盘 + 返回更新后参数
            - STAGED_AND_PERSIST：等同于 PERSIST_NOW
        """
        with self._lock:
            if not self._changes:
                return source_params

            result = copy.deepcopy(source_params)

            for key_path, record in self._changes.items():
                _set_nested(result, key_path, record.value)
                record.mark_applied()

            if mode in (APPLY_MODE.PERSIST_NOW, APPLY_MODE.STAGED_AND_PERSIST):
                self._persist(result)

            # 清空缓冲区
            self._changes.clear()
            return result

    def clear(self) -> None:
        """清空缓冲区（通常在落盘后调用）"""
        with self._lock:
            self._changes.clear()

    def get_pending(self) -> List[Dict[str, Any]]:
        """返回所有待落盘的变更（不含已应用的）"""
        with self._lock:
            return [
                {
                    "key_path": rec.key_path,
                    "value": rec.value,
                    "reason": rec.reason,
                    "staged_at": rec.staged_at,
                }
                for rec in self._changes.values()
            ]

    def get_applied(self) -> List[Dict[str, Any]]:
        """返回已落盘的变更历史"""
        with self._lock:
            return [
                {
                    "key_path": rec.key_path,
                    "value": rec.value,
                    "reason": rec.reason,
                    "staged_at": rec.staged_at,
                    "applied_at": rec.applied_at,
                }
                for rec in list(self._pending_apply)
                if rec.get("applied")
            ]

    # ---- 内部方法 ----

    def _persist(self, params: Dict[str, Any]) -> None:
        """持久化到 JSON 文件"""
        try:
            # 确保目录存在
            dir_path = os.path.dirname(self._persist_path)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)

            # 更新 _system 元数据
            if "_system" not in params:
                params["_system"] = {}
            params["_system"]["last_modified_at"] = time.time()
            params["_system"]["last_modified_by"] = "async_write_loop"

            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(params, f, ensure_ascii=False, indent=2)

            # 记录已落盘的变更
            for rec in list(self._changes.values()):
                self._pending_apply.append({
                    "key_path": rec.key_path,
                    "value": rec.value,
                    "reason": rec.reason,
                    "staged_at": rec.staged_at,
                    "applied_at": rec.applied_at,
                    "applied": True,
                })
            # 保留最近 200 条历史
            while len(self._pending_apply) > 200:
                self._pending_apply.pop(0)

        except Exception as e:
            # 落盘失败不抛异常，打印警告
            print(f"[WARNING] 参数落盘失败: {self._persist_path}, error={e}")


# ============================================================================
# 嵌套字典辅助
# ============================================================================

def _set_nested(params: Dict[str, Any], key_path: str, value: Any) -> None:
    """
    将 key_path（如 "thresholds.pipeline_max_execution_time_ms"）
    安全地设置到嵌套 dict 中。

    如果中间路径不存在，自动创建中间 dict。
    """
    keys = key_path.split(".")
    current = params
    for k in keys[:-1]:
        if k not in current:
            current[k] = {}
        current = current[k]
    current[keys[-1]] = value


def _get_nested(params: Dict[str, Any], key_path: str, default: Any = None) -> Any:
    """安全读取嵌套 dict"""
    keys = key_path.split(".")
    current = params
    for k in keys:
        if not isinstance(current, dict) or k not in current:
            return default
        current = current[k]
    return current
