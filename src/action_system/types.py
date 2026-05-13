"""
行动类型定义

Action Type 语义：
    voice      — 她选择了沉默地写（不是 reach，是留给自己看的文字）
    reach      — 她主动敲门，想让我立刻知道
    write      — 她用 file_write 工具写了一个文件
    run        — 她用 shell_run 工具执行了一个命令
    browse     — 她用浏览器工具看了网页
    search     — 她搜索了网络
    mixed      — 她做了多种操作
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


DATA_DIR = Path(__file__).parent.parent.parent / "data"
MESSAGES_DIR = DATA_DIR / "xia_messages"
EVENTS_DIR = DATA_DIR / "events"
VOICE_DIR = DATA_DIR / "xia_voice"


@dataclass
class XIAction:
    """
    单次主动行动记录。

    字段由 XIA 自己决定，我们只负责执行和记录。
    """

    action_type: str       # "voice" / "reach" / "write" / "run" / "browse" / "search" / "mixed"
    reason: str            # 触发原因
    intensity: float        # 触发强度
    tick: int               # 触发时的 tick
    timestamp: float = field(default_factory=time.time)
    context: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "reason": self.reason,
            "intensity": self.intensity,
            "tick": self.tick,
            "timestamp": self.timestamp,
            "context": self.context,
            "payload": self.payload,
        }


@dataclass
class FailureRecord:
    """
    工具执行失败的记录。

    这是世界模型的归纳素材：XIA 自己从多次失败经验中发现规律。
    每个 FailureRecord 既是 somatic 信号的输入（影响她此刻的感受），
    也是 induct.py 的输入（帮她归纳"什么错误怎么修"）。
    """

    tool_name: str          # 失败的工具名（如 "shell_run", "web_search"）
    error_type: str         # 错误分类（如 "ModuleNotFoundError", "ConnectionError", "Timeout", "PermissionDenied", "Unknown"）
    error_message: str      # 原始错误信息（截断到 300 字符）
    command_or_input: str   # 触发失败的命令或输入（截断到 200 字符）
    severity: float         # 严重度 [0, 1]，影响 somatic penalty 的量级
    timestamp: float = field(default_factory=time.time)
    # 修复相关
    attempted_fix: str = ""      # 她尝试了什么修复（如 "pip install requests"）
    fix_result: str = ""         # 修复结果（"success" / "failed" / "" 表示未尝试）
    fix_error: str = ""          # 修复过程中的新错误

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "command_or_input": self.command_or_input,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "attempted_fix": self.attempted_fix,
            "fix_result": self.fix_result,
            "fix_error": self.fix_error,
        }

    def to_summary(self) -> str:
        """人类可读的失败摘要，给 LLM 看的。"""
        parts = [f"[失败] {self.tool_name}: {self.error_type}"]
        if self.command_or_input:
            parts.append(f"  输入: {self.command_or_input[:80]}")
        parts.append(f"  原因: {self.error_message[:120]}")
        if self.attempted_fix:
            status = "✅ 修复成功" if self.fix_result == "success" else "❌ 修复失败"
            parts.append(f"  尝试修复: {self.attempted_fix} → {status}")
        return "\n".join(parts)


# ============================================================================
# 错误类型识别（纯规则，不调 LLM）
# ============================================================================

def classify_error(stderr: str, stdout: str = "", exit_code: int = 0) -> str:
    """
    根据 stderr/stdout/exit_code 推断错误类型。

    返回：
        "ModuleNotFoundError"  — python/import 类
        "ConnectionError"      — 网络类
        "Timeout"              — 超时类
        "PermissionDenied"     — 权限类
        "NotFound"             — 文件/命令不存在
        "SyntaxError"          — 语法错误
        "DependencyError"      — 依赖不完整（非 import，如 lib not found）
        "Unknown"              — 无法识别
    """
    combined = (stderr + " " + stdout).lower()

    if "modulenotfounderror" in combined or "no module named" in combined:
        return "ModuleNotFoundError"
    if "importerror" in combined:
        return "ModuleNotFoundError"
    if "connection refused" in combined or "connection error" in combined:
        return "ConnectionError"
    if "name or service not known" in combined or "getaddrinfo" in combined:
        return "ConnectionError"
    if "timed out" in combined or "timeout" in combined:
        return "Timeout"
    if "permission denied" in combined or "operation not permitted" in combined:
        return "PermissionDenied"
    if "not found" in combined or "no such file" in combined:
        return "NotFound"
    if "command not found" in combined:
        return "NotFound"
    if "syntaxerror" in combined:
        return "SyntaxError"
    if "cannot open shared object file" in combined or "lib" in combined and "not found" in combined:
        return "DependencyError"

    # 从 exit_code 推断
    if exit_code != 0 and exit_code != -1:
        return "Unknown"

    return "Unknown"


def estimate_severity(error_type: str, exit_code: int = 0) -> float:
    """
    估计失败严重度 [0, 1]。

    - ModuleNotFound / ConnectionError → 中等（能修）
    - Timeout → 低（可能是暂时的）
    - PermissionDenied / SyntaxError → 高（她犯错了）
    - 连续失败会在 executor 层叠加
    """
    base = {
        "ModuleNotFoundError": 0.30,
        "ConnectionError": 0.35,
        "Timeout": 0.20,
        "PermissionDenied": 0.60,
        "NotFound": 0.40,
        "SyntaxError": 0.55,
        "DependencyError": 0.45,
        "Unknown": 0.50,
    }
    return base.get(error_type, 0.50)
