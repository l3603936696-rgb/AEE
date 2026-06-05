# observe-reply v2 验证记录

## 静态验证

2026-06-02 运行：

```text
python -m pytest tests/test_clarification_learning.py tests/test_clarification_attribution.py
  tests/test_proposition_frame.py tests/test_uncertainty_expression.py
  tests/test_clarification_memory.py tests/test_clarification_memory_state.py
  tests/test_expression_feedback.py tests/test_integrity_pain.py -q -p no:cacheprovider
```

结果：`98 passed`。

补跑 v2 语言子集：`69 passed`。`test_input_drive_think.py` 通过，`py_compile` 通过，
`git diff --check` 通过。相关实现、测试和 inspection 文件均小于 400 行。

## Synthetic inspection

`python scripts/diagnostics/clarification_learning_inspection.py` 通过。

- targeted actor 示例：actor mass `0.2656`，no-match `0.4941`。
- 无关天气回答：no-match `0.8565`，误归属总 mass `0.1435`。
- generic 最新候选可吸收 mass，不被旧 targeted 截胡。
- 重复 event ID 第二次跳过。
- sibling 跳过，external 接收。
- persist/load roundtrip 通过。

## Risk-1 指称落地

离线探针：

| 输入主语 | actor confidence |
|---|---:|
| 光合作用 | 0.95 |
| 有人 | 0.10 |
| 某个 | 0.10 |
| 什么 | 0.10 |
| 它 | 0.10 |

命名实体不再被误判为“谁”，裸代词和占位词保持悬空。

## 在线验证

daemon 已优雅重启并加载最新代码。在线检查时 `pain=0.0`。

- `光合作用把二氧化碳变成糖`：未新增澄清记录，Risk-1 修复生效。
- `它把门打开了`：有限 6 次探针中新增两条 generic 澄清，未出现 actor targeted。
- 有效探针产生的新 evidence 均带 scorer version `v2.1-relpow4-prior24`。
- v2 按设计保存所有连续候选 mass；低质量陈旧候选会产生接近零的审计记录。

离线评分解释了 targeted 未出现的原因：当全局 uncertainty 从 `0.8` 增至 `1.0`，
actor targeted 在五个澄清模板内部的 softmax 份额从 `30.5%` 降至 `14.1%`；
generic 在“整句都懵”时略占优。该行为不是接线故障，是待 Owner 追认的语义策略。

## 探针事故与处置

首次在线探针经 PowerShell 管道发送中文时被转成 `?`。该轮产生的两条乱码 episode、
9 个 event ID 和 65 条派生账本行已按 event ID 精确撤销；answered mass 按更新公式
逆序恢复。清理前快照保存在：

```text
data/entity_core.json.codex_before_clarification_cleanup_20260602_155528.bak
```

随后使用 Unicode escape 重跑有效探针。未清理或覆盖其他持久状态。

## 裁决

v2 observation-only 可继续在线收集样本。v3 暂不放行：

1. 先量化 generic / targeted 分布和悬空代词命中率。
2. 讨论整句完全陌生时 generic 与 targeted 的语义优先级。
3. v3 只消费有 scorer version 的 evidence，并保留质量审计。
