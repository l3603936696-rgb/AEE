"""
Quenching Schema — 数据结构定义。

包含：QuenchingRecord dataclass。
"""

from dataclasses import dataclass


@dataclass
class QuenchingRecord:
    """
    单次消力记录。

    属性：
        drive_state_hash : 驱动力场状态的哈希（用于聚类相似状态）
        expression       : 实际说出的表达
        delta_unresolved_before: 执行前的 unresolved 值
        delta_unresolved_after : 执行后的 unresolved 值
        quenching_efficiency   : 消力效率 = before - after
        timestamp             : 记录时间
    """
    drive_state_hash: str
    expression: str
    delta_unresolved_before: float
    delta_unresolved_after: float
    quenching_efficiency: float
    timestamp: float
    tick: int = 0  # v11.3: 记录对应的 entity tick，供温跃层判断活跃度
    template_idx: int = -1  # v11.6: 句子模板索引，-1 表示未使用模板
