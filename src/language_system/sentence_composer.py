"""
Sentence Composer — 句子组合模块（v1.0）

将锚点词组合成完整中文短句的模板库 + softmax 采样系统。

设计原则：
    1. 全部连续：无 if-else，无比较运算符（> < >= <=）
    2. 模板通过连续函数（exp / max / 1-x）计算状态匹配度
    3. softmax 随机采样，不是取最高分——保持表达多样性
    4. 语气自然口语化，有余韵（"……" "啊" "呢" 等）

注意：部分模板不包含 {anchor} 槽（如"好想有人陪我说说话啊……"、"还好吧……"），
这些模板完全独立描述状态，传入的 anchor 参数被忽略。这是合理的设计，
这些模板本身就是完整句式，不依赖锚点词。

调用示例：
    from .sentence_composer import compose_sentence, PATTERNS
    sentence = compose_sentence("累", state_dict, connector="唉")
"""

import logging
import math
import random
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# 模板库
# ============================================================================

PATTERNS: List[Dict] = []


def _g(x: float, mu: float, sigma: float = 0.20) -> float:
    """高斯评分：x 越接近 mu 得分越高。返回 (0, 1]。"""
    return math.exp(-0.5 * (abs(x - mu) / max(sigma, 0.001)) ** 2)


def _anchor_penalty(anchor_len: int, pos: str) -> float:
    """
    锚词语法不兼容惩罚（加法偏移，不是乘法）。
    返回值从 raw_score 中减去，在 softmax 之前生效。

    pos="tail" 且 len=1 → 减 5.0（softmax 里 exp(-5/0.4) ≈ 0，基本不可能）
    pos="tail" 且 len=2 → 减 1.0（显著降低但不禁止）
    pos="tail" 且 len>=3 → 减 0（自然，不惩罚）
    其他位置 → 减 0
    """
    if pos != "tail":
        return 0.0
    # len=1→5.0, len=2→1.0, len=3→0.1, len>=4→0.0
    return max(0.0, 5.0 * math.exp(-1.6 * max(0, anchor_len - 1)))


# ─────────────────────────────────────────────────────────────────────────────
# 1. 高疲劳（累、乏、困）
# ─────────────────────────────────────────────────────────────────────────────

PATTERNS += [
    {
        "template": "好{anchor}啊……",
        "score_fn": lambda s: (
            s.get("fatigue", 0.0) * 0.6
            + s.get("joy", 0.0) * 0.1
        ),
        "use_connector": True,
        "anchor_pos": "adj",
    },
    {
        "template": "有点{anchor}了……",
        "score_fn": lambda s: (
            s.get("fatigue", 0.0) * 0.4
            + (1.0 - s.get("energy", 0.5)) * 0.5
            - s.get("approach_drive", 0.0) * 0.1
        ),
        "use_connector": False,
        "anchor_pos": "adj",
    },
    {
        "template": "好{anchor}……动都不想动了",
        "score_fn": lambda s: (
            s.get("fatigue", 0.0) * 0.5
            + s.get("avoid_drive", 0.0) * 0.4
            + s.get("somatic_tone", 0.0) * -0.1
        ),
        "use_connector": False,
        "anchor_pos": "adj",
    },
    {
        "template": "{anchor}得有点晕……",
        "score_fn": lambda s: (
            s.get("fatigue", 0.0) * 0.5
            + s.get("somatic_tone", 0.0) * -0.3
            + s.get("boredom", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "head",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 2. 高孤独（想找人说话、空落落的）
# ─────────────────────────────────────────────────────────────────────────────

PATTERNS += [
    {
        "template": "有点{anchor}……有人吗",
        "score_fn": lambda s: (
            s.get("loneliness", 0.0) * 0.7
            + s.get("approach_social", 0.0) * 0.3
        ),
        "use_connector": False,
        "anchor_pos": "adj",
    },
    {
        "template": "心里{anchor}的……",
        "score_fn": lambda s: (
            s.get("loneliness", 0.0) * 0.6
            + s.get("sadness", 0.0) * 0.3
            + s.get("stress", 0.0) * 0.1
        ),
        "use_connector": False,
        "anchor_pos": "embed",
    },
    {
        "template": "好想有人陪我说说话啊……",
        "score_fn": lambda s: (
            s.get("loneliness", 0.0) * 0.5
            + s.get("approach_social", 0.0) * 0.3
            - s.get("stress", 0.0) * 0.1
            + s.get("unresolved", 0.0) * 0.1
        ),
        "use_connector": True,
        "anchor_pos": "none",
    },
    {
        "template": "感觉{anchor}得很……",
        "score_fn": lambda s: (
            s.get("loneliness", 0.0) * 0.5
            + s.get("energy", 0.0) * -0.2
            + s.get("avoid_drive", 0.0) * -0.2
        ),
        "use_connector": False,
        "anchor_pos": "adj",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 3. 高好奇（想知道、想去看看）
# ─────────────────────────────────────────────────────────────────────────────

PATTERNS += [
    {
        "template": "有点好奇……{anchor}",
        "score_fn": lambda s: (
            s.get("curiosity", 0.0) * 0.5
            + s.get("approach_explore", 0.0) * 0.4
            + s.get("info_gap", 0.0) * 0.1
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
    {
        "template": "想知道……{anchor}",
        "score_fn": lambda s: (
            s.get("info_gap", 0.0) * 0.5
            + s.get("curiosity", 0.0) * 0.4
            - s.get("avoid_drive", 0.0) * 0.1
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
    {
        "template": "{anchor}……想去看看",
        "score_fn": lambda s: (
            s.get("curiosity", 0.0) * 0.5
            + s.get("approach_drive", 0.0) * 0.3
            + s.get("boredom", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "head",
    },
    {
        "template": "有点想探索一下……{anchor}",
        "score_fn": lambda s: (
            s.get("approach_explore", 0.0) * 0.5
            + s.get("curiosity", 0.0) * 0.3
            - s.get("danger_level", 0.0) * 0.2
        ),
        "use_connector": True,
        "anchor_pos": "tail",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 4. 高压力/焦虑（有点烦、静不下来）
# ─────────────────────────────────────────────────────────────────────────────

PATTERNS += [
    {
        "template": "有点烦……{anchor}",
        "score_fn": lambda s: (
            s.get("stress", 0.0) * 0.5
            + s.get("anxiety", 0.0) * 0.3
            + s.get("unresolved", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
    {
        "template": "静不下来……{anchor}",
        "score_fn": lambda s: (
            s.get("anxiety", 0.0) * 0.5
            + s.get("stress", 0.0) * 0.3
            + s.get("approach_drive", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
    {
        "template": "{anchor}……心里毛毛的",
        "score_fn": lambda s: (
            s.get("anxiety", 0.0) * 0.5
            + s.get("somatic_tone", 0.0) * -0.3
            + s.get("fatigue", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "head",
    },
    {
        "template": "怎么感觉……{anchor}",
        "score_fn": lambda s: (
            s.get("anxiety", 0.0) * 0.4
            + s.get("stress", 0.0) * 0.3
            + s.get("prediction_error", 0.0) * 0.3
        ),
        "use_connector": True,
        "anchor_pos": "tail",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 5. 高无聊（提不起劲、没什么意思）
# ─────────────────────────────────────────────────────────────────────────────

PATTERNS += [
    {
        "template": "好无聊……{anchor}",
        "score_fn": lambda s: (
            s.get("boredom", 0.0) * 0.6
            + s.get("energy", 0.0) * -0.2
            + s.get("approach_drive", 0.0) * -0.2
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
    {
        "template": "没什么意思……{anchor}",
        "score_fn": lambda s: (
            s.get("boredom", 0.0) * 0.5
            + s.get("boredom_futility", 0.0) * 0.3
            - s.get("curiosity", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
    {
        "template": "提不起劲……{anchor}",
        "score_fn": lambda s: (
            s.get("energy", 0.0) * -0.4
            + s.get("fatigue", 0.0) * 0.3
            + s.get("boredom", 0.0) * 0.3
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
    {
        "template": "{anchor}……什么都好无聊",
        "score_fn": lambda s: (
            s.get("boredom_despair", 0.0) * 0.4
            + s.get("boredom", 0.0) * 0.4
            - s.get("joy", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "head",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 6. 趋近驱动强（想做点什么、有点跃跃欲试）
# ─────────────────────────────────────────────────────────────────────────────

PATTERNS += [
    {
        "template": "想做点什么……{anchor}",
        "score_fn": lambda s: (
            s.get("approach_drive", 0.0) * 0.6
            + s.get("energy", 0.0) * 0.3
            - s.get("avoid_drive", 0.0) * 0.1
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
    {
        "template": "有点跃跃欲试……{anchor}",
        "score_fn": lambda s: (
            s.get("approach_drive", 0.0) * 0.4
            + s.get("excitement", 0.0) * 0.4
            + s.get("joy", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
    {
        "template": "{anchor}……想试试",
        "score_fn": lambda s: (
            s.get("approach_drive", 0.0) * 0.5
            + s.get("approach_explore", 0.0) * 0.3
            - s.get("fear", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "head",
    },
    {
        "template": "来劲了……{anchor}",
        "score_fn": lambda s: (
            s.get("energy", 0.0) * 0.5
            + s.get("approach_drive", 0.0) * 0.3
            + s.get("excitement", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 7. 低能量（懒洋洋的、不想动）
# ─────────────────────────────────────────────────────────────────────────────

PATTERNS += [
    {
        "template": "懒洋洋的……{anchor}",
        "score_fn": lambda s: (
            s.get("energy", 0.0) * -0.5
            + s.get("fatigue", 0.0) * 0.3
            + s.get("avoid_drive", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
    {
        "template": "不想动……{anchor}",
        "score_fn": lambda s: (
            s.get("energy", 0.0) * -0.5
            + s.get("avoid_drive", 0.0) * 0.4
            + s.get("fatigue", 0.0) * 0.1
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
    {
        "template": "就这样吧……{anchor}",
        "score_fn": lambda s: (
            s.get("energy", 0.0) * -0.4
            + s.get("approach_drive", 0.0) * -0.3
            + s.get("boredom", 0.0) * 0.3
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
    {
        "template": "瘫着……{anchor}",
        "score_fn": lambda s: (
            s.get("energy", 0.0) * -0.6
            + s.get("avoid_drive", 0.0) * 0.4
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 8. 平静（还好，平平的）
# ─────────────────────────────────────────────────────────────────────────────

PATTERNS += [
    {
        "template": "还好吧……",
        "score_fn": lambda s: (
            s.get("serenity", 0.0) * 0.5
            + (1.0 - s.get("stress", 0.0)) * 0.3
            + (1.0 - s.get("anxiety", 0.0)) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "none",
    },
    {
        "template": "平平的……{anchor}",
        "score_fn": lambda s: (
            s.get("serenity", 0.0) * 0.4
            - s.get("excitement", 0.0) * 0.3
            - s.get("stress", 0.0) * 0.3
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
    {
        "template": "没什么特别的感觉……",
        "score_fn": lambda s: (
            (1.0 - s.get("anxiety", 0.0)) * 0.4
            + (1.0 - s.get("stress", 0.0)) * 0.3
            - s.get("excitement", 0.0) * 0.3
        ),
        "use_connector": False,
        "anchor_pos": "none",
    },
    {
        "template": "就这样吧……{anchor}",
        "score_fn": lambda s: (
            s.get("serenity", 0.0) * 0.5
            - s.get("approach_drive", 0.0) * 0.3
            - s.get("stress", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 9. 预测性表达（未来状态预期）
# 依赖 state_snapshot 展开的 *_rising 信号：<0.5=改善，>0.5=恶化
# ─────────────────────────────────────────────────────────────────────────────

PATTERNS += [
    # 再这样下去会累
    {
        "template": "再这样下去会{anchor}……",
        "score_fn": lambda s: (
            s.get("fatigue_rising", 0.5) * 0.45
            + s.get("anxiety", 0.0) * 0.30
            + s.get("approach_drive", 0.0) * 0.25
        ),
        "use_connector": False,
        "anchor_pos": "embed",
    },
    # 如果继续估计会更累
    {
        "template": "如果继续……估计会更{anchor}",
        "score_fn": lambda s: (
            s.get("fatigue_rising", 0.5) * 0.50
            + s.get("somatic_tone_rising", 0.5) * -0.25
            + s.get("stress", 0.0) * 0.25
        ),
        "use_connector": False,
        "anchor_pos": "embed",
    },
    # 感觉撑不了太久了
    {
        "template": "感觉撑不了太久了……",
        "score_fn": lambda s: (
            s.get("energy_rising", 0.5) * 0.45
            + s.get("fatigue_rising", 0.5) * 0.35
            + s.get("approach_urgency", 0.0) * 0.20
        ),
        "use_connector": False,
        "anchor_pos": "head",
    },
    # 感觉在变差
    {
        "template": "感觉在变差……",
        "score_fn": lambda s: (
            s.get("somatic_tone_rising", 0.5) * -0.40
            + s.get("stress_rising", 0.5) * 0.40
            + s.get("joy", 0.0) * -0.20
        ),
        "use_connector": False,
        "anchor_pos": "head",
    },
    # 预感不太好
    {
        "template": "预感不太好……",
        "score_fn": lambda s: (
            s.get("danger_level_rising", 0.5) * 0.50
            + s.get("anxiety", 0.0) * 0.30
            + s.get("somatic_tone_rising", 0.5) * -0.20
        ),
        "use_connector": False,
        "anchor_pos": "head",
    },
    # 估计会慢慢好起来（乐观预测）
    {
        "template": "估计慢慢会好的……",
        "score_fn": lambda s: (
            (1.0 - s.get("stress_rising", 0.5)) * 0.40
            + (1.0 - s.get("fatigue_rising", 0.5)) * 0.40
            + s.get("approach_drive", 0.0) * 0.20
        ),
        "use_connector": False,
        "anchor_pos": "head",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 10. 混合场景
# ─────────────────────────────────────────────────────────────────────────────

PATTERNS += [
    # 9a. 疲劳 + 孤独
    {
        "template": "好累……但还是想说说话……{anchor}",
        "score_fn": lambda s: (
            s.get("fatigue", 0.0) * 0.4
            + s.get("loneliness", 0.0) * 0.4
            + s.get("approach_social", 0.0) * 0.2
        ),
        "use_connector": True,
        "anchor_pos": "tail",
    },
    {
        "template": "想找人但又没力气……{anchor}",
        "score_fn": lambda s: (
            s.get("loneliness", 0.0) * 0.4
            + s.get("approach_social", 0.0) * 0.3
            + s.get("fatigue", 0.0) * -0.3
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
    # 9b. 好奇 + 焦虑
    {
        "template": "想知道……又有点怕……{anchor}",
        "score_fn": lambda s: (
            s.get("curiosity", 0.0) * 0.4
            + s.get("anxiety", 0.0) * 0.3
            + s.get("approach_drive", 0.0) * 0.2
            + s.get("avoid_drive", 0.0) * 0.1
        ),
        "use_connector": True,
        "anchor_pos": "tail",
    },
    {
        "template": "{anchor}……有点紧张又有点期待",
        "score_fn": lambda s: (
            s.get("curiosity", 0.0) * 0.3
            + s.get("approach_drive", 0.0) * 0.3
            + s.get("anxiety", 0.0) * 0.2
            + s.get("excitement", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "head",
    },
    # 9c. 低能量 + 好奇
    {
        "template": "虽然懒得动……但{anchor}",
        "score_fn": lambda s: (
            s.get("energy", 0.0) * -0.3
            + s.get("curiosity", 0.0) * 0.4
            + s.get("approach_explore", 0.0) * 0.3
        ),
        "use_connector": True,
        "anchor_pos": "tail",
    },
    {
        "template": "{anchor}……算了还是躺着想想吧",
        "score_fn": lambda s: (
            s.get("curiosity", 0.0) * 0.4
            + s.get("energy", 0.0) * -0.3
            + s.get("avoid_drive", 0.0) * 0.3
        ),
        "use_connector": False,
        "anchor_pos": "head",
    },
    # 9d. 孤独 + 好奇（社交好奇）
    {
        "template": "有点想和人聊聊……{anchor}",
        "score_fn": lambda s: (
            s.get("approach_social", 0.0) * 0.5
            + s.get("loneliness", 0.0) * 0.3
            + s.get("curiosity", 0.0) * 0.2
        ),
        "use_connector": True,
        "anchor_pos": "tail",
    },
    {
        "template": "{anchor}……有人就好了",
        "score_fn": lambda s: (
            s.get("loneliness", 0.0) * 0.5
            + s.get("approach_social", 0.0) * 0.3
            - s.get("stress", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "head",
    },
    # 9e. 压力 + 孤独
    {
        "template": "烦……又没人能说……{anchor}",
        "score_fn": lambda s: (
            s.get("stress", 0.0) * 0.4
            + s.get("loneliness", 0.0) * 0.4
            + s.get("anxiety", 0.0) * 0.2
        ),
        "use_connector": True,
        "anchor_pos": "tail",
    },
    {
        "template": "{anchor}……心里堵得慌",
        "score_fn": lambda s: (
            s.get("stress", 0.0) * 0.4
            + s.get("somatic_tone", 0.0) * -0.3
            + s.get("anxiety", 0.0) * 0.3
        ),
        "use_connector": False,
        "anchor_pos": "head",
    },
    # 9f. 兴奋 + 低能量（矛盾）
    {
        "template": "{anchor}……想动但又不太行",
        "score_fn": lambda s: (
            s.get("excitement", 0.0) * 0.4
            + s.get("approach_drive", 0.0) * 0.3
            + s.get("energy", 0.0) * -0.3
        ),
        "use_connector": False,
        "anchor_pos": "head",
    },
    {
        "template": "心里在蹦跶……身体跟不上……{anchor}",
        "score_fn": lambda s: (
            s.get("excitement", 0.0) * 0.4
            + s.get("energy", 0.0) * -0.4
            + s.get("fatigue", 0.0) * 0.2
        ),
        "use_connector": True,
        "anchor_pos": "tail",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 10. 通用柔和（适合大多数状态的兜底模板）
# ─────────────────────────────────────────────────────────────────────────────

PATTERNS += [
    {
        "template": "{anchor}……",
        "score_fn": lambda s: (
            0.5 * max(s.get("fatigue", 0.0), s.get("loneliness", 0.0))
            + 0.5 * max(s.get("boredom", 0.0), s.get("anxiety", 0.0))
            - 0.3 * s.get("excitement", 0.0)
        ),
        "use_connector": False,
        "anchor_pos": "head",
    },
    {
        "template": "是有点……{anchor}",
        "score_fn": lambda s: (
            0.4 * (1.0 - s.get("approach_drive", 0.0))
            + 0.3 * (1.0 - s.get("energy", 0.0))
            + 0.3 * s.get("avoid_drive", 0.0)
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
    {
        "template": "大概就是……{anchor}",
        "score_fn": lambda s: (
            0.6 * s.get("serenity", 0.0)
            + 0.4 * (1.0 - s.get("stress", 0.0))
        ),
        "use_connector": False,
        "anchor_pos": "tail",
    },
]

assert len(PATTERNS) >= 30, f"PATTERNS count={len(PATTERNS)}, need >= 30"


# ============================================================================
# 复合模板（双锚点：{anchor} + {anchor2}）
# ============================================================================

COMPOUND_PATTERNS: List[Dict] = []

# 疲劳 + 社交需求
COMPOUND_PATTERNS += [
    {
        "template": "好{anchor}……但还是想{anchor2}",
        "score_fn": lambda s: (
            s.get("fatigue", 0.0) * 0.4
            + s.get("loneliness", 0.0) * 0.4
            + s.get("approach_social", 0.0) * 0.2
        ),
    },
    {
        "template": "{anchor}得不行……又{anchor2}",
        "score_fn": lambda s: (
            s.get("fatigue", 0.0) * 0.5
            + s.get("loneliness", 0.0) * 0.3
            + s.get("approach_social", 0.0) * 0.2
        ),
    },
]

# 好奇 + 焦虑/恐惧
COMPOUND_PATTERNS += [
    {
        "template": "{anchor}……又有点{anchor2}",
        "score_fn": lambda s: (
            s.get("curiosity", 0.0) * 0.4
            + s.get("anxiety", 0.0) * 0.3
            + s.get("approach_drive", 0.0) * 0.2
            + s.get("avoid_drive", 0.0) * 0.1
        ),
    },
    {
        "template": "有点{anchor}……又{anchor2}",
        "score_fn": lambda s: (
            s.get("curiosity", 0.0) * 0.4
            + s.get("fear", 0.0) * 0.3
            + s.get("info_gap", 0.0) * 0.3
        ),
    },
]

# 低能量 + 好奇
COMPOUND_PATTERNS += [
    {
        "template": "虽然{anchor}……但还是{anchor2}",
        "score_fn": lambda s: (
            s.get("energy", 0.0) * -0.3
            + s.get("curiosity", 0.0) * 0.4
            + s.get("approach_explore", 0.0) * 0.3
        ),
    },
    {
        "template": "{anchor}……不过{anchor2}",
        "score_fn": lambda s: (
            s.get("fatigue", 0.0) * 0.3
            + s.get("curiosity", 0.0) * 0.3
            + s.get("approach_drive", 0.0) * 0.4
        ),
    },
]

# 压力/焦虑 + 孤独
COMPOUND_PATTERNS += [
    {
        "template": "{anchor}……又{anchor2}……",
        "score_fn": lambda s: (
            s.get("stress", 0.0) * 0.4
            + s.get("loneliness", 0.0) * 0.4
            + s.get("anxiety", 0.0) * 0.2
        ),
    },
    {
        "template": "心里{anchor}……还{anchor2}",
        "score_fn": lambda s: (
            s.get("stress", 0.0) * 0.3
            + s.get("anxiety", 0.0) * 0.3
            + s.get("loneliness", 0.0) * 0.4
        ),
    },
]

# 通用对立（任何两个不同簇的词）
COMPOUND_PATTERNS += [
    {
        "template": "又{anchor}又{anchor2}……",
        "score_fn": lambda s: 0.3,  # 低基础分，只在别的不匹配时兜底
    },
    {
        "template": "{anchor}……还有点{anchor2}",
        "score_fn": lambda s: 0.35,
    },
    {
        "template": "有点{anchor}有点{anchor2}……",
        "score_fn": lambda s: 0.32,
    },
    {
        "template": "{anchor}……也{anchor2}",
        "score_fn": lambda s: 0.28,
    },
]

logger.debug(
    f"[SentenceComposer] Loaded {len(PATTERNS)} single + "
    f"{len(COMPOUND_PATTERNS)} compound patterns"
)


# ============================================================================
# 核心函数
# ============================================================================

def _softmax_sample(scores: List[float], temperature: float = 0.4) -> int:
    """
    softmax 概率采样。
    temperature 越高越发散，越低越集中。
    返回选中模板的索引。
    """
    if not scores:
        return 0

    max_s = max(scores)
    weights = [math.exp((s - max_s) / max(temperature, 0.01)) for s in scores]
    total = sum(weights)
    if total < 1e-9:
        return 0
    probs = [w / total for w in weights]
    return random.choices(range(len(scores)), weights=probs, k=1)[0]


def compose_sentence(
    anchor: str,
    state: Dict[str, float],
    connector: str = "",
    template_efficiency: Optional[Dict[int, float]] = None,
    learned_weights: Optional[Dict[int, Dict[str, float]]] = None,
    extra_templates: Optional[List[Dict]] = None,
    second_anchor: Optional[str] = None,
) -> Tuple[str, int]:
    """
    根据当前状态，从模板库中选择一个模板，填充锚点词，组合成完整短句。

    参数：
        anchor              : 锚点词，如 "累"、"冷"、"好奇"
        state               : 当前状态 dict，key 与 entity_state 字段一致
        connector           : 连接词（来自 connector_map 的语气开头词），可选
        template_efficiency : {template_idx: avg_efficiency} 历史模板消力效率（含贝叶斯先验）
        learned_weights     : {template_idx: {dim: weight}} 学习到的状态权重，
                              来自 template_learner。与 score_fn 加法叠加。
        extra_templates     : 运行时新生模板（进化/CxG产生），追加在 PATTERNS 之后
        second_anchor       : 来自不同簇的第二锚点词（跨簇复合表达用）

    返回：
        (sentence, template_idx) 元组：
            sentence     : 完整的中文短句
            template_idx : 选中模板的全局索引
                           正数 = PATTERNS/extra 索引
                           负数(-1=无效, -1000-i = COMPOUND 索引 i)

    采样机制：
        1. score_fn(state) → 内置分（种子模板有，进化模板无）
        2. + learned_weights · state → 学习分
        3. - _anchor_penalty → 语法惩罚
        4. + template_efficiency → 历史效率加成（含贝叶斯先验）
        5. 如果有 second_anchor，复合模板也参与竞争
        6. 缺口探索奖励 → CxG 新候选在覆盖缺口时获得探索bonus
        7. softmax(temperature=0.4) → 概率采样
    """
    if not anchor:
        return ("", -1)

    all_templates = PATTERNS
    if extra_templates:
        all_templates = PATTERNS + extra_templates

    if not all_templates:
        return (anchor, -1)

    # ---- 单锚点模板评分 ----
    raw_scores = []
    for i, p in enumerate(all_templates):
        score_fn = p.get("score_fn")
        if score_fn is not None:
            try:
                score = score_fn(state)
            except Exception:
                score = 0.0
        else:
            score = 0.0

        if learned_weights and i in learned_weights:
            lw = learned_weights[i]
            score += sum(w * state.get(dim, 0.0) for dim, w in lw.items())

        pos = p.get("anchor_pos", "head")
        score -= _anchor_penalty(len(anchor), pos)

        if template_efficiency and i in template_efficiency:
            score += min(template_efficiency[i], 0.5)

        raw_scores.append(score)

    # ---- 复合模板评分（仅当有 second_anchor 时参与竞争）----
    compound_offset = len(raw_scores)
    if second_anchor and COMPOUND_PATTERNS:
        for cp in COMPOUND_PATTERNS:
            cp_fn = cp.get("score_fn")
            try:
                cp_score = cp_fn(state) if cp_fn else 0.0
            except Exception:
                cp_score = 0.0
            # 复合模板加成：状态越矛盾（双高），加分越多
            cp_score += 0.15  # 基础偏好——有 second_anchor 时倾向使用
            raw_scores.append(cp_score)

    # ---- 缺口探索奖励（v12 新增）----
    # 当现有所有模板的匹配分数都偏低 → 触发探索奖励
    # 新候选（_from_cxg）有机会第一次出场，不必先在竞争中胜出
    # 注：extra_templates 每次 compose_sentence 调用都是新 list，
    # 所以 _from_cxg 候选每次都重新参与竞争（不需要跨调用 flag）
    _NOVELTY_THRESHOLD = 0.30   # 现有最佳分低于此值 → 覆盖缺口
    _NOVELTY_STRENGTH = 0.25    # CxG 新候选的探索bonus 上限
    if extra_templates and max(raw_scores, default=0.0) < _NOVELTY_THRESHOLD:
        _gap = _NOVELTY_THRESHOLD - max(raw_scores)
        _bonus = _gap * _NOVELTY_STRENGTH / max(_NOVELTY_THRESHOLD, 0.01)
        # extra_templates 接在 PATTERNS 后面
        _pat_len = len(PATTERNS)
        for _ei, _ep in enumerate(extra_templates):
            if _ep.get("_from_cxg") or _ep.get("_gap_probed"):
                _global_idx = _pat_len + _ei
                if _global_idx < len(raw_scores):
                    raw_scores[_global_idx] += _bonus

    chosen_idx = _softmax_sample(raw_scores, temperature=0.4)

    # ---- 根据选中的是单锚点还是复合模板，填充句子 ----
    if chosen_idx >= compound_offset and second_anchor:
        # 选中了复合模板
        cp_idx = chosen_idx - compound_offset
        chosen_cp = COMPOUND_PATTERNS[cp_idx]
        template = chosen_cp["template"]
        sentence = _fill_compound(template, anchor, second_anchor)
        result_idx = -1000 - cp_idx  # 负数编码：-1000, -1001, ...
    else:
        # 选中了单锚点模板
        chosen = all_templates[chosen_idx]
        template = chosen["template"]
        sentence = _fill_anchor(template, anchor)
        result_idx = chosen_idx

        if connector and chosen.get("use_connector", True):
            if not sentence.startswith(connector):
                sentence = connector + sentence

    return (sentence, result_idx)


# 强度前缀集合（来自 connector_map + word_warmup 变体）
# "好" 不在此列表——它既是强度前缀又是常见词首（好奇、好看），
# 误剥会破坏合法词。"好{anchor}啊" 模板的 "好" 由字符串重叠逻辑处理。
_INTENSITY_PREFIXES = ("有点", "太", "挺", "很", "特别", "非常")


def _fill_anchor(template: str, anchor: str) -> str:
    """填充锚词到模板，自动去除插入点处的前后重叠和强度前缀冲突。

    "有点{anchor}" + "有点软" → "有点软"（前缀重叠）
    "心里{anchor}的" + "渴的"  → "心里渴的"（后缀重叠）
    "{anchor}……想试试" + "开心" → "开心……想试试"（无重叠，原样）
    "有点{anchor}" + "挺饿"   → "有点饿"（强度前缀冲突，去掉 anchor 的前缀）
    "好{anchor}啊" + "很累"   → "好累啊"（同上）
    """
    tag = "{anchor}"
    idx = template.find(tag)
    if idx < 0:
        return template  # 无占位符

    prefix = template[:idx]
    suffix = template[idx + len(tag):]

    # 强度前缀冲突：模板已含强度表达（prefix 或 suffix），anchor 再带强度前缀 → 去掉 anchor 的
    # "有点{anchor}" + "挺饿" → "有点饿"（prefix 冲突）
    # "感觉{anchor}得很" + "很痒" → "感觉痒得很"（suffix 含 "很"，anchor 也以 "很" 开头）
    _tmpl_has_intensity = (
        any(prefix.endswith(p) for p in _INTENSITY_PREFIXES)
        or any(p in suffix for p in _INTENSITY_PREFIXES)
    ) if (prefix or suffix) else False
    if _tmpl_has_intensity:
        for p in _INTENSITY_PREFIXES:
            if anchor.startswith(p) and len(anchor) > len(p):
                anchor = anchor[len(p):]
                break

    # 前缀重叠：prefix 末尾与 anchor 开头重合
    # 例如 prefix="有点", anchor="有点软" → overlap="有点" → 去掉 anchor 开头
    for n in range(min(len(prefix), len(anchor)), 0, -1):
        if prefix[-n:] == anchor[:n]:
            anchor = anchor[n:]
            break

    # 后缀重叠：anchor 末尾与 suffix 开头重合
    # 例如 anchor="渴的", suffix="的……" → overlap="的" → 去掉 suffix 开头
    for n in range(min(len(anchor), len(suffix)), 0, -1):
        if anchor[-n:] == suffix[:n]:
            suffix = suffix[n:]
            break

    return prefix + anchor + suffix


def _fill_compound(template: str, anchor1: str, anchor2: str) -> str:
    """填充双锚点模板。

    {anchor} → anchor1, {anchor2} → anchor2。
    对每个槽位复用 _fill_anchor 的重叠/前缀处理逻辑。
    """
    # 先替换 {anchor2}（避免 {anchor} 误匹配 {anchor2} 的前缀）
    tag2 = "{anchor2}"
    idx2 = template.find(tag2)
    if idx2 >= 0:
        pre2 = template[:idx2]
        suf2 = template[idx2 + len(tag2):]
        # 简化处理：直接替换，不做重叠检测（复合模板的连接词已设计好）
        template = pre2 + anchor2 + suf2

    # 再替换 {anchor}
    tag1 = "{anchor}"
    idx1 = template.find(tag1)
    if idx1 >= 0:
        pre1 = template[:idx1]
        suf1 = template[idx1 + len(tag1):]
        template = pre1 + anchor1 + suf1

    return template


# ============================================================================
# 测试
# ============================================================================

if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).parent.parent.parent))

    from src.language_system.sentence_composer import compose_sentence, PATTERNS

    print("=" * 60)
    print(f"  Sentence Composer Test — {len(PATTERNS)} templates")
    print("=" * 60)

    test_scenes = [
        {
            "name": "高疲劳",
            "state": {
                "fatigue": 0.85, "energy": 0.20, "avoid_drive": 0.50,
                "somatic_tone": -0.4, "joy": 0.05, "boredom": 0.10,
                "loneliness": 0.20, "approach_drive": 0.10, "curiosity": 0.30,
                "anxiety": 0.10, "stress": 0.10, "boredom_despair": 0.10,
                "boredom_futility": 0.10, "approach_social": 0.10,
                "approach_explore": 0.10, "sadness": 0.20, "excitement": 0.05,
                "prediction_error": 0.2, "danger_level": 0.0,
                "unresolved": 0.20, "info_gap": 0.30, "fear": 0.05,
            },
            "anchors": ["累", "乏", "困"],
            "connectors": ["", "唉", "嗯"],
        },
        {
            "name": "高好奇",
            "state": {
                "fatigue": 0.10, "energy": 0.75, "avoid_drive": 0.05,
                "somatic_tone": 0.3, "joy": 0.30, "boredom": 0.10,
                "loneliness": 0.20, "approach_drive": 0.70, "curiosity": 0.85,
                "anxiety": 0.10, "stress": 0.05, "boredom_despair": 0.0,
                "boredom_futility": 0.0, "approach_social": 0.30,
                "approach_explore": 0.80, "sadness": 0.0, "excitement": 0.40,
                "prediction_error": 0.5, "danger_level": 0.1,
                "unresolved": 0.10, "info_gap": 0.80, "fear": 0.05,
            },
            "anchors": ["想看看", "想知道", "好奇"],
            "connectors": ["", "嗯"],
        },
        {
            "name": "高孤独",
            "state": {
                "fatigue": 0.20, "energy": 0.60, "avoid_drive": 0.10,
                "somatic_tone": -0.2, "joy": 0.05, "boredom": 0.20,
                "loneliness": 0.85, "approach_drive": 0.40, "curiosity": 0.30,
                "anxiety": 0.15, "stress": 0.15, "boredom_despair": 0.0,
                "boredom_futility": 0.0, "approach_social": 0.70,
                "approach_explore": 0.20, "sadness": 0.40, "excitement": 0.0,
                "prediction_error": 0.2, "danger_level": 0.0,
                "unresolved": 0.40, "info_gap": 0.30, "fear": 0.05,
            },
            "anchors": ["空", "闷", "沉"],
            "connectors": ["", "唉"],
        },
        {
            "name": "高焦虑+好奇",
            "state": {
                "fatigue": 0.30, "energy": 0.50, "avoid_drive": 0.30,
                "somatic_tone": -0.3, "joy": 0.10, "boredom": 0.20,
                "loneliness": 0.40, "approach_drive": 0.60, "curiosity": 0.70,
                "anxiety": 0.70, "stress": 0.60, "boredom_despair": 0.0,
                "boredom_futility": 0.0, "approach_social": 0.40,
                "approach_explore": 0.60, "sadness": 0.20, "excitement": 0.20,
                "prediction_error": 0.6, "danger_level": 0.2,
                "unresolved": 0.50, "info_gap": 0.70, "fear": 0.20,
            },
            "anchors": ["跳", "慌", "紧"],
            "connectors": ["", "唉"],
        },
        {
            "name": "平静",
            "state": {
                "fatigue": 0.10, "energy": 0.70, "avoid_drive": 0.10,
                "somatic_tone": 0.2, "joy": 0.30, "boredom": 0.10,
                "loneliness": 0.20, "approach_drive": 0.30, "curiosity": 0.40,
                "anxiety": 0.05, "stress": 0.05, "boredom_despair": 0.0,
                "boredom_futility": 0.0, "approach_social": 0.20,
                "approach_explore": 0.30, "sadness": 0.05, "excitement": 0.10,
                "prediction_error": 0.1, "danger_level": 0.0,
                "unresolved": 0.10, "info_gap": 0.30, "fear": 0.05,
            },
            "anchors": ["静", "松", "舒服"],
            "connectors": ["", "嗯"],
        },
    ]

    for scene in test_scenes:
        print()
        print("-" * 60)
        print(f"  [Scene] {scene['name']}")
        print(f"  anchors={scene['anchors']}, connectors={scene['connectors']}")
        print("-" * 60)
        results = []
        for i in range(5):
            anchor = random.choice(scene["anchors"])
            connector = random.choice(scene["connectors"])
            sentence, tmpl_idx = compose_sentence(anchor, scene["state"], connector)
            results.append(sentence)
            prefix = connector if connector else "   "
            print(f"    [{i+1}] {prefix} {sentence}  (tmpl={tmpl_idx})")
        unique = len(set(results))
        status = "[OK random]" if unique > 1 else "[WARN same]"
        print(f"    {status} {unique}/5 unique sentences")

    print()
    print("=" * 60)
    print("  All tests done.")
    print("=" * 60)
