"""
Access — 参数系统公开 API

这是参数系统对外暴露的唯一入口。
下游模块应仅通过此模块的函数访问参数系统。

四大接口：
    create_snapshot  — 同步管线启动时调用，生成不可变只读快照
    get_param        — 从快照中安全读取参数（支持嵌套键）
    stage_changes    — 将修改写入待生效缓冲区（不落盘）
    apply_staged    — 异步写入循环调用，真正落盘

硬约束：
    - 同步管线执行期间，绝对不能调用 apply_staged
    - 任何绕过本接口的修改尝试，必须被拦截
    - PARAM_DEFAULTS 本身绝不直接传给管线，必须先 create_snapshot
"""

from __future__ import annotations

import copy
import json
import os
import time
import threading
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .parameters import PARAM_DEFAULTS
from .governance import ChangeGovernance, get_governance, reset_governance, ParameterStatus, ChangeRequest
from .snapshot import ParameterSnapshot, ReadOnlyView
from .staging import StagedChanges, APPLY_MODE, _get_nested, _set_nested

if TYPE_CHECKING:
    from .snapshot import ParameterSnapshot


# ============================================================================
# 持久化文件路径（可通过 set_param_file() 覆盖）
# ============================================================================

PARAM_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "param_store.json"
)


def set_param_file(path: str) -> None:
    """设置参数持久化文件路径（必须在首次 create_snapshot 前调用）"""
    global PARAM_FILE
    PARAM_FILE = path


# ============================================================================
# 全局状态
# ============================================================================

_current_snapshot: Optional[ParameterSnapshot] = None
_staged_changes: Optional[StagedChanges] = None
_tick_counter: int = 0
_tick_counter_lock = threading.Lock()

# 初始化全局 staging 实例（惰性创建）
_staged_lock = threading.Lock()


def _get_staged() -> StagedChanges:
    """获取或创建全局 staging 实例"""
    global _staged_changes
    with _staged_lock:
        if _staged_changes is None:
            _staged_changes = StagedChanges(PARAM_FILE)
        return _staged_changes


# ============================================================================
# 公开 API
# ============================================================================

def create_snapshot(
    overrides: Optional[Dict[str, Any]] = None,
    persist_path: Optional[str] = None,
) -> ParameterSnapshot:
    """
    为当前同步管线 Tick 创建不可变参数快照。

    调用时机：每个 Tick 管线启动时（所有同步逻辑之前）
    调用次数：每个 Tick 仅调用一次

    参数：
        overrides  : 可选，覆盖参数（如从 JSON 加载的持久化参数）
        persist_path : 可选，覆盖持久化路径

    返回：
        ParameterSnapshot — 包含只读视图的快照对象

    约束：
        - 快照一旦创建，在对应 Tick 结束前绝对不可修改
        - 不得将 PARAM_DEFAULTS 直接传给管线，必须先 create_snapshot
    """
    global _current_snapshot, _tick_counter

    # 加载持久化参数（优先）或使用默认
    path = persist_path or PARAM_FILE
    base_params: Dict[str, Any]

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            base_params = copy.deepcopy(loaded)
        except Exception:
            base_params = copy.deepcopy(PARAM_DEFAULTS)
    else:
        base_params = copy.deepcopy(PARAM_DEFAULTS)

    # 应用 overrides（允许在快照级别临时覆盖参数）
    if overrides:
        for key, value in overrides.items():
            if key in base_params and isinstance(base_params[key], dict) and isinstance(value, dict):
                base_params[key].update(value)
            else:
                base_params[key] = copy.deepcopy(value)

    with _tick_counter_lock:
        _tick_counter += 1
        tick_index = _tick_counter

    snapshot = ParameterSnapshot.create(
        params=base_params,
        tick_index=tick_index,
    )

    # 更新全局当前快照（线程安全）
    global _current_snapshot
    _current_snapshot = snapshot

    return snapshot


def get_param(
    snapshot: Optional[ParameterSnapshot],
    key_path: str,
    default: Any = None,
) -> Any:
    """
    从快照中安全读取参数（支持嵌套键，用 "." 分隔）。

    参数：
        snapshot  : 参数快照（create_snapshot 的返回值）
        key_path  : 参数路径，如 "thresholds.pipeline_max_execution_time_ms"
                    或 "drives.curiosity_baseline"
        default   : 参数不存在时的默认值

    返回：
        参数值（float / bool / int / str / dict 等）

    约束：
        - 不得在读取后直接修改返回值
        - 不得将返回值作为写入目标

    示例：
        timeout = get_param(snapshot, "thresholds.pipeline_max_execution_time_ms", 5000)
    """
    if snapshot is None:
        # 兼容处理：快照为空时从 staging 读取
        staged = _get_staged()
        staged_val = staged.get_staged(key_path)
        if staged_val is not None:
            return staged_val
        return _get_nested(PARAM_DEFAULTS, key_path, default)

    # 验证快照有效性
    snapshot.validate()

    params = snapshot.params._data
    value = _get_nested(params, key_path, default=None)

    if value is None:
        return default

    # 对 dict/list 返回深拷贝，防止引用修改
    if isinstance(value, (dict, list)):
        return copy.deepcopy(value)
    return value


def stage_changes(
    key_path: str,
    value: Any,
    reason: str,
    snapshot: Optional[ParameterSnapshot] = None,
    governance: Optional[ChangeGovernance] = None,
) -> ChangeRequest:
    """
    将参数修改写入待生效缓冲区。

    调用时机：同步管线执行期间（AI 决策或世界模型归纳产生修改提案）

    参数：
        key_path   : 参数路径，如 "thresholds.narrative_memory_pressure_note_gate"
        value      : 提议值
        reason     : 修改原因（必须填写，用于审计）
        snapshot   : 当前快照（用于治理状态检查，可选）
        governance : 可选，注入治理实例（默认使用全局单例）

    返回：
        ChangeRequest — 包含审批状态的请求对象

    约束：
        - 绝对不能在同步管线返回前调用 apply_staged
        - 任何绕过本接口的修改尝试必须被拦截
    """
    gov = governance or get_governance()

    # ---- 第一通道：AI 内部评估提交提案 ----
    request = gov.submit(
        key_path=key_path,
        proposed_value=value,
        reason=reason,
        channel="ai_internal",
        requester="ai",
    )

    # ---- 写入待生效缓冲区（即使在 pending 状态也写入，供异步循环处理）----
    staged = _get_staged()
    staged.stage(key_path=key_path, value=value, reason=reason)

    return request


def apply_staged(
    mode: str = "staged_only",
    governance: Optional[ChangeGovernance] = None,
) -> Dict[str, Any]:
    """
    应用待生效的修改到持久化参数表（异步写入循环专用）。

    调用时机：Tick 结束后，由异步写入循环调用

    参数：
        mode      : "staged_only"（默认，仅更新内存）
                    "persist_now"（立即落盘）
                    "staged_and_persist"（等同于 persist_now）
        governance : 可选，注入治理实例

    返回：
        应用后的完整参数表

    约束：
        - 绝对不能在同步管线执行期间调用 PERSIST_NOW 模式
        - 本函数仅供 entity_zero_iteration.py 的异步写入循环调用
    """
    # 解析 mode
    if mode in ("persist_now", "staged_and_persist"):
        apply_mode = APPLY_MODE.PERSIST_NOW
    else:
        apply_mode = APPLY_MODE.STAGED_ONLY

    # 加载当前持久化参数
    source_params: Dict[str, Any]
    if os.path.exists(PARAM_FILE):
        try:
            with open(PARAM_FILE, "r", encoding="utf-8") as f:
                source_params = json.load(f)
        except Exception:
            source_params = copy.deepcopy(PARAM_DEFAULTS)
    else:
        source_params = copy.deepcopy(PARAM_DEFAULTS)

    staged = _get_staged()
    return staged.apply_staged(source_params, mode=apply_mode)


def load_params_from_file(path: Optional[str] = None) -> Dict[str, Any]:
    """
    从 JSON 文件加载参数表。

    参数：
        path : 可选，参数文件路径（默认使用 PARAM_FILE）

    返回：
        参数字典（可写深拷贝）
    """
    file_path = path or PARAM_FILE
    if not os.path.exists(file_path):
        return copy.deepcopy(PARAM_DEFAULTS)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return copy.deepcopy(PARAM_DEFAULTS)


def save_params_to_file(
    params: Dict[str, Any],
    path: Optional[str] = None,
) -> bool:
    """
    将参数表写入 JSON 文件。

    参数：
        params : 参数字典
        path   : 可选，文件路径（默认使用 PARAM_FILE）

    返回：
        是否成功
    """
    file_path = path or PARAM_FILE
    try:
        dir_path = os.path.dirname(file_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[ERROR] 参数保存失败: {e}")
        return False


def get_governance_status(key_path: Optional[str] = None) -> str:
    """
    查询治理状态（用于调试和监控）。

    参数：
        key_path : 可选，查询特定 key 的状态；默认返回全局状态

    返回：
        状态字符串："locked" | "governed" | "pending_approval" | "cooldown"
    """
    gov = get_governance()
    status = gov.get_status(key_path)
    return status.value


def list_staged_changes() -> List[Dict[str, Any]]:
    """
    列出当前所有待生效的修改。

    返回：
        [{"key_path": "...", "value": ..., "reason": "...", "staged_at": ...}, ...]
    """
    staged = _get_staged()
    return [
        {
            "key_path": rec.key_path,
            "value": rec.value,
            "reason": rec.reason,
            "staged_at": rec.staged_at,
        }
        for rec in staged.list_pending()
    ]


def get_current_snapshot() -> Optional[ParameterSnapshot]:
    """返回当前活跃的快照（供调试用）"""
    return _current_snapshot


# ============================================================================
# 硬约束验证（可选开启）
# ============================================================================

def _verify_no_bypass_attempt(params: Any) -> None:
    """
    检测是否有绕过 access API 的直接修改尝试。

    如果检测到 PARAM_DEFAULTS 被直接传入管线，抛出异常。
    此函数由 create_snapshot 内部调用。
    """
    if params is PARAM_DEFAULTS:
        raise ValueError(
            "CRITICAL: 检测到 PARAM_DEFAULTS 被直接传给管线！"
            "必须先 create_snapshot() 生成只读快照。"
            "正确用法：snapshot = create_snapshot(); "
            "get_param(snapshot, 'thresholds.pipeline_max_execution_time_ms')"
        )


# 在 create_snapshot 开头插入验证
_original_create_snapshot = create_snapshot


def create_snapshot(
    overrides: Optional[Dict[str, Any]] = None,
    persist_path: Optional[str] = None,
) -> ParameterSnapshot:
    _verify_no_bypass_attempt(overrides)
    return _original_create_snapshot(overrides, persist_path)
