# 风化系统 + 可观测性 实现计划

> 给 Cursor 的完整实现指南。按步骤顺序执行，每步独立可验证。
> 每个文件不超过 300 行。所有代码必须模块化。

---

## 前置知识：现有代码接口

### Rule dataclass (`src/world_model_update/rules.py`)

```python
@dataclass
class Rule:
    id: str = ""
    content: str = ""
    confidence: float = 0.5
    source_experience_count: int = 1
    stability_score: float = 0.5
    stability_band: float = 0.1
    created_at: float = 0.0
    last_verified_at: float = 0.0
    last_decay_at: float = 0.0
    status: str = "active"          # "active" | "pending" | "decayed"
    domain: str = "general"         # ← 已存在，不需要再加
    context: str = ""
    predicts: Predicts = ...
    evidence: List[Evidence] = ...
    expected_deltas: Dict[str, float] = ...  # 规律追踪的状态维度及预期变化量
    _debug_meta: Dict[str, Any] = ...
```

- `to_dict()` 和 `from_dict()` 已正确处理 `domain` 字段。
- **不需要修改 rules.py**。

### compute_inertia (`src/world_model_update/model_inertia.py`)

```python
def compute_inertia(
    rule: Rule,
    all_rules: Optional[List[Rule]] = None,
    now: Optional[float] = None,
) -> float:
    """返回 [0, 1]。高值 = 深嵌核心信念。"""
```

内部已有 `_compute_coupling(rule, all_rules)` 计算下游耦合度。

### ParameterSnapshot (`src/parameter_system/snapshot.py`)

```python
@dataclass
class ParameterSnapshot:
    snapshot_id: str
    created_at: float
    params: ReadOnlyView    # 只读 dict，通过 get_param() 访问
    tick_index: int
    is_valid: bool = True
```

用 `get_param(snapshot, "dot.path.key", default)` 读参数值。

### EntityCore (`src/core/entity_core.py`)

关键状态字段（全部 [0,1] 除 somatic_tone [-1,1]）：
`energy`, `loneliness`, `unresolved`, `fatigue`, `info_gap`, `somatic_tone`,
`danger_level`, `approach_drive`, `avoid_drive`, `curiosity`, `boredom_despair`, `boredom_futility`

### 项目路径约定

- 项目根目录: `E:/XIA/`
- 源码: `E:/XIA/src/`
- 日志: `E:/XIA/logs/`
- 数据: `E:/XIA/data/`
- 从 `src/observability/` 引用兄弟包用 `from ..xxx import yyy`

---

## 第一步：可观测性基础设施

### 文件 1: `src/observability/events.py` (~120 行)

```python
"""
Observability Events — 可观测性事件类型定义

所有事件都是不可变 dataclass，可直接 JSON 序列化。
每种事件类型对应一个 JSONL 日志文件。
"""

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class DriftEvent:
    """参数漂移记录 → logs/drift_trace.jsonl"""
    tick: int
    param_path: str             # 例 "personality.introverted_bias"
    old_value: float
    new_value: float
    drift_source: str           # "weathering" | "shattering" | "manual"
    signal_strength: float      # 驱动这次漂移的信号强度
    baseline: float             # 当前 EMA baseline
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RuleLifecycleEvent:
    """规律生命周期 → logs/rule_lifecycle.jsonl"""
    tick: int
    rule_id: str
    event_type: str             # "created" | "merged" | "decayed" | "shattered"
                                # | "promoted" | "verified" | "resisted"
    confidence_before: float
    confidence_after: float
    cause: str                  # 人类可读的原因描述
    domain: str = "general"     # 规律所属认知域
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ShatteringEvent:
    """崩塌事件 → logs/shattering_events.jsonl"""
    tick: int
    rule_id: str
    rule_content: str           # 规律内容（方便人类阅读）
    shattering_force: float
    update_resistance: float
    outcome: str                # "resisted" | "collapsed" | "forced_collapse"
    suppressed_tension: float   # 当前累积的压抑张力
    affected_params: List[str]  # 受影响的参数路径列表
    confidence_before: float
    confidence_after: float
    inertia: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TensionSnapshot:
    """张力状态快照 → logs/tension_snapshots.jsonl"""
    tick: int
    total_tension: float
    suppressed_tension: float
    contradiction_count: int    # 当前矛盾规律对数
    rule_count: int             # 活跃规律总数
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)
```

### 文件 2: `src/observability/event_log.py` (~130 行)

```python
"""
Event Log — JSONL 事件写入器

线程安全，按事件类型路由到不同日志文件。
所有写入同步进行（JSONL 追加写入很快，不需要异步）。
"""

import json
import logging
import threading
from pathlib import Path
from typing import Any

from .events import (
    DriftEvent,
    RuleLifecycleEvent,
    ShatteringEvent,
    TensionSnapshot,
)

logger = logging.getLogger(__name__)

# 项目根目录 / logs
_LOGS_DIR = Path(__file__).parent.parent.parent / "logs"

# 事件类型 → 日志文件名
_EVENT_FILE_MAP = {
    DriftEvent: "drift_trace.jsonl",
    RuleLifecycleEvent: "rule_lifecycle.jsonl",
    ShatteringEvent: "shattering_events.jsonl",
    TensionSnapshot: "tension_snapshots.jsonl",
}

# 全局写锁（per 文件）
_file_locks: dict = {}
_global_lock = threading.Lock()


def _get_lock(filename: str) -> threading.Lock:
    """获取文件级写锁（懒初始化）"""
    if filename not in _file_locks:
        with _global_lock:
            if filename not in _file_locks:
                _file_locks[filename] = threading.Lock()
    return _file_locks[filename]


def _ensure_logs_dir() -> None:
    """确保日志目录存在"""
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)


def emit_event(event: Any) -> bool:
    """
    写入一条事件到对应的 JSONL 文件。

    参数：
        event: DriftEvent | RuleLifecycleEvent | ShatteringEvent | TensionSnapshot

    返回：
        bool — 写入成功返回 True，失败返回 False（静默，不抛异常）
    """
    event_type = type(event)
    filename = _EVENT_FILE_MAP.get(event_type)
    if filename is None:
        logger.warning(f"[observability] Unknown event type: {event_type.__name__}")
        return False

    try:
        _ensure_logs_dir()
        filepath = _LOGS_DIR / filename
        line = json.dumps(event.to_dict(), ensure_ascii=False, default=str)

        lock = _get_lock(filename)
        with lock:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return True

    except Exception as e:
        logger.debug(f"[observability] Failed to write {filename}: {e}")
        return False


def read_events(filename: str, limit: int = 100) -> list:
    """
    读取最近 N 条事件（用于调试和前端展示）。

    参数：
        filename: 日志文件名（如 "drift_trace.jsonl"）
        limit: 最多返回的条目数

    返回：
        list[dict] — 最近的事件列表（最新在后）
    """
    filepath = _LOGS_DIR / filename
    if not filepath.exists():
        return []

    try:
        lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()
        recent = lines[-limit:] if len(lines) > limit else lines
        result = []
        for line in recent:
            line = line.strip()
            if line:
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return result
    except Exception:
        return []
```

### 文件 3: `src/observability/__init__.py` (~25 行)

```python
"""
Observability — 可观测性基础设施

公共 API:
    emit_event(event)       — 写入事件到 JSONL
    read_events(file, n)    — 读取最近 N 条事件

事件类型:
    DriftEvent              — 参数漂移
    RuleLifecycleEvent      — 规律生命周期
    ShatteringEvent         — 崩塌事件
    TensionSnapshot         — 张力快照
"""

from .events import (
    DriftEvent,
    RuleLifecycleEvent,
    ShatteringEvent,
    TensionSnapshot,
)
from .event_log import emit_event, read_events

__all__ = [
    "DriftEvent",
    "RuleLifecycleEvent",
    "ShatteringEvent",
    "TensionSnapshot",
    "emit_event",
    "read_events",
]
```

### 验证第一步

在项目根目录运行：

```bash
cd E:/XIA
python -c "
from src.observability import emit_event, DriftEvent, RuleLifecycleEvent
e = DriftEvent(tick=1, param_path='test.param', old_value=0.5, new_value=0.6,
               drift_source='test', signal_strength=0.1, baseline=0.5)
ok = emit_event(e)
print(f'emit ok: {ok}')

r = RuleLifecycleEvent(tick=1, rule_id='r1', event_type='created',
                        confidence_before=0.0, confidence_after=0.5, cause='test')
ok2 = emit_event(r)
print(f'emit ok: {ok2}')

from src.observability import read_events
events = read_events('drift_trace.jsonl', limit=5)
print(f'read back: {len(events)} events')
print(events[-1] if events else 'empty')
"
```

预期输出：
```
emit ok: True
emit ok: True
read back: 1 events
{'tick': 1, 'param_path': 'test.param', ...}
```

---

## 第二步：风化系统

### 文件 4: `src/weathering/registry.py` (~130 行)

```python
"""
Weathering Registry — 参数漂移元数据注册表

定义哪些参数可漂移、漂移层级（表层/中层/深层）、EMA 窗口、有效范围。
漂移速率由 drift_tier 决定，不需要手动指定每个参数的速率。

三层结构：
    SURFACE (表层)  — τ = 86,400 ticks (1天)   — 表达风格、注意力分配
    MID     (中层)  — τ = 604,800 ticks (1周)  — 信任阈值、社交评估
    DEEP    (深层)  — τ = 3,888,000 ticks (45天) — 人格核心、认知基础结构
"""

from dataclasses import dataclass
from typing import Dict, Optional


# ============================================================================
# 漂移层级定义
# ============================================================================

# EMA 窗口 (ticks) — 决定 baseline 的追踪速度
SURFACE_WINDOW = 86_400       # 1 天
MID_WINDOW = 604_800          # 1 周
DEEP_WINDOW = 3_888_000       # 45 天

# 基础漂移速率 (每 tick 的最大漂移量)
SURFACE_DRIFT_RATE = 1e-4
MID_DRIFT_RATE = 1e-5
DEEP_DRIFT_RATE = 1e-6

# 弹簧力系数 — 偏离 baseline 时的回拉强度
SURFACE_SPRING = 0.01
MID_SPRING = 0.005
DEEP_SPRING = 0.002

# 非对称系数 — 负方向漂移比正方向快
NEGATIVE_DRIFT_MULTIPLIER = 1.5
POSITIVE_DRIFT_MULTIPLIER = 0.7


@dataclass(frozen=True)
class DriftableParam:
    """单个可漂移参数的元数据"""
    path: str               # 参数路径，如 "personality.introverted_bias"
    tier: str                # "surface" | "mid" | "deep"
    default_value: float     # 出厂默认值
    min_value: float         # 有效下界
    max_value: float         # 有效上界

    @property
    def ema_window(self) -> int:
        return _TIER_CONFIG[self.tier]["window"]

    @property
    def drift_rate(self) -> float:
        return _TIER_CONFIG[self.tier]["drift_rate"]

    @property
    def spring_constant(self) -> float:
        return _TIER_CONFIG[self.tier]["spring"]


# 层级配置查找表
_TIER_CONFIG = {
    "surface": {
        "window": SURFACE_WINDOW,
        "drift_rate": SURFACE_DRIFT_RATE,
        "spring": SURFACE_SPRING,
    },
    "mid": {
        "window": MID_WINDOW,
        "drift_rate": MID_DRIFT_RATE,
        "spring": MID_SPRING,
    },
    "deep": {
        "window": DEEP_WINDOW,
        "drift_rate": DEEP_DRIFT_RATE,
        "spring": DEEP_SPRING,
    },
}


# ============================================================================
# 可漂移参数注册表
# ============================================================================

DRIFTABLE_PARAMS: Dict[str, DriftableParam] = {}

def _register(path: str, tier: str, default: float,
              min_v: float = 0.0, max_v: float = 1.0) -> None:
    DRIFTABLE_PARAMS[path] = DriftableParam(
        path=path, tier=tier, default_value=default,
        min_value=min_v, max_value=max_v,
    )

# ---- 表层：表达风格、注意力分配 ----
_register("llm.temperature",                            "surface", 0.7,  0.1, 1.5)
_register("decision.max_suggestions",                   "surface", 2.0,  1.0, 5.0)
_register("decision.module_weights.TemporalPressure",   "surface", 1.0,  0.2, 3.0)

# ---- 中层：信任、社交评估、自我感知 ----
_register("decision.survival_override_threshold",       "mid",     0.85, 0.5, 1.0)
_register("web_search.info_hunger_threshold",           "mid",     0.6,  0.2, 0.95)
_register("personality.introverted_bias",               "mid",     0.2,  0.0, 0.8)
_register("personality.extroverted_bias",               "mid",     0.1,  0.0, 0.8)
_register("decision.module_weights.SelfState",          "mid",     1.0,  0.2, 3.0)
_register("decision.module_weights.WorldModel",         "mid",     1.0,  0.2, 3.0)

# ---- 深层：认知基础结构 ----
_register("world_model.decay_rate",                     "deep",    0.02, 0.005, 0.1)
_register("world_model.decay_endocrine_stress_multiplier", "deep", 1.5,  0.5, 4.0)
_register("world_model.decay_stability_resistance_factor", "deep", 2.0,  0.5, 5.0)
_register("world_model.induction_min_rounds",           "deep",    5.0,  3.0, 20.0)


def get_driftable(path: str) -> Optional[DriftableParam]:
    """查询参数是否可漂移。返回 None 表示该参数不在漂移注册表中。"""
    return DRIFTABLE_PARAMS.get(path)


def get_tier_params(tier: str) -> Dict[str, DriftableParam]:
    """返回指定层级的所有参数。"""
    return {k: v for k, v in DRIFTABLE_PARAMS.items() if v.tier == tier}
```

### 文件 5: `src/weathering/baseline.py` (~160 行)

```python
"""
Weathering Baseline — EMA 基线管理 + 弹簧力计算

每个可漂移参数维护一个 EMA baseline。
baseline 随当前值缓慢移动，为弹簧力提供"常态"锚点。
持久化到 data/weathering_baselines.json。
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from .registry import (
    DRIFTABLE_PARAMS,
    NEGATIVE_DRIFT_MULTIPLIER,
    POSITIVE_DRIFT_MULTIPLIER,
)

logger = logging.getLogger(__name__)

# 持久化路径
_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_BASELINE_PATH = _DATA_DIR / "weathering_baselines.json"


class BaselineManager:
    """
    管理所有可漂移参数的 EMA baseline 和 suppressed_tension。

    用法：
        mgr = BaselineManager.load()
        mgr.update_baseline("personality.introverted_bias", current_value=0.25)
        spring = mgr.compute_spring_force("personality.introverted_bias", current_value=0.25)
        mgr.save()
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        self._baselines: Dict[str, float] = {}
        self._suppressed_tension: float = 0.0

        if data:
            self._baselines = dict(data.get("baselines", {}))
            self._suppressed_tension = float(data.get("suppressed_tension", 0.0))

        # 用默认值初始化缺失的 baseline
        for path, param in DRIFTABLE_PARAMS.items():
            if path not in self._baselines:
                self._baselines[path] = param.default_value

    # ---- 持久化 ----

    @classmethod
    def load(cls) -> "BaselineManager":
        """从磁盘加载。文件不存在则返回默认值。"""
        if _BASELINE_PATH.exists():
            try:
                raw = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
                return cls(data=raw)
            except Exception as e:
                logger.warning(f"[weathering] Failed to load baselines: {e}")
        return cls()

    def save(self) -> None:
        """持久化到磁盘。"""
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "baselines": {k: round(v, 8) for k, v in self._baselines.items()},
                "suppressed_tension": round(self._suppressed_tension, 6),
            }
            _BASELINE_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[weathering] Failed to save baselines: {e}")

    # ---- Baseline 操作 ----

    def get_baseline(self, path: str) -> float:
        """获取参数的当前 baseline。"""
        param = DRIFTABLE_PARAMS.get(path)
        if param is None:
            return 0.0
        return self._baselines.get(path, param.default_value)

    def update_baseline(self, path: str, current_value: float) -> None:
        """
        用当前值更新 EMA baseline。

        alpha = 1 / window_ticks，window 由参数的 tier 决定。
        """
        param = DRIFTABLE_PARAMS.get(path)
        if param is None:
            return
        alpha = 1.0 / param.ema_window
        old_baseline = self._baselines.get(path, param.default_value)
        self._baselines[path] = old_baseline * (1.0 - alpha) + current_value * alpha

    def compute_spring_force(self, path: str, current_value: float) -> float:
        """
        计算弹簧力：偏离 baseline 越远，回拉越强。

        返回值方向指向 baseline（正 = 向上拉，负 = 向下拉）。
        公式：force = -spring_constant × (current - baseline)²  × sign(deviation)
        """
        param = DRIFTABLE_PARAMS.get(path)
        if param is None:
            return 0.0
        baseline = self._baselines.get(path, param.default_value)
        deviation = current_value - baseline
        force = param.spring_constant * (deviation ** 2)
        if deviation > 0:
            return -force  # 当前值高于 baseline，向下拉
        else:
            return force   # 当前值低于 baseline，向上拉

    # ---- Suppressed Tension ----

    @property
    def suppressed_tension(self) -> float:
        return self._suppressed_tension

    def add_suppressed_tension(self, amount: float) -> None:
        """累积压抑张力（崩塌被抵抗时调用）。"""
        self._suppressed_tension = max(0.0, self._suppressed_tension + amount)

    def release_suppressed_tension(self) -> float:
        """释放全部压抑张力（崩塌发生时调用）。返回释放量。"""
        released = self._suppressed_tension
        self._suppressed_tension = 0.0
        return released

    # ---- 非对称漂移速率 ----

    @staticmethod
    def asymmetric_rate(base_rate: float, drift_direction: float) -> float:
        """
        非对称漂移速率：负方向漂移更快。

        drift_direction < 0 → 乘 1.5（受损方向更快）
        drift_direction >= 0 → 乘 0.7（恢复方向更慢）
        """
        if drift_direction < 0:
            return base_rate * NEGATIVE_DRIFT_MULTIPLIER
        else:
            return base_rate * POSITIVE_DRIFT_MULTIPLIER
```

### 文件 6: `src/weathering/drift.py` (~200 行)

```python
"""
Weathering Drift — 参数漂移引擎

两条漂移路径：
    1. apply_normal_drift()  — 常规漂移，由累积预测误差驱动，每轮微量
    2. apply_acute_drift()   — 急剧漂移，由崩塌事件触发，单次大量

两条路径最终都通过 _apply_single_drift() 执行，统一接口。
每步 emit DriftEvent 到 logs/drift_trace.jsonl。
"""

import logging
from typing import Any, Dict, List, Optional

from ..observability import DriftEvent, emit_event
from .registry import DRIFTABLE_PARAMS, get_driftable
from .baseline import BaselineManager

logger = logging.getLogger(__name__)


def _apply_single_drift(
    path: str,
    current_value: float,
    drift_amount: float,
    drift_source: str,
    tick: int,
    baseline_mgr: BaselineManager,
) -> float:
    """
    对单个参数执行漂移，返回新值。

    步骤：
        1. 计算弹簧力（偏离 baseline 的阻力）
        2. 计算非对称漂移速率
        3. 合成最终漂移量
        4. 钳位到有效范围
        5. 更新 baseline
        6. emit DriftEvent
    """
    param = get_driftable(path)
    if param is None:
        return current_value

    # 弹簧力
    spring_force = baseline_mgr.compute_spring_force(path, current_value)

    # 非对称速率
    effective_rate = baseline_mgr.asymmetric_rate(param.drift_rate, drift_amount)

    # 最终漂移 = 信号驱动 + 弹簧回拉
    total_drift = drift_amount * effective_rate + spring_force * param.drift_rate

    # 钳位
    new_value = max(param.min_value, min(param.max_value, current_value + total_drift))

    # 变化太小则跳过
    if abs(new_value - current_value) < 1e-9:
        return current_value

    # 更新 baseline
    baseline_mgr.update_baseline(path, new_value)

    # emit 事件
    emit_event(DriftEvent(
        tick=tick,
        param_path=path,
        old_value=round(current_value, 6),
        new_value=round(new_value, 6),
        drift_source=drift_source,
        signal_strength=round(abs(drift_amount), 6),
        baseline=round(baseline_mgr.get_baseline(path), 6),
    ))

    return new_value


def apply_normal_drift(
    tick: int,
    drift_signals: Dict[str, float],
    current_params: Dict[str, float],
    baseline_mgr: BaselineManager,
) -> Dict[str, float]:
    """
    常规漂移：由累积预测误差信号驱动的缓慢参数漂移。

    参数：
        tick: 当前 tick
        drift_signals: {param_path: signal_strength}
                       正值 = 参数应增大，负值 = 应减小。
                       来源：CovarianceTracker 长期统计（待后续桥接）。
        current_params: {param_path: current_value} 当前参数值
        baseline_mgr: BaselineManager 实例

    返回：
        {param_path: new_value} — 只包含实际发生漂移的参数
    """
    drifted: Dict[str, float] = {}

    for path, signal in drift_signals.items():
        if path not in DRIFTABLE_PARAMS:
            continue
        if abs(signal) < 1e-8:
            continue

        current = current_params.get(path)
        if current is None:
            continue

        new_value = _apply_single_drift(
            path=path,
            current_value=current,
            drift_amount=signal,
            drift_source="weathering",
            tick=tick,
            baseline_mgr=baseline_mgr,
        )
        if new_value != current:
            drifted[path] = new_value

    return drifted


def apply_acute_drift(
    tick: int,
    affected_params: List[str],
    shattering_force: float,
    current_params: Dict[str, float],
    baseline_mgr: BaselineManager,
    drift_direction: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """
    急剧漂移：由崩塌事件触发的大幅参数位移。

    参数：
        tick: 当前 tick
        affected_params: 受影响的参数路径列表
        shattering_force: 崩塌力（决定漂移幅度）
        current_params: {param_path: current_value}
        baseline_mgr: BaselineManager 实例
        drift_direction: {param_path: direction} 可选。
                        正值=增大，负值=减小。默认全部向防御方向漂移（-1）。

    返回：
        {param_path: new_value} — 只包含实际发生漂移的参数
    """
    if drift_direction is None:
        drift_direction = {}

    drifted: Dict[str, float] = {}

    # 急剧漂移的幅度放大因子
    # shattering_force 通常在 0.01 - 1.5 范围
    # 乘以 500x drift_rate 以产生可感知的即时变化
    amplifier = 500.0

    for path in affected_params:
        param = get_driftable(path)
        if param is None:
            continue

        current = current_params.get(path)
        if current is None:
            continue

        direction = drift_direction.get(path, -1.0)  # 默认负方向（防御/收缩）
        drift_amount = direction * shattering_force * amplifier

        new_value = _apply_single_drift(
            path=path,
            current_value=current,
            drift_amount=drift_amount,
            drift_source="shattering",
            tick=tick,
            baseline_mgr=baseline_mgr,
        )
        if new_value != current:
            drifted[path] = new_value

    return drifted
```

### 文件 7: `src/weathering/shattering.py` (~250 行)

```python
"""
Weathering Shattering — 崩塌检测与抵抗判定

在世界模型更新完成后调用，比较旧规律和新规律的置信度变化，
检测是否有高置信规律被摧毁（shattering），以及系统是否抵抗了更新。

崩塌力公式：
    shattering_force = confidence_drop * inertia * contradiction_pressure * emotional_weight

抵抗力公式：
    update_resistance = identity_binding + attractor_strength + sunk_cost

判定：
    force > resistance  →  collapsed（崩塌，触发急剧漂移）
    force <= resistance →  resisted（抵抗，累积 suppressed_tension）
    suppressed_tension > threshold → forced_collapse（压抑到极限，强制崩塌）
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from ..observability import ShatteringEvent, emit_event
from .registry import DRIFTABLE_PARAMS

logger = logging.getLogger(__name__)

# ---- 阈值常量 ----

# 最低置信度：原始置信度低于此值的规律不参与崩塌检测
MIN_CONFIDENCE_FOR_SHATTERING = 0.7

# 最低置信度跌幅
MIN_CONFIDENCE_DROP = 0.2

# 正常衰减近似值（用于计算 contradiction_pressure）
NORMAL_DECAY_PER_CYCLE = 0.02

# contradiction_pressure 归一化基准
CONTRADICTION_NORM = 0.3

# suppressed_tension 强制崩塌阈值
FORCED_COLLAPSE_THRESHOLD = 3.0

# 默认 emotional_weight（未来可按维度动态计算）
DEFAULT_EMOTIONAL_WEIGHT = 1.0


def _safe_rule_field(rule: Any, field: str, default: Any = None) -> Any:
    """安全读取规律字段（兼容 dict 和 dataclass）。"""
    if isinstance(rule, dict):
        return rule.get(field, default)
    return getattr(rule, field, default)


def _compute_contradiction_pressure(confidence_drop: float) -> float:
    """
    矛盾压力：置信度跌幅超过正常衰减的部分越大，矛盾越强。

    正常衰减 → pressure 约 0
    剧烈下跌 → pressure → 1.0
    """
    excess = max(0.0, confidence_drop - NORMAL_DECAY_PER_CYCLE)
    return min(1.0, excess / CONTRADICTION_NORM)


def _compute_update_resistance(
    inertia: float,
    rule: Any,
    all_rules: List[Any],
) -> float:
    """
    计算更新阻力。

    identity_binding = 下游耦合度（共享 expected_deltas 字段的其他活跃规律占比）
    attractor_strength = inertia * 0.5
    sunk_cost = source_experience_count / 100
    """
    my_fields = set((_safe_rule_field(rule, "expected_deltas") or {}).keys())
    coupling = 0.0
    if my_fields and all_rules:
        active_count = 0
        overlap_total = 0
        my_id = _safe_rule_field(rule, "id")
        for other in all_rules:
            other_id = _safe_rule_field(other, "id")
            if other_id == my_id:
                continue
            if _safe_rule_field(other, "status") != "active":
                continue
            active_count += 1
            other_fields = set((_safe_rule_field(other, "expected_deltas") or {}).keys())
            overlap_total += len(my_fields & other_fields)
        if active_count > 0:
            coupling = min(1.0, overlap_total / max(1.0, active_count))

    identity_binding = coupling
    attractor_strength = inertia * 0.5
    exp_count = int(_safe_rule_field(rule, "source_experience_count", 1))
    sunk_cost = min(1.0, exp_count / 100.0)

    return identity_binding + attractor_strength + sunk_cost


def _find_affected_params(rule: Any) -> List[str]:
    """
    根据规律追踪的维度，找出可能受影响的可漂移参数。

    维度 → 参数路径的映射。未匹配则返回空列表。
    """
    expected_deltas = _safe_rule_field(rule, "expected_deltas") or {}
    tracked_fields = set(expected_deltas.keys())

    if not tracked_fields:
        return []

    dimension_to_params = {
        "loneliness": [
            "personality.introverted_bias",
            "personality.extroverted_bias",
            "decision.module_weights.SelfState",
        ],
        "energy": [
            "world_model.decay_rate",
            "world_model.decay_endocrine_stress_multiplier",
        ],
        "fatigue": [
            "world_model.decay_endocrine_stress_multiplier",
            "decision.survival_override_threshold",
        ],
        "info_gap": [
            "web_search.info_hunger_threshold",
            "decision.module_weights.WorldModel",
        ],
        "danger_level": [
            "decision.survival_override_threshold",
            "decision.module_weights.TemporalPressure",
        ],
        "approach_drive": [
            "personality.extroverted_bias",
        ],
        "avoid_drive": [
            "personality.introverted_bias",
            "decision.survival_override_threshold",
        ],
    }

    affected = set()
    for dim in tracked_fields:
        for mapped_param in dimension_to_params.get(dim, []):
            if mapped_param in DRIFTABLE_PARAMS:
                affected.add(mapped_param)

    return list(affected)


def detect_and_process_shattering(
    old_rules: List[Any],
    new_rules: List[Any],
    all_rules: List[Any],
    tick: int,
    get_inertia_fn: Callable[[Any], float],
    suppressed_tension: float = 0.0,
) -> List[ShatteringEvent]:
    """
    崩塌检测主入口。比较更新前后的规律，检测崩塌事件。

    参数：
        old_rules: 更新前的规律列表（dict 格式，来自 old_rules_snapshot）
        new_rules: 更新后的规律列表（Rule 或 dict 格式）
        all_rules: 全部活跃规律（用于计算 identity_binding）
        tick: 当前 tick
        get_inertia_fn: (rule) -> float，计算规律惯性
        suppressed_tension: 当前已累积的压抑张力

    返回：
        List[ShatteringEvent] — 检测到的崩塌/抵抗事件列表

    调用方（async_pipeline.py）示例：
        shattering_events = detect_and_process_shattering(
            old_rules=old_rules_snapshot,
            new_rules=entity.wm_rules,
            all_rules=entity.wm_rules,
            tick=entity.tick_index,
            get_inertia_fn=lambda r: compute_inertia(r),
            suppressed_tension=baseline_mgr.suppressed_tension,
        )
    """
    # 旧规律置信度查找表
    old_conf_map: Dict[str, float] = {}
    old_rule_map: Dict[str, Any] = {}
    for r in old_rules:
        rid = _safe_rule_field(r, "id")
        if rid:
            old_conf_map[rid] = float(_safe_rule_field(r, "confidence", 0.5))
            old_rule_map[rid] = r

    # 新规律置信度查找表
    new_conf_map: Dict[str, float] = {}
    for r in new_rules:
        rid = _safe_rule_field(r, "id")
        if rid:
            new_conf_map[rid] = float(_safe_rule_field(r, "confidence", 0.5))

    events: List[ShatteringEvent] = []
    current_tension = suppressed_tension

    for rule_id, old_conf in old_conf_map.items():
        if old_conf < MIN_CONFIDENCE_FOR_SHATTERING:
            continue

        new_conf = new_conf_map.get(rule_id, 0.0)
        conf_drop = old_conf - new_conf

        if conf_drop < MIN_CONFIDENCE_DROP:
            continue

        old_rule = old_rule_map.get(rule_id)
        if old_rule is None:
            continue

        # 计算崩塌力
        try:
            from ..world_model_update.rules import Rule as _Rule
            rule_obj = _Rule.from_dict(old_rule) if isinstance(old_rule, dict) else old_rule
            inertia = get_inertia_fn(rule_obj)
        except Exception:
            inertia = 0.5

        contradiction = _compute_contradiction_pressure(conf_drop)
        emotional_weight = DEFAULT_EMOTIONAL_WEIGHT

        shattering_force = conf_drop * inertia * contradiction * emotional_weight

        # 计算抵抗力
        resistance = _compute_update_resistance(inertia, old_rule, all_rules)

        # 受影响参数
        affected = _find_affected_params(old_rule)

        # 判定
        if current_tension >= FORCED_COLLAPSE_THRESHOLD:
            outcome = "forced_collapse"
            current_tension = 0.0
        elif shattering_force > resistance:
            outcome = "collapsed"
        else:
            outcome = "resisted"
            current_tension += shattering_force * 0.5

        rule_content = str(_safe_rule_field(old_rule, "content", ""))

        event = ShatteringEvent(
            tick=tick,
            rule_id=rule_id,
            rule_content=rule_content[:100],
            shattering_force=round(shattering_force, 5),
            update_resistance=round(resistance, 5),
            outcome=outcome,
            suppressed_tension=round(current_tension, 5),
            affected_params=affected,
            confidence_before=round(old_conf, 4),
            confidence_after=round(new_conf, 4),
            inertia=round(inertia, 4),
        )

        emit_event(event)
        events.append(event)

        logger.info(
            f"[weathering] Shattering {outcome}: rule={rule_id}, "
            f"force={shattering_force:.4f}, resistance={resistance:.4f}"
        )

    return events
```

### 文件 8: `src/weathering/__init__.py` (~30 行)

```python
"""
Weathering — 风化系统

长期参数漂移机制。历史通过预测误差和崩塌事件对参数层施加缓慢结构塑形。

公共 API:
    apply_normal_drift()              — 常规漂移（每轮微量）
    apply_acute_drift()               — 急剧漂移（崩塌触发）
    detect_and_process_shattering()   — 崩塌检测
    BaselineManager                   — EMA 基线管理器
    DRIFTABLE_PARAMS                  — 可漂移参数注册表
"""

from .registry import DRIFTABLE_PARAMS, DriftableParam, get_driftable, get_tier_params
from .baseline import BaselineManager
from .drift import apply_normal_drift, apply_acute_drift
from .shattering import detect_and_process_shattering

__all__ = [
    "DRIFTABLE_PARAMS",
    "DriftableParam",
    "get_driftable",
    "get_tier_params",
    "BaselineManager",
    "apply_normal_drift",
    "apply_acute_drift",
    "detect_and_process_shattering",
]
```

### 验证第二步

```bash
cd E:/XIA
python -c "
from src.weathering import (
    DRIFTABLE_PARAMS, BaselineManager,
    detect_and_process_shattering, apply_acute_drift,
)
print(f'Registered params: {len(DRIFTABLE_PARAMS)}')
for path, p in DRIFTABLE_PARAMS.items():
    print(f'  {p.tier:8s} {path} = {p.default_value}')

mgr = BaselineManager()
bl = mgr.get_baseline('personality.introverted_bias')
print(f'\nBaseline for introverted_bias: {bl}')

spring = mgr.compute_spring_force('personality.introverted_bias', 0.5)
print(f'Spring force at 0.5 (baseline=0.2): {spring:.6f}')

mgr.save()
print('Baseline saved to data/weathering_baselines.json')
"
```

预期输出：
```
Registered params: 13
   surface llm.temperature = 0.7
   surface decision.max_suggestions = 2.0
   surface decision.module_weights.TemporalPressure = 1.0
   mid     decision.survival_override_threshold = 0.85
   mid     web_search.info_hunger_threshold = 0.6
   mid     personality.introverted_bias = 0.2
   mid     personality.extroverted_bias = 0.1
   mid     decision.module_weights.SelfState = 1.0
   mid     decision.module_weights.WorldModel = 1.0
   deep    world_model.decay_rate = 0.02
   deep    world_model.decay_endocrine_stress_multiplier = 1.5
   deep    world_model.decay_stability_resistance_factor = 2.0
   deep    world_model.induction_min_rounds = 5.0

Baseline for introverted_bias: 0.2
Spring force at 0.5 (baseline=0.2): -0.000450
Baseline saved to data/weathering_baselines.json
```

---

## 第三步：Rule domain 字段

**已完成**。`rules.py` 的 `Rule` dataclass 第 141 行已有 `domain: str = "general"`。
`to_dict()` 和 `from_dict()` 均已正确处理。**无需修改。**

---

## 第四步：接入点 — async_pipeline.py 修改

**文件**: `src/pipeline_runner/async_pipeline.py`

**操作**: 替换第 167-189 行（现有的崩塌检测代码块）为以下内容：

```python
                        # ---- 崩塌检测 ----
                        try:
                            from ..weathering.shattering import detect_and_process_shattering
                            from ..weathering.drift import apply_acute_drift
                            from ..weathering.baseline import BaselineManager
                            from ..world_model_update.model_inertia import compute_inertia

                            _baseline_mgr = BaselineManager.load()

                            shattering_events = detect_and_process_shattering(
                                old_rules=old_rules_snapshot,
                                new_rules=entity.wm_rules,
                                all_rules=entity.wm_rules,
                                tick=getattr(entity, "tick_index", 0),
                                get_inertia_fn=lambda r: compute_inertia(r) if hasattr(r, "confidence") else 0.5,
                                suppressed_tension=_baseline_mgr.suppressed_tension,
                            )

                            if shattering_events:
                                from ..parameter_system.access import get_param as _get_param
                                from ..weathering.registry import DRIFTABLE_PARAMS as _DP

                                # 收集当前参数值
                                _current_params = {}
                                for _evt in shattering_events:
                                    for _p in _evt.affected_params:
                                        if _p not in _current_params:
                                            _def = _DP[_p].default_value if _p in _DP else 0.0
                                            _current_params[_p] = _get_param(param_snapshot, _p, _def)

                                for _evt in shattering_events:
                                    if _evt.outcome in ("collapsed", "forced_collapse"):
                                        _drifted = apply_acute_drift(
                                            tick=_evt.tick,
                                            affected_params=_evt.affected_params,
                                            shattering_force=_evt.shattering_force,
                                            current_params=_current_params,
                                            baseline_mgr=_baseline_mgr,
                                        )
                                        if _drifted:
                                            logger.info(
                                                f"[weathering] Acute drift: {_evt.rule_id} -> "
                                                f"{list(_drifted.keys())}"
                                            )
                                            # TODO: 写入参数系统 (stage_changes + apply_staged)
                                    elif _evt.outcome == "resisted":
                                        _baseline_mgr.add_suppressed_tension(
                                            _evt.shattering_force * 0.5
                                        )

                                _baseline_mgr.save()

                        except Exception as e:
                            logger.debug(f"[weathering] Shattering detection skipped: {e}")
```

**注意缩进**：这段代码位于多层 try/if 内，缩进层级为 6 层（24 个空格）。
请参照该文件中上下文的实际缩进对齐。

**关键说明**：`apply_acute_drift` 目前只返回新参数值，不直接写入参数系统。
实际写入需要后续通过 `stage_changes()` + `apply_staged()` 桥接。
当前阶段只做检测 + 日志记录 + baseline 更新。

---

## 文件清单

| 操作 | 文件路径 | 预估行数 |
|------|---------|---------|
| 新建 | `src/observability/__init__.py` | ~25 |
| 新建 | `src/observability/events.py` | ~120 |
| 新建 | `src/observability/event_log.py` | ~130 |
| 新建 | `src/weathering/__init__.py` | ~30 |
| 新建 | `src/weathering/registry.py` | ~130 |
| 新建 | `src/weathering/baseline.py` | ~160 |
| 新建 | `src/weathering/drift.py` | ~200 |
| 新建 | `src/weathering/shattering.py` | ~250 |
| 修改 | `src/pipeline_runner/async_pipeline.py` 第 167-189 行 | 替换约 40 行 |
| 已完成 | `src/world_model_update/rules.py` — domain 字段 | 无需修改 |

---

## 待后续迭代（本次不实现）

1. **CovarianceTracker → 漂移信号桥接**
   - 从 CovarianceTracker 长期统计提取漂移信号
   - 实现 `signal_accumulator.py`
   - 接入 `apply_normal_drift()` 的 `drift_signals` 参数

2. **参数写入桥接**
   - `apply_acute_drift` 返回的新值写入 parameter_system
   - 通过 `stage_changes()` + `apply_staged()` 实现

3. **TensionSnapshot 定期 emit**
   - 在 tick_engine 中每 N tick emit 一次 TensionSnapshot
   - 统计矛盾规律对数、总张力

4. **emotional_weight 动态计算**
   - 按规律追踪的维度的当前驱动压力计算情绪权重
   - 替换 `shattering.py` 中的 `DEFAULT_EMOTIONAL_WEIGHT`

5. **域隔离**
   - 漂移和崩塌按 domain 隔离
   - `social.intimate` 域的崩塌不影响 `work` 域的参数

6. **前端可视化**
   - 读取 JSONL 日志，展示漂移轨迹和崩塌时间线

7. **规律生态（rule merging + contradiction pressure）**
   - `world_model_update/ecology.py`
   - 相似规律合并、矛盾规律产生张力

---

## 执行顺序

```
第一步: 创建 src/observability/ 下 3 个文件 → 运行验证脚本
第二步: 创建 src/weathering/ 下 5 个文件 → 运行验证脚本
第三步: 跳过（已完成）
第四步: 修改 src/pipeline_runner/async_pipeline.py 第 167-189 行 → 替换为带漂移调用的版本
```

每步完成后运行对应的验证脚本确认无错。
