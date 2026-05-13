"""
验证测试：inner_diary.py 内心日记模块

覆盖：
- DiaryEntry 数据结构
- write_diary_entry 触发条件
- _describe_state 状态独白生成
- _describe_action 行动描述
- read_diary_entries 读取
- 写入失败不抛异常
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import src.inner_diary as inner_diary


class MockEntity:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.tick = kwargs.get('tick', 0)
        self.last_interaction_timestamp = kwargs.get('last_interaction_timestamp', 0)


class TestDiaryEntry:
    """DiaryEntry 数据结构。"""

    def test_to_dict_roundtrip(self):
        entry = inner_diary.DiaryEntry(
            tick=10,
            timestamp=1234567890.0,
            diary_type="feeling",
            text="有点孤独。",
            state_snapshot={"loneliness": 0.8, "energy": 0.5},
            emotional_keywords=["孤独"],
        )
        d = entry.to_dict()
        assert d["tick"] == 10
        assert d["type"] == "feeling"
        assert d["text"] == "有点孤独。"
        assert d["state_snapshot"]["loneliness"] == 0.8
        assert d["emotional_keywords"] == ["孤独"]

    def test_defaults(self):
        entry = inner_diary.DiaryEntry(
            tick=1, timestamp=0.0, diary_type="thought", text="test"
        )
        assert entry.emotional_keywords == []
        assert entry.state_snapshot == {}


class TestWriteDiaryEntry:
    """write_diary_entry 触发条件和写入。"""

    def test_returns_none_when_no_content(self):
        """无内心内容且非摘要 tick 时返回 None。"""
        tmp = Path(tempfile.mkdtemp())
        entity = MockEntity(
            tick=1, loneliness=0.3, fatigue=0.1, boredom=0.2,
            energy=0.8, stress=0.0, somatic_tone=0.0,
            unresolved=0.2, info_gap=0.5
        )
        with patch.object(inner_diary, '_INTERNAL_LOG', tmp / 'empty.jsonl'):
            result = inner_diary.write_diary_entry(entity, decision=None, prev_state=None)
        assert result is None

    def test_high_loneliness_writes_entry(self):
        """高孤独感时写入内心日记。"""
        tmp = Path(tempfile.mkdtemp())
        entity = MockEntity(
            tick=5, loneliness=0.9, fatigue=0.1, boredom=0.2,
            energy=0.8, stress=0.0, somatic_tone=0.0,
            unresolved=0.2, info_gap=0.5
        )
        with patch.object(inner_diary, '_INTERNAL_LOG', tmp / 'lonely.jsonl'):
            result = inner_diary.write_diary_entry(entity, decision=None, prev_state=None)
        assert result is not None
        assert result.type == "feeling"
        assert "孤独" in result.text
        assert result.state_snapshot["loneliness"] == 0.9

    def test_high_boredom_writes_entry(self):
        """高无聊时写入内心日记。"""
        tmp = Path(tempfile.mkdtemp())
        entity = MockEntity(
            tick=6, loneliness=0.3, fatigue=0.1, boredom=0.9,
            energy=0.8, stress=0.0, somatic_tone=0.0,
            unresolved=0.2, info_gap=0.5
        )
        with patch.object(inner_diary, '_INTERNAL_LOG', tmp / 'bored.jsonl'):
            result = inner_diary.write_diary_entry(entity, decision=None, prev_state=None)
        assert result is not None

    def test_decision_reach_writes_entry(self):
        """decision 中有 reach 时写入内心日记。"""
        tmp = Path(tempfile.mkdtemp())
        entity = MockEntity(
            tick=7, loneliness=0.3, fatigue=0.1, boredom=0.2,
            energy=0.8, stress=0.0, somatic_tone=0.0,
            unresolved=0.2, info_gap=0.5
        )
        decision = {"action": "reach", "priority": 0.7}
        with patch.object(inner_diary, '_INTERNAL_LOG', tmp / 'reach.jsonl'):
            result = inner_diary.write_diary_entry(entity, decision=decision, prev_state=None)
        assert result is not None
        assert "敲门" in result.text

    def test_summary_tick_writes_entry(self):
        """tick=10 时：如果 describe_state 生成了内容就用它，否则写观察。"""
        tmp = Path(tempfile.mkdtemp())
        # somatic_tone=0.0 不会触发任何独白 → text=None → tick=10 触发摘要兜底
        entity = MockEntity(
            tick=10, loneliness=0.3, fatigue=0.5, boredom=0.3,
            energy=0.4, stress=0.2, somatic_tone=0.0,
            unresolved=0.2, info_gap=0.5
        )
        with patch.object(inner_diary, '_INTERNAL_LOG', tmp / 'summary.jsonl'):
            result = inner_diary.write_diary_entry(entity, decision=None, prev_state=None)
        assert result is not None
        # tick=10 一定写条目
        assert result.tick == 10

    def test_write_failure_does_not_raise(self):
        """写入失败时不抛异常（静默跳过）。"""
        entity = MockEntity(
            tick=1, loneliness=0.3, fatigue=0.1, boredom=0.2,
            energy=0.8, stress=0.0, somatic_tone=0.0,
            unresolved=0.2, info_gap=0.5
        )
        bad = Path('/nonexistent/that/wont/exist.jsonl')
        with patch.object(inner_diary, '_INTERNAL_LOG', bad):
            result = inner_diary.write_diary_entry(entity, decision=None, prev_state=None)
        assert result is None


class TestDescribeState:
    """_describe_state 状态独白生成。"""

    def test_high_fatigue_low_energy(self):
        entity = MockEntity(
            loneliness=0.3, fatigue=0.9, boredom=0.2,
            energy=0.1, stress=0.0, somatic_tone=0.0,
            unresolved=0.2, info_gap=0.5, tick=1
        )
        result = inner_diary._describe_state(entity, prev_state=None)
        assert result is not None
        assert "累" in result or "能量" in result

    def test_high_stress(self):
        entity = MockEntity(
            loneliness=0.3, fatigue=0.1, boredom=0.2,
            energy=0.8, stress=0.7, somatic_tone=0.0,
            unresolved=0.2, info_gap=0.5, tick=1
        )
        result = inner_diary._describe_state(entity, prev_state=None)
        assert result is not None

    def test_all_low_returns_none(self):
        """所有维度都很低时没有内心独白（energy 也要不过高）。"""
        entity = MockEntity(
            loneliness=0.05, fatigue=0.1, boredom=0.05,
            energy=0.7, stress=0.0, somatic_tone=0.0,
            unresolved=0.05, info_gap=0.05, tick=1
        )
        result = inner_diary._describe_state(entity, prev_state=None)
        assert result is None

    def test_delta_loneliness_rising(self):
        """孤独感上升时有"又"的描述。"""
        entity = MockEntity(
            loneliness=0.8, fatigue=0.1, boredom=0.2,
            energy=0.8, stress=0.0, somatic_tone=0.0,
            unresolved=0.2, info_gap=0.5, tick=1
        )
        prev = MockEntity(
            loneliness=0.4, fatigue=0.1, boredom=0.2,
            energy=0.8, stress=0.0, somatic_tone=0.0,
            unresolved=0.2, info_gap=0.5, tick=0
        )
        result = inner_diary._describe_state(entity, prev_state=prev)
        assert result is not None
        assert "又" in result


class TestDescribeAction:
    """_describe_action 行动描述。"""

    def test_rest_action(self):
        result = inner_diary._describe_action({"action": "rest", "priority": 0.6})
        assert result is not None
        assert "休息" in result

    def test_seek_action(self):
        result = inner_diary._describe_action({"action": "seek", "priority": 0.5})
        assert result is not None
        assert "靠近" in result

    def test_idle_action_returns_none(self):
        result = inner_diary._describe_action({"action": "idle", "priority": 0.0})
        assert result is None

    def test_none_decision_returns_none(self):
        result = inner_diary._describe_action(None)
        assert result is None


class TestReadDiaryEntries:
    """read_diary_entries 读取功能。"""

    def test_read_empty_returns_empty_list(self):
        tmp = Path(tempfile.mkdtemp())
        empty_path = tmp / 'empty_diary.jsonl'
        with patch.object(inner_diary, '_INTERNAL_LOG', empty_path):
            result = inner_diary.read_diary_entries(limit=10)
        assert result == []

    def test_read_entries_reverse_order(self):
        tmp = Path(tempfile.mkdtemp())
        log_path = tmp / 'read_test.jsonl'
        entries = [
            {"tick": 1, "timestamp": 1000.0, "type": "thought", "text": "第一条",
             "state_snapshot": {}, "emotional_keywords": []},
            {"tick": 2, "timestamp": 2000.0, "type": "feeling", "text": "第二条",
             "state_snapshot": {}, "emotional_keywords": []},
            {"tick": 3, "timestamp": 3000.0, "type": "observation", "text": "第三条",
             "state_snapshot": {}, "emotional_keywords": []},
        ]
        with open(log_path, 'w', encoding='utf-8') as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        with patch.object(inner_diary, '_INTERNAL_LOG', log_path):
            result = inner_diary.read_diary_entries(limit=50)
        assert len(result) == 3
        assert result[0].tick == 3
        assert result[1].tick == 2
        assert result[2].tick == 1

    def test_read_limit(self):
        tmp = Path(tempfile.mkdtemp())
        log_path = tmp / 'limit_test.jsonl'
        with open(log_path, 'w', encoding='utf-8') as f:
            for i in range(10):
                f.write(json.dumps({
                    "tick": i, "timestamp": float(i * 100),
                    "type": "thought", "text": f"条目 {i}",
                    "state_snapshot": {}, "emotional_keywords": []
                }, ensure_ascii=False) + "\n")
        with patch.object(inner_diary, '_INTERNAL_LOG', log_path):
            result = inner_diary.read_diary_entries(limit=3)
        assert len(result) == 3
        assert result[0].tick == 9


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
