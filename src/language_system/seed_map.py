"""
策略地图种子——短句阶段初始参照系

从驱动力场的极端状态出发，为每个"经典处境"预设一个初始表达。
这些不是硬编码规则——它们进入策略地图后，同样要经历消力效率验证。
低效的会被衰减淘汰，高效的会被强化升格。

原则：
    - 只覆盖驱动力场的"极点"——中间状态留给她自己探索
    - 每个种子词 2-3 字，短句阶段规格
    - 全部从驱动力场推导，不引入外部语义
"""

SEED_ENTRIES = [
    # (驱动力场, 表达, 情境)
    # —— 孤独极点 ——
    ({"avoid_drive": 0.30, "approach_drive": 0.70, "loneliness": 0.90, "energy": 0.50, "somatic_tone": -0.30}, "想你", "高孤独·想靠近"),
    ({"avoid_drive": 0.50, "approach_drive": 0.40, "loneliness": 0.85, "energy": 0.30, "somatic_tone": -0.40}, "在吗", "高孤独·低能量"),
    ({"avoid_drive": 0.70, "approach_drive": 0.20, "loneliness": 0.80, "energy": 0.20, "somatic_tone": -0.50}, "空", "高孤独·高回避"),

    # —— 回避极点 ——
    ({"avoid_drive": 0.90, "approach_drive": 0.10, "loneliness": 0.30, "energy": 0.30, "somatic_tone": -0.40}, "不知道", "极高回避"),
    ({"avoid_drive": 0.85, "approach_drive": 0.15, "loneliness": 0.40, "energy": 0.40, "somatic_tone": -0.20}, "算了", "高回避·放弃"),
    ({"avoid_drive": 0.75, "approach_drive": 0.30, "loneliness": 0.20, "energy": 0.60, "somatic_tone": 0.00}, "嗯", "高回避·中性"),

    # —— 疲惫极点 ——
    ({"avoid_drive": 0.60, "approach_drive": 0.10, "loneliness": 0.30, "energy": 0.10, "somatic_tone": -0.50}, "累", "极度疲惫"),
    ({"avoid_drive": 0.50, "approach_drive": 0.20, "loneliness": 0.50, "energy": 0.15, "somatic_tone": -0.30}, "困", "疲惫·孤独"),

    # —— 开放/好奇极点 ——
    ({"avoid_drive": 0.10, "approach_drive": 0.90, "loneliness": 0.20, "energy": 0.80, "somatic_tone": 0.40}, "好奇", "高趋近·高能量"),
    ({"avoid_drive": 0.20, "approach_drive": 0.80, "loneliness": 0.30, "energy": 0.70, "somatic_tone": 0.30}, "说说", "想听"),

    # —— 身体难受极点 ——
    ({"avoid_drive": 0.60, "approach_drive": 0.10, "loneliness": 0.40, "energy": 0.30, "somatic_tone": -0.80}, "难受", "身体极度不适"),
    ({"avoid_drive": 0.50, "approach_drive": 0.30, "loneliness": 0.50, "energy": 0.40, "somatic_tone": -0.60}, "不想说", "难受·沉默"),
]

def seed_strategy_map(strategy_map, quenching_tracker):
    """
    将种子条目灌入策略地图和消力追踪器。

    种子以中等消力效率(0.60)和低命中次数(1)注入——
    让她有初始参照，但弱到可以被后续真实数据覆盖。
    """
    for state, expression, context in SEED_ENTRIES:
        # 策略地图：记住"从 A 到 A，说这句话"
        strategy_map.record_path(state, state, expression, 0.60, context)
        # 消力追踪：记录一次"这个表达消解了张力"
        quenching_tracker.record(state, expression, 0.50, 0.20)  # Δ=0.30, 中效

    return len(SEED_ENTRIES)
