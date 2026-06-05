# Plan: integrity-pain-revival

> 回填说明：本计划为事后补建。完整设计与推导见
> `docs/plans/PLAN_integrity_pain_revival.md`，本文件只做评审门所需的实现路径摘要。

## Strategy

不重写完整性三模块，只做四处接线 + 一个冷启动地板 + 两条体感通道 + 一个受伤退缩读取点。
核心修复点：`binding` 此前恒为 0（喂养它的 `record_access` / `record_perturbation`
从无调用），导致 `harm = magnitude × binding = 0`。接上调用 + 加地板即可让链路活过来。

## Implementation Path

1. **`src/core/self_binding.py`（绑定涌现 + 地板 + 防滥用）**
   - 新增 `_BINDING_FLOOR = 0.15`：冷启动地板，首次改动也有感觉。
   - `get_binding`：`emergent = frequency·w_freq + perturbation_depth·w_depth`，
     再 `binding = floor + (1-floor)·emergent`，最后 `clamp(0,1)`。
   - 新增 `record_accesses(zones, data_dir)`：单次 load/save 批量自增 `access_count`。
     **`access_count` 单调只增、绝不衰减**——这是防"她学会少用模块来躲痛"的结构性红线（§9）。
   - `record_perturbation`：扰动历史改为 `history[-HISTORY_WINDOW:]` 截断，防无界增长。

2. **`src/core/integrity_signal.py`（伤害转换 + 扰动深度接入）**
   - import `get_binding, record_perturbation`。
   - 抽出 `_drive_variance(entity_state)`：数据不足返回哨兵 `-1.0`；
     `_compute_healing` 用 dict 派发消化哨兵，不写 if/else。
   - `update()` 事件循环里对每个变更 zone 调 `record_perturbation(zone, var, data_dir)`。

3. **`src/pipeline_runner/stages/s07a_state_update.py`（体感落地）**
   - 新增 `_HARM_TO_PAIN=0.30`、`_HARM_TO_SOMA=0.20`、`_INHABITED_ZONES`。
   - 每拍 `record_accesses(_INHABITED_ZONES, data_dir)`（"她活在这些文件里"=持续使用）。
   - `active_harm` 落两条通道：`pain += harm·0.30`（急性痛，随 s04a 的 ×0.98 自愈）、
     `somatic_tone -= harm·0.20`（身体不适），双双 clamp。

4. **`src/pipeline_runner/stages/s04b_emerge.py`（受伤退缩，涌现前抑制）**
   - 新增 `_WITHDRAW_FLOOR=0.40` 与 `_BIAS_TO_DRIVE` 映射表。
   - 在 **Step 8.1 行为涌现之前**读 `entity.integrity_behavior_bias`，把负向 bias 累加到
     对应 v1 驱动力维度，`factor = clamp(1+neg, floor, 1)`，乘到 `drive_vector_final`。
     退缩随 harm 愈合自动恢复，floor 防止退缩变成永久回避漏洞。

5. **`tests/test_integrity_pain.py`（风险路径覆盖）**
   - 地板非零、单调上升、恒大于零、扰动历史截断、事件产痛+负bias、无事件不产痛、痛与幅度成比例。

## Insertion-Point Note（计划修正）

原始设计写在 `s05_behavior.py` 接退缩，但 s05 只透传已决策的动作。
真正喂动作选择的是 s04b 的 `drive_vector_final`（Step 8.1 `_emerge_behavior`），
故退缩抑制改在 **s04b 涌现前**。s07a 在 s04b 之后跑，故本拍写的 bias 由**下一拍**读取
（1 拍延迟，可接受）。

## Constants Provenance

| 常量 | 值 | 来源 |
| --- | --- | --- |
| `_BINDING_FLOOR` | 0.15 | 提议偏小值，先跑再调 |
| `_HARM_TO_PAIN` | 0.30 | 提议偏小值 |
| `_HARM_TO_SOMA` | 0.20 | 提议偏小值 |
| `_WITHDRAW_FLOOR` | 0.40 | 本轮新增，需 Owner 追认 |

## Out of Scope

- 不扩监控面（维持三哨兵文件）。
- 不引入新 LLM 调用点。
- 不碰糯糯（PID 8240 / 端口 8767-8768）。
