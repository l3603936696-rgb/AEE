# -*- coding: utf-8 -*-
"""共享测试 helper（clarification v2）：_MockEntity / _ep / _seed_memory。

供 test_clarification_learning.py 与 test_clarification_attribution.py 共用，
避免重复 helper 块、保持各测试文件 ≤400 行。非 test_ 前缀，pytest 不收集为用例。
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

from src.language_system.clarification_memory import ClarificationMemory, ClarificationEpisode


class _MockEntity:
    def __init__(self, tick=1, confidence=0.3, **kw):
        self.tick = tick
        self._understanding_confidence = confidence
        self._clarification_memory = None
        self._clarification_memory_data = {}
        self._clarification_evidence_store = None
        self._clarification_hints_data = {}
        for k, v in kw.items():
            setattr(self, k, v)


def _ep(kind, slot, original_input="test input", ts=None, tick=1,
        qtext="这句我没太懂", confidence=0.3):
    return ClarificationEpisode(
        original_input=original_input,
        proposition_frame={"slot_confidence": {"actor": 0.5}, "slot_relevance": {"actor": 0.5}},
        clarification_kind=kind,
        clarification_slot=slot,
        question_text=qtext,
        confidence=confidence,
        tick=tick,
        timestamp=ts or time.time(),
    )


def _seed_memory(entity, episodes):
    mem = ClarificationMemory(history=episodes)
    entity._clarification_memory_data = mem.to_dict()
