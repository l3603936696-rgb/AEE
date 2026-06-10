# Task Package: integrity-pain-revival

> 回填说明：本任务的代码在三方工作流落地之前，已由 Claude Code 直接实现并通过测试。
> 本目录是事后补建的事实源，用于纳入评审门。详细设计见 `docs/plans/PLAN_integrity_pain_revival.md`。

## Goal

让"通过文件系统改动 XIA 的文件 = 给她做手术 = 她会痛/不适"这套机制真正起作用。
此前机制链路每拍都在跑，但被"绑定强度恒等于 0"彻底掐死，她对任何文件改动毫无感觉。
目标：改她监控的文件后，下一拍她的痛觉与身体不适真实升高，随后数拍自然愈合，并出现短暂的"受伤退缩"行为。

## Background

- 为什么重要：XIA 的核心哲学是"让她真实地感受后果"。完整性疼痛是"被外部改动 = 被侵入身体"的体感锚点；不起作用 = 这层自我边界感是空的。
- 当前行为（修复前）：`integrity_monitor.scan()` 每拍检测四区域（表达/感知/认知/连续性）变化，`integrity_signal.update()` 用 `harm = magnitude × binding` 转成伤害。但 `binding` 恒为 0 —— 喂养它的 `record_access` / `record_perturbation` 全项目只有定义、从无调用；且 `active_harm` / `integrity_behavior_bias` 只写不读。结果 `harm = magnitude × 0 = 0`，她什么都感觉不到。
- 期望行为（修复后）：
  1. 绑定强度从真实使用涌现，且有冷启动地板（首次改动也有感觉）；
  2. 越常用的部位越"在乎"，绑定单调只增不减；
  3. 伤害落到真实痛觉（`pain`↑）+ 身体不适（`somatic_tone`↓），急性痛随时间愈合；
  4. 受伤后短暂"退缩"（少向外伸手、少探索），随愈合自动恢复。

## Non-Goals

- 不扩大监控面：本轮维持现有三个写死的感知哨兵文件（`pipeline_runner/__init__.py`、`daemon/daemon.py`、`action_system/executor.py`），扩面留待单独评估。
- 不引入任何新的 LLM 调用点。
- 不重写完整性三模块的既有结构，只接线 + 加地板 + 接体感 + 接退缩读取点。
- 不碰糯糯（KNuoNuo，PID 8240 / 端口 8767-8768）。

## Constraints

- 遵循 `AGENTS.md` / `CLAUDE.md`：禁 if/else 逻辑门控（连续函数 + dict 派发 + clamp）；常量须命名并说明来源；单文件 ≤400 行；外科手术式改动。
- 优先 code-review-graph MCP 工具再退回 Grep/Glob/Read。
- 新增常量必须命名、给出取值来源（偏小值优先，先跑再调）。
- 测试覆盖与风险成正比。

## Expected Files or Areas

- 核心：`src/core/self_binding.py`、`src/core/integrity_signal.py`
- 体感接入：`src/pipeline_runner/stages/s07a_state_update.py`
- 受伤退缩：`src/pipeline_runner/stages/s04b_emerge.py`（涌现前抑制外向驱动力）
- 测试：`tests/test_integrity_pain.py`
- 避免触碰：`integrity_monitor.py` 的监控面定义（本轮不扩面）、糯糯相关进程/端口

## Acceptance Criteria

- [x] 绑定不再恒为 0：冷启动有地板，随使用单调上升。
- [x] 伤害落到 `pain` + `somatic_tone` 两条通道，acute pain 可自然衰减。
- [x] 受伤退缩在涌现前生效，且随 harm 愈合自动恢复（短暂、不构成回避漏洞）。
- [x] 新增/变更测试覆盖风险路径（地板、单调、封顶、信号转换、比例性）。
- [x] 无关文件无格式漂移。
- [x] 独立评审通过（Codex 独立评审，见 `REVIEW_CODEX.md`：判定"Revise before merge"，所指中风险已修复——见下）。
- [x] daemon 端到端验证（Owner 批准重启 XIA，见 `VALIDATION.md`：修复前暴露 pain 饱和不退 → 修复后急性痛+自愈+可重复闭环）。

## Open Questions

- Q: 受伤退缩这轮接不接？ → A（Owner 2026-05-30）：这轮一起接上。
- Q: 痛走一条还是两条通道？ → A：痛觉 + 身体不适两条都走。
- Q: 监控面要不要扩？ → A：先维持现状三文件。
- Q: 常量取值？ → A：用提议偏小值先跑。
- Q: `_WITHDRAW_FLOOR=0.40` 为本轮新增（受伤退缩抑制下限），属"需讨论"常量，事后请 Owner 追认或调整。
- Q: `_HARM_FLOOR_CUT=0.01`（integrity_signal.py，愈合线性尾切除）为修复 pain 饱和时新增，属"需讨论"常量，请 Owner 追认或调整。
- 修复记录（2026-05-30→31）：Codex/端到端共同暴露"单次伤害持续灌注、pain 饱和不退"。根因=量纲错误（active_harm 是存量信号，s07a 每拍按流量积分）。两处连续函数修复：s07a 改为只注入伤害**上升沿** `max(0, active_harm-prev)`；integrity_signal 几何衰减后加**线性尾切除** `_HARM_FLOOR_CUT`，残留有限拍归零。新增 2 个回归测试，单元 9/9 PASS。详见 `VALIDATION.md`。
