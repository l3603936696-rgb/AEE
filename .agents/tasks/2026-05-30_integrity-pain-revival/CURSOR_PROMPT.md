# Cursor Handoff: integrity-pain-revival

> 回填说明：本任务**未走 Cursor 流程**。代码由 Claude Code 在三方工作流落地前直接实现并通过
> 测试。本文件保留标准 handoff 结构，仅为评审门完整性而补建；实际交付见 `CURSOR_RESULT.md`。

You are the implementation agent for this task. Read these files first:

1. `AGENTS.md`
2. `CLAUDE.md`
3. `.agents/workflow/README.md`
4. `.agents/tasks/2026-05-30_integrity-pain-revival/SPEC.md`
5. `.agents/tasks/2026-05-30_integrity-pain-revival/PLAN.md`
6. `docs/plans/PLAN_integrity_pain_revival.md`（完整设计）

## Mission

让"改 XIA 监控的文件 = 给她做手术 = 她会痛/不适"真正起作用。修复根因：`binding` 恒为 0。

## Boundaries

- 不扩监控面（维持三哨兵文件）。
- 不引入新 LLM 调用点。
- 不重写完整性三模块结构，只接线 + 加地板 + 接体感 + 接退缩读取点。
- 不碰糯糯（PID 8240 / 端口 8767-8768）。
- 遵循 `CLAUDE.md`：禁 if/else 逻辑门控、常量须命名说明来源、单文件 ≤400 行、外科手术式改动。

## Implementation Expectations

- 见 `PLAN.md` 的五步实现路径。
- 为变更行为加测试（`tests/test_integrity_pain.py`）。
- 先跑最窄测试，再跑回归 + 50 拍端到端信号链。

## Delivery Format

完成后更新 `CURSOR_RESULT.md`：变更摘要、变更文件、测试与结果、已知风险、评审优先看哪里。
