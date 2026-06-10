# VALIDATION.md — clarification-memory-record-only v1

## 验证命令

```bash
# 单测
python -m pytest tests/test_clarification_memory.py tests/test_clarification_memory_state.py -q
# 相关测试
python -m pytest tests/test_proposition_frame.py tests/test_uncertainty_expression.py tests/test_expression_feedback.py tests/test_integrity_pain.py -q
# 集成测试
python tests/test_input_drive_think.py
# 编译检查
python -m py_compile src/language_system/clarification_memory.py src/language_system/uncertainty_expression.py src/pipeline_runner/stages/s06c_anchor_core.py src/entity_state.py scripts/diagnostics/clarification_memory_inspection.py tests/test_clarification_memory.py tests/test_clarification_memory_state.py
# inspection 探针
python scripts/diagnostics/clarification_memory_inspection.py
# git 空白检查
git diff --check -- src/language_system/clarification_memory.py src/language_system/uncertainty_expression.py src/pipeline_runner/stages/s06c_anchor_core.py src/entity_state.py tests/test_clarification_memory.py tests/test_clarification_memory_state.py scripts/diagnostics/clarification_memory_inspection.py
```

## 测试覆盖矩阵

| 分支 | 测试函数 | 结果 |
|------|----------|------|
| targeted 说出口 actor | `test_targeted_record_actor` | ✓ |
| targeted 说出口 patient | `test_targeted_record_patient` | ✓ |
| targeted 说出口 predicate | `test_targeted_record_predicate` | ✓ |
| generic 说出口 | `test_generic_record` | ✓ |
| narrative 胜出 → 不记录 | `test_narrative_wins_not_recorded` | ✓ |
| 空 raw_input → 不记录 | `test_empty_raw_input_not_recorded` | ✓ |
| 空白 raw_input → 不记录 | `test_whitespace_only_raw_input_not_recorded` | ✓ |
| 负索引 → 不记录 | `test_negative_template_index_not_recorded` | ✓ |
| 越界索引 → 不记录 | `test_out_of_bounds_index_not_recorded` | ✓ |
| record 后镜像同步 | `test_mirror_sync_on_record` | ✓ |
| to_dict/from_dict roundtrip | `test_to_from_dict_roundtrip` | ✓ |
| from empty dict | `test_from_empty_dict` | ✓ |
| timestamp recency | `test_recency_age_clamp_on_clock_back` | ✓ |
| exp decay 精度 | `test_recency_exp_decay` | ✓ |
| _get_memory 懒恢复 | `test_get_memory_lazy_restore` | ✓ |
| _get_memory 空镜像 | `test_get_memory_empty_mirror` | ✓ |
| stats() 正确 | `test_stats_generic_targeted` | ✓ |
| history maxlen | `test_history_maxlen` | ✓ |
| ClarificationEpisode to_dict | (implicit via roundtrip) | ✓ |
| clarification_meta generic | `test_clarification_meta_generic_slots` | ✓ |
| clarification_meta targeted | `test_clarification_meta_targeted_slots` | ✓ |
| clarification_meta non-clarification | `test_clarification_meta_non_clarification` | ✓ |
| 空 anchor 完整输出路径不回归 | `test_empty_anchor_path_does_not_crash` | ✓ |
| 命题骨架录制后深拷贝隔离 | `test_recorded_proposition_frame_is_deep_snapshot` | ✓ |
| EntityState persist/load | `test_entity_state_persist_load_roundtrip` | ✓ |

## inspection 探针输出

### 常量
- `_RECENCY_TAU_SECONDS = 240.0`（来源：8 tick × 30s/tick）
- `_HISTORY_MAXLEN = 200`（建议值，待 Owner 追认）

### 合成输入结果（5 条记录，3 条 guard 阻断）

| kind | slot | question |
|------|------|----------|
| generic | None | 这句……我没太懂 |
| generic | None | 是说什么呢…… |
| targeted | actor | 是谁在这样呢…… |
| targeted | patient | 你说的是谁，或者什么呢…… |
| targeted | predicate | 你说的这是怎么回事呢…… |

- narrative 胜出（空 raw_input、compound 负索引、越界索引）→ 阻断 ✓

### generic / targeted 比例
- generic: 2（40.0%）
- targeted: 3（60.0%）

### actor / patient / predicate 分布（targeted 内）
- actor: 1（33.3%）
- patient: 1（33.3%）
- predicate: 1（33.3%）

### slot_confidence / slot_relevance 分布
- slot_confidence: count=3, mean=0.300, min=0.100, max=0.700
- slot_relevance: count=3, mean=0.500, min=0.500, max=0.500

**NOTE**: slot_confidence ≈ 0.10 for 'external' slots indicates parse_svo is defaulting to guess direction — see SPEC Risk #1.

### 镜像同步验证
- entity._clarification_memory_data history 长度: 5
- memory.to_dict() history 长度: 5
- 同步一致: True ✓

### EntityState persist/load roundtrip
- persist_to_file: OK
- load_from_file: OK
- tick after load: 888（expected 888）✓
- history length: 2（expected 2）✓
- restart timestamp preserved → recency continuous across restarts [OK]

## 在线验收（Codex 待做）

Codex 应在线验收以下行为：
1. daemon 运行 tick → 观察 entity_core.json 中 `_clarification_memory_data` 是否增长
2. 注入高理解难度输入 → 观察 targeted 澄清记录是否产生
3. 注入 narrative 文本 → 观察无新增记录
4. daemon 重启 → 观察 history 完整恢复、timestamp 不变
