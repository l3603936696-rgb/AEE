"""
验证自我开导 / 自欺式保底贷款（self_counsel.py）

贷款结构（见 PLAN_self_counsel.md）：
    她自我表达 → 即时无条件支取表层缓解（孤独表层 + 不可答困惑），
    本金（loneliness_core / 可答困惑）不还。

覆盖性质：
    1. 满额支取 → surface↓ + core 微升（渗透）+ 体感小升 + "自我宽慰"粒子
    2. 连续支取 → 边际递减（条款 A·热度）
    3. core 高 → 孤独贷款趋零（条款 B·信用上限）
    4. 可答性闸（§4）：input_(可答) 不降 unresolved；action_(不可答) 降（小额，无渗透）
    5. 空表达 → 零支取
"""

import sys as _sys
import os as _os

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from src.language_system import self_counsel as sc


class MockEntity:
    """最小 mock，匹配 EntityState 自我开导相关字段接口。"""
    def __init__(self, **kwargs):
        self.loneliness_core = 0.2
        self.loneliness_surface = 0.3
        self.loneliness = 0.5
        self.unresolved = 0.4
        self.somatic_tone = 0.0
        self.relief_debt = 0.5
        self.tick = 100
        self._pending_questions = []
        self.wm_rules = []
        for k, v in kwargs.items():
            setattr(self, k, v)

    def _sync_loneliness(self):
        self.loneliness = min(1.0, self.loneliness_core + self.loneliness_surface)


# ============================================================================
# 1. 满额支取
# ============================================================================

def test_full_draw_relieves_surface_seeps_core_and_feels():
    """满额支取：surface↓ + core 微升（渗透）+ 体感小升 + 自我宽慰粒子。"""
    e = MockEntity(loneliness_core=0.2, loneliness_surface=0.3, somatic_tone=0.0)
    surf0, core0, tone0 = e.loneliness_surface, e.loneliness_core, e.somatic_tone

    summary = sc.apply_self_counsel(e, "好安静啊，不过没关系", 100)

    # 表层被支取（下降）
    assert e.loneliness_surface < surf0
    assert summary["lone_loan"] > 0.0
    # 本金被微量渗透抬升（利息·长期成本），增量 = 实际支取额 × _SEEP_RATE。
    # 实际支取额 = surface 缓解量（未取整，与 summary 的 round 区分）。
    assert e.loneliness_core > core0
    _actual_loan = surf0 - e.loneliness_surface
    assert abs((e.loneliness_core - core0) - _actual_loan * sc._SEEP_RATE) < 1e-9
    # 即时体感安慰（小，因是自欺）
    assert e.somatic_tone > tone0
    # 余韵粒子：排了一颗"自我宽慰"
    q = e._pending_feeling_injections
    labels = [f["dimension"] for f in q]
    assert sc._LONE_LABEL in labels
    assert all(f["intensity"] > 0.0 for f in q)


def test_seepage_is_tiny_relative_to_surface_relief():
    """渗透是'微量'：core 增量远小于 surface 缓解量（自欺只拖时间）。"""
    e = MockEntity(loneliness_core=0.2, loneliness_surface=0.3)
    sc.apply_self_counsel(e, "我没事的", 100)
    surf_relief = 0.3 - e.loneliness_surface
    core_gain = e.loneliness_core - 0.2
    assert core_gain < surf_relief * 0.2   # 渗透率 0.10 → 远小于缓解


# ============================================================================
# 2. 边际递减（条款 A）
# ============================================================================

def test_diminishing_returns_on_repeated_draw():
    """连续支取（同拍内热度不衰减）→ 第二笔额度明显小于第一笔。"""
    e = MockEntity(loneliness_core=0.2, loneliness_surface=0.9)
    first = sc.apply_self_counsel(e, "我没事", 100)
    second = sc.apply_self_counsel(e, "真的没事", 100)
    assert second["lone_loan"] < first["lone_loan"]
    assert second["factor_a"] < first["factor_a"]


def test_heat_decays_over_time():
    """热度随拍数衰减：隔够久再支取，额度回升（耐受性恢复）。"""
    e = MockEntity(loneliness_core=0.2, loneliness_surface=0.9)
    sc.apply_self_counsel(e, "我没事", 100)              # 升温
    soon = sc.apply_self_counsel(e, "还是没事", 101)      # 紧接着，热度高
    e2 = MockEntity(loneliness_core=0.2, loneliness_surface=0.9)
    sc.apply_self_counsel(e2, "我没事", 100)
    later = sc.apply_self_counsel(e2, "现在想通了", 100 + int(sc._HEAT_TAU * 5))  # 远后，热度近零
    assert later["factor_a"] > soon["factor_a"]


# ============================================================================
# 3. 信用上限（条款 B）
# ============================================================================

def test_ceiling_chokes_loan_when_core_high():
    """loneliness_core 接近 _CEILING → 孤独贷款额趋零（逼她找真实连接）。"""
    low = MockEntity(loneliness_core=0.1, loneliness_surface=0.5)
    high = MockEntity(loneliness_core=sc._CEILING - 1e-6, loneliness_surface=0.5)
    s_low = sc.apply_self_counsel(low, "没事", 100)
    s_high = sc.apply_self_counsel(high, "没事", 100)
    assert s_high["lone_loan"] < s_low["lone_loan"]
    assert s_high["factor_b"] < 0.01     # core 达上限 → 趋零


def test_ceiling_zero_at_or_above():
    """core 达/超 _CEILING → factor_b=0 → 孤独贷款为零。"""
    e = MockEntity(loneliness_core=sc._CEILING, loneliness_surface=0.5)
    surf0 = e.loneliness_surface
    s = sc.apply_self_counsel(e, "没事", 100)
    assert s["lone_loan"] == 0.0
    assert abs(e.loneliness_surface - surf0) < 1e-12


# ============================================================================
# 4. 困惑可答性闸（§4 核心决策）
# ============================================================================

def test_answerable_confusion_not_loaned():
    """可答困惑（rule trigger input_*）→ 不降 unresolved（保护求知）。"""
    e = MockEntity(unresolved=0.5)
    e.wm_rules = [{"id": "r_ans", "predicts": {"trigger": "input_warmth_in_chat"}}]
    e._pending_questions = [{"rule_id": "r_ans", "priority": 0.8}]
    ur0 = e.unresolved
    s = sc.apply_self_counsel(e, "为什么会这样呢", 100)
    assert s["conf_loan"] == 0.0
    assert abs(e.unresolved - ur0) < 1e-12


def test_unanswerable_confusion_loaned_no_seepage():
    """不可答困惑（rule trigger action_*）→ 降 unresolved（小额），且无渗透到任何本金。"""
    e = MockEntity(unresolved=0.5)
    e.wm_rules = [{"id": "r_unans", "predicts": {"trigger": "action_explore"}}]
    e._pending_questions = [{"rule_id": "r_unans", "priority": 0.8}]
    ur0 = e.unresolved
    s = sc.apply_self_counsel(e, "我大概永远没法知道吧", 100)
    assert s["conf_loan"] > 0.0
    assert e.unresolved < ur0
    # 释怀粒子
    labels = [f["dimension"] for f in e._pending_feeling_injections]
    assert sc._CONF_LABEL in labels


def test_mixed_questions_only_unanswerable_drawn():
    """可答+不可答混在 pending → 只对不可答的那条支取。"""
    e = MockEntity(unresolved=0.5)
    e.wm_rules = [
        {"id": "r_ans", "predicts": {"trigger": "input_foo_in_bar"}},
        {"id": "r_unans", "predicts": {"trigger": "action_baz"}},
    ]
    e._pending_questions = [
        {"rule_id": "r_ans", "priority": 0.9},
        {"rule_id": "r_unans", "priority": 0.7},
    ]
    s = sc.apply_self_counsel(e, "嗯", 100)
    # 只一条不可答 → conf_loan == 单条不可答额度（满权重 × 基础额 × factor_a(heat=0)=1）
    assert abs(s["conf_loan"] - sc._BASE_CONF_LOAN) < 1e-9


# ============================================================================
# 5. 空表达守卫
# ============================================================================

def test_empty_expression_no_draw():
    """空表达不支取任何贷款。"""
    e = MockEntity(loneliness_core=0.2, loneliness_surface=0.3, unresolved=0.5)
    surf0, core0, ur0 = e.loneliness_surface, e.loneliness_core, e.unresolved
    s = sc.apply_self_counsel(e, "", 100)
    assert s["drawn"] == 0.0
    assert e.loneliness_surface == surf0
    assert e.loneliness_core == core0
    assert e.unresolved == ur0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
