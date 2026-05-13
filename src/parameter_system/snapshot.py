"""
Snapshot — 快照隔离与只读视图

核心约束：
    - 每个同步管线 Tick 启动时生成不可变快照
    - 快照一旦生成，在其生命周期内绝对不可修改
    - 所有下游模块只能通过 get_param(snapshot, ...) 读取
    - 禁止将原始 PARAM_DEFAULTS 传给管线，必须先 create_snapshot
"""

from __future__ import annotations

import copy
import time
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# ============================================================================
# 只读视图（防写保护）
# ============================================================================

class ReadOnlyView:
    """
    不可变参数视图。

    底层使用普通 dict 存储数据（保证读取性能），
    所有修改操作均抛 AttributeError。
    """

    __slots__ = ("_data",)

    def __init__(self, data: Dict[str, Any]) -> None:
        # 浅拷贝，防止外部修改引用
        self._data: Dict[str, Any] = dict(data)

    # ---- 字典协议（只读） ----

    def __getitem__(self, key: str) -> Any:
        val = self._data[key]
        # dict → 返回只读视图包装，防止嵌套写入
        if isinstance(val, dict):
            return ReadOnlyView(val)
        # list/tuple → 返回不可变序列
        if isinstance(val, (list, tuple)):
            return tuple(val)
        return val

    def get(self, key: str, default: Any = None) -> Any:
        if key not in self._data:
            return default
        return self.__getitem__(key)

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def copy(self) -> Dict[str, Any]:
        """返回一份可变的深拷贝（供外部分析用，不影响快照）"""
        return copy.deepcopy(self._data)

    def raw(self) -> Dict[str, Any]:
        """返回原始数据引用（仅供 access.py 内部使用）"""
        return self._data

    # ---- 防写保护 ----

    def __setitem__(self, key: str, value: Any) -> None:
        raise AttributeError(
            "参数快照是只读的，禁止直接修改。"
            "请使用 stage_changes() 接口将修改写入待生效缓冲区。"
        )

    def __delitem__(self, key: str) -> None:
        raise AttributeError(
            "参数快照是只读的，禁止删除。"
            "请使用 stage_changes() 接口。"
        )

    def clear(self) -> None:
        raise AttributeError("参数快照是只读的，禁止清空。")

    def pop(self, *args) -> Any:
        raise AttributeError("参数快照是只读的，禁止 pop 操作。")

    def popitem(self) -> tuple:
        raise AttributeError("参数快照是只读的，禁止 popitem 操作。")

    def setdefault(self, *args) -> Any:
        raise AttributeError(
            "参数快照是只读的，禁止 setdefault。"
            "请使用 stage_changes() 接口。"
        )

    def update(self, *args, **kwargs) -> None:
        raise AttributeError(
            "参数快照是只读的，禁止 update。"
            "请使用 stage_changes() 接口。"
        )

    def __repr__(self) -> str:
        return f"<ReadOnlyView snapshot_id={self._snapshot_id!r}>"

    @property
    def _snapshot_id(self) -> str:
        return self._data.get("_system", {}).get("snapshot_id", "unknown")


# ============================================================================
# 参数快照
# ============================================================================

@dataclass
class ParameterSnapshot:
    """
    单次同步管线的参数只读快照。

    生命周期：
        1. create_snapshot() 生成
        2. 同步管线执行期间只读
        3. 管线结束后自然失效（不需显式销毁）
    """
    snapshot_id: str                    # 唯一标识
    created_at: float                   # 创建时间戳
    params: ReadOnlyView               # 只读参数视图
    tick_index: int                    # 对应的 tick 序号
    is_valid: bool = field(default=True)   # 有效性标志

    @classmethod
    def create(
        cls,
        params: Dict[str, Any],
        tick_index: int,
        snapshot_id: Optional[str] = None,
    ) -> "ParameterSnapshot":
        """
        创建新的参数快照。

        参数：
            params      : 完整参数表（从 JSON 加载或 PARAM_DEFAULTS）
            tick_index  : 当前 tick 序号
            snapshot_id : 可选快照 ID（默认自动生成）
        """
        params = copy.deepcopy(params)
        if "_system" not in params:
            params["_system"] = {}
        params["_system"]["snapshot_id"] = snapshot_id or uuid.uuid4().hex[:12]
        params["_system"]["snapshot_created_at"] = time.time()
        params["_system"]["snapshot_tick_index"] = tick_index

        return cls(
            snapshot_id=params["_system"]["snapshot_id"],
            created_at=time.time(),
            params=ReadOnlyView(params),
            tick_index=tick_index,
            is_valid=True,
        )

    def invalidate(self) -> None:
        """使快照失效（通常在 tick 结束后调用）"""
        self.is_valid = False

    def validate(self) -> None:
        """检查快照有效性，无效则抛异常"""
        if not self.is_valid:
            raise ValueError(
                f"参数快照 {self.snapshot_id} 已失效（tick {self.tick_index} 已结束）。"
                "请为当前 tick 创建新快照。"
            )
