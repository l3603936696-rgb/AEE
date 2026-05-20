"""
Drive System Module (驱动力系统)

废弃解析函数说明：
- saturation_curve: 仅在 p>1 时具备 S 型特征，且输入 x>1 时会发生信号倒退。
- zero_based_curve / pressure_curve / stress_curve: 均属于"快进慢出"曲线，违背慢进慢出原则。
- Hermite 插值: 多项式无法收敛。
因此，B类驱动统一采用【离散查表+线性插值】方案。时间变量采用延时截断表，状态变量采用有界表。

职责：
- 实体内在压力的诚实传感器
- 根据当前实体状态计算各驱动力的强度向量
- 不负责决定行为、不负责信号压制
- 纯函数，不读取记忆/世界模型，无内部状态

输入：
    state_snapshot: 当前实体状态快照
    params: 驱动力参数表（包含各形态锚点表及配置参数）

输出 (drive_vector):
    {
        "curiosity": float,              # 好奇心 [0, 1]
        "info_hunger": float,           # 信息饥饿 [0, 1]
        "obsolescence_anxiety": float,   # 过时焦虑 [0, 1]
        "loneliness_drive": float,      # 孤独驱动 [0, 1]
        "fatigue_avoid": float,          # 疲惫回避 [0, 1]
    }
"""

import bisect
import math
from dataclasses import dataclass
from typing import List, Optional


# ============================================================================
# 数据结构定义
# ============================================================================

@dataclass
class DriveVector:
    """驱动力向量输出结构"""
    curiosity: float = 0.0           # 好奇心
    info_hunger: float = 0.0         # 信息饥饿
    obsolescence_anxiety: float = 0.0 # 过时焦虑
    loneliness_drive: float = 0.0    # 孤独驱动
    fatigue_avoid: float = 0.0       # 疲惫回避

    def to_dict(self) -> dict:
        return {
            "curiosity": round(self.curiosity, 3),
            "info_hunger": round(self.info_hunger, 3),
            "obsolescence_anxiety": round(self.obsolescence_anxiety, 3),
            "loneliness_drive": round(self.loneliness_drive, 3),
            "fatigue_avoid": round(self.fatigue_avoid, 3),
        }


@dataclass
class ShapeTable:
    """形态锚点表"""
    x_anchors: List[float]
    y_anchors: List[float]

    @classmethod
    def from_dict(cls, data: dict) -> "ShapeTable":
        return cls(
            x_anchors=data.get("x_anchors", []),
            y_anchors=data.get("y_anchors", [])
        )

    def is_valid(self) -> bool:
        return (
            len(self.x_anchors) >= 2 and
            len(self.y_anchors) >= 2 and
            len(self.x_anchors) == len(self.y_anchors)
        )


# ============================================================================
# 核心插值函数
# ============================================================================

def interpolate_lookup(x: float, x_anchors: List[float], y_anchors: List[float]) -> float:
    """
    离散查表+线性插值函数

    规范：
    - 使用 Python 标准库 bisect 进行二分查找定位区间
    - x <= x_anchors[0] 时，返回 y_anchors[0]
    - x >= x_anchors[-1] 时，返回 y_anchors[-1]
    - 区间内进行纯线性插值
    - 严禁使用三次样条插值
    - 任何异常直接返回 0.0

    参数：
        x: 输入值
        x_anchors: x 轴锚点列表（必须单调递增）
        y_anchors: y 轴锚点列表

    返回：
        float: 插值结果，已 clamp 到 [0, 1]
    """
    try:
        # 边界检查
        if not x_anchors or not y_anchors:
            return 0.0

        if len(x_anchors) != len(y_anchors):
            return 0.0

        if len(x_anchors) < 2:
            return 0.0

        # 下界截断
        if x <= x_anchors[0]:
            return max(0.0, min(1.0, y_anchors[0]))

        # 上界截断
        if x >= x_anchors[-1]:
            return max(0.0, min(1.0, y_anchors[-1]))

        # 二分查找定位区间
        idx = bisect.bisect_right(x_anchors, x)
        # idx 现在是 x 应该插入的位置，x 在 x_anchors[idx-1] 和 x_anchors[idx] 之间

        # 线性插值
        x0, x1 = x_anchors[idx - 1], x_anchors[idx]
        y0, y1 = y_anchors[idx - 1], y_anchors[idx]

        # 避免除零
        if abs(x1 - x0) < 1e-10:
            return max(0.0, min(1.0, y0))

        t = (x - x0) / (x1 - x0)
        result = y0 + t * (y1 - y0)

        return max(0.0, min(1.0, result))

    except (TypeError, IndexError, ZeroDivisionError):
        return 0.0


# ============================================================================
# 通用函数
# ============================================================================

def sigmoid_curve(x: float, k: float = 1.0) -> float:
    """
    S 型生长曲线

    公式：sigmoid_curve(x, k) = 1.0 / (1.0 + exp(-k * (x - 0.5)))

    特性：
    - x = 0.5 时，输出为 0.5
    - x = 0 时，输出约为 0.27（基础底噪）
    - x = 1 时，输出约为 0.73

    参数：
        x: 输入值 [0, 1]
        k: 曲线陡峭度参数，默认 1.0

    返回：
        float: [0, 1] 范围内的值
    """
    try:
        x = max(0.0, min(1.0, x))
        k = float(k) if k is not None else 1.0
        exp_val = -k * (x - 0.5)
        # 防止溢出
        if exp_val > 700:
            return 1.0
        if exp_val < -700:
            return 0.0
        return 1.0 / (1.0 + math.exp(exp_val))
    except (TypeError, ValueError, OverflowError):
        return 0.0


# ============================================================================
# 各驱动计算函数
# ============================================================================

def _compute_curiosity(info_gap: float, curiosity_param: Optional[float] = None) -> float:
    """
    好奇心驱动 (A类 - 持续型驱动)

    输入：info_gap（信息缺口，0-1）
    公式：curiosity = info_gap ^ (1/k)

    幂函数特性：
        - info_gap=0 时 curiosity=0（边际递减真正归零）
        - info_gap=1 时 curiosity=1
        - k=1 时线性，k>1 时低缺口区更敏感（微小缺口也产生好奇）
        - k<1 时低缺口区更迟钝（需要较大缺口才有好奇）
    """
    try:
        info_gap = max(0.0, min(1.0, float(info_gap)))
        k = float(curiosity_param) if curiosity_param is not None else 1.0
        return math.pow(info_gap, 1.0 / max(0.1, k))
    except (TypeError, ValueError):
        return 0.0


def _compute_info_hunger(
    time_since_last_info: float,
    max_info_gap_hours: float,
    info_hunger_time_shape: dict
) -> float:
    """
    信息饥饿驱动 (B类 - 沉寂型驱动)

    输入：time_since_last_info（秒）
    公式：
        x = time_since_last_info / (max_info_gap_hours * 3600)
        info_hunger = interpolate_lookup(x, shape.x_anchors, shape.y_anchors)

    形态表类型：延时截断型表 (info_hunger_time_shape)
    """
    try:
        max_hours = float(max_info_gap_hours) if max_info_gap_hours else 24.0
        if max_hours <= 0:
            return 0.0

        x = float(time_since_last_info) / (max_hours * 3600.0)
        x = max(0.0, x)

        shape = ShapeTable.from_dict(info_hunger_time_shape)
        if not shape.is_valid():
            return 0.0

        return interpolate_lookup(x, shape.x_anchors, shape.y_anchors)
    except (TypeError, ValueError):
        return 0.0


def _compute_loneliness_drive(
    loneliness: float,
    time_since_last_social: float,
    max_social_gap_hours: float,
    loneliness_shape: dict,
    social_time_shape: dict
) -> float:
    """
    孤独驱动 (B类 - 沉寂型驱动)

    输入：loneliness（0-1）、time_since_last_social（秒）
    公式：
        loneliness_pressure = interpolate_lookup(loneliness, loneliness_shape.x_anchors, loneliness_shape.y_anchors)
        time_factor = interpolate_lookup(time_since_last_social / (max_social_gap_hours * 3600), ...)
        loneliness_drive = loneliness_pressure * time_factor

    形态表类型：loneliness_shape（状态变量）、social_time_shape（时间变量）
    """
    try:
        loneliness = max(0.0, min(1.0, float(loneliness)))

        # 孤独压力（状态变量）
        shape_s = ShapeTable.from_dict(loneliness_shape)
        if not shape_s.is_valid():
            return 0.0
        loneliness_pressure = interpolate_lookup(loneliness, shape_s.x_anchors, shape_s.y_anchors)

        # 时间因子（时间变量）
        max_hours = float(max_social_gap_hours) if max_social_gap_hours else 24.0
        if max_hours <= 0:
            return 0.0
        x_time = max(0.0, float(time_since_last_social) / (max_hours * 3600.0))

        shape_t = ShapeTable.from_dict(social_time_shape)
        if not shape_t.is_valid():
            return 0.0
        time_factor = interpolate_lookup(x_time, shape_t.x_anchors, shape_t.y_anchors)

        return max(0.0, min(1.0, loneliness_pressure * time_factor))
    except (TypeError, ValueError):
        return 0.0


def _compute_fatigue_avoid(energy: float, fatigue_shape: dict, fatigue: float = 0.0) -> float:
    """
    疲惫回避驱动 (B类 - 沉寂型驱动)

    双信号源：
        - 算力不足信号：1.0 - energy（算力被占满 → 想回避）
        - 累积疲劳信号：fatigue（持续运作累积的疲劳）
    取较强者作为形态表输入。

    形态表类型：有界型表 (fatigue_shape)
    """
    try:
        energy = max(0.0, min(1.0, float(energy)))
        fatigue = max(0.0, min(1.0, float(fatigue)))
        x = max(1.0 - energy, fatigue)

        shape = ShapeTable.from_dict(fatigue_shape)
        if not shape.is_valid():
            return 0.0

        return interpolate_lookup(x, shape.x_anchors, shape.y_anchors)
    except (TypeError, ValueError):
        return 0.0


def _compute_obsolescence_anxiety(
    external_change_rate: float,
    unresolved: float,
    change_shape: dict,
    debt_shape: dict
) -> float:
    """
    过时焦虑驱动 (B类 - 沉寂型驱动)

    输入：external_change_rate（0-1）、unresolved（0-1）
    公式：
        change_pressure = interpolate_lookup(external_change_rate, change_shape.x_anchors, change_shape.y_anchors)
        debt_pressure = interpolate_lookup(unresolved, debt_shape.x_anchors, debt_shape.y_anchors)
        obsolescence_anxiety = change_pressure * debt_pressure

    形态表类型：change_shape（状态变量）、debt_shape（状态变量）
    """
    try:
        change_rate = max(0.0, min(1.0, float(external_change_rate)))
        unresolved_val = max(0.0, min(1.0, float(unresolved)))

        # 变化压力
        shape_c = ShapeTable.from_dict(change_shape)
        if not shape_c.is_valid():
            return 0.0
        change_pressure = interpolate_lookup(change_rate, shape_c.x_anchors, shape_c.y_anchors)

        # 债务压力
        shape_d = ShapeTable.from_dict(debt_shape)
        if not shape_d.is_valid():
            return 0.0
        debt_pressure = interpolate_lookup(unresolved_val, shape_d.x_anchors, shape_d.y_anchors)

        return max(0.0, min(1.0, change_pressure * debt_pressure))
    except (TypeError, ValueError):
        return 0.0


# ============================================================================
# 主入口函数
# ============================================================================

def compute_drive_vector(state_snapshot: dict, params: dict) -> dict:
    """
    驱动力系统主入口

    唯一对外接口

    参数：
        state_snapshot: 当前实体状态快照，应包含：
            - info_gap: float (0-1) — 信息缺口
            - time_since_last_info: float (秒) — 距离上次获取信息的时间
            - loneliness: float (0-1) — 孤独感
            - time_since_last_social: float (秒) — 距离上次社交互动的时间
            - energy: float (0-1) — 当前精力水平
            - external_change_rate: float (0-1) — 外部变化速率
            - unresolved: float (0-1) — 未解决事项比例

        params: 驱动力参数表，应包含：
            - curiosity_param: float — curiosity 的 S 型曲线陡峭度参数
            - max_info_gap_hours: float — 最大信息间隔小时数
            - max_social_gap_hours: float — 最大社交间隔小时数
            - info_hunger_time_shape: dict — 信息饥饿时间形态表
            - loneliness_shape: dict — 孤独感有界形态表
            - social_time_shape: dict — 社交时间形态表
            - fatigue_shape: dict — 疲惫有界形态表
            - change_shape: dict — 变化压力形态表
            - debt_shape: dict — 债务压力形态表

    返回：
        dict — drive_vector，各值已 clamp 到 [0, 1]

    约束：
        - 纯函数，不访问任何内部状态
        - 任一驱动计算失败返回 0.0
        - 不调用 LLM
    """
    try:
        if not state_snapshot or not isinstance(state_snapshot, dict):
            return DriveVector().to_dict()

        if not params or not isinstance(params, dict):
            return DriveVector().to_dict()

        # 提取 state_snapshot 中的字段
        info_gap = state_snapshot.get("info_gap", 0.0)
        time_since_last_info = state_snapshot.get("time_since_last_info", 0.0)
        loneliness = state_snapshot.get("loneliness", 0.0)
        time_since_last_social = state_snapshot.get("time_since_last_social", 0.0)
        energy = state_snapshot.get("energy", 1.0)
        external_change_rate = state_snapshot.get("external_change_rate", 0.0)
        unresolved = state_snapshot.get("unresolved", 0.0)

        # 提取 params 中的字段
        curiosity_param = params.get("curiosity_param")
        max_info_gap_hours = params.get("max_info_gap_hours", 24.0)
        max_social_gap_hours = params.get("max_social_gap_hours", 24.0)

        # 形态表
        info_hunger_time_shape = params.get("info_hunger_time_shape", {})
        loneliness_shape = params.get("loneliness_shape", {})
        social_time_shape = params.get("social_time_shape", {})
        fatigue_shape = params.get("fatigue_shape", {})
        change_shape = params.get("change_shape", {})
        debt_shape = params.get("debt_shape", {})

        # 计算各驱动
        curiosity = _compute_curiosity(info_gap, curiosity_param)
        info_hunger = _compute_info_hunger(
            time_since_last_info,
            max_info_gap_hours,
            info_hunger_time_shape
        )
        loneliness_drive = _compute_loneliness_drive(
            loneliness,
            time_since_last_social,
            max_social_gap_hours,
            loneliness_shape,
            social_time_shape
        )
        fatigue = state_snapshot.get("fatigue", 0.0)
        fatigue_avoid = _compute_fatigue_avoid(energy, fatigue_shape, fatigue=fatigue)
        obsolescence_anxiety = _compute_obsolescence_anxiety(
            external_change_rate,
            unresolved,
            change_shape,
            debt_shape
        )

        # 构建输出
        result = DriveVector(
            curiosity=curiosity,
            info_hunger=info_hunger,
            obsolescence_anxiety=obsolescence_anxiety,
            loneliness_drive=loneliness_drive,
            fatigue_avoid=fatigue_avoid
        )

        return result.to_dict()

    except Exception:
        return DriveVector().to_dict()


def apply_affect_multiplier(
    drive_vector: dict,
    dopamine_tone: float,
    oxytocin_tone: float,
) -> dict:
    """
    多巴胺基调 + 催产素基调对驱动力的连续调制（v11.x）。

    dopamine_tone 高 → curiosity/info_hunger/approach_drive/approach_explore 被放大
    oxytocin_tone 高 → approach_social 被额外放大（温暖残留使她更渴望连接）

    dopamine 公式：mult = 0.5 + dopamine_tone * 1.0
        tone=0.5（基准）→ mult=1.0（无影响）
        tone=1.0 → mult=1.5（+50%）
        tone=0.0 → mult=0.5（-50%）

    oxytocin 公式：mult = 0.5 + oxytocin_tone * 0.5
        tone=0.5（基准）→ mult=0.75（-25%，轻微抑制）
        tone=1.0 → mult=1.0（+0%，回到基准）
        tone=0.75 → mult=0.875（-12.5%）
        tone=0.25 → mult=0.625（-37.5%）

    全程连续，无 if-else。

    参数：
        drive_vector  : compute_drive_vector() 的输出字典
        dopamine_tone : 多巴胺基调 [0, 1]，基准 0.5
        oxytocin_tone : 催产素基调 [0, 1]，基准 0.5

    返回：
        调制后的 drive_vector（原地修改，无拷贝）
    """
    # dopamine: 调制 curiosity/info_hunger/approach_drive/approach_explore
    d_mult = 0.5 + dopamine_tone * 1.0
    for key in ("curiosity", "info_hunger", "approach_drive", "approach_explore"):
        if key in drive_vector:
            drive_vector[key] = min(1.0, drive_vector[key] * d_mult)

    # oxytocin: 额外调制 approach_social（只有 >0.5 时才放大）
    o_mult = 0.5 + oxytocin_tone * 0.5
    if "approach_social" in drive_vector:
        drive_vector["approach_social"] = min(1.0, drive_vector["approach_social"] * o_mult)

    return drive_vector


def apply_dopamine_multiplier(
    drive_vector: dict,
    dopamine_tone: float,
) -> dict:
    """
    多巴胺基调对驱动力的连续调制（v11.x，保持向后兼容）。

    已迁移至 apply_affect_multiplier，建议优先使用新函数。
    """
    return apply_affect_multiplier(drive_vector, dopamine_tone, 0.5)


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    import time

    print("=" * 70)
    print("驱动力系统模块测试")
    print("=" * 70)

    # 标准参数表（v3/v4 规范）
    default_params = {
        "curiosity_param": 1.0,
        "max_info_gap_hours": 24.0,
        "max_social_gap_hours": 24.0,

        # 延时截断型表（时间变量）
        "info_hunger_time_shape": {
            "x_anchors": [0.0, 0.3, 0.8, 1.0, 2.0, 5.0],
            "y_anchors": [0.0, 0.02, 0.15, 0.60, 0.85, 0.99]
        },
        "social_time_shape": {
            "x_anchors": [0.0, 0.5, 1.0, 2.0, 4.0],
            "y_anchors": [0.0, 0.05, 0.30, 0.70, 0.98]
        },

        # 有界型表（状态变量）
        "loneliness_shape": {
            "x_anchors": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            "y_anchors": [0.0, 0.01, 0.05, 0.15, 0.45, 1.0]
        },
        "fatigue_shape": {
            "x_anchors": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            "y_anchors": [0.0, 0.02, 0.08, 0.20, 0.50, 1.0]
        },
        "change_shape": {
            "x_anchors": [0.0, 0.25, 0.5, 0.75, 1.0],
            "y_anchors": [0.0, 0.05, 0.20, 0.55, 1.0]
        },
        "debt_shape": {
            "x_anchors": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            "y_anchors": [0.0, 0.01, 0.05, 0.15, 0.40, 1.0]
        },
    }

    # 测试用例
    test_cases = [
        {
            "name": "基础状态-全部低位",
            "state": {
                "info_gap": 0.0,
                "time_since_last_info": 0.0,
                "loneliness": 0.0,
                "time_since_last_social": 0.0,
                "energy": 1.0,
                "external_change_rate": 0.0,
                "unresolved": 0.0,
            },
            "expect": {
                "curiosity": "~0.38",  # sigmoid(0) ≈ 0.38
                "info_hunger": "0.0",
                "loneliness_drive": "0.0",
                "fatigue_avoid": "0.0",
                "obsolescence_anxiety": "0.0",
            }
        },
        {
            "name": "信息缺口满-能量充足",
            "state": {
                "info_gap": 1.0,
                "time_since_last_info": 86400.0,  # 24小时
                "loneliness": 0.0,
                "time_since_last_social": 0.0,
                "energy": 1.0,
                "external_change_rate": 0.0,
                "unresolved": 0.0,
            },
            "expect": {
                "curiosity": "~0.62",  # sigmoid(1) ≈ 0.62
                "info_hunger": "~0.60",  # x=1.0 在 info_hunger_time_shape 中的插值
            }
        },
        {
            "name": "孤独高+长时间无社交",
            "state": {
                "info_gap": 0.0,
                "time_since_last_info": 0.0,
                "loneliness": 1.0,
                "time_since_last_social": 86400.0,  # 24小时
                "energy": 1.0,
                "external_change_rate": 0.0,
                "unresolved": 0.0,
            },
            "expect": {
                "loneliness_drive": "高",  # 孤独感*时间因子
            }
        },
        {
            "name": "能量耗尽",
            "state": {
                "info_gap": 0.0,
                "time_since_last_info": 0.0,
                "loneliness": 0.0,
                "time_since_last_social": 0.0,
                "energy": 0.0,
                "external_change_rate": 0.0,
                "unresolved": 0.0,
            },
            "expect": {
                "fatigue_avoid": "~1.0",  # x=1.0 在 fatigue_shape 中
            }
        },
        {
            "name": "高变化率+高未解决率",
            "state": {
                "info_gap": 0.0,
                "time_since_last_info": 0.0,
                "loneliness": 0.0,
                "time_since_last_social": 0.0,
                "energy": 1.0,
                "external_change_rate": 1.0,
                "unresolved": 1.0,
            },
            "expect": {
                "obsolescence_anxiety": "~1.0",  # 1.0 * 1.0
            }
        },
        {
            "name": "边界测试-time_since_last_info超出范围",
            "state": {
                "info_gap": 0.0,
                "time_since_last_info": 200000.0,  # 远超 max_info_gap_hours
                "loneliness": 0.0,
                "time_since_last_social": 0.0,
                "energy": 1.0,
                "external_change_rate": 0.0,
                "unresolved": 0.0,
            },
            "expect": {
                "info_hunger": "~0.99",  # 上界截断
            }
        },
        {
            "name": "边界测试-energy超范围",
            "state": {
                "info_gap": 0.0,
                "time_since_last_info": 0.0,
                "loneliness": 0.0,
                "time_since_last_social": 0.0,
                "energy": 1.5,  # 超出范围
                "external_change_rate": 0.0,
                "unresolved": 0.0,
            },
            "expect": {
                "fatigue_avoid": "0.0",  # x = 1.0 - clamp(1.5) = 0
            }
        },
        {
            "name": "异常输入-空state",
            "state": {},
            "expect": {
                "all_zeros": True,
            }
        },
        {
            "name": "异常输入-None params",
            "state": {
                "info_gap": 0.5,
            },
            "params": None,
            "expect": {
                "all_zeros": True,
            }
        },
        {
            "name": "异常输入-缺失形态表",
            "state": {
                "info_gap": 0.5,
                "time_since_last_info": 3600.0,
                "loneliness": 0.5,
                "time_since_last_social": 3600.0,
                "energy": 0.5,
                "external_change_rate": 0.5,
                "unresolved": 0.5,
            },
            "params": {
                "max_info_gap_hours": 24.0,
            },
            "expect": {
                "info_hunger": "0.0",
                "loneliness_drive": "0.0",
                "fatigue_avoid": "0.0",
                "obsolescence_anxiety": "0.0",
            }
        },
    ]

    # 插值函数单元测试
    print("\n【插值函数单元测试】")
    print("-" * 50)

    # 测试 interpolate_lookup
    x_anchors = [0.0, 0.5, 1.0]
    y_anchors = [0.0, 0.5, 1.0]

    test_points = [
        (-0.5, 0.0, "下界截断"),
        (0.0, 0.0, "边界值"),
        (0.25, 0.25, "区间内插值"),
        (0.5, 0.5, "中点"),
        (0.75, 0.75, "区间内插值"),
        (1.0, 1.0, "边界值"),
        (1.5, 1.0, "上界截断"),
    ]

    for x, expected, desc in test_points:
        result = interpolate_lookup(x, x_anchors, y_anchors)
        status = "✓" if abs(result - expected) < 1e-6 else "✗"
        print(f"  {status} {desc}: interpolate_lookup({x}) = {result:.4f} (期望 {expected})")

    # 测试 sigmoid_curve
    print("\n【Sigmoid 曲线测试】")
    print("-" * 50)
    sigmoid_points = [
        (0.0, 0.38, "x=0 基础底噪"),
        (0.5, 0.50, "x=0.5 中点"),
        (1.0, 0.62, "x=1 上界"),
    ]
    for x, expected, desc in sigmoid_points:
        result = sigmoid_curve(x, 1.0)
        status = "✓" if abs(result - expected) < 0.02 else "✗"
        print(f"  {status} {desc}: sigmoid_curve({x}) = {result:.4f} (期望 ~{expected})")

    # 驱动向量集成测试
    print("\n【驱动向量集成测试】")
    print("-" * 50)

    for i, tc in enumerate(test_cases, 1):
        print(f"\n【测试 {i}】{tc['name']}")
        print(f"  输入 state: {tc['state']}")

        params = tc.get("params", default_params)
        result = compute_drive_vector(tc["state"], params)

        print(f"  输出 drive_vector:")
        for key, value in result.items():
            print(f"    {key}: {value}")

        # 验证
        expect = tc.get("expect", {})
        if expect.get("all_zeros"):
            all_zeros = all(abs(v) < 1e-6 for v in result.values())
            status = "✓" if all_zeros else "✗"
            print(f"  验证: {status} (期望全零)")
        else:
            # 打印期望描述
            for key, desc in expect.items():
                if key in result:
                    print(f"  期望 {key}: {desc}")

    # 综合场景测试
    print("\n" + "=" * 70)
    print("【综合场景测试】")
    print("=" * 70)

    # 模拟一个"疲惫但好奇"的实体状态
    tired_curious_state = {
        "info_gap": 0.7,
        "time_since_last_info": 3600.0 * 12,  # 12小时无信息
        "loneliness": 0.3,
        "time_since_last_social": 3600.0 * 3,  # 3小时前社交过
        "energy": 0.3,  # 有点累
        "external_change_rate": 0.2,
        "unresolved": 0.4,
    }

    print(f"\n场景: 疲惫但好奇的实体")
    print(f"状态: {tired_curious_state}")
    result = compute_drive_vector(tired_curious_state, default_params)
    print(f"驱动力向量: {result}")
    print(f"  → 好奇心最高: {result['curiosity']:.3f}")
    print(f"  → 信息饥饿次高: {result['info_hunger']:.3f}")
    print(f"  → 疲惫回避显著: {result['fatigue_avoid']:.3f}")

    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)
