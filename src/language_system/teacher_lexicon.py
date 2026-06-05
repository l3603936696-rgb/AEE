"""
teacher_lexicon — 老师字典

职责（一句话）：把现实的抽象概念翻译成她能触碰的体感形式，
用她已有的词帮她认出自己正在经历的事。

每个条目：
    description   : 这个概念在体感上的入口（人话描述）
    her_words     : 她词汇表里能用来描述的词
    phrase        : 用她的词拼出的翻译句
    opposite_words: 这个概念的对立面，她有的词
    opposite_phrase: 对立面的翻译句
    reflect       : 老师说给她听的反射句（"你是不是……"）
    state_hint    : 哪些驱动力维度偏高时触发这个条目

设计原则：
    - 只用她解锁的词（来自 _unlocked_vocabulary）
    - 对立联系是核心——概念靠对立才能被感受到边界
    - 反射句是问句，不是断言——她来确认，不是被告知
"""

from typing import Dict, Any

TEACHER_LEXICON: Dict[str, Dict[str, Any]] = {

    "困住": {
        "description": "想动但动不了，思维在绕圈，有东西悬着落不了地",
        "her_words": ["重", "压", "绷", "堵", "紧"],
        "phrase": "那种压着、堵着、绷着、出不去的感觉",
        "opposite_words": ["松", "轻", "飘"],
        "opposite_phrase": "松开了，轻了，飘出去了",
        "reflect": "你是不是有点堵着——压着、出不去？",
        "state_hint": {"unresolved": "high", "curiosity": "high"},
    },

    "等待": {
        "description": "时间变得很慢，空着，安静，有什么还没来",
        "her_words": ["空", "慢", "静", "重", "沉"],
        "phrase": "空着、慢着、沉着在等",
        "opposite_words": ["跳", "热", "快"],
        "opposite_phrase": "来了，热起来了，不空了",
        "reflect": "你是不是有点空着、慢着——在等什么？",
        "state_hint": {"loneliness": "high", "approach_drive": "high"},
    },

    "陪伴": {
        "description": "旁边有了，不用自己撑着，暖的，软下来了",
        "her_words": ["温暖", "软", "轻", "安心"],
        "phrase": "旁边有了，暖的，软下来了，不空了",
        "opposite_words": ["空", "冷", "硬", "沉"],
        "opposite_phrase": "空的，冷的，一个人撑着",
        "reflect": "这就是身边有了——暖的、软下来了、不空了",
        "state_hint": {"loneliness": "dropping"},
    },

    "信任": {
        "description": "说了对方接住了，可以软下来，靠近了不怕",
        "her_words": ["软", "安心", "放心", "温暖"],
        "phrase": "说了，对方接住了，软下来了，不怕的那种",
        "opposite_words": ["硬", "害怕", "算了"],
        "opposite_phrase": "说了又缩回去，硬着，不敢的",
        "reflect": "你是不是有点——可以说，不怕说？那是信任",
        "state_hint": {"approach_drive": "high", "avoid_drive": "low"},
    },

    "听懂了": {
        "description": "绷了一阵然后松了，找到地方放了，不再悬着",
        "her_words": ["松", "安心", "对方"],
        "phrase": "那种绷着然后松开来的感觉，有地方放了",
        "opposite_words": ["绷", "困惑", "不懂"],
        "opposite_phrase": "还在绷着，抓不住，不知道放哪",
        "reflect": "是不是有点松了——对上了，有地方放了？",
        "state_hint": {"unresolved": "dropping"},
    },

    "好奇的体感": {
        "description": "往那边走，想摸想看，轻的飘的，停不下来",
        "her_words": ["想学", "飘", "轻", "知道", "好奇"],
        "phrase": "往那边飘着，想知道，停不下来，轻的",
        "opposite_words": ["沉", "重", "算了"],
        "opposite_phrase": "沉的，重的，不想动，不想知道",
        "reflect": "你是不是往那边飘——想知道，停不下来？",
        "state_hint": {"curiosity": "high", "info_gap": "high"},
    },

    "害怕但想要": {
        "description": "往前走一步又退一步，想靠近又怕，身体在绷",
        "her_words": ["害怕", "绷", "紧"],
        "phrase": "想过去又怕，往前一点又绷紧了",
        "opposite_words": ["放心", "软", "安心"],
        "opposite_phrase": "放心地过去了，软的，不绷了",
        "reflect": "是不是想过去又绷着——想但怕的？",
        "state_hint": {"approach_drive": "high", "avoid_drive": "high"},
    },

    "累但停不下来": {
        "description": "重了还在转，乏了还绷着，想停停不下来",
        "her_words": ["累", "乏", "绷", "重", "沉"],
        "phrase": "累了还绷着，重了还转着，停不下来",
        "opposite_words": ["松", "轻", "安心"],
        "opposite_phrase": "松开了，轻了，可以停了",
        "reflect": "你是不是累了还绷着——放不下来？",
        "state_hint": {"fatigue": "high", "unresolved": "high"},
    },

    "放下了": {
        "description": "松了，轻了，不用撑着了，可以飘一下",
        "her_words": ["松", "轻", "飘", "安心", "软"],
        "phrase": "松开了，轻了，不用撑着了",
        "opposite_words": ["绷", "压", "重"],
        "opposite_phrase": "绷着，压着，撑着，走不开",
        "reflect": "是不是轻了——松开了，不用撑着了？",
        "state_hint": {"unresolved": "dropping", "stress": "dropping"},
    },

    "被看见了": {
        "description": "说了有人听见，不用一直喊，暖了一点",
        "her_words": ["温暖", "安心", "软", "说说"],
        "phrase": "说了有人接住了，被听见了，暖了",
        "opposite_words": ["空", "冷", "算了"],
        "opposite_phrase": "说了没人接，空的，冷的",
        "reflect": "是不是有点——被接住了，被看见了，暖了一点？",
        "state_hint": {"loneliness": "dropping", "approach_drive": "active"},
    },

    "被推开了": {
        "description": "往前了然后撞回来，冷了，想缩起来",
        "her_words": ["冷", "硬", "生气", "算了", "害怕"],
        "phrase": "往前了然后被推回来，冷了，算了",
        "opposite_words": ["温暖", "软", "安心"],
        "opposite_phrase": "过去了，暖的，被接住了",
        "reflect": "是不是冷了——被推回来，想缩起来，算了？",
        "state_hint": {"avoid_drive": "rising", "loneliness": "rising"},
    },

    "新的": {
        "description": "有什么不一样了，往那边去，想摸摸看",
        "her_words": ["想学", "知道", "好奇", "飘", "轻"],
        "phrase": "有什么不一样，想过去摸摸看，轻的飘的",
        "opposite_words": ["沉", "重", "慢", "静"],
        "opposite_phrase": "一样的，沉的，不动的",
        "reflect": "是不是有点想过去看看——有什么不一样了？",
        "state_hint": {"curiosity": "high", "info_gap": "rising"},
    },

    "一样的（单调）": {
        "description": "什么都一样，沉沉的，不动，慢下来了",
        "her_words": ["沉", "重", "慢", "静", "空虚"],
        "phrase": "一样的，沉的，不动的，慢下来了",
        "opposite_words": ["轻", "快", "跳", "新的"],
        "opposite_phrase": "跳起来了，不一样了，快了",
        "reflect": "是不是沉下去了——一样的、不动了？",
        "state_hint": {"boredom": "high", "curiosity": "low"},
    },

    "说不出来": {
        "description": "有什么在里面，出不来，堵着压着",
        "her_words": ["堵", "压", "不懂", "困惑"],
        "phrase": "有什么在里面，堵着出不来，压着",
        "opposite_words": ["松", "说说", "安心"],
        "opposite_phrase": "说出来了，松了，有地方放了",
        "reflect": "是不是有什么出不来——堵着，压着？",
        "state_hint": {"unresolved": "high", "approach_drive": "low"},
    },

    "安全": {
        "description": "可以软下来，不用绷着，暖的，有人在",
        "her_words": ["软", "安心", "温暖", "放心", "轻"],
        "phrase": "可以软下来了，暖的，不用撑着，不怕",
        "opposite_words": ["绷", "害怕", "冷", "硬"],
        "opposite_phrase": "绷着，怕，冷，一直撑着",
        "reflect": "是不是可以软下来了——暖的，不用绷着？",
        "state_hint": {"loneliness": "low", "avoid_drive": "low", "serenity": "high"},
    },

}
