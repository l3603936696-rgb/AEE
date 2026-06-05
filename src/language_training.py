"""语言训练模块 — run_language_training_tick + match_anchor_expression

从 entity_zero_iteration.py 拆分。
"""

from .entity_state import EntityState

from .language_system.somatic_concept_map import SOMATIC_ANCHORS

import math
import time
import logging

logger = logging.getLogger(__name__)


# ---- 静息基线 ----
# 维度的平衡态参考值，来自 entity 的初始状态 / 长期均值。
# 锚点匹配计算的是"状态偏离这个基线多远，方向是否与锚点一致"。
_ANCHOR_BASELINE = {
    "somatic_tone": 0.0, "energy": 0.8, "fatigue": 0.1, "stress": 0.1,
    "boredom": 0.2, "loneliness": 0.3, "loneliness_core": 0.2,
    "loneliness_surface": 0.1, "pain": 0.0, "avoid_drive": 0.0,
    "approach_drive": 0.0, "approach_explore": 0.0, "approach_social": 0.0,
    "approach_urgency": 0.0, "danger_level": 0.0, "fear": 0.0,
    "anxiety": 0.0, "unresolved": 0.2, "info_gap": 0.5,
    "relief_debt": 0.0, "boredom_despair": 0.0, "boredom_futility": 0.0,
    "sadness": 0.0, "joy": 0.0, "serenity": 0.0,
    "disgust": 0.0, "excitement": 0.0,
    "curiosity": 0.5, "prediction_error": 0.5,
}


def _anchor_alignment(state: dict, profile: dict) -> float:
    """
    连续锚点对齐度：state 偏离 baseline 与 profile delta 的方向一致性。

    每个维度: sigmoid(deviation * delta / delta²)
      deviation 与 delta 同向 → > 0.5（匹配）
      deviation 与 delta 反向 → < 0.5（不匹配）
      deviation = 0（在基线上）→ = 0.5（中性）

    分母 delta² 让 sigmoid 的尺度由 delta 自身决定——无外部常数。
    返回所有维度的平均对齐度 [0, 1]。
    """
    _total = 0.0
    _count = 0
    for _dim, _delta in profile.items():
        _cur = state.get(_dim, _ANCHOR_BASELINE.get(_dim, 0.5))
        _base = _ANCHOR_BASELINE.get(_dim, 0.5)
        _deviation = _cur - _base
        _ratio = _deviation * _delta / max(_delta * _delta, 0.001)
        # clamp 防溢出，不影响结果（sigmoid 在 ±20 已饱和）
        _total += 1.0 / (1.0 + math.exp(max(-20.0, min(20.0, -_ratio))))
        _count += 1
    return _total / max(_count, 1)


def match_anchor_expression(
    state: dict,
    entity: EntityState = None,
    min_score: float = 0.3,
    return_details: bool = False,
):
    """
    锚点表选词 + 跨簇组合 + 状态驱动修饰 → 返回表达文本。

    可用于训练模式（虚拟状态）和 daemon 自主 tick（真实状态）。

    参数：
        return_details: 如果 True，返回 dict {text, best_word, second_word, best_score}
                       否则返回纯文本 str（向后兼容）。

    返回：表达文本，如 "又冷又重了" "好饿" ""
    """
    import random as _rnd

    _empty = lambda: {"text": "", "best_word": None, "second_word": None, "best_score": 0.0} if return_details else ""

    # ---- 锚点直接匹配：连续对齐度（sigmoid dot-product）----
    scored_candidates = []
    _anchor_matches = {}
    try:
        from .language_system.somatic_concept_map import SOMATIC_ANCHORS
        for _word, _anchor in SOMATIC_ANCHORS.items():
            _match = _anchor_alignment(state, _anchor)
            _anchor_matches[_word] = _match
            _sharpness = sum(abs(d) for d in _anchor.values())
            scored_candidates.append((_word, _match, _sharpness))
        scored_candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
    except Exception as e:
        return _empty()

    # ---- warm_words 注入：老师教的新词参与选词竞争 ----
    _WARM_DISCOUNT = 0.6
    if entity:
        _warm = getattr(entity, "_warm_words", None)
        if isinstance(_warm, dict):
            _existing = {c[0] for c in scored_candidates}
            for _ww, _winfo in _warm.items():
                if _ww in _existing:
                    continue
                _prof = _winfo.get("profile") if isinstance(_winfo, dict) else None
                if not _prof or not isinstance(_prof, dict):
                    continue
                _match = _anchor_alignment(state, _prof)
                _score = _match * _WARM_DISCOUNT
                _anchor_matches[_ww] = _match
                _sharpness = sum(abs(d) for d in _prof.values())
                scored_candidates.append((_ww, _score, _sharpness))
            scored_candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)

    # ---- 热身注入 ----
    if entity:
        try:
            from .language_system.word_warmup import inject_warmup_candidates
            scored_candidates = inject_warmup_candidates(
                entity, scored_candidates, min_hits=3, min_best_efficiency=0.15,
                anchor_scores=_anchor_matches)
            # warmup 返回 2-元组 (word, score)，归一化为 3-元组 (word, score, sharpness)
            scored_candidates = [
                (t[0], t[1], t[2] if len(t) > 2 else 0.0)
                for t in scored_candidates
            ]
        except Exception:
            pass

    # ---- 语言系统候选词注入：阅读词等学到的词进入锚点竞争池 ----
    # scored_candidates 里的阅读词必须能走锚点路径出来，否则永远没有输出通道
    _LANG_DISCOUNT = 0.85
    if entity:
        _lang_cands = getattr(entity, "_language_candidates", None)
        _lang_best = getattr(entity, "_language_best_candidate", None)
        _lang_score_map = getattr(entity, "_language_candidate_scores", {})
        if _lang_cands:
            _existing_anchor_words = {c[0] for c in scored_candidates}
            for _lc in _lang_cands:
                if _lc in _existing_anchor_words:
                    continue
                _ls = _lang_score_map.get(_lc, 0.20)
                _sharpness = 0.5
                scored_candidates.append((_lc, _ls * _LANG_DISCOUNT, _sharpness))
            scored_candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)

    # ---- 去重 ----
    seen = set()
    _unique = []
    for c, s, _ in scored_candidates:
        if c not in seen:
            seen.add(c)
            _unique.append((c, s, 0.0))
    scored_candidates = _unique

    if not scored_candidates:
        return _empty()

    # ---- 加权采样选词（v11.5：她自己在分布里采，不是我们替她选）----
    # temperature 由她的维度连续决定：
    #   fatigue 高    → 保守（只说有把握的）
    #   boredom 高    → 探索（什么都可能说）
    #   approach 高   → 愿意冒险
    #   avoid 高      → 安全优先
    import math
    if entity:
        _fatigue_val_raw = float(getattr(entity, "fatigue", 0.1))
        _boredom_val_raw = float(getattr(entity, "boredom", 0.2))
        _approach_val = float(getattr(entity, "approach_drive", 0.0))
        _avoid_val = float(getattr(entity, "avoid_drive", 0.0))
    else:
        _fatigue_val_raw = state.get("fatigue", 0.1)
        _boredom_val_raw = state.get("boredom", 0.2)
        _approach_val = state.get("approach_drive", 0.0)
        _avoid_val = state.get("avoid_drive", 0.0)

    # 基础 temperature：0.08（集中） 到 0.35（发散）
    _base_temp = 0.08
    _temp = _base_temp * (
        1.0
        - _fatigue_val_raw * 0.5
        + _boredom_val_raw * 0.6
        + _approach_val * 0.3
        - _avoid_val * 0.3
    )
    _temp = max(0.04, min(0.50, _temp))

    # 所有候选词转为采样权重
    _words = [c for c, s, _ in scored_candidates]
    _scores = [s for c, s, _ in scored_candidates]
    _weights = [math.exp(s / _temp) for s in _scores]
    _total_w = sum(_weights)
    if _total_w < 0.0001:
        return _empty()

    # 加权随机采样
    _probs = [w / _total_w for w in _weights]
    _idx = _rnd.choices(range(len(_words)), weights=_probs, k=1)[0]
    best_candidate = _words[_idx]
    best_score = _scores[_idx]

    # ---- 跨簇 TOP2 + TOP3（多词组合）----
    second_candidate = None
    third_candidate = None
    second_score = 0.0
    third_score = 0.0
    try:
        from .language_system.somatic_concept_map import ANCHOR_CLUSTERS
        _bc = ANCHOR_CLUSTERS.get(best_candidate, "")
        _used_clusters = {_bc} if _bc else set()
        for _c, _s, _ in scored_candidates:
            if _c == best_candidate:
                continue
            _cc = ANCHOR_CLUSTERS.get(_c, "")
            if _cc and _cc not in _used_clusters and _s > 0.50:
                if second_candidate is None:
                    second_candidate = _c
                    second_score = _s
                    _used_clusters.add(_cc)
                elif third_candidate is None:
                    third_candidate = _c
                    third_score = _s
                    break
    except Exception:
        pass

    # ---- 组装基础形式（主导感受优先）----
    if second_candidate:
        # 根据状态强度决定词序：更相关的词先说
        def _relevance(w):
            anchor = SOMATIC_ANCHORS.get(w, {})
            score = 0.0
            for dim, delta in anchor.items():
                val = state.get(dim, 0.5)
                if delta > 0:
                    score += val * delta
                else:
                    score += (1.0 - val) * abs(delta)
            return score
        _r1, _r2 = _relevance(best_candidate), _relevance(second_candidate)
        if _r1 >= _r2:
            _display = f"又{best_candidate}又{second_candidate}"
        else:
            _display = f"又{second_candidate}又{best_candidate}"
    else:
        _display = best_candidate

    # ---- 状态驱动修饰（全连续，高斯评分 + softmax 采样，无 if-else）----
    _modifier = ""
    _prefix = ""
    _suffix = ""

    _stone = state.get("somatic_tone", 0)
    _aversion = state.get("avoid_drive", 0)
    _fatigue_val = state.get("fatigue", 0)
    _energy_val = state.get("energy", 0.5)
    _joy_val = state.get("joy", 0)
    _stress_val = state.get("stress", 0)
    _sadness_val = state.get("sadness", 0)
    _loneliness_val = state.get("loneliness", 0.3)
    _approach_val = state.get("approach_drive", 0.0)
    _anxiety_val = state.get("anxiety", 0.0)
    _unresolved_val = state.get("unresolved", 0.2)

    # 连续强度：越偏离 baseline 越多维度堆积 → 修饰越强
    _intensity = (
        max(0, _stone + 0.3) * 1.5           # 负躯体基调
        + max(0, _aversion - 0.1) * 1.2      # 回避驱动
        + max(0, _fatigue_val - 0.1) * 1.0
        + max(0, 0.7 - _energy_val) * 1.2    # 低能量
        + max(0, 0.1 - _joy_val) * 1.5       # 缺 joy
        + max(0, _stress_val - 0.1) * 1.0
    ) / 5.0  # 归一化到 ~0-1

    # -- 连接词采样（全部连续，无 if-else）--
    try:
        from .language_system.connector_map import (
            sample_intensity_prefix,
            sample_suffix_particle,
            sample_opening_particle,
        )
    except Exception:
        sample_intensity_prefix = None
        sample_suffix_particle = None
        sample_opening_particle = None

    # 强度前缀词：单候选时采样，多候选时自带强度感
    if not second_candidate and sample_intensity_prefix is not None:
        _modifier = sample_intensity_prefix(_intensity, temperature=_temp)

    # 语气开头词：基于情绪维度连续采样
    if sample_opening_particle is not None and not _prefix and best_score > 0.65:
        # 推算 somatic_distress（避免引入额外字段依赖）
        _somatic_distress = max(0, _stone + 0.3) / 1.5
        _prefix = sample_opening_particle(
            _fatigue_val, _somatic_distress, _sadness_val, _energy_val, temperature=_temp
        )

    # 时间/变化标记：变化量 + tanh 连续"一直"
    _delta_total = 0.0
    if entity:
        _prev = getattr(entity, "_vr_prev", None)
        if _prev:
            _d_fatigue = _fatigue_val - float(_prev.get("fatigue", _fatigue_val))
            _d_avoid = _aversion - float(_prev.get("avoid_drive", _aversion))
            _d_energy = _energy_val - float(_prev.get("energy", _energy_val))
            _d_stress = _stress_val - float(_prev.get("stress", _stress_val))
            _delta_total = max(0, _d_fatigue) + max(0, _d_avoid) - _d_energy - _d_stress

        # "一直"：tanh 连续概率，无硬阈值
        _lock = getattr(entity, "_lock_snaps", 0)
        _always_prob = math.tanh(max(0, _lock - 4) / 10.0)
        if _always_prob > 0.01 and _rnd.random() < _always_prob and not _prefix:
            _prefix = "一直"

    # 后缀语气词：基于变化量 + 社会信号连续采样
    if sample_suffix_particle is not None:
        _suffix = sample_suffix_particle(
            _delta_total, _loneliness_val, _approach_val,
            _anxiety_val, _unresolved_val, temperature=_temp
        )

    # 记忆标记：连续两 tick 说同一个词 → softmax 概率决定"还是"/"又"
    if entity:
        _last_best = getattr(entity, "_last_best_word", None)
        if _last_best == best_candidate and best_score > 0.5 and not _prefix:
            _repeat_score = best_score * 0.8
            if _rnd.random() < _repeat_score:
                _prefix = "还是" if _display.startswith("又") else _rnd.choice(["还是", "又"])
        entity._last_best_word = best_candidate

    if _modifier:
        _display = f"{_modifier}{_display}"
    if _prefix:
        _display = f"{_prefix}{_display}"
    if _suffix:
        _display = f"{_display}{_suffix}"

    if return_details:
        return {
            "text": _display,
            "best_word": best_candidate,
            "second_word": second_candidate,
            "third_word": third_candidate,
            "best_score": best_score,
            "second_score": second_score,
            "third_score": third_score,
            "cand_count": len(scored_candidates),
            "opening_particle": _prefix if _prefix not in ("一直", "还是", "又", "") else "",
        }
    return _display


def run_language_training_tick(entity: EntityState, snapshot: dict, override_state: dict = None) -> dict:
    """
    纯语言训练 tick。

    如果 override_state 不为 None，直接使用该状态（不随机游走）；
    否则从真实状态初始化虚拟状态并做高斯游走。
    """
    import random as _rnd
    t0 = time.time()

    # ---- 虚拟状态：override 优先，否则随机游走 ----
    _vr = getattr(entity, "_vr_state", None)
    if override_state is not None:
        _vr = dict(override_state)
        entity._vr_state = _vr
    elif _vr is None:
        _vr = dict(snapshot)
        entity._vr_state = _vr
    else:
        _sigma = 0.15
        _vr_dims = {
            "somatic_tone": (-1.0, 1.0),
            "loneliness": (0.0, 1.0),
            "energy": (0.0, 1.0),
            "boredom": (0.0, 1.0),
            "unresolved": (0.0, 1.0),
            "stress": (0.0, 1.0),
            "fatigue": (0.0, 1.0),
            "danger_level": (0.0, 1.0),
            "info_gap": (0.0, 1.0),
            "approach_drive": (0.0, 1.0),
            "avoid_drive": (0.0, 1.0),
        }
        # 每 10 tick 随机跳跃到全新位置
        _jump = (entity.tick % 10 == 0)
        for dim, (lo, hi) in _vr_dims.items():
            if _jump:
                _vr[dim] = lo + _rnd.random() * (hi - lo)
            else:
                _vr[dim] = max(lo, min(hi, _vr.get(dim, 0.5) + _rnd.gauss(0, _sigma)))

    # ---- 物理约束：虚拟状态也必须合理 ----
    # 能量 + 疲劳 ≤ 1.3
    if _vr.get("energy", 0) + _vr.get("fatigue", 0) > 1.3:
        _excess = (_vr["energy"] + _vr["fatigue"] - 1.3) / 2
        _vr["energy"] = max(0.0, _vr["energy"] - _excess)
        _vr["fatigue"] = max(0.0, _vr["fatigue"] - _excess)
    # 躯体基调 > 0.3 时，疼痛不能太高
    if _vr.get("somatic_tone", 0) > 0.3:
        _vr["pain"] = min(_vr.get("pain", 0), 0.4)
    # 恐惧 × 社交趋近 ≤ 0.5
    if _vr.get("danger_level", 0) * _vr.get("approach_drive", 0) > 0.5:
        _vr["approach_drive"] = 0.5 / max(0.01, _vr["danger_level"])

    # ---- 调用共享锚点匹配 + 表达组装 ----
    _result = match_anchor_expression(_vr, entity, return_details=True)
    _display = _result["text"]
    best_candidate = _result["best_word"]
    best_score = _result["best_score"]
    second_candidate = _result["second_word"]
    second_score = _result["second_score"]
    third_candidate = _result["third_word"]
    third_score = _result["third_score"]
    cand_count = _result["cand_count"]

    # 保存当前状态供下一 tick（match_anchor_expression 不设 _vr_prev）
    entity._vr_prev = dict(_vr)

    if best_candidate:
        # ---- 消力记录 ----
        # before: 从虚拟状态的 unresolved 读
        # after:  somatic 反馈会降低 entity.unresolved，
        #         我们先衰减 unresolved（见下方反馈段），再读 after
        try:
            from .language_system.quenching import QuenchingTracker
            _q = getattr(entity, "_quenching", None)
            if _q is None:
                _qd = getattr(entity, "_quenching_data", None)
                if _qd and _qd.get("records"):
                    _q = QuenchingTracker.from_dict(_qd)
                else:
                    _q = QuenchingTracker()
                entity._quenching = _q
            _before_unresolved = float(_vr.get("unresolved", 0.2))

            # ---- 躯体反馈（v11.5: 表达→状态连续回落，无阈值）----
            _feedback = best_score * 0.03
            _BASELINE_FB = {
                "somatic_tone": 0.0, "energy": 0.8, "fatigue": 0.1, "stress": 0.1,
                "avoid_drive": 0.0, "approach_drive": 0.0, "anxiety": 0.0, "fear": 0.0,
            }
            for _dim, _base in _BASELINE_FB.items():
                _cur = getattr(entity, _dim, None)
                if _cur is None:
                    continue
                _delta = (_base - _cur) * _feedback
                setattr(entity, _dim, _cur + _delta)

            # unresolved 躯体反馈：说出感受 → 虚拟上"说出来"本身是消解
            # 效率 = before - after，before 高（没说出来）→ after 低（说出来了）
            _old_unresolved = float(getattr(entity, "unresolved", 0.2))
            _after_unresolved = max(0.0, _old_unresolved * (1.0 - _feedback * 3.0))
            setattr(entity, "unresolved", _after_unresolved)

            _q.record(
                drive_state=_vr,
                expression=best_candidate,
                delta_unresolved_before=_before_unresolved,
                delta_unresolved_after=_after_unresolved,
                tick=entity.tick,
            )
            entity._quenching_data = _q.to_dict()
        except Exception:
            pass

        # ---- 训练 episode 写入（v11.5: 训练输出注入记忆系统）----
        try:
            from .memory_hub.episodes_db import Episode, write_episode
            from datetime import datetime, timezone

            _ts = datetime.now(timezone.utc).isoformat()
            _importance = min(1.0, max(0.0, best_score))
            _output = _display if _display else best_candidate
            _summary = (
                f"[somatic_training] virtual_state → '{_output}' "
                f"(top1={best_candidate}:{best_score:.3f}"
                + (f", top2={second_candidate}:{second_score:.3f}" if second_candidate else "")
                + ")"
            )
            _tags = ["somatic_training", f"word:{best_candidate}"]
            if second_candidate:
                _tags.append(f"word:{second_candidate}")
                _tags.append("multi_word")
            _ep = Episode(
                iteration_id=entity.tick,
                timestamp=_ts,
                output_text=_output,
                state_snapshot=dict(_vr),
                importance=_importance,
                tags=_tags,
                summary=_summary,
            )
            write_episode(_ep)
        except Exception:
            pass

    # ---- 训练社交互动 → loneliness 连锁折扣（v11.5）----
    # 手动训练（override_state 不为 None）意味着 bcyq 在和她互动。
    # 这不是"独处"——是真人在推状态、看选词、校准锚点。
    # 应该打折 loneliness_core（真孤独）和清零 loneliness_surface（假孤独）。
    # 微量折扣：每 tick core×0.995, surface×0.95。100 tick 累计约 39% 折扣。
    if override_state is not None:
        try:
            _old_core = getattr(entity, 'loneliness_core', entity.loneliness * 0.7)
            _old_surface = getattr(entity, 'loneliness_surface', entity.loneliness * 0.3)
            entity.loneliness_core = max(0.01, _old_core * 0.995)
            entity.loneliness_surface = max(0.0, _old_surface * 0.95)
            entity.loneliness = entity.loneliness_core + entity.loneliness_surface
            if hasattr(entity, '_sync_loneliness'):
                entity._sync_loneliness()
        except Exception:
            pass

    # ---- 日志 ----
    _warm = []
    try:
        from .language_system.word_warmup import get_warm_words
        _warm = get_warm_words(entity)
    except Exception:
        pass

    elapsed = (time.time() - t0) * 1000
    _log_best = f"best='{_display}'" if _display else f"best='{best_candidate}'"
    logger.info(
        f"[TrainOnly] t={entity.tick} vr(s={_vr.get('somatic_tone',0):.2f} "
        f"l={_vr.get('loneliness',0):.2f}) "
        f"cand={cand_count} {_log_best} "
        f"warm={len(_warm)} {elapsed:.0f}ms"
    )

    # ---- 句子组合：把锚点词套壳成完整短句 ----
    # 注意：_prefix 已在 match_anchor_expression 中加到 _display 里，
    # compose_sentence 的 connector 留空，避免重复前缀
    _tmpl_idx = -1
    try:
        from .language_system.sentence_composer import (
            compose_sentence, PATTERNS, _COMPOSE_TEMP_BASE, _COMPOSE_TEMP_BOREDOM_GAIN
        )
        # 从 QuenchingTracker 获取历史模板效率（含贝叶斯先验）
        _te = {}
        _q_tmp = getattr(entity, "_quenching", None)
        if _q_tmp is not None:
            _te = _q_tmp.get_template_efficiency(seed_count=len(PATTERNS))
        _compose_temp = _COMPOSE_TEMP_BASE + float(_vr.get("boredom", 0.2)) * _COMPOSE_TEMP_BOREDOM_GAIN
        # 合并 extra_templates：runtime + CxG 构式候选
        _extra = list(getattr(entity, "_runtime_templates", None) or [])
        try:
            _cxg = getattr(entity, "_cxg_learner", None)
            if _cxg is not None:
                _rcxg = getattr(entity, "_recursive_gen", None)
                _al = list(getattr(entity, "_unlocked_vocabulary", []))[:20]
                _cxg_cands = _cxg.generate_candidates(
                    best_candidate or "", _vr,
                    second_anchor=second_candidate or "",
                    recursive_generator=_rcxg,
                    anchor_words=_al,
                    action_context=getattr(entity, "_current_action", "") or "",
                )
                _extra.extend(_cxg_cands)
        except Exception:
            pass
        _composed, _tmpl_idx = compose_sentence(
            best_candidate if best_candidate else "",
            _vr,
            connector="",
            template_efficiency=_te,
            learned_weights=getattr(entity, "_template_learned_weights", None),
            extra_templates=_extra or None,
            second_anchor=second_candidate,
            temperature=_compose_temp,
        )
    except Exception:
        _composed = _display if _display else best_candidate or ""

    entity._last_template_idx = _tmpl_idx
    entity.tick += 1
    return {
        "vr_state": _vr,
        "best": best_candidate,
        "best_score": best_score,
        "second": second_candidate,
        "second_score": second_score,
        "third": third_candidate,
        "display": _display,
        "composed": _composed,
        "template_idx": _tmpl_idx,
        "cand_count": cand_count,
        "warm_count": len(_warm),
        "ms": elapsed,
    }
