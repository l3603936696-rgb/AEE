# Cursor 指令：风化系统剩余任务

共 3 个任务。每个任务独立，可按顺序做。
**规则：每个文件不超过 400 行。所有新代码匹配现有风格。**

---

## 任务 1：TensionSnapshot 周期性发射

**目的**：每 600 tick（10分钟）从 `suppressed_tension.json` 读取压抑张力，emit 一条 TensionSnapshot 事件到 `logs/tension_snapshots.jsonl`，供前端和事后分析使用。

### 1A. 修改 `E:\XIA\src\daemon\tick_engine.py`

在 **line 361 之后**（风化常规漂移代码块结束后），插入：

```python
# ---- 风化系统：张力快照（每 600 tick）----
if self._tick_count % 600 == 0:
    try:
        from ..observability import TensionSnapshot, emit_event
        from ..weathering.shattering import _load_suppressed_tension

        tension_data = _load_suppressed_tension()
        total_tension = sum(tension_data.values())

        emit_event(TensionSnapshot(
            tick=self._tick_count,
            total_tension=round(total_tension, 4),
            suppressed_tension=round(total_tension, 4),
            active_contradictions=0,  # 未来扩展：计算活跃矛盾对数
            contradiction_pairs=[],
            parameter_drift_summary={},
        ))
    except Exception as _ts_err:
        logger.debug(f"[weathering] TensionSnapshot emit skipped: {_ts_err}")
```

### 1B. 导出 `_load_suppressed_tension`

目前 `_load_suppressed_tension` 是 `shattering.py` 的私有函数（下划线前缀）。需要改为公开：

**文件**: `E:\XIA\src\weathering\shattering.py`
- 把 `_load_suppressed_tension` 重命名为 `load_suppressed_tension`（去掉下划线）
- 同时更新文件内所有调用点（line 159 和 函数定义 line 18）
- `_save_suppressed_tension` 保持私有不变

**文件**: `E:\XIA\src\weathering\__init__.py`
- 在 imports 中加入 `load_suppressed_tension`
- 在 `__all__` 中加入 `"load_suppressed_tension"`

### 1C. 扩展 `get_status()` 返回张力

**文件**: `E:\XIA\src\daemon\tick_engine.py`，`get_status()` 方法（从 line 514 开始的 return dict）

在 return dict 末尾追加：

```python
# 风化张力
"suppressed_tension": self._last_tension_total,
```

并在 `__init__` 方法中加初始值：
```python
self._last_tension_total = 0.0
```

在任务 1A 的代码块中，emit 之前加一行缓存：
```python
self._last_tension_total = round(total_tension, 4)
```

**验证**：重启 daemon，等 600 tick 后查看 `logs/tension_snapshots.jsonl` 有新行。`curl http://127.0.0.1:8765/status` 返回 `suppressed_tension` 字段。

---

## 任务 2：前端风化可视化

**目的**：让风化系统的日志文件在 Logs 页可查看，在 Status 页显示张力指标。

### 2A. Logs 页添加风化日志文件

**文件**: `E:\XIA\frontend\src\components\Logs\Logs.jsx`

找到 `LOG_FILES` 数组（硬编码的文件名列表），添加 4 个风化日志文件：

```js
'drift_trace.jsonl',
'shattering_events.jsonl',
'tension_snapshots.jsonl',
'rule_lifecycle.jsonl',
```

放在现有列表后面即可。这些都是 `.jsonl` 格式，已有的 JSONL 渲染逻辑会自动生效。

**顺便修 bug**：`selectedFile` 默认值是 `'daemon_live.log'`，但这个文件不在 `LOG_FILES` 列表中。改为 `'daemon.log'`（列表中的第一个文件）。

### 2B. Status 页添加张力指标

**文件**: `E:\XIA\frontend\src\components\Status\Status.jsx`

在 "Drives" 区块之后、"Current Behavior" 区块之前，新增一个区块：

```jsx
{/* 风化张力 */}
<div className="status-section">
  <h3>{t ? t('status_tension') : '风化张力'}</h3>
  <div className="status-bar-item">
    <span className="status-label">
      {t ? t('status_suppressed_tension') : '压抑张力'}
    </span>
    <div className="status-bar">
      <div
        className="status-bar-fill"
        style={{
          width: `${Math.min(100, (xiaState?.suppressed_tension || 0) / 1.5 * 100)}%`,
          backgroundColor: (xiaState?.suppressed_tension || 0) > 1.0 ? '#e74c3c' : '#f39c12'
        }}
      />
    </div>
    <span className="status-value">
      {(xiaState?.suppressed_tension || 0).toFixed(3)}
    </span>
  </div>
</div>
```

说明：
- 进度条满值对应 1.5（即 `FORCED_COLLAPSE_TENSION` 阈值）
- 超过 1.0 变红色（接近崩塌）
- 低于 1.0 为橙色

### 2C. i18n 字符串

**文件**: `E:\XIA\frontend\src\i18n\strings.js`

在 `zh` 和 `en` 对象中各加：

```js
// zh
status_tension: "风化张力",
status_suppressed_tension: "压抑张力",

// en
status_tension: "Weathering Tension",
status_suppressed_tension: "Suppressed Tension",
```

**验证**：
- 打开 Logs 页 → dropdown 里能看到 `drift_trace.jsonl` 等 4 个文件 → 选中后显示内容
- Status 页 → 看到"风化张力"区块，数值显示正确
- 切换英文 → 标签变为 "Weathering Tension"

---

## 任务 3：域隔离（Domain Isolation）

**目的**：常规漂移和崩塌后的急剧漂移应按 domain 过滤，避免"社交域"的规律崩塌影响"信息搜索域"的参数。

### 背景

- 每条 Rule 有 `domain: str`，默认 `"general"`
- `DIMENSION_DRIFT_MAP` 中的维度天然属于某些 domain（如 loneliness → 社交，info_gap → 信息）
- `shattering.py` 已经按 domain 跟踪 suppressed_tension，但 **不过滤** 哪些规则参与评估
- `tick_engine.py` 的常规漂移不区分 domain
- `async_pipeline.py` 的急剧漂移不区分 domain

### 3A. 新建 `E:\XIA\src\weathering\domain_map.py`（~40行）

```python
"""Domain → 参数路径映射。确定每个 domain 可以影响哪些参数。"""

from __future__ import annotations
from typing import Dict, FrozenSet

# domain → 允许漂移的参数路径集合
# "general" 可以影响所有参数
DOMAIN_PARAM_SCOPE: Dict[str, FrozenSet[str]] = {
    "social": frozenset({
        "personality.trust_threshold",
        "personality.rejection_sensitivity",
        "personality.introverted_bias",
        "personality.social_risk_weight",
        "personality.extroverted_bias",
    }),
    "information": frozenset({
        "web_search.info_hunger_threshold",
        "personality.novelty_reward",
    }),
    "survival": frozenset({
        "decision.survival_override_threshold",
        "personality.recovery_rate",
    }),
    "expression": frozenset({
        "llm.temperature",
    }),
}


def get_allowed_params(domain: str) -> FrozenSet[str] | None:
    """
    返回该 domain 允许影响的参数路径集合。
    "general" 返回 None（表示不限制）。
    未知 domain 也返回 None。
    """
    if domain == "general":
        return None
    return DOMAIN_PARAM_SCOPE.get(domain)
```

### 3B. 在 `async_pipeline.py` 的急剧漂移中加域过滤

**文件**: `E:\XIA\src\pipeline_runner\async_pipeline.py`，约 line 216-258（崩塌检测后的急剧漂移代码）

在 `if shattering_events:` 块内，收集 `_all_affected` 参数路径后、执行漂移前，加过滤：

找到这段代码（约 line 232-233）：
```python
# 执行急剧漂移 + 写入参数
if _all_affected and _max_force > 0:
```

在这两行之前插入：
```python
# 域隔离：只保留该域允许影响的参数
try:
    from ..weathering.domain_map import get_allowed_params
    # 收集所有崩塌事件的域（取最强力事件的域）
    _collapse_domain = "general"
    for evt in shattering_events:
        if evt.outcome == "collapsed" and evt.shattering_force == _max_force:
            _collapse_domain = evt.domain
            break
    _allowed = get_allowed_params(_collapse_domain)
    if _allowed is not None:
        _all_affected = _all_affected & set(_allowed)
except Exception:
    pass  # 过滤失败时放行
```

### 3C. 在 `tick_engine.py` 的常规漂移中加域过滤

这个比较复杂——常规漂移来自 CovarianceTracker 的全局相关性，不是基于单条规则的 domain。暂不加域过滤（CovarianceTracker 的相关性是全局统计，按域拆分需要 per-domain tracker，工程量大且当前只有少量规则）。

**所以任务 3C 不做。** 只做急剧漂移的域过滤（3B）就够了。

### 3D. 更新 `__init__.py` 导出

**文件**: `E:\XIA\src\weathering\__init__.py`

添加：
```python
from .domain_map import get_allowed_params, DOMAIN_PARAM_SCOPE
```

`__all__` 中加：
```python
"get_allowed_params", "DOMAIN_PARAM_SCOPE",
```

**验证**：
- 单元测试：构造一个 domain="social" 的规则崩塌，确认只漂移了 `personality.*` 参数，没漂移 `web_search.*`
- 构造一个 domain="general" 的规则崩塌，确认所有相关参数都漂移了

---

## 不做的事

- **Rule ecology（规则合并 + 矛盾压力）**：需要先设计，不适合机械实现。会单独出设计文档。
- **CovarianceTracker 的 per-domain 拆分**：当前规则数量太少，全局统计足够。
- **TensionSnapshot 的 `active_contradictions` 和 `contradiction_pairs` 填充**：需要额外的矛盾追踪基础设施，属于 Rule ecology 范畴。目前留空 `(0, [])` 即可。

---

## 文件变更清单

| 操作 | 文件 | 行数估计 |
|------|------|---------|
| 修改 | `src/daemon/tick_engine.py` — TensionSnapshot emit + get_status 字段 | +20行 |
| 修改 | `src/weathering/shattering.py` — 重命名 `_load_suppressed_tension` → `load_suppressed_tension` | ~3行改 |
| 修改 | `src/weathering/__init__.py` — 加导出 | +3行 |
| 新建 | `src/weathering/domain_map.py` — 域→参数映射 | ~40行 |
| 修改 | `src/pipeline_runner/async_pipeline.py` — 急剧漂移域过滤 | +12行 |
| 修改 | `frontend/src/components/Logs/Logs.jsx` — 加4个日志文件 + 修默认值 | +5行 |
| 修改 | `frontend/src/components/Status/Status.jsx` — 张力区块 | +20行 |
| 修改 | `frontend/src/i18n/strings.js` — 2个新 key | +4行 |
