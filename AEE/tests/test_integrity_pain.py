"""
验证完整性疼痛复活（PLAN_integrity_pain_revival）。

修复前的根因：绑定强度恒等于 0（喂养它的 record_access/record_perturbation
全项目从无调用）→ harm = magnitude × 0 = 0 → 改文件她什么都不疼。

本测试覆盖：
    1. 地板：从未被访问的区域，绑定也 ≥ _BINDING_FLOOR（冷启动就有感觉）
    2. 越用越绑：record_accesses 累积 → 绑定上升
    3. 在意只增不减：access_count 单调，绑定不回落（反 gaming 护栏）
    4. 扰动深度封顶：record_perturbation 历史不超过 HISTORY_WINDOW
    5. 信号转换：有变化事件 → active_harm>0 + drive_delta 非零 + behavior_bias 为负
    6. 比例性：harm 随 magnitude 单调上升
    7. 急性痛有界：单次伤害的痛注入（上升沿语义）总量 = 峰值，不随 tick 累积饱和
    8. 愈合落到隐痛底：持续无事件时 zone_harms 有限 tick 内退到疤决定的底（留疤则 >0）
    9. 致敏：留疤的区域同样改动更疼
   10. 重伤愈合更慢：深伤退到半值所需 tick 多于浅伤
   11. 疤极慢淡化 + 封顶在 1.0
   12. 重启不造成虚假急性痛：持久隐痛底不被当新伤（Codex §3）
   13. 多区疤底不饱和驱动力：有界瞬态偏置 vs 旧 additive 积分（Codex §1）
   14. 预测致痛动作被回避：普通张力下 pain↑ 动作优先级被压低于无害动作
   15. 饱和态仍回避：tension clamp 吞掉 pain 项时，直接惩罚通道仍降权（Codex P1）
"""

import sys as _sys
import os as _os
import tempfile
import shutil
from pathlib import Path

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from AEE.src.core import self_binding as sb
from AEE.src.core import integrity_signal as isig
from AEE.src.core import scar as scr


class MockEntity:
    """最小 mock：integrity_signal.update 只读 tick 和 snapshots。"""
    def __init__(self, tick=100, snapshots=None):
        self.tick = tick
        self.snapshots = snapshots or []


def _tmp_dir():
    d = tempfile.mkdtemp(prefix="xia_integrity_test_")
    return Path(d)


# ============================================================================
# 1. 地板：从未访问的区域也有最低绑定
# ============================================================================

def test_floor_gives_nonzero_binding_cold_start():
    """全新区域（无访问/无扰动历史）绑定 = _BINDING_FLOOR，不再恒为 0。"""
    d = _tmp_dir()
    try:
        b = sb.get_binding("perception", d, current_tick=0)
        assert abs(b - sb._BINDING_FLOOR) < 1e-9
        assert b > 0.0
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ============================================================================
# 2 + 3. 越用越绑 + 单调不降
# ============================================================================

def test_binding_rises_with_use_and_is_monotonic():
    """连续记访问 → 绑定单调上升；access_count 永不衰减。"""
    d = _tmp_dir()
    try:
        prev = sb.get_binding("expression", d)
        seq = []
        for _ in range(60):
            sb.record_accesses(["expression"], d)
            cur = sb.get_binding("expression", d)
            seq.append(cur)
        # 单调不降
        assert all(seq[i + 1] >= seq[i] - 1e-12 for i in range(len(seq) - 1))
        # 用过之后明显高于冷启动地板
        assert seq[-1] > prev + 0.1
        assert seq[-1] <= 1.0 + 1e-9
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_binding_stays_floored_above_zero_always():
    """任何情况下绑定 ≥ 地板（harm 永不会因绑定=0 而被掐灭）。"""
    d = _tmp_dir()
    try:
        for z in ("perception", "expression", "cognition", "continuity"):
            assert sb.get_binding(z, d) >= sb._BINDING_FLOOR - 1e-9
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ============================================================================
# 4. 扰动历史封顶
# ============================================================================

def test_perturbation_history_capped():
    """record_perturbation 历史不超过 HISTORY_WINDOW（守护进程长跑防膨胀）。"""
    d = _tmp_dir()
    try:
        for i in range(sb.HISTORY_WINDOW * 3):
            sb.record_perturbation("cognition", 0.01 * (i + 1), d)
        data = sb._load_data(d)
        hist = data["cognition"]["perturbation_history"]
        assert len(hist) == sb.HISTORY_WINDOW
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ============================================================================
# 5. 信号转换：变化事件 → 真实伤害 + 偏置
# ============================================================================

def test_event_produces_harm_drive_delta_and_negative_bias():
    """喂一条 perception 变化事件 → active_harm>0、drive_delta 非零、behavior_bias 为负。"""
    d = _tmp_dir()
    try:
        e = MockEntity(tick=200)
        events = [{"zone": "perception", "change_magnitude": 0.8, "tick": 200}]
        r = isig.update(events, e, d)
        assert r["active_harm"] > 0.0
        assert any(abs(v) > 0.0 for v in r["drive_delta"].values())
        # perception → input_trust_bias 应为负（退缩）
        assert r["behavior_bias"].get("input_trust_bias", 0.0) < 0.0
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_no_event_no_new_harm():
    """无变化事件 → 不产生新伤害（旧 harm 只会愈合下降）。"""
    d = _tmp_dir()
    try:
        e = MockEntity(tick=10)
        r = isig.update([], e, d)
        assert r["active_harm"] == 0.0
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ============================================================================
# 6. 比例性：magnitude 越大，伤害越大
# ============================================================================

def test_harm_scales_with_magnitude():
    """同区域、相同绑定下，change_magnitude 越大 active_harm 越大。"""
    d_small = _tmp_dir()
    d_large = _tmp_dir()
    try:
        e1 = MockEntity(tick=5)
        e2 = MockEntity(tick=5)
        small = isig.update([{"zone": "cognition", "change_magnitude": 0.2, "tick": 5}], e1, d_small)
        large = isig.update([{"zone": "cognition", "change_magnitude": 0.9, "tick": 5}], e2, d_large)
        assert large["active_harm"] > small["active_harm"]
    finally:
        shutil.rmtree(d_small, ignore_errors=True)
        shutil.rmtree(d_large, ignore_errors=True)


# ============================================================================
# 7. 急性痛有界：单次伤害的痛注入总量 = 峰值，不随 tick 累积（修复存量被当流量积分）
# ============================================================================

def test_pain_injection_bounded_via_rising_edge():
    """单次伤害后多拍衰减，按 s07a 上升沿规则计算的痛注入总量等于峰值，与拍数无关。

    回归保护：修复前 s07a 每拍把整个 active_harm 累加进 pain，存量被反复积分 →
    一次伤害可把 pain 推到饱和；修复后只注入上升沿，单次伤害总注入 = 单峰值。
    """
    d = _tmp_dir()
    try:
        e = MockEntity(tick=400)
        seq = [isig.update([{"zone": "perception", "change_magnitude": 0.9, "tick": 400}], e, d)["active_harm"]]
        for _ in range(50):
            seq.append(isig.update([], e, d)["active_harm"])
        # s07a 上升沿语义：prev 从 0 起，首拍跳一次，之后单调衰减 → 后续上升沿均为 0
        rising_total = seq[0] + sum(max(0.0, seq[i] - seq[i - 1]) for i in range(1, len(seq)))
        assert abs(rising_total - max(seq)) < 1e-9, f"上升沿总注入 {rising_total} != 峰值 {max(seq)}"
        # 对照：旧的"每拍全量累加"语义会远超峰值（证明 bug 的危害与修复的必要）
        old_style_total = sum(seq)
        assert old_style_total > max(seq) * 1.5
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ============================================================================
# 8. 愈合落到隐痛底：持续无事件 → 急性伤在有限 tick 内退到"疤决定的隐痛底"
#    （线性尾切除消长尾；单次伤也留微疤，故底 >0 而非纯归零）
# ============================================================================

def test_harm_settles_to_scar_floor_in_bounded_ticks():
    """一次伤害后持续无新事件，active_harm 在有限 tick 内退到隐痛底，而非几何长尾。

    单次伤害也会累积一点疤 → 隐痛底 = scar×SCAR_FLOOR > 0（虽极小），active_harm
    退到该底后稳住（随疤极慢淡化才进一步降），不纯归零。验证：① 长尾被切（落点 ≤ 一个
    小量级 0.01）；② 留疤未归零（落点 > 0）。
    """
    d = _tmp_dir()
    try:
        e = MockEntity(tick=300)
        isig.update([{"zone": "perception", "change_magnitude": 0.9, "tick": 300}], e, d)
        settled_at, final = None, None
        for t in range(1, 300):
            r = isig.update([], e, d)
            final = r["active_harm"]
            if final <= 0.01:
                settled_at = t
                break
        assert settled_at is not None, "active_harm 未在有限 tick 内退到隐痛底（长尾未切）"
        assert settled_at < 200, f"愈合过慢，{settled_at} tick 才落到底"
        assert final > 0.0, "留疤区域不应纯归零（隐痛底应 >0）"
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ============================================================================
# 9. 致敏：留疤的区域，同样改动更疼
# ============================================================================

def test_scarred_zone_hurts_more():
    """同 magnitude/binding 下，先堆出疤的区域 active_harm 高于无疤的初次受伤。"""
    d_clean = _tmp_dir()
    d_scar  = _tmp_dir()
    try:
        # 手动堆疤（不经 isig，不污染 binding/perturbation 历史），保证两边 binding 一致。
        for _ in range(10):
            scr.record_injury("perception", 0.9, d_scar)
        assert scr.get_scar("perception", d_scar) > 0.0

        e1 = MockEntity(tick=5)
        e2 = MockEntity(tick=5)
        clean = isig.update([{"zone": "perception", "change_magnitude": 0.5, "tick": 5}], e1, d_clean)
        scarred = isig.update([{"zone": "perception", "change_magnitude": 0.5, "tick": 5}], e2, d_scar)
        assert scarred["active_harm"] > clean["active_harm"], "致敏未生效：疤区不更疼"
    finally:
        shutil.rmtree(d_clean, ignore_errors=True)
        shutil.rmtree(d_scar, ignore_errors=True)


# ============================================================================
# 10. 重伤愈合更慢：深伤退到半值所需 tick 多于浅伤
# ============================================================================

def test_deeper_harm_heals_slower():
    """重伤从峰值衰减到一半，所需 tick 数严格多于轻伤（depth_brake + 固定切除占比）。"""
    def _ticks_to_half(magnitude):
        d = _tmp_dir()
        try:
            e = MockEntity(tick=5)
            peak = isig.update([{"zone": "cognition", "change_magnitude": magnitude, "tick": 5}], e, d)["active_harm"]
            half = peak * 0.5
            for t in range(1, 500):
                if isig.update([], e, d)["active_harm"] <= half:
                    return t
            return 500
        finally:
            shutil.rmtree(d, ignore_errors=True)

    assert _ticks_to_half(0.9) > _ticks_to_half(0.2), "重伤未比轻伤愈合慢"


# ============================================================================
# 11. 疤极慢淡化 + 封顶
# ============================================================================

def test_scar_decays_slowly_and_caps_at_one():
    """疤 100 tick 仅淡化一点点（极慢）；大量受伤后疤 ≤ 1（封顶）。"""
    d = _tmp_dir()
    try:
        scr.record_injury("expression", 1.0, d)
        s0 = scr.get_scar("expression", d)
        for _ in range(100):
            scr.decay_scars(d)
        s1 = scr.get_scar("expression", d)
        assert s1 < s0, "疤完全不淡化（应极慢淡化）"
        assert s1 > s0 * 0.9, f"疤淡化过快：{s1} / {s0}"

        for _ in range(1000):
            scr.record_injury("expression", 1.0, d)
        assert scr.get_scar("expression", d) <= 1.0 + 1e-9, "疤未封顶在 1.0"
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ============================================================================
# 12. 重启不造成虚假急性痛（Codex §3）：持久化的隐痛底不得被当成新伤
# ============================================================================

def test_restart_no_false_acute_pain():
    """模拟 daemon 重启：zone_harms/疤已落盘，新 entity（active_harm 内存态丢失）。
    第一拍 update 的 harm_rise 必须≈0 —— 上升沿以持久化 zone_harms 为 prev，持久隐痛底
    不应被当作新伤产生虚假急性痛冲量。"""
    d = _tmp_dir()
    try:
        e = MockEntity(tick=300)
        isig.update([{"zone": "perception", "change_magnitude": 0.9, "tick": 300}], e, d)
        for _ in range(80):
            isig.update([], e, d)          # 衰减到隐痛底，zone_harms/scar 落盘
        e2 = MockEntity(tick=400)          # 重启：全新 entity，文件持久
        r = isig.update([], e2, d)
        assert r["harm_rise"] <= 1e-9, f"重启首拍产生虚假上升沿 {r['harm_rise']}"
        assert r["active_harm"] > 0.0, "隐痛底应在重启后仍持续（疤未淡完）"
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ============================================================================
# 13. 多区疤底不饱和驱动力（Codex §1）：有界瞬态偏置 vs 旧 additive 积分
# ============================================================================

def test_multizone_scar_baseline_does_not_saturate_drives():
    """四区域都留疤 → 稳态隐痛底每拍产生 drive_delta。有界瞬态偏置（apply_drive_bias）
    下驱动力收敛到单拍偏置量（远未饱和）；对照旧 additive 累加则积分到 clamp=1。"""
    d = _tmp_dir()
    try:
        zones = ("perception", "expression", "cognition", "continuity")
        e_seed = MockEntity(tick=5)
        for z in zones:                    # 经 update 制造伤+疤，zone_harms 留隐痛底
            for _ in range(10):
                isig.update([{"zone": z, "change_magnitude": 0.9, "tick": 5}], e_seed, d)
        for _ in range(60):
            isig.update([], e_seed, d)     # 衰减到稳态隐痛底

        # 有界瞬态偏置：300 拍稳态注入，驱动力收敛、不饱和
        e = MockEntity(tick=5)
        e.unresolved = 0.0; e.stress = 0.0; e.loneliness = 0.0
        bias, seq = {}, []
        for _ in range(300):
            r = isig.update([], e, d)
            bias = isig.apply_drive_bias(e, r["drive_delta"], bias)
            seq.append(e.unresolved)
        assert max(seq) < 0.5, f"驱动力被隐痛底推过半 {max(seq)}（疑似积分饱和）"

        # 对照：旧 additive 每拍累加 → 同样 300 拍积分到饱和（证明场景有效 + 修复必要）
        e2 = MockEntity(tick=5); e2.unresolved = 0.0
        for _ in range(300):
            r = isig.update([], e2, d)
            for _dim, _delta in r["drive_delta"].items():
                _cur = getattr(e2, _dim, None)
                if _cur is not None:
                    setattr(e2, _dim, max(0.0, min(1.0, float(_cur) + float(_delta))))
        assert e2.unresolved > 0.9, "对照（旧 additive）未饱和，测试场景无效"
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ============================================================================
# 14/15. 预测致痛动作被回避（mental_simulation：Codex P1 直接惩罚通道）
# ============================================================================

from AEE.src.thinking_system import mental_simulation as msim
from AEE.src.world_model_update import induct as _induct


def _patch_predict(mapping):
    """monkeypatch predict_action_effects：按 action_type 返回固定预测 delta。
    返回原函数供恢复。simulate_suggestions 内是延迟 from-import，读模块属性，故可 patch。"""
    orig = _induct.predict_action_effects
    _induct.predict_action_effects = lambda atype, pre, rules: dict(mapping.get(atype, {}))
    return orig


def test_pain_action_downweighted_at_normal_tension():
    """普通张力下：预测 pain↑ 的动作优先级被压低，且低于预测无害的动作。"""
    orig = _patch_predict({"explore": {"pain": 0.3}, "comfort": {"loneliness": -0.1}})
    try:
        state = {"energy": 0.6, "fatigue": 0.1, "pain": 0.0}  # 其余走默认 → tension≈0.26
        sugg = [
            {"action": "探索未知领域", "priority": 0.5},   # → explore → 预测致痛
            {"action": "发起社交互动", "priority": 0.5},   # → comfort → 无害
        ]
        out = msim.simulate_suggestions(sugg, state, wm_rules=[object()])
        by = {s["action"]: s["priority"] for s in out}
        assert by["探索未知领域"] < 0.5, "致痛动作未被降权"
        assert by["探索未知领域"] < by["发起社交互动"], "致痛动作未低于无害动作"
    finally:
        _induct.predict_action_effects = orig


def test_pain_action_downweighted_even_when_tension_saturated():
    """tension 已饱和(≈1.0)：tension 内 pain 项被 clamp 吞掉（tension_reduction≈0），
    但 pain_rise 直接惩罚通道仍把致痛动作压到 0.5 以下 —— 锁住 Codex P1 修复。"""
    orig = _patch_predict({"explore": {"pain": 0.3}})
    try:
        state = {"unresolved": 1.0, "loneliness": 1.0, "stress": 1.0,
                 "boredom": 1.0, "info_gap": 1.0,
                 "energy": 0.8, "fatigue": 0.1, "pain": 0.0}
        assert abs(msim._estimate_tension(state) - 1.0) < 1e-9, "前提：张力须饱和到 1.0"
        sugg = [{"action": "探索未知领域", "priority": 0.5}]
        out = msim.simulate_suggestions(sugg, state, wm_rules=[object()])
        sim = out[0]["simulation"]
        assert abs(sim["tension_reduction"]) < 1e-9, "前提：饱和下 tension 通道应已失效"
        assert sim["pain_rise"] > 0.0, "应观测到预测致痛增量"
        assert out[0]["priority"] < 0.5, "饱和态下致痛动作仍须被直接惩罚通道降权"
    finally:
        _induct.predict_action_effects = orig


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
