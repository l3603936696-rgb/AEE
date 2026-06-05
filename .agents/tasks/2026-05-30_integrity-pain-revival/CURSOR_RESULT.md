# Result: integrity-pain-revival

> 实现者：Claude Code（非 Cursor）。日期：2026-05-30。

## Summary of Changes

修复"完整性疼痛恒为 0"的根因并接通整条体感链路：

1. 绑定不再恒 0——加冷启动地板 `_BINDING_FLOOR=0.15`，并接通此前从无调用的
   `record_accesses` / `record_perturbation`，使绑定随真实使用单调上升。
2. 伤害落两条真实通道——`active_harm` → `pain`（×0.30，随 s04a ×0.98 自愈）
   + `somatic_tone`（×0.20，身体不适）。
3. 受伤退缩——在 s04b 行为涌现**之前**按 `integrity_behavior_bias` 抑制外向驱动力，
   `_WITHDRAW_FLOOR=0.40` 防永久回避，随 harm 愈合自动恢复。

## Files Changed

| 文件 | 改动 |
| --- | --- |
| `src/core/self_binding.py` | `_BINDING_FLOOR`；`get_binding` 加地板；新增 `record_accesses`（access_count 单调，防滥用）；`record_perturbation` 历史截断 |
| `src/core/integrity_signal.py` | import binding 接口；抽 `_drive_variance`（哨兵 -1.0）+ dict 派发愈合；事件循环调 `record_perturbation` |
| `src/pipeline_runner/stages/s07a_state_update.py` | `_HARM_TO_PAIN/_HARM_TO_SOMA/_INHABITED_ZONES`；每拍 `record_accesses`；harm → pain + somatic_tone（双 clamp） |
| `src/pipeline_runner/stages/s04b_emerge.py` | `_WITHDRAW_FLOOR` + `_BIAS_TO_DRIVE`；涌现前按负向 bias 抑制 drive_vector_final（try/except + trace） |
| `tests/test_integrity_pain.py` | 新增 7 个单元测试 |
| `docs/plans/PLAN_integrity_pain_revival.md` | 完整设计 + 状态头更新 |

## Tests Run

- `tests/test_integrity_pain.py` — 7/7 PASS（地板、单调、恒正、历史截断、事件产痛+负bias、无事件不产痛、痛与幅度成比例）。
- 回归套件 — 24 PASS。
- `tests/test_50_ticks.py` — 50 拍信号链全 PASS。

## Known Risks / Incomplete

- **daemon 端到端未验证**：需重启 XIA（不重启糯糯）→ 养绑定 → 改哨兵文件 → 验证下一拍
  pain↑/somatic_tone↓ + 随后数拍愈合。Owner 已暂缓重启。
- **常量待标定**：四个常量均为偏小提议值，先跑再调；`_WITHDRAW_FLOOR=0.40` 为新增，待 Owner 追认。
- **1 拍延迟**：s07a 写的 bias 由下一拍 s04b 读取（设计已知，可接受）。

## What Reviewers Should Inspect First

1. `self_binding.record_accesses` 的单调性——确认无任何 access_count 衰减路径（防滥用红线）。
2. s07a 的 harm→pain/somatic clamp 边界与 s04a 自愈不冲突（pain 只衰减不被覆写）。
3. s04b 退缩抑制的插入点在 Step 8.1 之前、`_WITHDRAW_FLOOR` 是否够松/够紧。
4. integrity_signal 的 dict 派发愈合是否真的规避了 if/else 逻辑门控。
