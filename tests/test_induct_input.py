"""②b 输入触发归纳 induct_input 冒烟测试（纯脚本，无 pytest）。

验证：
  1. 带 input_class 的快照 → 建出 input 规则，trigger 形如 input_{class}_in_{ctx}。
  2. top-K 收窄：即使 5 个字段都显著，规则也只保留 _K_INPUT_FIELDS 个（且取 |delta| 最大者）。
  3. input_class="" 的快照 → 不建任何 input 规则（留给 action 路径）。
  4. 已有同 trigger 规则 → EMA 更新 + confidence 上升，不新建。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.world_model_update import induct_input as ii
from src.world_model_update.rules import Snap

_PARAMS = {}  # 用默认值（get_raw_value 兜底）


def _mk_snap(input_class, deltas):
    """造一个 input 快照：pre 全 0.5，post = pre+delta，pred_error=delta（冷启动）。"""
    pre = {f: 0.5 for f in deltas}
    post = {f: 0.5 + d for f, d in deltas.items()}
    return Snap(
        snap_index=1,
        action_type="voice",
        pre_state=pre,
        post_state=post,
        prediction_error_map=dict(deltas),
        input_class=input_class,
    )


def test_input_rule_created():
    snap = _mk_snap("theme_0", {"info_gap": -0.3, "unresolved": -0.2})
    rules = ii.induct_input_rules([], [snap], _PARAMS)
    assert len(rules) == 1, f"应建 1 条 input 规则，实得 {len(rules)}"
    r = rules[0]
    assert r.predicts.trigger.startswith("input_theme_0_in_"), r.predicts.trigger
    assert r._debug_meta.get("induction_method") == "input_prediction_error_driven"
    assert r._debug_meta.get("input_class") == "theme_0"


def test_topk_narrowing():
    # 5 个显著字段，K=1 → 只保留 |delta| 最大的那个（verify 只能解析单字段 expect）
    deltas = {
        "info_gap": -0.50, "unresolved": -0.40, "boredom": -0.10,
        "energy": -0.05, "fatigue": 0.03,
    }
    snap = _mk_snap("theme_1", deltas)
    rules = ii.induct_input_rules([], [snap], _PARAMS)
    assert len(rules) == 1
    kept = set(rules[0].expected_deltas.keys())
    assert len(kept) == ii._K_INPUT_FIELDS, f"应只留 {ii._K_INPUT_FIELDS} 个字段，实得 {len(kept)}"
    assert kept == {"info_gap"}, f"应留 |delta| 最大的那个，实得 {kept}"


def test_empty_input_class_skipped():
    snap = _mk_snap("", {"info_gap": -0.3, "unresolved": -0.2})
    rules = ii.induct_input_rules([], [snap], _PARAMS)
    assert len(rules) == 0, "input_class='' 不应建 input 规则（留给 action 路径）"


def test_existing_rule_ema_update():
    snap1 = _mk_snap("theme_0", {"info_gap": -0.3})
    created = ii.induct_input_rules([], [snap1], _PARAMS)
    assert len(created) == 1
    base = created[0]
    conf_before = base.confidence
    # 同 trigger 再来一条 → 更新已有，不新建
    snap2 = _mk_snap("theme_0", {"info_gap": -0.5})
    new = ii.induct_input_rules([base], [snap2], _PARAMS)
    assert len(new) == 0, "同 trigger 应更新已有规则，不新建"
    assert base.confidence > conf_before, "命中应抬升 confidence"
    assert base.source_experience_count == 2


if __name__ == "__main__":
    tests = [
        ("建出 input 规则", test_input_rule_created),
        ("top-K 收窄", test_topk_narrowing),
        ("空 input_class 跳过", test_empty_input_class_skipped),
        ("同 trigger EMA 更新", test_existing_rule_ema_update),
    ]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as ex:
            print(f"  [FAIL] {name}: {ex!r}")
    print(f"\n{passed}/{len(tests)} passed")
    raise SystemExit(0 if passed == len(tests) else 1)
