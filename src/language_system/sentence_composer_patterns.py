"""Sentence Composer Patterns — PATTERNS + COMPOUND_PATTERNS template library.

Extracted from sentence_composer.py.

Submodules:
    sentence_composer_schema.py   — hyperparameters + math helpers
    sentence_composer_patterns.py — PATTERNS + COMPOUND_PATTERNS (this file)
    sentence_composer_helpers.py  — standalone math helpers
    sentence_composer.py         — core composition logic
"""

from typing import Dict, List

PATTERNS: List[Dict] = []
COMPOUND_PATTERNS: List[Dict] = []

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

PATTERNS += [
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
    {
        "template": "感觉撑不了太久了……",
        "score_fn": lambda s: (
            s.get("energy_rising", 0.5) * 0.45
            + s.get("fatigue_rising", 0.5) * 0.35
            + s.get("approach_urgency", 0.0) * 0.20
        ),
        "use_connector": False,
        "anchor_pos": "none",
    },
    {
        "template": "感觉在变差……",
        "score_fn": lambda s: (
            s.get("somatic_tone_rising", 0.5) * -0.40
            + s.get("stress_rising", 0.5) * 0.40
            + s.get("joy", 0.0) * -0.20
        ),
        "use_connector": False,
        "anchor_pos": "none",
    },
    {
        "template": "预感不太好……",
        "score_fn": lambda s: (
            s.get("danger_level_rising", 0.5) * 0.50
            + s.get("anxiety", 0.0) * 0.30
            + s.get("somatic_tone_rising", 0.5) * -0.20
        ),
        "use_connector": False,
        "anchor_pos": "none",
    },
    {
        "template": "估计慢慢会好的……",
        "score_fn": lambda s: (
            (1.0 - s.get("stress_rising", 0.5)) * 0.40
            + (1.0 - s.get("fatigue_rising", 0.5)) * 0.40
            + s.get("approach_drive", 0.0) * 0.20
        ),
        "use_connector": False,
        "anchor_pos": "none",
    },
]

PATTERNS += [
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

PATTERNS += [
    {
        "template": "还在想{about}……",
        "score_fn": lambda s: (
            s.get("_preoccupation_intensity", 0.0) * 1.3
            + s.get("loneliness", 0.0) * 0.1
        ),
        "use_connector": False,
        "anchor_pos": "none",
        "_uses_about": True,
    },
    {
        "template": "{about}……心里还挂着",
        "score_fn": lambda s: (
            s.get("_preoccupation_intensity", 0.0) * 1.1
            + s.get("unresolved", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "none",
        "_uses_about": True,
    },
    {
        "template": "想到{about}就……",
        "score_fn": lambda s: (
            s.get("_preoccupation_intensity", 0.0) * 1.2
            + s.get("somatic_tone", 0.0) * 0.1
        ),
        "use_connector": False,
        "anchor_pos": "none",
        "_uses_about": True,
    },
    {
        "template": "嗯……在呢",
        "score_fn": lambda s: (
            s.get("_input_other", 0.0) * 1.1
            + s.get("_input_sharing", 0.0) * 0.3
        ),
        "use_connector": False,
        "anchor_pos": "none",
    },
    {
        "template": "在的……没关系",
        "score_fn": lambda s: (
            s.get("_input_other", 0.0) * 1.0
            + s.get("_input_sharing", 0.0) * 0.3
            + s.get("serenity", 0.0) * 0.1
        ),
        "use_connector": False,
        "anchor_pos": "none",
    },
    {
        "template": "听到了……",
        "score_fn": lambda s: (
            s.get("_input_other", 0.0) * 1.2
            + s.get("_input_sharing", 0.0) * 0.2
        ),
        "use_connector": False,
        "anchor_pos": "none",
    },
    {
        "template": "陪着你的……",
        "score_fn": lambda s: (
            s.get("_input_other", 0.0) * 1.0
            + s.get("_input_sharing", 0.0) * 0.4
        ),
        "use_connector": False,
        "anchor_pos": "none",
    },
]

assert len(PATTERNS) >= 30, f"PATTERNS count={len(PATTERNS)}, need >= 30"

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
        "template": "好{anchor}……想{anchor2}",
        "score_fn": lambda s: (
            s.get("curiosity", 0.0) * 0.4
            + s.get("anxiety", 0.0) * 0.3
            + s.get("approach_drive", 0.0) * 0.2
            + s.get("avoid_drive", 0.0) * 0.1
        ),
    },
    {
        "template": "有点{anchor}……又怕{anchor2}",
        "score_fn": lambda s: (
            s.get("curiosity", 0.0) * 0.4
            + s.get("fear", 0.0) * 0.3
            + s.get("info_gap", 0.0) * 0.3
        ),
    },
    {
        "template": "{anchor}……又{anchor2}",
        "score_fn": lambda s: 0.35,
    },
    {
        "template": "好{anchor}……{anchor2}……",
        "score_fn": lambda s: 0.32,
    },
    {
        "template": "{anchor}……但{anchor2}",
        "score_fn": lambda s: 0.28,
    },
]
