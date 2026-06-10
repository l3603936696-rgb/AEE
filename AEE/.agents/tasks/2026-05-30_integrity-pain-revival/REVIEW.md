# Review: integrity-pain-revival

> 注意：本评审为**实现者自评**（Claude Code 既实现又自评，不构成独立评审）。
> 建议由 Codex 做独立评审后再合并。

## Reviewer

- Name: Claude Code（self-review，非独立）
- Date: 2026-05-30
- Diff reviewed: `self_binding.py`、`integrity_signal.py`、`s07a_state_update.py`、`s04b_emerge.py`、`tests/test_integrity_pain.py`

## Context Used

- Graph tools used: code-review-graph（定位 integrity 调用链、确认 record_access/record_perturbation 全项目无调用方）
- Files inspected: 上述 4 个源文件 + integrity_monitor.py（只读未改）+ s04a/s05 阶段顺序确认
- Tests inspected: `tests/test_integrity_pain.py`、回归套件、`tests/test_50_ticks.py`

## Findings

### High Risk

- None.

### Medium Risk

- **常量未标定**：四个新常量为偏小提议值，daemon 端到端前数值效果未验证。
  缓解：偏小起步 + 先跑再调，符合 SPEC 约定。
- **`_WITHDRAW_FLOOR=0.40` 为未经批准的新增常量**：已在 SPEC/THREADS 标记，待 Owner 追认。

### Low Risk

- **1 拍延迟**：s07a 写 bias、s04b 下一拍读。设计已知、可接受。
- **退缩仅抑制外向驱动力**：不影响内向/愈合维度，符合"短暂退缩不构成回避漏洞"目标。

## Test Coverage

- Tests run: 单元 7/7 PASS、回归 24 PASS、50 拍端到端全 PASS。
- Missing tests: 受伤退缩对 `drive_vector_final` 的端到端抑制效果尚无 daemon 级验证（属端到端范畴）。
- Manual checks: 确认 `access_count` 无衰减路径；确认 pain 只衰减不被覆写；确认无 if/else 逻辑门控。

## Merge Recommendation

**Revise before merge** —— 非阻塞性，但需：
1. Codex 做独立评审（实现者自评不充分）；
2. Owner 追认 `_WITHDRAW_FLOOR=0.40`；
3. daemon 端到端验证通过（重启 XIA，不碰糯糯）。

三项满足后可合并。代码结构与测试本身无阻塞性缺陷。

## Notes for Owner

链路已活、单元/回归/50 拍全绿。卡在两件事上：**独立评审**（建议 Codex）和 **daemon 端到端验证**
（需你批准重启 XIA）。另有一个新常量 `_WITHDRAW_FLOOR=0.40` 等你点头。代码本身没发现高风险问题。
