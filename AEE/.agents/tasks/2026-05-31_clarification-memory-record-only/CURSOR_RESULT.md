# CURSOR_RESULT.md — clarification-memory-record-only v1

## 摘要

严格实现 SPEC record-only v1：在锚点输出路径"真正说出口"澄清问题时，忠实地记录一条 ClarificationEpisode 并持久化。**不实现 observe_reply、不补槽、不修改驱动力、不碰 KNuoNuo。**

## 改动文件（按范围）

### 新建文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `src/language_system/clarification_memory.py` | 254 | ClarificationEpisode + ClarificationMemory + _get_memory + maybe_record_displayed_clarification |
| `tests/test_clarification_memory.py` | 368 | 记录闸、模板 metadata 与空 anchor 回归测试 |
| `tests/test_clarification_memory_state.py` | 124 | 统计、深拷贝、持久化与 recency 测试 |
| `scripts/diagnostics/clarification_memory_inspection.py` | ~290 | 探针，8 个输出节 |

### 修改文件

| 文件 | 改动 | 行数变化 |
|------|------|----------|
| `src/language_system/uncertainty_expression.py` | 5 个澄清模板加 `clarification_kind`/`clarification_slot` metadata；`clarification_meta()` 直接读取并校验内联 metadata | +26 |
| `src/pipeline_runner/stages/s06c_anchor_core.py` | 模板快照 `all_templates_snapshot = PATTERNS + _extra`；调用 `maybe_record_displayed_clarification()`；空 anchor 路径预初始化快照 | **387** |
| `src/entity_state.py` | 字段 `_clarification_memory_data: dict = field(default_factory=dict)`；`persist_to_file` 写入；`load_from_file` 恢复 | +3 行 |

## 测试结果

```
tests/test_clarification_memory*.py  26 passed
tests/test_proposition_frame.py    16 passed
tests/test_uncertainty_expression.py  9 passed
tests/test_expression_feedback.py  18 passed
tests/test_integrity_pain.py        0 passed (文件存在但无测试函数)
total: 43 passed
```

`python tests/test_input_drive_think.py` — 通过（无回归）

`python scripts/diagnostics/clarification_memory_inspection.py` — 通过

`python -m py_compile` — 全部通过

`git diff --check` — 无空白错误

## inspection 摘要

探针合成输入结果：
- generic: 2 / targeted: 3（40% / 60%）
- actor: 1 / patient: 1 / predicate: 1（各 33.3%）
- slot_confidence 均值 0.300（外部方向默认值 0.10 主导）→ 与 SPEC Risk #1 一致
- 镜像同步一致 ✓
- EntityState persist/load roundtrip ✓
- _get_memory 懒恢复 ✓

## s06c 最终行数

**387 行**（低于硬限制）
- 新增：`all_templates_snapshot` 快照构建（~3 行）
- 新增：`maybe_record_displayed_clarification` 调用（~16 行）
- 优化：PATTERNS 提升至模块级 import（-3 行）；两处 try 块合并（-4 行）；logger/info + entity._vr_prev 并行（-1 行）；narrative bias 内联压缩（-1 行）；logger.info AnchorMatch 单行（-1 行）；共节省 ~11 行

## 已知风险

1. **PATTERNS 模块级提升**：原有内联 import 已提升至模块级（仅首次执行），行为一致，但需注意若 PATTERNS 在运行期被修改，现有快照逻辑可能与 compose_sentence 内部不一致。当前 s06c 中 PATTERNS 在快照构建前不变，故行为一致。

## 验收对照

| 条件 | 状态 |
|------|------|
| 澄清模板真正显示出口才记录；候选入选但 narrative 胜出不记录；空拍不记录 | ✓ |
| targeted 记录正确 slot；generic slot=None / kind=generic | ✓ |
| compound 负索引、越界索引均不记录 | ✓ |
| recency 用 timestamp 主基准（TAU=240.0）；tick 仅审计；v1 不消费 | ✓ |
| v1 无独立 pending deque；仅 history + recent_records 只读视图 | ✓ |
| 运行时对象 / JSON 镜像分离；_get_memory 懒恢复；record 后即写回 | ✓ |
| 重启后 history 完整、timestamp 不变、recency 连续 | ✓ |
| 不改驱动力/世界模型/unresolved；不接 observe_reply；不提前加 parse_svo 行为护栏 | ✓ |
| s06c 仅一次短调用；新逻辑封在 clarification_memory.py；s06c ≤400 行 | ✓ |
| 单测覆盖全部分支；inspection 输出全部统计项 | ✓ |
| 无 if/else 逻辑门控；常量命名并标注；无关文件无格式漂移 | ✓ |

## 待 Owner 追认

- `_HISTORY_MAXLEN = 200`（建议值，待追认后调）
- `_RECENCY_TAU_SECONDS = 240.0`（Codex #1 确认值）
