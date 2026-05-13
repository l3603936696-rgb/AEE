"""
Semantic Understanding Module (感性认识模块)

纯规则引擎，对用户输入的单句自然语言进行语义分析。
输入: raw_input (str) — 用户输入的单句话
输出: semantic_packet (dict) — 结构化语义包

约束:
- 纯函数，不读任何内部状态
- 不调用LLM
- 任一规则失败返回默认值
"""

from dataclasses import dataclass
from typing import List
import re


# ============================================================================
# 数据结构定义
# ============================================================================

@dataclass
class SemanticPacket:
    """语义包 — 感性认识模块的输出格式"""
    emotion: float      # 范围 [-1, 1], 情绪极性
    intent: str         # 意图标签枚举
    intensity: float    # 范围 (0, 1], 情感强度
    anchors: List[str] # 触发的意图锚点标签列表

    def to_dict(self) -> dict:
        return {
            "emotion": round(self.emotion, 3),
            "intent": self.intent,
            "intensity": round(self.intensity, 3),
            "anchors": self.anchors
        }


# ============================================================================
# 意图标签枚举
# ============================================================================

class IntentType:
    """意图标签枚举"""
    SEEK_HELP = "求助"      # 寻求帮助或支持
    SHARE = "分享"          # 主动分享信息或情感
    CHALLENGE = "挑战"      # 对抗、质疑或指责
    CHAT = "闲聊"           # 日常轻松对话
    COMPLAIN = "抱怨"       # 表达不满或负面情绪
    COMMAND = "指令"        # 推动事情，给出明确方向


# ============================================================================
# 规则引擎 — 情绪关键词库
# ============================================================================

# 正向情绪词
POSITIVE_WORDS = {
    "好": 0.2, "喜欢": 0.4, "爱": 0.5, "开心": 0.5, "高兴": 0.4,
    "棒": 0.4, "赞": 0.3, "优秀": 0.4, "完美": 0.5, "谢谢": 0.3,
    "感谢": 0.3, "不错": 0.3, "舒服": 0.4, "愉快": 0.4, "期待": 0.3,
    "希望": 0.3, "相信": 0.2, "满意": 0.4, "惊喜": 0.5, "兴奋": 0.5,
    "哈哈": 0.3, "嘿嘿": 0.3, "太棒了": 0.5, "真棒": 0.5, "爱你": 0.5,
    "加油": 0.3, "厉害": 0.3, "可爱": 0.3, "漂亮": 0.3, "牛": 0.3,
}

# 负向情绪词
NEGATIVE_WORDS = {
    "难过": -0.4, "伤心": -0.4, "生气": -0.5, "愤怒": -0.6, "讨厌": -0.4,
    "烦": -0.3, "糟": -0.4, "差": -0.3, "烂": -0.4, "呸": -0.5,
    "恨": -0.5, "怕": -0.3, "担心": -0.3, "焦虑": -0.4, "压力": -0.3,
    "累": -0.2, "困": -0.2, "饿": -0.2, "疼": -0.3, "痛": -0.3,
    "哭": -0.4, "泪": -0.3, "唉": -0.3, "哼": -0.3,
    "滚": -0.6, "死": -0.4, "烦死了": -0.5, "好烦": -0.4, "无聊": -0.3,
    "不爽": -0.4, "不满": -0.4, "委屈": -0.4, "失望": -0.4,
}

# 强度放大词
INTENSITY_BOOST_WORDS = {
    "超": 0.15, "非常": 0.15, "特别": 0.15, "极其": 0.2, "十分": 0.15,
    "真": 0.1, "太": 0.15, "巨": 0.2, "炸": 0.15,
    "彻底": 0.15, "完全": 0.1, "简直": 0.15, "超级": 0.15,
}


# ============================================================================
# 规则引擎 — 意图识别模式
# ============================================================================

# 求助模式（问句特征优先）
SEEK_HELP_PATTERNS = [
    (r"\?$|？$", 0.8),
    (r"请问|咨询|求解|帮忙|帮帮我|帮我|帮一下", 0.9),
    (r"怎么办|怎么[办做]|如何|为何|为什么", 0.8),
    (r"能不能|会不会|是不是|可不可以", 0.5),
    (r"^(你|我|有)能[^做让叫]|^你可以|有没有人|谁知道", 0.5),
]

# 分享模式（情感表达优先）
SHARE_PATTERNS = [
    (r"[哈哈|嘿嘿|呵|哇|呀|诶|哎]", 0.5),
    (r"开心|高兴|兴奋|激动|快乐|好笑", 0.7),
    (r"告诉(你|他)|跟你说|说实话|真的", 0.6),
    (r"今天|昨天|刚才|刚刚", 0.3),
    (r"太好|真棒|真厉害|好厉害", 0.7),
    (r"考试|成绩|通过了|成功了", 0.4),
]

# 挑战模式（对抗质疑）
CHALLENGE_PATTERNS = [
    (r"凭什么", 1.0),
    (r"不对|不是|错|瞎说|胡说", 0.7),
    (r"质疑|怀疑|不信", 0.7),
    (r"少来|得了吧|拉倒|别扯|算了吧", 0.8),
    (r"你懂什么|你知道什么", 0.8),
]

# 抱怨模式（负面情绪）
COMPLAIN_PATTERNS = [
    (r"好烦|真烦|超烦|烦人|烦死了|累死了", 0.9),
    (r"好累|太累|累死了", 0.7),
    (r"讨厌|怎么又|总是|每次都", 0.6),
    (r"倒霉|不幸|惨|悲催", 0.7),
    (r"不满|委屈|憋屈|郁闷", 0.7),
    (r"什么破|什么鬼|什么玩意儿", 0.7),
    (r"运气差|真倒霉|好倒霉|运气真差", 0.9),
]

# 指令模式（推动事情）
COMMAND_PATTERNS = [
    (r"去做|快去|赶紧|立刻|马上", 0.9),
    (r"必须|一定|一定要|必须得", 0.8),
    (r"听我说|给我|让你", 0.7),
    (r"^[别不要准禁止不许]", 0.8),
    (r"闹了|别闹", 0.7),
    (r"开始|停止|结束", 0.6),
]


# ============================================================================
# 核心分析函数
# ============================================================================

def _preprocess(text: str) -> str:
    """预处理：统一空白字符"""
    text = re.sub(r'\s+', ' ', text.strip())
    return text


def _calculate_emotion(text: str) -> float:
    """计算情绪极性，返回 [-1, 1]"""
    try:
        text_lower = text.lower()
        score = 0.0

        # 统计情绪词
        positive_count = 0
        negative_count = 0

        for word in POSITIVE_WORDS:
            if word in text_lower:
                score += POSITIVE_WORDS[word]
                positive_count += 1

        for word in NEGATIVE_WORDS:
            if word in text_lower:
                score += NEGATIVE_WORDS[word]
                negative_count += 1

        # 标点放大效应
        exclamation_count = text.count('!') + text.count('！')
        if exclamation_count > 0:
            score *= (1 + 0.1 * min(exclamation_count, 3))

        # 感叹号且有情绪词时强化
        if exclamation_count > 0 and (positive_count > 0 or negative_count > 0):
            score *= 1.2

        # clamp到[-1, 1]
        return max(-1.0, min(1.0, score))

    except Exception:
        return 0.0


def _calculate_intensity(text: str, emotion_score: float) -> float:
    """计算情感强度，返回 (0, 1]"""
    try:
        text_lower = text.lower()
        length = max(len(text), 1)

        # 1. 情绪词密度
        emotion_word_count = 0
        for word in POSITIVE_WORDS:
            emotion_word_count += text_lower.count(word)
        for word in NEGATIVE_WORDS:
            emotion_word_count += text_lower.count(word)

        emotion_density = emotion_word_count / length
        intensity = min(0.3, emotion_density * 5)

        # 2. 标点放大效应
        exclamation_count = text.count('!') + text.count('！')
        intensity += min(0.15, exclamation_count * 0.08)

        question_count = text.count('?') + text.count('？')
        intensity += min(0.1, question_count * 0.05)

        # 句末标点加成
        stripped = text.strip()
        if stripped.endswith('!') or stripped.endswith('！'):
            intensity += 0.1
        if stripped.endswith('?') or stripped.endswith('？'):
            intensity += 0.05

        # 3. 强度词加成
        for word, boost in INTENSITY_BOOST_WORDS.items():
            if word in text_lower:
                intensity += boost

        # 4. 情感浓度
        intensity += abs(emotion_score) * 0.2

        # 基线强度
        intensity = max(intensity, 0.5)

        return max(0.1, min(1.0, intensity))

    except Exception:
        return 0.5


def _recognize_intent(text: str) -> tuple[str, List[str]]:
    """识别意图类型，返回 (intent_tag, anchors)"""
    try:
        text_lower = text.lower()
        text_stripped = text.strip()
        text_len = len(text_stripped)

        scores = {
            IntentType.SEEK_HELP: 0.0,
            IntentType.SHARE: 0.0,
            IntentType.CHALLENGE: 0.0,
            IntentType.CHAT: 0.0,
            IntentType.COMPLAIN: 0.0,
            IntentType.COMMAND: 0.0,
        }
        anchor_records = []

        # 模式匹配
        for pattern, weight in SEEK_HELP_PATTERNS:
            if re.search(pattern, text_lower):
                scores[IntentType.SEEK_HELP] += weight
                anchor_records.append(("求助", pattern))

        for pattern, weight in SHARE_PATTERNS:
            if re.search(pattern, text_lower):
                scores[IntentType.SHARE] += weight
                anchor_records.append(("分享", pattern))

        for pattern, weight in CHALLENGE_PATTERNS:
            if re.search(pattern, text_lower):
                scores[IntentType.CHALLENGE] += weight
                anchor_records.append(("挑战", pattern))

        for pattern, weight in COMPLAIN_PATTERNS:
            if re.search(pattern, text_lower):
                scores[IntentType.COMPLAIN] += weight
                anchor_records.append(("抱怨", pattern))

        for pattern, weight in COMMAND_PATTERNS:
            if re.search(pattern, text_lower):
                scores[IntentType.COMMAND] += weight
                anchor_records.append(("指令", pattern))

        # 句末标点特殊加成
        if text_len >= 3:
            if text_stripped.endswith('?') or text_stripped.endswith('？'):
                scores[IntentType.SEEK_HELP] += 0.6
                anchor_records.append(("求助", "question_ending"))

            if text_stripped.endswith('!') or text_stripped.endswith('！'):
                if any(w in text_lower for w in ["好", "太", "真", "棒", "厉害", "开心"]):
                    scores[IntentType.SHARE] += 0.5
                    anchor_records.append(("分享", "exclamation_ending"))

        # 闲聊检测：短句（<=5字）且无任何模式匹配
        has_any_match = any(score > 0 for score in scores.values())

        # 短句且感叹号结尾 → 闲聊
        if text_len <= 5 and (text_stripped.endswith('!') or text_stripped.endswith('！')):
            return IntentType.CHAT, ["chat:greeting"]

        if text_len <= 5 and not has_any_match:
            return IntentType.CHAT, ["chat:greeting"]

        # 选择得分最高的意图
        best_intent = max(scores, key=scores.get)
        best_score = scores[best_intent]

        if best_score < 0.5:
            return IntentType.CHAT, ["chat:default"]

        # 构建anchors
        anchors = []
        for category, pattern in anchor_records:
            if category == best_intent and len(anchors) < 2:
                short_pattern = pattern.replace("|", ",")[:25]
                anchors.append(f"{category.lower()}:{short_pattern}")

        if not anchors:
            anchors = [best_intent.lower()]

        return best_intent, anchors

    except Exception:
        return IntentType.CHAT, ["chat:fallback"]


# ============================================================================
# 主入口函数
# ============================================================================

def analyze_semantic(raw_input: str) -> dict:
    """
    感性认识模块主入口

    Args:
        raw_input: str — 用户输入的单句话

    Returns:
        dict — semantic_packet
            {
                "emotion": float,   # 范围 [-1, 1]
                "intent": str,      # 意图标签
                "intensity": float, # 范围 (0, 1]
                "anchors": list     # 意图锚点标签
            }
    """
    # 默认值兜底
    default_packet = {
        "emotion": 0.0,
        "intent": IntentType.CHAT,
        "intensity": 0.5,
        "anchors": []
    }

    try:
        # 边界检查
        if not raw_input or not isinstance(raw_input, str):
            return default_packet

        # 预处理
        text = _preprocess(raw_input)
        if not text:
            return default_packet

        # 1. 情绪计算
        emotion = _calculate_emotion(text)

        # 2. 强度计算
        intensity = _calculate_intensity(text, emotion)

        # 3. 意图识别
        intent, anchors = _recognize_intent(text)

        # 构建输出
        packet = SemanticPacket(
            emotion=emotion,
            intent=intent,
            intensity=intensity,
            anchors=anchors
        )

        return packet.to_dict()

    except Exception:
        return default_packet


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    test_cases = [
        # 闲聊
        ("你好啊！", "闲聊"),
        ("嗨，在吗", "闲聊"),
        ("嗯嗯", "闲聊"),

        # 分享
        ("我今天很开心！", "分享"),
        ("哈哈，太好笑了", "分享"),
        ("告诉你一个秘密", "分享"),

        # 求助
        ("怎么解决这个问题？", "求助"),
        ("请问这个怎么做", "求助"),
        ("你能帮我吗", "求助"),

        # 挑战
        ("我觉得你不对", "挑战"),
        ("凭什么要听你的", "挑战"),
        ("少来这套", "挑战"),

        # 抱怨
        ("我好烦啊", "抱怨"),
        ("烦死了，什么破事", "抱怨"),
        ("今天运气真差", "抱怨"),

        # 指令
        ("快去做作业", "指令"),
        ("你必须听我的", "指令"),
        ("别闹了", "指令"),
    ]

    print("=" * 60)
    print("感性认识模块测试")
    print("=" * 60)

    correct = 0
    for text, expected_intent in test_cases:
        result = analyze_semantic(text)
        status = "✓" if result["intent"] == expected_intent else "✗"
        if result["intent"] == expected_intent:
            correct += 1
        print(f"\n{status} 输入: {text}")
        print(f"  期望: {expected_intent}, 输出: {result['intent']}")
        print(f"  emotion={result['emotion']}, intensity={result['intensity']}")
        print(f"  anchors: {result['anchors']}")

    print("\n" + "=" * 60)
    print(f"准确率: {correct}/{len(test_cases)} ({100*correct/len(test_cases):.1f}%)")
