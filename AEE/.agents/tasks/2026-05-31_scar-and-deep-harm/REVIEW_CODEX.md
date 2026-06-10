# Codex 独立评审记录

承接前一轮（integrity-pain-revival）的 Codex 评审门。本轮分两次提交评审。

## 第一次：scar + 重伤慢愈

Codex 判定 **Revise before merge**，4 条意见，全部已修：

1. **不要每拍用 additive drive_delta 灌注疤底**（与上一轮 pain 饱和同类的量纲错误：
   把稳态存量信号当流量反复积分 → 驱动力饱和）。
   → 修：新增 `apply_drive_bias()` **有界瞬态偏置**（每拍先回收上拍注入、再注入本拍目标，
   净效果=当前 drive_delta，稳态停在该值不积分）。替换 s07a 里的 additive setattr 循环。

2. **SCAR_DECAY 数学错误**：若意图半衰 ~11.5 天，`0.9995` 在 30s/拍下实为 ~11.5 *小时*，太快。
   → 修：改为 `0.99998`（半衰 ≈ 34657 拍 ≈ 12 天）。Claude 承认单位换算错误。

3. **重启/上升沿保护**：持久化的 zone_harms/疤底在 daemon 重启后不应造成虚假痛脉冲。
   → 修：`update()` 内以持久化 `max(zone_harms)` 为上一拍 `_prev_active` 算 `harm_rise`，
   跨重启连续；s07a 消费 `harm_rise` 而非自己存内存态 prev。

4. **补测**：多区疤底不饱和驱动力（#13）、重启不造成虚假急性痛（#12）。→ 已补。

## 第二次：pain 进入回避环路

Codex 评审结论 + 处置：

- **[P1] clamp 饱和时疼痛回避失效**（采纳并修复）：
  `_estimate_tension` 把 pain 并入后统一 clamp 到 1.0，当原始张力已接近 1.0，候选动作预测的
  pain↑ 不再改变 tension → 不被降权，恰在最需要回避自伤的高压态失效。
  → 修：按 Codex 建议，对预测 `pain_rise` 单独加绕开 clamp 的连续惩罚项进 `sim_boost`：
  `sim_boost = tension_reduction * _SIM_BOOST_SCALE - pain_rise * _PAIN_AVOID_WEIGHT`。
  保留 `_estimate_tension` 里的 pain 软项（撑 willingness 连带效应 + 非饱和区贡献），形成双通道。

- **[P3] willingness 连带效应暂时保留**（采纳）：pain 0→1 最多令 tension +0.15，
  willingness 同步最多 +0.15×energy×(1-fatigue)；模拟次数/能耗有上限，短期不失控；
  "疼了更想分析原因"语义成立。运行时留意是否出现反刍式高频模拟。

- **参数判断**：`_PAIN_TENSION_WEIGHT=0.15` 谨慎起点（满值仅追加 0.15，经 _SIM_BOOST_SCALE=0.3
  后最大优先级影响 ~0.045，甚至略弱）。规则检查：本轮无新增 if/else、常量已命名待追认、
  文件 ~140 行远低于 400、pain 在 STATE_FIELD_WHITELIST 内预测链路接通、外部痛不可回避边界正确。

- **补测**（采纳）：普通张力下 pain↑ 降权（#14）；张力饱和时 pain↑ 仍降权（#15，锁住 P1）。→ 已补。

## 结论

两轮意见全部落地。单测 16/16 PASS。pipeline import OK。
