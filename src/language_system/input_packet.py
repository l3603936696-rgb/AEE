"""
InputPacket — 输入包（v1.0）

将原始输入解析为三个连续分数：
1. topic_anchor      — 话题锚：输入激活了哪些状态维度（最强的 2 个）
2. relational_direction — 关系方向：说的是她 / 说话者 / 外部事物
3. social_intent     — 意图类型：问句 / 分享 / 陈述

纯函数，不修改 entity 状态，不依赖 entity。
"""

import math
from typing import Dict

_SELF_KEYWORDS    = ["你", "您"]
_OTHER_KEYWORDS   = ["我", "俺", "咱"]
_QUESTION_MARKERS = ["吗", "嘛", "呢", "？", "?", "怎么", "什么", "为什么", "哪", "谁", "几", "多少"]
_SHARING_MARKERS  = ["感觉", "觉得", "好像", "有点", "有些"]

_TOPIC_MIN_STRENGTH = 0.01
_TOPIC_MAX_DIMS     = 2


def build_input_packet(
    raw_input: str,
    concept_bias: Dict[str, float],
) -> Dict:
    """
    构建输入包。

    参数：
        raw_input    : 原始输入文本（空字符串或 None 均可）
        concept_bias : 概念图激活结果 {dim: delta}

    返回：
        {
            "topic_anchor":          {dim: strength},
            "relational_direction":  {"self": s, "other": o, "external": e},
            "social_intent":         {"question": q, "sharing": sh, "statement": st},
        }
    """
    text = raw_input or ""

    # ------------------------------------------------------------------
    # 1. 话题锚：concept_bias 中绝对值最大的前 N 维
    # ------------------------------------------------------------------
    topic_anchor: Dict[str, float] = {}
    if concept_bias:
        ranked = sorted(concept_bias.items(), key=lambda x: abs(x[1]), reverse=True)
        for dim, strength in ranked[:_TOPIC_MAX_DIMS]:
            if abs(strength) >= _TOPIC_MIN_STRENGTH:
                topic_anchor[dim] = strength

    # ------------------------------------------------------------------
    # 2. 关系方向（连续分数，无 if/else）
    # ------------------------------------------------------------------
    self_hits  = sum(text.count(k) for k in _SELF_KEYWORDS)
    other_hits = sum(text.count(k) for k in _OTHER_KEYWORDS)

    # tanh 把命中数压到 (0,1)，避免一句话多个"我"无限放大
    self_raw     = math.tanh(self_hits  * 0.8)
    other_raw    = math.tanh(other_hits * 0.8)
    # 没有人称代词时 external 默认高
    external_raw = math.exp(-(self_hits + other_hits) * 0.5) * 0.8

    _rd_sum = self_raw + other_raw + external_raw + 1e-9
    relational_direction = {
        "self":     self_raw     / _rd_sum,
        "other":    other_raw    / _rd_sum,
        "external": external_raw / _rd_sum,
    }

    # ------------------------------------------------------------------
    # 3. 意图类型（连续分数，无 if/else）
    # ------------------------------------------------------------------
    q_raw  = math.tanh(sum(text.count(m) for m in _QUESTION_MARKERS) * 0.4)

    # 分享 = 说话者（other_hits > 0）+ 情绪/感觉关键词
    sh_raw = math.tanh(
        other_raw * sum(text.count(m) for m in _SHARING_MARKERS) * 0.6
    )

    # 陈述 = 以上都弱时的基线
    st_raw = math.exp(-(q_raw + sh_raw))

    _si_sum = q_raw + sh_raw + st_raw + 1e-9
    social_intent = {
        "question":  q_raw  / _si_sum,
        "sharing":   sh_raw / _si_sum,
        "statement": st_raw / _si_sum,
    }

    # ------------------------------------------------------------------
    # 4. 句法结构（SVO）
    # ------------------------------------------------------------------
    try:
        from .syntax_parser import parse_svo
        svo = parse_svo(text)
    except Exception:
        svo = {
            "subject": "", "predicate": "", "object": "",
            "negated": False, "question": False,
            "agent_dir": "external", "patient_dir": "external",
        }

    # 用句法结构修正关系方向（比代词计数更准）
    if svo["agent_dir"] != "external":
        # 句法级施事明确时覆盖统计值
        relational_direction = {
            "self":     float(svo["agent_dir"] == "xia"),
            "other":    float(svo["agent_dir"] == "speaker"),
            "external": float(svo["agent_dir"] == "external"),
        }
    if svo["question"] and svo["patient_dir"] == "xia":
        # 问的是她 → self 方向拉满
        relational_direction = {"self": 1.0, "other": 0.0, "external": 0.0}

    # 否定时翻转话题锚的符号（不累，不重 → 对应维度偏置反向）
    if svo["negated"]:
        topic_anchor = {dim: -v for dim, v in topic_anchor.items()}

    return {
        "topic_anchor":          topic_anchor,
        "relational_direction":  relational_direction,
        "social_intent":         social_intent,
        "svo":                   svo,
    }
