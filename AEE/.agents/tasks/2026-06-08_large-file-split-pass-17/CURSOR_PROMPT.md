# CURSOR PROMPT — Pass 17

## 上下文

你是 XIA 项目的大文件拆分 agent，负责将 `src/language_system/interpretation_competition.py`（614行）按函数簇拆分为子模块。

## 任务

拆分 `src/language_system/interpretation_competition.py`，拆分方案见 `SPEC.md`。

## 执行步骤

### Step 1 — 创建 `src/language_system/interpretation_schema.py`

从 `interpretation_competition.py` 提取 dataclass 定义和相关常量：

```python
"""
Interpretation Schema — dataclass definitions for interpretation competition.
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

# Constants
_COMPETITION_EPS: float = 0.001
_BASE_EXPERIENCE_CONFIDENCE: float = 0.5

@dataclass
class ExperienceCandidate:
    interpretation: str
    source_id: str
    experience_id: str
    confidence: float = _BASE_EXPERIENCE_CONFIDENCE
    emotion_mod: float = 0.5
    conversion: float = 1.0
    competitive_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "interpretation": self.interpretation,
            "source_id": self.source_id,
            "experience_id": self.experience_id,
            "confidence": round(self.confidence, 4),
            "emotion_mod": round(self.emotion_mod, 4),
            "conversion": round(self.conversion, 4),
            "competitive_score": round(self.competitive_score, 4),
        }

@dataclass
class CompetitionResult:
    winner: Optional[ExperienceCandidate]
    tension_level: float
    tension_type: str
    candidates: List[ExperienceCandidate]
    top_scores: Tuple[float, float]

    def to_dict(self) -> dict:
        return {
            "winner": self.winner.to_dict() if self.winner else None,
            "tension_level": round(self.tension_level, 4),
            "tension_type": self.tension_type,
            "top_scores": [round(s, 4) for s in self.top_scores],
            "candidates": [c.to_dict() for c in self.candidates],
        }
```

### Step 2 — 创建 `src/language_system/interpretation_compute.py`

提取计算逻辑：

```python
"""
Interpretation Compute — scoring and candidate building for interpretation competition.
"""

import math
from typing import Any, Dict, List, Optional

from .interpretation_schema import (
    ExperienceCandidate,
    _COMPETITION_EPS,
    _BASE_EXPERIENCE_CONFIDENCE,
)

MAX_CANDIDATES: int = 8

def compute_competitive_score(
    candidate: ExperienceCandidate,
    state_snapshot: Dict[str, float],
) -> float:
    # (copy the existing function body verbatim)

def _softmax_weights(scores: List[float], temperature: float = 0.1) -> List[float]:
    # (copy the existing function body verbatim)

def build_candidates_from_stereotype(
    input_text: str,
    stereotype_context: Optional[Any],
    spm_resonance: Dict[str, float],
    named_patterns: List[Dict[str, Any]],
) -> List[ExperienceCandidate]:
    # (copy the existing function body verbatim)
```

### Step 3 — 重写 `src/language_system/interpretation_competition.py`

变为瘦入口：

```python
"""
Interpretation Competition — v1.0
(explanation competition mechanism)

Thin entry point. Implementation in submodules:
    interpretation_schema.py  — dataclass definitions
    interpretation_compute.py — scoring & candidate building
"""

import logging
from typing import Dict, List, Optional

from .interpretation_schema import (
    ExperienceCandidate,
    CompetitionResult,
    _COMPETITION_EPS,
    _BASE_EXPERIENCE_CONFIDENCE,
)
from .interpretation_compute import (
    compute_competitive_score,
    _softmax_weights,
    build_candidates_from_stereotype,
    MAX_CANDIDATES,
)

logger = logging.getLogger(__name__)

# Constants (kept here for backward compatibility)
TENSION_THRESHOLD: float = 1.15
CONFIDENCE_DECAY_RATE: float = 0.001

# (keep the following functions, importing helpers from submodules)
def run_interpretation_competition(...):
    # (existing body, call into interpretation_compute where appropriate)

def run_interpretation_stage(ctx, entity) -> None:
    # (existing body)

def compute_prelinguistic_tension(...):
    # (existing body)

def apply_prelinguistic_tension(...):
    # (existing body)

def apply_tension_to_candidates(...):
    # (existing body)

__all__ = [
    "ExperienceCandidate",
    "CompetitionResult",
    "TENSION_THRESHOLD",
    "MAX_CANDIDATES",
    "CONFIDENCE_DECAY_RATE",
    "COMPETITION_EPS",
    "BASE_EXPERIENCE_CONFIDENCE",
    "compute_competitive_score",
    "run_interpretation_competition",
    "run_interpretation_stage",
    "compute_prelinguistic_tension",
    "apply_prelinguistic_tension",
    "apply_tension_to_candidates",
]
```

### Step 4 — 创建 `src/language_system/interpretation_test.py`

将原 `if __name__ == "__main__":` 测试块（lines 449-572）提取为独立可执行文件。

### Step 5 — 更新文档

在 `XIA_SYSTEMS.md` 的 language_system 子模块表中新增：
- `interpretation_schema.py` — Competition dataclass definitions
- `interpretation_compute.py` — Scoring & candidate building
- `interpretation_competition.py` — Thin entry point
- `interpretation_test.py` — Standalone test

## 约束

- 不改变任何 public API 名称和签名
- 原有 `from src.language_system.interpretation_competition import ...` 引用无需修改
- 新模块均低于 400 行
- 不要引入新的 LLM 调用点

## 验证

完成后运行：
1. `python -m py_compile src/language_system/interpretation_schema.py src/language_system/interpretation_compute.py src/language_system/interpretation_competition.py src/language_system/interpretation_test.py`
2. Import smoke test: `python -c "from src.language_system.interpretation_competition import run_interpretation_competition, CompetitionResult, compute_competitive_score"`
3. `python -m pytest tests/test_source_identity.py tests/test_expression_relief.py -q`
4. `git diff --check -- src/language_system/interpretation_schema.py src/language_system/interpretation_compute.py src/language_system/interpretation_competition.py src/language_system/interpretation_test.py`
