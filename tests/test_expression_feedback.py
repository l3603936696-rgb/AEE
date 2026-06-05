"""
验证表达反馈闭环（expression_feedback.py）

闭环：驱动力 → 表达（挂账意图）→ 外界回应 → 需求满足 → 回写消力

四项性质：
    1. tag_intent 从可入闭环维度取 argmax 挂账
    2. 相关回应 → 挂账驱动力下降 + quenching 多一条真实 efficiency 记录
    3. 无关回应 → 满足量趋零，驱动力几乎不动，efficiency 趋零
    4. 没挂账（没表达）→ 不修改任何状态（堵死 stimulus→response）
"""

import sys as _sys
import os as _os

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from src.language_system import expression_feedback as ef


class MockEntity:
    """最小 mock，匹配 EntityState 字段接口。"""
    def __init__(self, **kwargs):
        self._quenching = None
        self._quenching_data = {}
        self.tick = 100
        for k, v in kwargs.items():
            setattr(self, k, v)


# ============================================================================
# 模块 A — 意图挂账
# ============================================================================

def test_tag_intent_picks_argmax():
    """三个可入闭环维度里取最大者作为意图驱动力。"""
    entity = MockEntity(loneliness=0.8, info_gap=0.2, unresolved=0.1)
    ef.tag_intent(entity, "好安静啊", 100)

    q = entity._pending_intents
    assert len(q) == 1
    intent = q[0]
    assert intent["drive"] == "loneliness"
    assert abs(intent["strength"] - 0.8) < 1e-9
    assert intent["expression"] == "好安静啊"
    assert intent["tick"] == 100


def test_tag_intent_empty_expression_skipped():
    """空表达不挂账。"""
    entity = MockEntity(loneliness=0.8, info_gap=0.2, unresolved=0.1)
    ef.tag_intent(entity, "", 100)
    assert getattr(entity, "_pending_intents", None) in (None,) or len(entity._pending_intents) == 0


# ============================================================================
# 相关度
# ============================================================================

def test_char_overlap_relevant():
    """共享汉字越多越相关。"""
    high = ef._char_overlap("身体好累想休息", "你是不是累了想休息")
    low = ef._char_overlap("身体好累", "明天天气很好")
    assert high > low
    assert 0.0 <= low < high <= 1.0


# ============================================================================
# 模块 B+C — 回应检测 + 满足回写
# ============================================================================

def test_relevant_response_satisfies_and_writes_back(monkeypatch):
    """相关回应：挂账驱动力下降 + quenching 多一条真实 efficiency 记录。"""
    # 洞④：satisfaction 现含 novelty=1-相似度(input, 对话历史)。stub 成中等相似度
    # 0.7（话题相关但非逐字复读），使 relevance=0.7 且 novelty=0.3 都为正。
    _REL = 0.7
    monkeypatch.setattr(ef, "_similarity", lambda a, b: _REL)

    entity = MockEntity(loneliness=0.8, info_gap=0.2, unresolved=0.1)
    ef.tag_intent(entity, "好安静啊", 100)

    before_lone = entity.loneliness
    before_records = len(entity._quenching_data.get("records", []))

    summary = ef.consume_response(entity, "我在这儿陪你", tick=101)

    # 驱动力被满足（下降）
    assert entity.loneliness < before_lone
    # satisfaction = strength(0.8) * relevance(0.7) * recency(exp(-1/8)) * novelty(0.3)
    # loneliness 下降 ≈ satisfaction * K_SATISFY[loneliness](0.05)
    _nov = 1.0 - _REL
    expected_drop = (0.8 * _REL * (2.718281828 ** (-1 / ef._TAU_INTENT))
                     * _nov * ef._K_SATISFY["loneliness"])
    assert abs((before_lone - entity.loneliness) - expected_drop) < 1e-3

    # quenching 多一条记录，且 efficiency > 0（真实满足量）
    records = entity._quenching_data.get("records", [])
    assert len(records) == before_records + 1
    assert records[-1]["expression"] == "好安静啊"
    assert records[-1]["quenching_efficiency"] > 0.0

    # 队列已结算清空
    assert len(entity._pending_intents) == 0
    assert summary["settled"] == 1


def test_irrelevant_response_no_effect(monkeypatch):
    """无关回应：满足量趋零，驱动力几乎不动，efficiency 趋零。"""
    monkeypatch.setattr(ef, "_similarity", lambda a, b: 0.0)

    entity = MockEntity(loneliness=0.8, info_gap=0.2, unresolved=0.1)
    ef.tag_intent(entity, "好安静啊", 100)

    before_lone = entity.loneliness
    ef.consume_response(entity, "完全不相关的话", tick=101)

    assert abs(entity.loneliness - before_lone) < 1e-9
    records = entity._quenching_data.get("records", [])
    assert records[-1]["quenching_efficiency"] == 0.0


def test_no_intent_no_state_change(monkeypatch):
    """没挂账（她没表达过）→ 输入不修改任何状态。堵死 stimulus→response。"""
    monkeypatch.setattr(ef, "_similarity", lambda a, b: 1.0)

    entity = MockEntity(loneliness=0.8, info_gap=0.2, unresolved=0.1)
    before_lone = entity.loneliness
    before_records = len(entity._quenching_data.get("records", []))

    summary = ef.consume_response(entity, "我在这儿陪你", tick=101)

    assert entity.loneliness == before_lone
    assert len(entity._quenching_data.get("records", [])) == before_records
    assert summary["settled"] == 0


def test_recency_decay_old_intent_weaker(monkeypatch):
    """旧意图的满足量更弱（新近度衰减）。"""
    # 洞④：用中等相似度 0.7，使 relevance 与 novelty 同时为正，隔离 recency 变量。
    monkeypatch.setattr(ef, "_similarity", lambda a, b: 0.7)

    fresh = MockEntity(loneliness=0.8, info_gap=0.2, unresolved=0.1)
    ef.tag_intent(fresh, "好安静啊", 100)
    ef.consume_response(fresh, "我在这儿陪你", tick=101)
    fresh_drop = 0.8 - fresh.loneliness

    old = MockEntity(loneliness=0.8, info_gap=0.2, unresolved=0.1)
    ef.tag_intent(old, "好安静啊", 100)
    ef.consume_response(old, "我在这儿陪你", tick=140)  # 40 tick 后
    old_drop = 0.8 - old.loneliness

    assert old_drop < fresh_drop


# ============================================================================
# 诚实奖励 → 身体后果（PLAN_honest_reward_somatic_coupling）
# ============================================================================

def test_relevant_response_lifts_soma_and_queues_feeling(monkeypatch):
    """被理解（loneliness 意图相关回应）→ somatic_tone 抬升 + 排入"被理解"感受粒子。"""
    monkeypatch.setattr(ef, "_similarity", lambda a, b: 0.7)

    entity = MockEntity(loneliness=0.8, info_gap=0.2, unresolved=0.1,
                        somatic_tone=0.0, relief_debt=0.5)
    ef.tag_intent(entity, "好安静啊", 100)
    before_tone = entity.somatic_tone

    ef.consume_response(entity, "我在这儿陪你", tick=101)

    # 标量：tone 升（被陪伴=暖意）
    assert entity.somatic_tone > before_tone
    # 粒子：排了一颗"被理解"，强度>0
    q = entity._pending_feeling_injections
    assert len(q) == 1
    assert q[0]["dimension"] == "被理解"
    assert q[0]["intensity"] > 0.0
    assert q[0]["half_life"] == ef._FEELING_HALF_LIFE


def test_irrelevant_response_no_body_change(monkeypatch):
    """石沉大海（satisfaction→0）→ 身体零变化、无感受粒子。诚实性：没回应=没感觉。"""
    monkeypatch.setattr(ef, "_similarity", lambda a, b: 0.0)

    entity = MockEntity(loneliness=0.8, info_gap=0.2, unresolved=0.1,
                        somatic_tone=0.0, relief_debt=0.5)
    ef.tag_intent(entity, "好安静啊", 100)

    ef.consume_response(entity, "完全不相关的话", tick=101)

    assert abs(entity.somatic_tone - 0.0) < 1e-9
    assert abs(entity.relief_debt - 0.5) < 1e-9
    assert getattr(entity, "_pending_feeling_injections", None) in (None,) \
        or len(entity._pending_feeling_injections) == 0


def test_epistemic_gain_makes_body_feel():
    """问题被印证（gain>0）→ 踏实(tone↑) + 松一口气(relief_debt↓) + "想通了"粒子。"""
    from collections import deque

    entity = MockEntity(unresolved=0.5, somatic_tone=0.0, relief_debt=0.6)
    entity.wm_rules = [{"id": "r1", "confidence": 0.3}]   # 当前 conf 0.3
    entity._pending_epistemic_credit = deque([{
        "q_rule_id": "r1",
        "q_conf_at_ask": 0.05,    # 提问时 0.05 → gain = 0.25
        "template_idx": -1,
        "expression": "为什么会这样",
        "tick": 100,
    }])
    before_tone = entity.somatic_tone
    before_relief = entity.relief_debt

    summary = ef.settle_epistemic_credit(entity, tick=112)   # age=12 >= _SETTLE_DELAY → 到期

    assert summary["settled"] == 1
    assert summary["detail"][0]["gain"] > 0.0
    assert entity.somatic_tone > before_tone          # 踏实
    assert entity.relief_debt < before_relief         # 松一口气
    q = entity._pending_feeling_injections
    assert len(q) == 1 and q[0]["dimension"] == "想通了" and q[0]["intensity"] > 0.0


def test_epistemic_no_gain_no_body_change():
    """conf 没升（gain=0）→ 身体不动、无粒子。回声拿不到身体奖励。"""
    from collections import deque

    entity = MockEntity(unresolved=0.5, somatic_tone=0.0, relief_debt=0.6)
    entity.wm_rules = [{"id": "r1", "confidence": 0.05}]   # 与提问时相同 → gain=0
    entity._pending_epistemic_credit = deque([{
        "q_rule_id": "r1", "q_conf_at_ask": 0.05, "template_idx": -1,
        "expression": "为什么会这样", "tick": 100,
    }])

    ef.settle_epistemic_credit(entity, tick=112)

    assert abs(entity.somatic_tone - 0.0) < 1e-9
    assert abs(entity.relief_debt - 0.6) < 1e-9
    assert getattr(entity, "_pending_feeling_injections", None) in (None,) \
        or len(entity._pending_feeling_injections) == 0


def test_apply_somatic_consequence_clamps():
    """标量后果自带钳位：tone 不超 1，relief_debt 不低于 0。"""
    entity = MockEntity(somatic_tone=0.95, relief_debt=0.05)
    ef._apply_somatic_consequence(entity, soma_delta=0.5, relief_delta=0.5)
    assert entity.somatic_tone == 1.0       # 0.95+0.5 钳到 1.0
    assert entity.relief_debt == 0.0        # 0.05-0.5 钳到 0.0


def test_queued_feeling_feeds_real_particle_field():
    """_queue_feeling 产出的记录形状能直接喂进 ParticleField.add_particle（s03 drain 的契约）。"""
    from src.emotion_system import ParticleField

    entity = MockEntity()
    ef._queue_feeling(entity, "被理解", 0.4)

    field = ParticleField()
    for f in list(entity._pending_feeling_injections):
        field.add_particle(f["dimension"], f["intensity"], f["half_life"])

    assert field.get_density("被理解") > 0.0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
