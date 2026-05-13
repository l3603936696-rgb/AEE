"""
Governance — 参数治理状态机与双重审批流

四种状态：
    locked       — 完全禁止修改，仅开发者手动解锁
    governed    — 默认状态，所有修改请求进入 pending_approval
    pending_approval — 等待双重审批
    cooldown    — 不稳定期，阈值突破模式触发，所有请求直接丢弃

双重审批路由：
    第一通道（AI 内部评估）：基于世界模型反馈或驱动力累积产生修改提案
    第二通道（外部审计）：开发者日志审计或手动介入确认

安全约束：
    - AI 自己不能当裁判（第一通道提案 → 第二通道审批）
    - 绕过 change_governance 的修改尝试必须被拦截并记录最高级别警告
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ============================================================================
# 状态枚举
# ============================================================================

class ParameterStatus(Enum):
    """参数治理状态"""
    LOCKED = "locked"
    GOVERNED = "governed"
    PENDING_APPROVAL = "pending_approval"
    COOLDOWN = "cooldown"


# ============================================================================
# 变更请求
# ============================================================================

@dataclass
class ChangeRequest:
    """参数修改请求"""
    key_path: str          # "thresholds.pipeline_max_execution_time_ms"
    proposed_value: Any   # 提议值
    reason: str            # 修改原因
    channel: str          # "ai_internal" | "developer_external"
    requested_at: float   # 时间戳
    requester: str         # "ai" | "developer" | "world_model"

    # 审批信息（由 change_governance 填写）
    approved: bool = False
    approved_at: Optional[float] = None
    approver: Optional[str] = None    # "ai" | "developer"
    rejection_log: Optional[str] = None


# ============================================================================
# 治理记录
# ============================================================================

@dataclass
class GovernanceRecord:
    """单条治理记录"""
    timestamp: float
    key_path: str
    action: str            # "request" | "approve" | "reject" | "cooldown_triggered" | "locked" | "unlocked"
    channel: str
    requester: str
    approver: Optional[str]
    proposed_value: Any
    final_value: Any
    reason: str


# ============================================================================
# 变更治理核心
# ============================================================================

RECORDS_CAPACITY = 1000   # 内存中保留的最大治理记录数


class ChangeGovernance:
    """
    双重审批路由器。

    约束：
        - 所有参数修改必须经过本路由器
        - AI 内部评估（第一通道）→ 提案 → 等待外部审批（第二通道）
        - 绕过本类的修改尝试必须被拦截
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._status: Dict[str, ParameterStatus] = {}   # per-key 状态
        self._global_status = ParameterStatus.GOVERNED   # 全局默认
        self._records: List[GovernanceRecord] = []
        self._cooldown_until: Optional[float] = None
        self._cooldown_duration: float = 60.0            # cooldown 持续 60 秒
        self._threshold_burst_count: int = 0             # 短时间内请求计数
        self._threshold_burst_window: float = 5.0        # 5 秒窗口
        self._threshold_burst_limit: int = 3            # 超过 3 次触发 cooldown

    # ---- 公开 API ----

    def get_status(self, key_path: Optional[str] = None) -> ParameterStatus:
        """读取当前治理状态（全局或指定 key）"""
        with self._lock:
            if key_path:
                return self._status.get(key_path, self._global_status)
            return self._global_status

    def set_status(self, status: ParameterStatus, key_path: Optional[str] = None) -> None:
        """设置治理状态（仅供开发者/测试调用）"""
        with self._lock:
            if key_path:
                self._status[key_path] = status
            else:
                self._global_status = status
            self._log(
                action="locked" if status == ParameterStatus.LOCKED else "unlocked",
                channel="developer",
                requester="developer",
                approver=None,
                key_path=key_path or "global",
                proposed_value=None,
                final_value=status.value,
                reason="manual_status_change",
            )

    def submit(
        self,
        key_path: str,
        proposed_value: Any,
        reason: str,
        channel: str,
        requester: str,
    ) -> ChangeRequest:
        """
        提交修改请求（第一通道：AI 内部评估产出提案）。

        返回 ChangeRequest，其中 approved=False，等待第二通道审批。
        """
        with self._lock:
            self._check_cooldown_expired_unlocked()
            status = self._status.get(key_path, self._global_status)

            if status == ParameterStatus.LOCKED:
                self._warn_bypass(key_path, "LOCKED")
                return self._make_request(
                    key_path, proposed_value, reason, channel, requester,
                    approved=False, rejection_log="参数处于 LOCKED 状态，禁止修改",
                )

            if status == ParameterStatus.COOLDOWN:
                self._log(
                    action="reject",
                    channel=channel,
                    requester=requester,
                    approver=None,
                    key_path=key_path,
                    proposed_value=proposed_value,
                    final_value=None,
                    reason=f"COOLDOWN 状态下请求被丢弃: {reason}",
                )
                return self._make_request(
                    key_path, proposed_value, reason, channel, requester,
                    approved=False, rejection_log="参数处于 COOLDOWN 状态，请求被丢弃",
                )

            # governed 或 pending_approval：接受提案，状态转为 pending_approval
            self._status[key_path] = ParameterStatus.PENDING_APPROVAL
            req = self._make_request(
                key_path, proposed_value, reason, channel, requester,
                approved=False,
            )
            self._records.append(GovernanceRecord(
                timestamp=time.time(),
                key_path=key_path,
                action="request",
                channel=channel,
                requester=requester,
                approver=None,
                proposed_value=proposed_value,
                final_value=None,
                reason=reason,
            ))
            self._enforce_capacity()
            self._check_threshold_burst_unlocked(channel)

            return req

    def approve(
        self,
        key_path: str,
        approver: str,       # "ai" | "developer"
        reason: Optional[str] = None,
    ) -> bool:
        """
        第二通道审批入口。

        注意：审批者不能是同一轮提案的请求者（AI 不能给自己审批）。
        """
        with self._lock:
            if approver == "ai":
                # AI 审批仅允许在 developer 显式授权的情况下
                # 为简化实现，这里直接拒绝 AI 审批（除非 developer 预先解除限制）
                self._log(
                    action="reject",
                    channel="ai_internal",
                    requester="ai",
                    approver=approver,
                    key_path=key_path,
                    proposed_value=None,
                    final_value=None,
                    reason="AI 无法审批自己的提案（第二通道必须为外部审计）",
                )
                return False

            self._log(
                action="approve",
                channel="developer_external",
                requester="",
                approver=approver,
                key_path=key_path,
                proposed_value=None,
                final_value=None,
                reason=reason or "developer 手动审批通过",
            )
            return True

    def reject(
        self,
        key_path: str,
        approver: str,
        reason: str,
    ) -> None:
        """拒绝修改请求"""
        with self._lock:
            self._log(
                action="reject",
                channel="",
                requester="",
                approver=approver,
                key_path=key_path,
                proposed_value=None,
                final_value=None,
                reason=reason,
            )

    def get_pending(self) -> List[ChangeRequest]:
        """返回所有待审批请求（从 records 中重建）"""
        with self._lock:
            pending: List[ChangeRequest] = []
            for rec in self._records:
                if rec.action == "request":
                    pending.append(ChangeRequest(
                        key_path=rec.key_path,
                        proposed_value=rec.proposed_value,
                        reason=rec.reason,
                        channel=rec.channel,
                        requested_at=rec.timestamp,
                        requester=rec.requester,
                        approved=False,
                    ))
            return pending

    def get_records(self, limit: int = 100) -> List[GovernanceRecord]:
        """返回最近 N 条治理记录"""
        with self._lock:
            return list(self._records[-limit:])

    def reset(self) -> None:
        """重置所有状态（仅供测试用）"""
        with self._lock:
            self._status.clear()
            self._global_status = ParameterStatus.GOVERNED
            self._records.clear()
            self._cooldown_until = None
            self._threshold_burst_count = 0

    # ---- 内部方法 ----

    def _make_request(
        self,
        key_path: str,
        proposed_value: Any,
        reason: str,
        channel: str,
        requester: str,
        approved: bool = False,
        rejection_log: Optional[str] = None,
    ) -> ChangeRequest:
        return ChangeRequest(
            key_path=key_path,
            proposed_value=proposed_value,
            reason=reason,
            channel=channel,
            requested_at=time.time(),
            requester=requester,
            approved=approved,
            rejection_log=rejection_log,
        )

    def _check_cooldown_expired_unlocked(self) -> None:
        """检查 cooldown 是否已过期（调用方必须持有 _lock）"""
        if self._cooldown_until is not None and time.time() > self._cooldown_until:
            self._cooldown_until = None
            self._global_status = ParameterStatus.GOVERNED

    def _check_threshold_burst_unlocked(self, channel: str) -> None:
        """阈值突破检测（调用方必须持有 _lock）"""
        if channel != "ai_internal":
            return

        now = time.time()
        # 重置过期计数
        recent = [r for r in self._records if r.action == "request"
                  and now - r.timestamp <= self._threshold_burst_window]
        self._threshold_burst_count = len(recent)

        if self._threshold_burst_count >= self._threshold_burst_limit:
            self._enter_cooldown_unlocked()

    def _enter_cooldown_unlocked(self) -> None:
        """进入 cooldown（调用方必须持有 _lock）"""
        self._cooldown_until = time.time() + self._cooldown_duration
        self._global_status = ParameterStatus.COOLDOWN
        self._log(
            action="cooldown_triggered",
            channel="system",
            requester="system",
            approver=None,
            key_path="global",
            proposed_value=None,
            final_value=self._cooldown_duration,
            reason=f"阈值突破：{self._threshold_burst_count} 次请求在 {self._threshold_burst_window}s 内触发 cooldown（持续 {self._cooldown_duration}s）",
        )

    def _warn_bypass(self, key_path: str, reason: str) -> None:
        """记录最高级别警告：绕过治理的修改尝试"""
        print(f"[CRITICAL SECURITY WARNING] 绕过参数治理的修改尝试被拦截！key={key_path}, reason={reason}")

    def _log(
        self,
        action: str,
        channel: str,
        requester: str,
        approver: Optional[str],
        key_path: str,
        proposed_value: Any,
        final_value: Any,
        reason: str,
    ) -> None:
        """写入治理记录"""
        self._records.append(GovernanceRecord(
            timestamp=time.time(),
            key_path=key_path,
            action=action,
            channel=channel,
            requester=requester,
            approver=approver,
            proposed_value=proposed_value,
            final_value=final_value,
            reason=reason,
        ))
        self._enforce_capacity()

    def _enforce_capacity(self) -> None:
        """容量限制"""
        while len(self._records) > RECORDS_CAPACITY:
            self._records.pop(0)


# ============================================================================
# 全局单例（模块级）
# ============================================================================

_GOVERNANCE_INSTANCE: Optional[ChangeGovernance] = None
_GOVERNANCE_LOCK = threading.Lock()


def get_governance() -> ChangeGovernance:
    """获取全局治理实例（单例）"""
    global _GOVERNANCE_INSTANCE
    with _GOVERNANCE_LOCK:
        if _GOVERNANCE_INSTANCE is None:
            _GOVERNANCE_INSTANCE = ChangeGovernance()
        return _GOVERNANCE_INSTANCE


def reset_governance() -> None:
    """重置全局治理实例（仅供测试用）"""
    global _GOVERNANCE_INSTANCE
    with _GOVERNANCE_LOCK:
        if _GOVERNANCE_INSTANCE is not None:
            _GOVERNANCE_INSTANCE.reset()
        _GOVERNANCE_INSTANCE = None
