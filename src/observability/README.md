# Observability Layer — 第0步：现有设施盘点 + 新增落点设计

## 现有设施

| 名称 | 位置 | 功能 | 局限性 |
|------|------|------|--------|
| `ctx._trace` | `pipeline_runner/__init__.py` | 每阶段调用/成功/耗时记录 | 仅覆盖13个阶段名，无模块级粒度 |
| `PipelineTrace` | `entity_state.py` | trace 数据结构 | 仅存储，无聚合/报告 |
| `emergence.jsonl` | `logs/` | 每 tick 一次状态快照+输出 | 固定格式，不可配置 |
| `tension_snapshots.jsonl` | `logs/` | 张力快照（每600 tick） | 稀疏，仅覆盖 world_model |
| `drift_trace.jsonl` | `logs/` | 参数漂移记录 | 仅覆盖 weathering |
| `observability/events.py` | `src/observability/` | 4种结构化事件定义 | **已有框架但几乎未被使用** |
| `observability/event_log.py` | `src/observability/` | JSONL 写入器 | **已有框架但几乎未被使用** |

**关键发现**：现有 observability 层是"半成品"——定义了数据结构但从未真正 emit 事件。
`emergence.jsonl` 是唯一真正在写的，每行是一次 tick 的完整状态快照。

## 新增落点设计

### 数据结构

```
data/observability/
  _registry.json   ← 全局模块注册表（累计，写入前先读）
  module_calls/   ← 每个模块一条，按调用者分目录
    pipeline/
    language/
    llm/
  _meta.log       ← 观测层自身的错误日志（防静默黑洞）
```

### 注册表字段（per module_name）

```json
{
  "module_name": {
    "calls": 0,
    "successes": 0,
    "failures": 0,
    "first_tick": 0,
    "last_tick": 0,
    "last_call_time": 1700000000.0,
    "avg_duration_ms": 0.0,
    "last_error_type": "",
    "last_error_summary": "",
    "failure_sequence": 0,
    "consecutive_failures": 0,
    "health": "never_executed",
    "category": "pipeline_stage",
    "last_duration_ms": 0.0,
    "total_duration_ms": 0.0
  }
}
```

### 健康标签判定逻辑

```
never_executed:  calls == 0
sleeping:        last_tick > current_tick - 50  且 calls > 0（偶发）
active:          last_tick <= current_tick - 1 且 last_tick > 0
persistent_fail: consecutive_failures >= 5
sporadic:        调用次数少但非零（由外部触发器）
```

### 装饰器接口

```python
from src.observability import observe, observe_llm

# 基本观测
@observe("my_module")
def my_function():
    pass

# 带分类
@observe("my_module", category="language")
def another():
    pass

# LLM 观测（自动处理 fallback 检测）
@observe_llm("reflection_layer")
def call_llm():
    return llm(system_prompt=..., user_prompt=...)
```

### LLM 降级检测逻辑

```
每次 create_llm_callable() 返回的 callable 被调用后检查：
  - text is None → failure
  - error contains "not set" → fallback（无 key）
  - error contains "timeout" → fallback
  - error contains "balance" / "402" → fallback（余额耗尽）
  - error contains "401" / "auth" → failure（非降级）
  - error contains "500" / "server" → failure（非降级）
  - 其他 → failure
```

### 报告格式

```
=== XIA 可观测性报告 ===
时间: 2026-06-07 12:30
总 tick: 52
总 LLM 调用: 3
LLM 成功率: 0.0% (0/3)

【活跃】- 真正在跑的
  pipeline: s01_init        calls=52  ok=52  fail=0  0ms avg
  pipeline: s06_language    calls=52  ok=52  fail=0  0ms avg
  language: quenching       calls=52  ok=52  fail=0  0ms avg

【休眠】- 长期未被调用
  language: reflection_layer  calls=0  last=never  consecutive_fail=0
  language: teacher_lexicon  calls=0  last=never
  language: state_pattern_memory  calls=0  last=never

【持续失败】- 最近多次异常
  (none in last 50 ticks)

【LLM 状态】
  reflection_layer   [FALLBACK] 3/3 calls fell back
  candidate_generator [FALLBACK] 0/0 (not called)
  mirror            [FALLBACK] 0/0 (not called)
```

## 复用策略

- **emergence.jsonl**：保持原样，继续写。观测层报告不消费它。
- **observability/events.py**：已定义，**扩展**事件类型（新增 `ModuleCallEvent`, `LLMCallEvent`）。
- **observability/event_log.py**：保持原样，继续写 JSONL。观测层用独立文件。
- **ctx._trace**：保持原样。观测层在 stage 级别记录调用，粒度更细。
