"""
Parameter System — 参数系统

绝对稳定的可调参数存储、快照隔离的只读访问、带双重审批的异步写入机制。

架构原则（V4 硬约束）：
    - 极简三层参数结构
    - 快照隔离：同步管线只读，异步写入
    - 双重审批状态机：locked / governed / pending_approval / cooldown
    - 绝对禁止本轮写入被本轮读取
"""

from .parameters import (
    PARAM_DEFAULTS,
    PARAM_CATEGORIES,
)
from .governance import (
    ParameterStatus,
    ChangeRequest,
    ChangeGovernance,
    RECORDS_CAPACITY,
    get_governance,
    reset_governance,
)
from .snapshot import ParameterSnapshot, ReadOnlyView
from .staging import StagedChanges, ChangeRecord, APPLY_MODE
from .access import (
    create_snapshot,
    stage_changes,
    apply_staged,
    get_param,
    get_governance,
    reset_governance,
    get_governance_status,
    list_staged_changes,
    load_params_from_file,
    save_params_to_file,
    get_current_snapshot,
    PARAM_FILE,
)

__all__ = [
    # 参数默认值
    "PARAM_DEFAULTS",
    "PARAM_CATEGORIES",
    # 治理
    "ParameterStatus",
    "ChangeRequest",
    "ChangeGovernance",
    "RECORDS_CAPACITY",
    "get_governance",
    "reset_governance",
    # 快照
    "ParameterSnapshot",
    "ReadOnlyView",
    # 缓冲
    "StagedChanges",
    "ChangeRecord",
    "APPLY_MODE",
    # 公开 API
    "create_snapshot",
    "stage_changes",
    "apply_staged",
    "get_param",
    "get_governance_status",
    "list_staged_changes",
    "load_params_from_file",
    "save_params_to_file",
    "get_current_snapshot",
    "PARAM_FILE",
]
