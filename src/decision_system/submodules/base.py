"""
DriveSignal 数据结构

所有子模块必须返回此类型的列表。

V4 槽位映射（由 to_slot() 实现）：
    seek + pressure_flag=True  → pressure_relief 槽
    seek + pressure_flag=False → reward_gain     槽
    avoid + residue_cost_flag=False → cost       槽
    avoid + residue_cost_flag=True  → residue_cost 槽
    comfort                       → cost           槽

禁止将 AVOID 信号当成正向积分加到 SEEK 动作的得分上。

v3 改造：每个子模块同时支持两种调用方式：
    - evaluate()  : 旧接口，返回 List[DriveSignal]（向后兼容，裁决层降级保留）
    - perceive()  : v3 新接口，接收 EntityCore，直接修改其状态
      签名：perceive(inputs: dict, entity_core: Any) -> None
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


SignalSlot = Literal["reward_gain", "pressure_relief", "cost", "residue_cost"]


@dataclass
class DriveSignal:
    signal_type: str             # "seek" | "avoid" | "comfort"
    strength: float              # 强度 [0.0, 1.0]
    source: str                 # 子模块名称（与类名一致）
    target_locked: Optional[str] = None
    payload_draft: dict = field(default_factory=dict)
    pressure_flag: bool = False  # SEEK 时：压力驱动 → pressure_relief；否则 → reward_gain
    residue_cost_flag: bool = False  # AVOID 时：历史遗留沉没成本 → residue_cost；否则 → cost

    def to_dict(self) -> dict:
        return {
            "signal_type": self.signal_type,
            "strength": round(self.strength, 3),
            "source": self.source,
            "target_locked": self.target_locked,
            "payload_draft": self.payload_draft,
            "pressure_flag": self.pressure_flag,
            "residue_cost_flag": self.residue_cost_flag,
        }

    def to_slot(self) -> tuple[SignalSlot, float]:
        """
        将信号映射到四槽位（GLM5 致命伤修复）。
        AVOID 信号永远不能进入正向槽（reward_gain / pressure_relief）。
        """
        if self.signal_type == "seek":
            if self.pressure_flag:
                return ("pressure_relief", self.strength)
            else:
                return ("reward_gain", self.strength)
        elif self.signal_type == "avoid":
            if self.residue_cost_flag:
                return ("residue_cost", self.strength)
            else:
                return ("cost", self.strength)
        elif self.signal_type == "comfort":
            return ("cost", self.strength)
        else:
            return ("reward_gain", self.strength)


# ============================================================================
# v3 新接口：perceive() — 直接修改 EntityCore
# ============================================================================

def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _get_somatic_weight(entity_core: Any) -> float:
    """
    根据当前 somatic_tone 计算各模块的感知权重。
    v3.1: 从 1.0 + tone * 0.5 降为 1.0 + tone * 0.12，
    防止高 somatic_tone → 放大所有 approach delta → 感知正反馈锁死。
    权重范围 [0.88, 1.12]（原 [0.5, 1.5]）
    """
    tone = getattr(entity_core, "somatic_tone", 0.0)
    return 1.0 + tone * 0.12
