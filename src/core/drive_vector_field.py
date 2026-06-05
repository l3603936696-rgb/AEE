"""
DriveVectorField — 驱动力场（拮抗 + 连续质变版）

从文档「拮抗力 + 连续质变」改造而来。

设计原则：
    - 驱动力不再做 argmax，所有维度完整保留
    - 拮抗矩阵决定量的相互抑制
    - 连续质变输出 fragmentation，让行为有质地而非硬切换
    - rule.effect 完全内生（从历史 snapshots 归纳，不是人工预设）

命名策略（状态层而非行为层）：
    用 EntityCore 的实际状态变量作为 raw_drives 的维度，
    避免行为层命名（sleep/explore/connect）与现有架构冲突。
    最终行为质地由 LLM 从 behavior_vector 推导。

对外接口：
    compute_drive_field(entity_core, drive_vector, antagonism_matrix, alpha_k)
        → DriveFieldResult（含 raw_drives / net_drives / alpha / behavior_vector）
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ============================================================================
# 驱动力维度（状态层，7维）
# ============================================================================
#
# 每个维度对应 EntityCore 或 v1 输出中的状态变量。
# 对外暴露的 raw_drives 是归一化 [0, 1] 值。

DRIVE_DIMS: List[str] = [
    "curiosity",        # 好奇心（被疲惫/危险抑制）
    "info_hunger",      # 信息饥饿（被疲惫/危险抑制）
    "loneliness",       # 孤独感（疲惫时减弱）
    "fatigue",          # 疲惫感（抑制所有主动行为）
    "unresolved",       # 未闭合事项（疲惫/危险时减弱）
    "somatic_tone_p",  # 正向躯体基调（[-1,1] → [0,1]）
    "danger",           # 危险感（抑制探索）
]


def _raw_drives_from_entity(entity_core) -> Dict[str, float]:
    """
    从 EntityCore 提取 raw_drives。
    每个维度归一化到 [0, 1]。
    """
    tone = getattr(entity_core, "somatic_tone", 0.0)
    return {
        "curiosity":       max(0.0, min(1.0, getattr(entity_core, "curiosity",       0.0))),
        "info_hunger":     max(0.0, min(1.0, getattr(entity_core, "info_hunger",     0.0))),
        "loneliness":     max(0.0, min(1.0, getattr(entity_core, "loneliness",     0.0))),
        "fatigue":        max(0.0, min(1.0, getattr(entity_core, "fatigue",          0.0))),
        "unresolved":     max(0.0, min(1.0, getattr(entity_core, "unresolved",     0.0))),
        "somatic_tone_p": max(0.0, min(1.0, (tone + 1.0) / 2.0)),  # [-1,1] → [0,1]
        "danger":         max(0.0, min(1.0, getattr(entity_core, "danger_level",    0.0))),
    }


def _drives_from_v1(drive_vector: Dict[str, float]) -> Dict[str, float]:
    """
    将 v1 的 drive_vector 字段名映射为 V6 的 raw_drives 字段名（1:1）。

    v1 字段名 → V6 字段名（直接对应，无合并）：
        curiosity             → curiosity
        info_hunger           → info_hunger
        loneliness_drive      → loneliness
        fatigue_avoid         → fatigue
        obsolescence_anxiety  → danger
        unresolved_pressure   → unresolved
        somatic_tone          → somatic_tone_p（[-1,1] → [0,1]）

    若 v1 字段缺失某 key，用 0.0 填充（等效于"无此驱动力"）。
    """
    return {
        "curiosity":       max(0.0, min(1.0, float(drive_vector.get("curiosity",             0.0)))),
        "info_hunger":     max(0.0, min(1.0, float(drive_vector.get("info_hunger",           0.0)))),
        "loneliness":     max(0.0, min(1.0, float(drive_vector.get("loneliness_drive",      0.0)))),
        "fatigue":        max(0.0, min(1.0, float(drive_vector.get("fatigue_avoid",          0.0)))),
        "unresolved":     max(0.0, min(1.0, float(drive_vector.get("unresolved_pressure",    0.0)))),
        "somatic_tone_p": max(0.0, min(1.0, (float(drive_vector.get("somatic_tone", 0.0)) + 1.0) / 2.0)),
        "danger":         max(0.0, min(1.0, float(drive_vector.get("obsolescence_anxiety",    0.0)))),
    }


# ============================================================================
# 拮抗矩阵（7×7）
# ============================================================================
#
# antagonism_matrix[src][dst] = src 对 dst 的抑制权重 [0, 1]
# 含义：src 越强，对 dst 的抑制越强
#
# 初始默认值暂由工程师拍定，后续改为从经验 snapshots 自动归纳。
#
# 设计逻辑（初版）：
#   - fatigue（疲惫）是最大的抑制源：高疲惫时抑制所有主动行为
#   - danger（危险感）抑制探索和信息追求
#   - somatic_tone_p（正向情绪）抑制 danger 和 fatigue 的效果
#   - curiosity 和 info_hunger 相互轻度竞争（注意力竞争）
#   - loneliness 轻度抑制 info_hunger（孤独时更想要陪伴而非信息）
#
# 注意：当前为工程师硬编码，经验学习机制待实现。

DEFAULT_ANTAGONISM_MATRIX: Dict[str, Dict[str, float]] = {
    "curiosity": {
        "info_hunger":    0.20,   # 好奇心和信息饥饿争夺注意力
        "loneliness":     0.00,
        "fatigue":        0.15,   # 好奇心轻微掩盖疲劳感，但不能真正消除
        "unresolved":     0.15,
        "somatic_tone_p": 0.00,
        "danger":         0.40,   # 危险时抑制探索
    },
    "info_hunger": {
        "curiosity":      0.20,
        "loneliness":     0.15,   # 孤独时更想要陪伴而非信息
        "fatigue":        0.15,   # 信息饥饿轻微掩盖疲劳感，但不能真正消除
        "unresolved":     0.15,
        "somatic_tone_p": 0.00,
        "danger":         0.35,   # 危险时减少信息搜索
    },
    "loneliness": {
        "curiosity":      0.10,
        "info_hunger":    0.20,
        "fatigue":        0.15,   # 孤独感轻微掩盖疲劳感，但不能真正消除
        "unresolved":     0.10,
        "somatic_tone_p": 0.00,
        "danger":         0.00,
    },
    "fatigue": {
        "curiosity":      0.70,   # 非对称：累到极限时好奇心说了不算
        "info_hunger":    0.70,   # 非对称：累到极限时信息饥饿也压不过疲惫
        "loneliness":     0.60,
        "unresolved":     0.50,
        "somatic_tone_p": 0.30,  # 累了时正向情绪效果打折
        "danger":         0.25,
    },
    "unresolved": {
        "curiosity":      0.10,
        "info_hunger":    0.10,
        "loneliness":     0.10,
        "fatigue":        0.10,   # 未解决事项轻微掩盖疲劳感
        "somatic_tone_p": 0.00,
        "danger":         0.20,   # 危险时暂时搁置问题
    },
    "somatic_tone_p": {
        "curiosity":      0.00,
        "info_hunger":    0.00,
        "loneliness":     0.00,
        "fatigue":        0.20,  # 感觉好时疲惫感被抑制
        "unresolved":     0.00,
        "danger":         0.35,  # 心情好时不容易感到危险
    },
    "danger": {
        "curiosity":      0.40,
        "info_hunger":    0.35,
        "loneliness":     0.15,
        "fatigue":        0.00,
        "unresolved":     0.20,
        "somatic_tone_p": 0.35,  # 心情好时不容易感到危险（正向情绪抑制危险感）
    },
}


# ============================================================================
# alpha_k 个体化参数（连续质变平滑参数）
# ============================================================================
#
# alpha_k[src][dst] 控制 src 对 dst 的质变 sigmoid 平滑度。
# k 越大，质变越陡峭（接近阈值触发）；k 越小，质变越平滑。
#
# 初始全为 1.0（标准 sigmoid）。
# 通过经验学习可差异化：保守个体 k 高，灵活个体 k 低。

DEFAULT_ALPHA_K: Dict[str, Dict[str, float]] = {
    src: {dst: 1.0 for dst in DEFAULT_ANTAGONISM_MATRIX.get(src, {})}
    for src in DRIVE_DIMS
}


# ============================================================================
# 辅助函数
# ============================================================================

def _sigmoid(x: float) -> float:
    """标准 sigmoid，输出 [0, 1]."""
    if x > 700:
        return 1.0
    if x < -700:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _sigmoid_k(x: float, k: float) -> float:
    """带陡峭度参数的 sigmoid."""
    return _sigmoid(k * x)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# ============================================================================
# Step 2: 计算净力向量
# ============================================================================

def compute_net_drives(
    raw_drives: Dict[str, float],
    antagonism_matrix: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, float]:
    """
    计算每个驱动力的净力（指数衰减抑制）。

    net[dst] = raw[dst] * exp(-Σ(src ≠ dst) raw[src] * weight[src][dst])

    指数衰减保证：
        - 信号被削弱但永远不会清零
        - 多源叠加是连续递减，不会断崖归零
        - 强信号在同等抑制下存活率更高

    参数：
        raw_drives: raw_drives 字典
        antagonism_matrix: 拮抗矩阵，默认使用 DEFAULT_ANTAGONISM_MATRIX

    返回：
        net_drives 字典，各值 clamp 到 [0, 1]
    """
    if antagonism_matrix is None:
        antagonism_matrix = DEFAULT_ANTAGONISM_MATRIX

    net_drives: Dict[str, float] = {}

    for dst in DRIVE_DIMS:
        raw_dst = raw_drives.get(dst, 0.0)
        inhibition_sum = 0.0

        for src in DRIVE_DIMS:
            if src == dst:
                continue
            raw_src = raw_drives.get(src, 0.0)
            weight = antagonism_matrix.get(src, {}).get(dst, 0.0)
            inhibition_sum += raw_src * weight

        net = raw_dst * math.exp(-inhibition_sum)
        net_drives[dst] = _clamp(net, 0.0, 1.0)

    return net_drives


# ============================================================================
# Step 3: 连续质变（force deformation）
# ============================================================================

def compute_fragmentation_coefficients(
    raw_drives: Dict[str, float],
    antagonism_matrix: Optional[Dict[str, Dict[str, float]]] = None,
    alpha_k: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, float]:
    """
    对每个驱动力计算其质变系数 alpha（0=纯粹，1=高度变形）。

    alpha[dst] = clamp(
        Σ(src≠dst) sigmoid(k[src][dst] * raw[src] * weight[src][dst]) * raw[src]
        / max(1, Σ(src≠dst) raw[src])
        , 0, 1)

    用源的强度做加权平均，避免 alpha 超过 1.0，也避免所有源等权导致
    少数强源被多数弱源稀释的问题。
    """
    if antagonism_matrix is None:
        antagonism_matrix = DEFAULT_ANTAGONISM_MATRIX
    if alpha_k is None:
        alpha_k = DEFAULT_ALPHA_K

    alpha: Dict[str, float] = {}

    for dst in DRIVE_DIMS:
        weighted_sum = 0.0
        total_weight = 0.0

        for src in DRIVE_DIMS:
            if src == dst:
                continue
            raw_src = raw_drives.get(src, 0.0)
            if raw_src <= 0.0:
                continue
            weight = antagonism_matrix.get(src, {}).get(dst, 0.0)
            k = alpha_k.get(src, {}).get(dst, 1.0)
            contrib = _sigmoid_k(raw_src * weight, k)
            weighted_sum += contrib * raw_src
            total_weight += raw_src

        if total_weight > 1e-9:
            alpha[dst] = _clamp(weighted_sum / total_weight, 0.0, 1.0)
        else:
            alpha[dst] = 0.0

    return alpha


def compute_behavior_vector(
    raw_drives: Dict[str, float],
    net_drives: Dict[str, float],
    alpha: Dict[str, float],
) -> Dict[str, float]:
    """
    从 raw_drives / net_drives / alpha 生成 behavior_vector。

    behavior_vector[dst_intensity]     = net[dst] * (1 - alpha²)
    behavior_vector[dst_fragmentation] = net[dst] * alpha²

    - intensity：高 → 行为清晰、连贯
    - fragmentation：高 → 行为被其他力撕扯，断断续续

    用 alpha² 代替 alpha 避免 alpha=1.0 时 intensity 塌陷为 0。
    """
    bv: Dict[str, float] = {}

    for dst in DRIVE_DIMS:
        net = net_drives.get(dst, 0.0)
        a = alpha.get(dst, 0.0)
        a_sq = a * a

        bv[f"{dst}_intensity"]     = net * (1.0 - a_sq)
        bv[f"{dst}_fragmentation"] = net * a_sq

    return bv


# ============================================================================
# 合并版主函数
# ============================================================================

def compute_drive_field(
    entity_core,
    drive_vector: Optional[Dict[str, float]] = None,
    antagonism_matrix: Optional[Dict[str, Dict[str, float]]] = None,
    alpha_k: Optional[Dict[str, Dict[str, float]]] = None,
) -> "DriveFieldResult":
    """
    驱动力场主入口。

    参数：
        entity_core: EntityCore 实例
        drive_vector: 可选，来自 v1 的驱动力向量 dict。
                      若传入，拮抗矩阵作用于 v1 的输出；
                      否则从 entity_core 原始状态提取（向后兼容）。
        antagonism_matrix: 可选，自定义拮抗矩阵（个体化）
        alpha_k: 可选，个体化 sigmoid 陡峭度参数

    返回：
        DriveFieldResult（dataclass）
    """
    if drive_vector is not None:
        raw_drives = _drives_from_v1(drive_vector)
    else:
        raw_drives = _raw_drives_from_entity(entity_core)
    net_drives  = compute_net_drives(raw_drives, antagonism_matrix)
    alpha       = compute_fragmentation_coefficients(raw_drives, antagonism_matrix, alpha_k)
    bv          = compute_behavior_vector(raw_drives, net_drives, alpha)

    return DriveFieldResult(
        raw_drives=raw_drives,
        net_drives=net_drives,
        alpha=alpha,
        behavior_vector=bv,
        antagonism_matrix=antagonism_matrix or DEFAULT_ANTAGONISM_MATRIX,
        alpha_k=alpha_k or DEFAULT_ALPHA_K,
    )


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class DriveFieldResult:
    """驱动力场的完整计算结果（7维）."""
    raw_drives:       Dict[str, float]           # 7个原始驱动力
    net_drives:      Dict[str, float]           # 拮抗后净力（7维）
    alpha:            Dict[str, float]           # 质变系数（fragmentation 强度，7维）
    behavior_vector:  Dict[str, float]           # {dim_intensity, dim_fragmentation}（14个key）
    antagonism_matrix: Dict[str, Dict[str, float]]  # 7×7 拮抗矩阵
    alpha_k:          Dict[str, Dict[str, float]]  # 个体化 sigmoid 陡峭度

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_drives":      {k: round(v, 4) for k, v in self.raw_drives.items()},
            "net_drives":      {k: round(v, 4) for k, v in self.net_drives.items()},
            "alpha":           {k: round(v, 4) for k, v in self.alpha.items()},
            "behavior_vector": {k: round(v, 4) for k, v in self.behavior_vector.items()},
        }

    def dominant_dim(self) -> str:
        """净力最大的维度."""
        return max(self.net_drives, key=lambda k: self.net_drives[k])

    def tension_level(self) -> float:
        """拮抗张力：净力分布的均衡程度 [0,1]，1=完全均衡."""
        vals = list(self.net_drives.values())
        if not vals:
            return 0.0
        total = sum(vals) + 1e-9
        max_v = max(vals)
        second_v = sorted(vals, reverse=True)[1] if len(vals) > 1 else 0.0
        # 差越小，张力越高
        return 1.0 - abs(max_v - second_v) / total


# ============================================================================
# 日志（供调试和可解释性）
# ============================================================================

def format_drive_field_log(result: DriveFieldResult, tick: int = 0) -> str:
    """生成单行日志，便于追踪."""
    dom = result.dominant_dim()
    tens = result.tension_level()
    lines = [
        f"[Tick {tick}] DriveField (7维)",
        f"  raw:    " + "  ".join(f"{k}={v:.3f}" for k, v in result.raw_drives.items()),
        f"  net:    " + "  ".join(f"{k}={v:.3f}" for k, v in result.net_drives.items()),
        f"  alpha:  " + "  ".join(f"{k}={v:.3f}" for k, v in result.alpha.items()),
        f"  BV:     " + "  ".join(f"{k}={v:.3f}" for k, v in result.behavior_vector.items()),
        f"  dominant={dom}  tension={tens:.3f}",
    ]
    return "\n".join(lines)


# ============================================================================
# 单元测试
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("DriveVectorField — 单元测试（7维版）")
    print("=" * 60)

    class _MockEntity:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    test_cases = [
        {
            "name": "全部低位",
            "entity": _MockEntity(
                curiosity=0.0, info_hunger=0.0, loneliness=0.1, fatigue=0.0,
                unresolved=0.0, somatic_tone=0.2, danger_level=0.0,
            ),
            "expect_dom": "somatic_tone_p",
        },
        {
            "name": "高疲惫压制一切",
            "entity": _MockEntity(
                curiosity=0.9, info_hunger=0.9, loneliness=0.9, fatigue=0.9,
                unresolved=0.9, somatic_tone=0.5, danger_level=0.0,
            ),
            "expect_dom": "somatic_tone_p",
        },
        {
            "name": "孤独感主导（疲惫低时）",
            "entity": _MockEntity(
                curiosity=0.3, info_hunger=0.1, loneliness=0.9, fatigue=0.1,
                unresolved=0.2, somatic_tone=0.0, danger_level=0.0,
            ),
            "expect_dom": "loneliness",
        },
        {
            "name": "好奇心主导（无危险感）",
            "entity": _MockEntity(
                curiosity=0.9, info_hunger=0.3, loneliness=0.2, fatigue=0.1,
                unresolved=0.2, somatic_tone=0.0, danger_level=0.0,
            ),
            "expect_dom": "curiosity",
        },
        {
            "name": "危险感压制探索（7维独立）",
            "entity": _MockEntity(
                curiosity=0.9, info_hunger=0.9, loneliness=0.3, fatigue=0.2,
                unresolved=0.5, somatic_tone=0.0, danger_level=0.9,
            ),
            "expect_dom": "info_hunger",  # danger被somatic_tone_p抑制(0.9*0.35=0.315→net=0.365)，info_hunger被danger抑制(0.9*0.35=0.315→net=0.295)，两者接近，info_hunger胜
        },
        {
            "name": "正向情绪提升整体",
            "entity": _MockEntity(
                curiosity=0.5, info_hunger=0.5, loneliness=0.5, fatigue=0.5,
                unresolved=0.5, somatic_tone=0.8, danger_level=0.5,
            ),
            "expect_dom": "somatic_tone_p",
        },
    ]

    for i, tc in enumerate(test_cases, 1):
        result = compute_drive_field(tc["entity"])
        dom = result.dominant_dim()

        print(f"\n【{i}】{tc['name']}")
        print(f"  raw_drives: {result.raw_drives}")
        print(f"  net_drives: {result.net_drives}")
        print(f"  alpha:      {result.alpha}")
        print(f"  dominant: {dom}  tension: {result.tension_level():.3f}")

        ok = dom == tc["expect_dom"]
        print(f"  → {'✓' if ok else '✗ expected ' + tc['expect_dom']}")

        # 验证约束
        for k, v in result.behavior_vector.items():
            assert 0.0 <= v <= 1.0, f"Behavior vector out of range: {k}={v}"
        for k, v in result.net_drives.items():
            assert 0.0 <= v <= 1.0, f"Net drives out of range: {k}={v}"
        for k, v in result.alpha.items():
            assert 0.0 <= v <= 1.0, f"Alpha out of range: {k}={v}"

    # v1 映射测试
    print("\n【v1 映射】")
    v1_dv = {
        "curiosity": 0.8, "info_hunger": 0.5,
        "loneliness_drive": 0.9, "fatigue_avoid": 0.3,
        "unresolved_pressure": 0.1, "somatic_tone": 0.4,
        "obsolescence_anxiety": 0.0,
    }
    r = compute_drive_field(_MockEntity(), drive_vector=v1_dv)
    print(f"  raw_drives: {r.raw_drives}")
    print(f"  net_drives: {r.net_drives}")
    print(f"  dominant: {r.dominant_dim()}")
    assert r.raw_drives["curiosity"] == 0.8
    assert r.raw_drives["info_hunger"] == 0.5
    assert r.raw_drives["loneliness"] == 0.9
    assert r.raw_drives["fatigue"] == 0.3
    print("  ✓ 映射正确")

    # 极端输入
    entity_extreme = _MockEntity(
        curiosity=1.0, info_hunger=1.0, loneliness=1.0, fatigue=1.0,
        unresolved=1.0, somatic_tone=1.0, danger_level=1.0,
    )
    result_extreme = compute_drive_field(entity_extreme)
    print(f"\n【极端输入】全部=1.0")
    print(f"  net_drives: {result_extreme.net_drives}")
    print(f"  all >= 0: {all(v >= 0 for v in result_extreme.net_drives.values())}")
    print(f"  log:\n{format_drive_field_log(result_extreme, tick=999)}")

    print("\n" + "=" * 60)
    print("测试完成 ✓")
    print("=" * 60)
