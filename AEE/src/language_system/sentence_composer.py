"""
Sentence Composer — 句子组合模块（v1.0）

将锚点词组合成完整中文短句的模板库 + softmax 采样系统。

子模块：
    sentence_composer_schema.py   — 超参 + 数学辅助函数
    sentence_composer_patterns.py — PATTERNS + COMPOUND_PATTERNS 数据
    sentence_composer_helpers.py — 独立数学 helpers
    sentence_composer.py         — 核心组合逻辑
"""

import logging
import random
from typing import Callable, Dict, List, Optional, Tuple

from .sentence_composer_schema import (
    _COMPOSE_TEMP_BASE,
    _COMPOSE_TEMP_BOREDOM_GAIN,
    _ANCHOR_USE_BONUS,
    _ANCHOR_STRENGTH_GAIN,
    _ANCHOR_POS_WEIGHT,
    _STRUCTURE_BONUS_SCALE,
    _template_structure_score,
    _g,
    _anchor_penalty,
    _softmax_sample,
)

logger = logging.getLogger(__name__)

from .sentence_composer_patterns import PATTERNS, COMPOUND_PATTERNS
from .sentence_composer_helpers import _template_theoretical_max, _softmax_sample, _precompute_template_scales

# 预计算每个模板的归一化封顶值
_precompute_template_scales(PATTERNS)


def compose_sentence(
    anchor: str,
    state: Dict[str, float],
    connector: str = "",
    template_efficiency: Optional[Dict[int, float]] = None,
    learned_weights: Optional[Dict[int, Dict[str, float]]] = None,
    extra_templates: Optional[List[Dict]] = None,
    second_anchor: Optional[str] = None,
    temperature: float = _COMPOSE_TEMP_BASE,
    anchor_score: float = 0.0,
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

        # 量纲归一化封顶：超过 1.0 的家族压回 [0,1]，≤1.0 的恒等通过（PLAN §3）。
        score = score / p.get("_score_divisor", 1.0)

        if learned_weights and i in learned_weights:
            lw = learned_weights[i]
            # 防御未归一化维度（time_since_last_*）撑爆学习权重贡献：
            # state 值 clamp 到 [0,1]，与其他评分项保持同一量纲，避免天文数字。
            score += sum(
                w * max(0.0, min(1.0, state.get(dim, 0.0)))
                for dim, w in lw.items()
            )

        pos = p.get("anchor_pos", "head")
        score -= _anchor_penalty(len(anchor), pos)
        # 锚点使用奖励 × (1 + 强度增益)：锚点被选得越强，越压过无锚点模板
        score += _ANCHOR_USE_BONUS * _ANCHOR_POS_WEIGHT.get(pos, 0.0) * (1.0 + _ANCHOR_STRENGTH_GAIN * anchor_score)

        if template_efficiency and i in template_efficiency:
            score += min(template_efficiency[i], 0.5)

        # 结构性加成：带逻辑连接词的模板持续获得 softmax 偏向
        score += _STRUCTURE_BONUS_SCALE * _template_structure_score(p.get("template", ""))

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

    chosen_idx = _softmax_sample(raw_scores, temperature=temperature)

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
        # 心事引用模板：用 _preoccupation_about 填充 {about}
        if chosen.get("_uses_about") and "{about}" in template:
            _about = state.get("_preoccupation_about", "")
            if _about:
                sentence = template.replace("{about}", _about)
            else:
                # 没有心事对象 → 退回锚词
                sentence = _fill_anchor(template.replace("{about}", "{anchor}"), anchor)
        else:
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

    _sys.path.insert(0, str(_Path(__file__).parent.parent.parent.parent))

    from AEE.src.language_system.sentence_composer import compose_sentence, PATTERNS

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
