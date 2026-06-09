"""语言训练模块 — run_language_training_tick + match_anchor_expression

从 entity_zero_iteration.py 拆分。
"""

from .entity_state import EntityState
from .language_anchor_match import match_anchor_expression

from .language_system.somatic_concept_map import SOMATIC_ANCHORS

import math
import time
import logging

logger = logging.getLogger(__name__)


# ---- 静息基线 ----
# 维度的平衡态参考值，来自 entity 的初始状态 / 长期均值。
# 锚点匹配计算的是"状态偏离这个基线多远，方向是否与锚点一致"。
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
