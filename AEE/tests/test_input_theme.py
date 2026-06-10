"""②a 输入主题聚类 + Snap.input_class 往返 冒烟测试（纯脚本，无 pytest）。

不依赖 BGE（直接替换 input_theme._embed），验证：
  1. 固定 N 槽：不超过 _N_THEMES 个主题。
  2. 稳定性：相同向量反复 → 同一 theme_id。
  3. argmax 分配：填满后新输入归到最近质心。
  4. 空输入 / BGE 不可用 → 返回 ""。
  5. Snap.input_class 经 to_dict/from_dict 往返保留。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from AEE.src.world_model_update import input_theme as it
from AEE.src.world_model_update.rules import Snap


class _FakeEntity:
    pass


def _set_embed(mapping):
    """让 _embed(text) 返回 mapping.get(text)。返回原函数以便还原。"""
    orig = it._embed
    it._embed = lambda text: mapping.get(text)
    return orig


def test_fixed_n_themes_cap():
    n = it._N_THEMES
    mapping = {}
    for i in range(n + 3):
        v = [0.0] * (n + 3)
        v[i] = 1.0
        mapping[f"t{i}"] = v
    orig = _set_embed(mapping)
    try:
        e = _FakeEntity()
        ids = [it.classify_input(e, f"t{i}") for i in range(n + 3)]
        distinct = set(ids)
        assert len(distinct) == n, f"主题数应被卡在 {n}，实得 {len(distinct)}"
    finally:
        it._embed = orig


def test_stability_same_vec_same_theme():
    orig = _set_embed({"a": [1.0, 0.0, 0.0]})
    try:
        e = _FakeEntity()
        first = it.classify_input(e, "a")
        again = [it.classify_input(e, "a") for _ in range(5)]
        assert all(x == first for x in again), "相同输入必须稳定落同一主题"
    finally:
        it._embed = orig


def test_argmax_assignment_after_full():
    n = it._N_THEMES
    mapping = {}
    for i in range(n):
        v = [0.0] * n
        v[i] = 1.0
        mapping[f"t{i}"] = v
    near0 = [0.0] * n
    near0[0] = 0.98
    near0[1] = 0.20
    norm = sum(x * x for x in near0) ** 0.5
    mapping["near0"] = [x / norm for x in near0]
    orig = _set_embed(mapping)
    try:
        e = _FakeEntity()
        for i in range(n):
            it.classify_input(e, f"t{i}")
        assert it.classify_input(e, "near0") == "theme_0"
    finally:
        it._embed = orig


def test_blank_and_bge_down_return_empty():
    e = _FakeEntity()
    orig = _set_embed({})
    try:
        assert it.classify_input(e, "") == ""
        assert it.classify_input(e, "   ") == ""
    finally:
        it._embed = orig
    orig = it._embed
    it._embed = lambda text: None
    try:
        assert it.classify_input(e, "hello") == ""
    finally:
        it._embed = orig


def test_snap_input_class_roundtrip():
    s = Snap(snap_index=7, action_type="voice", input_class="theme_3")
    d = s.to_dict()
    assert d["input_class"] == "theme_3"
    back = Snap.from_dict(d)
    assert back.input_class == "theme_3"
    legacy = Snap.from_dict({"snap_index": 1, "action_type": "rest"})
    assert legacy.input_class == "", "旧格式 snap 应默认 input_class=''"


if __name__ == "__main__":
    tests = [
        ("固定 N 槽上限", test_fixed_n_themes_cap),
        ("相同输入稳定", test_stability_same_vec_same_theme),
        ("满槽后 argmax 分配", test_argmax_assignment_after_full),
        ("空输入/BGE down → ''", test_blank_and_bge_down_return_empty),
        ("Snap.input_class 往返", test_snap_input_class_roundtrip),
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
