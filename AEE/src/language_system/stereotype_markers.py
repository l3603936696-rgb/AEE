"""
Stereotype Markers — linguistic marker constants for stereotype learning.

Submodules of src.language_system.stereotype_learner:
    stereotype_markers.py — marker constants
    stereotype_learner.py — FeatureExtractor + TagInferrer + StereotypeLearner
"""

# Feature extraction window: number of recent messages to consider
FEATURE_WINDOW = 10

# Philosophical markers
PHILOSOPHICAL_MARKERS = frozenset({
    "可能", "也许", "应该", "其实", "我觉得", "我认为",
    "好像", "似乎", "大概", "或许", "究竟", "为什么",
    "是不是", "是不是说", "什么意思", "怎么理解",
})

# Metacognitive markers
METACOGNITIVE_MARKERS = frozenset({
    "我觉得", "我认为", "我以为", "我知道", "我不知道",
    "你懂", "你理解", "你明白", "理解", "不清楚",
    "记得", "忘了", "想起来", "不确定",
})

# Analytical markers
ANALYTICAL_MARKERS = frozenset({
    "因为", "所以", "但是", "如果", "虽然", "然而",
    "因此", "所以", "不过", "而且", "或者",
    "首先", "然后", "最后", "总之", "也就是说",
})

# First-person markers
FIRST_PERSON_MARKERS = frozenset({
    "我", "我们", "我的", "我们的", "我自己",
})

# Emotional markers (simplified)
EMOTIONAL_MARKERS = frozenset({
    "开心", "高兴", "快乐", "舒服", "满足", "幸福",
    "难过", "伤心", "痛苦", "难受", "焦虑", "害怕", "生气", "愤怒",
    "啊", "呀", "呢", "吧", "哦", "嗯",
})
