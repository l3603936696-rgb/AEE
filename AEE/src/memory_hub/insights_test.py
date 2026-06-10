"""
Insights — 单元测试入口

运行：`python -m src.memory_hub.insights_test`
或 `python src/memory_hub/insights_test.py`
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from AEE.src.memory_hub.insights_db import init_db, get_db_path
from AEE.src.memory_hub.insights_schema import _infer_type, _extract_situation
from AEE.src.memory_hub.insights_api import (
    write_insight,
    recall_insights,
    sync_decay,
    get_insight_count,
    get_all_insights,
)


def main():
    import sqlite3 as _sq3

    print("=" * 60)
    print("Insights DB — 单元测试")
    print("=" * 60)

    init_db()
    DB_PATH = get_db_path()
    _c = _sq3.connect(str(DB_PATH))
    _c.execute("DELETE FROM insights")
    _c.commit()
    _c.close()

    print("\n【测试 1】write_insight — 正常写入")
    rule1 = {
        "id": "wmu_abc12345",
        "content": "高能量时执行seek动作，信息差下降均值-0.100，对照组自然变化均值-0.010，区分度0.090",
        "confidence": 0.75,
        "status": "active",
        "context": "high_energy",
        "predicts": {"trigger": "action_seek_in_high_energy", "expect": "info_gap_decrease"},
    }
    ok1 = write_insight(rule1)
    print(f"  {'ok' if ok1 else 'FAIL'} write_insight = {ok1}")

    print("\n【测试 2】write_insight — 幂等更新")
    rule1_updated = dict(rule1)
    rule1_updated["confidence"] = 0.82
    ok2 = write_insight(rule1_updated)
    count = get_insight_count()
    ok2 = ok2 and count == 1
    print(f"  {'ok' if ok2 else 'FAIL'} 幂等写入后 count = {count}（期望 1）")

    print("\n【测试 3】recall_insights — 命中")
    matched = recall_insights(["high_energy", "seek"])
    ok3 = len(matched) >= 1
    print(f"  {'ok' if ok3 else 'FAIL'} tag=[high_energy] 命中 {len(matched)} 条")
    if matched:
        print(f"     -> {matched[0].content[:50]}...")

    print("\n【测试 4】recall_insights — 未命中")
    matched4 = recall_insights(["完全不相关", "xyz"])
    ok4 = len(matched4) == 0
    print(f"  {'ok' if ok4 else 'FAIL'} tag=[完全不相关] 命中 {len(matched4)} 条（期望 0）")

    print("\n【测试 5】_infer_type — 自动类型判定")
    rule_correction = {"context": "用户纠正", "content": "bcyq不喜欢被叫老师"}
    rule_pattern = {"context": "高能量情境", "content": "seek动作导致info_gap下降"}
    t1 = _infer_type(rule_correction)
    t2 = _infer_type(rule_pattern)
    ok5 = t1 == "user_preference" and t2 == "situation_pattern"
    print(f"  {'ok' if ok5 else 'FAIL'} 纠正类->{t1}，情境类->{t2}")

    print("\n【测试 6】_extract_situation — trigger 解析")
    rule_trigger = {"predicts": {"trigger": "action_seek_in_high_energy"}, "context": ""}
    s1 = _extract_situation(rule_trigger)
    rule_fallback = {"context": "high_loneliness", "predicts": {}}
    s2 = _extract_situation(rule_fallback)
    ok6 = s1 == "high_energy" and s2 == "high_loneliness"
    print(f"  {'ok' if ok6 else 'FAIL'} trigger->{s1}，fallback->{s2}")

    print("\n【测试 7】sync_decay — 置信度降低触发删除")
    write_insight({"id": "wmu_decay_t7", "content": "衰减测试7",
                   "confidence": 0.75, "status": "active",
                   "context": "decay_t7", "predicts": {}})
    sync_decay([{"id": "wmu_decay_t7", "confidence": 0.05, "status": "active"}])
    count_after7 = get_insight_count()
    ok7 = count_after7 == 1
    print(f"  {'ok' if ok7 else 'FAIL'} conf=0.05后insight被删除，count={count_after7}（期望1）")

    print("\n【测试 8】sync_decay — decayed状态")
    write_insight({"id": "wmu_decayed_t8", "content": "衰减测试8",
                   "confidence": 0.5, "status": "active",
                   "context": "test8", "predicts": {}})
    sync_decay([{"id": "wmu_decayed_t8", "confidence": 0.3, "status": "decayed"}])
    count8 = get_insight_count()
    ok8 = count8 == 1
    print(f"  {'ok' if ok8 else 'FAIL'} status=decayed后insight删除，count={count8}（期望1）")

    print("\n【测试 9】get_all_insights")
    write_insight({"id": "wmu_test9", "content": "测试9",
                   "confidence": 0.6, "status": "active",
                   "context": "test9", "predicts": {}})
    all_ins = get_all_insights()
    ok9 = len(all_ins) >= 1
    print(f"  {'ok' if ok9 else 'FAIL'} get_all_insights 返回 {len(all_ins)} 条")

    print("\n【测试 10】get_insight_count")
    count10 = get_insight_count()
    print(f"  当前 insight 总数: {count10}")

    print("\n" + "=" * 60)
    all_ok = ok1 and ok2 and ok3 and ok4 and ok5 and ok6 and ok7 and ok8 and ok9
    print(f"测试结果: {'全部通过 ok' if all_ok else '部分失败 FAIL'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
