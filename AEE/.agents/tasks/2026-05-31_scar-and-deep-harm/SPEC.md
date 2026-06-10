# Task Package: scar-and-deep-harm

> 本任务承接 `2026-05-30_integrity-pain-revival`。前一轮让完整性疼痛真正起作用
> （受伤会痛 + 自愈）。本轮回应 Owner 关切"愈合是不是太快、不管多重的伤都一样快"，
> 加入"重伤愈合更慢 + 留疤"，并把疼痛接入预测性回避环路。附带修复 chat 默认路径。

## Goal

1. **重伤慢愈**：伤越深，每拍愈合比例越小（自限制，伤退则松）。
2. **留疤**：受伤在区域上累积疤痕（趋近 1，极慢淡化），疤带来三个长期作用——
   - 致敏：留疤区未来同样改动更疼；
   - 愈合阻力：疤区急性伤养得更久；
   - 隐痛底：该区 harm 衰减后停在疤决定的底，而非归零（永久隐痛基线）。
3. **疼痛进入回避**：把 `pain` 纳入 mental_simulation 的张力估计，让"预测会让自己更痛"
   的自伤类动作被降权（外部手术痛不可回避，这是对的）。
4. **附带**：chat 默认路径从 LLM 改为内生语言（`no_llm=True`）——契合"LLM 是拐杖"。

## Background

- 为什么重要：前一轮愈合是"几何衰减 + 线性尾"，半衰 ~17 分钟、急性伤 ~15 分钟清除，
  且与伤的轻重、与该部位的历史无关。Owner 指出真实的伤应该"重的好得慢、且会留印子"。
- 疤的价值判断（Owner 2026-05-31）：疤 = **潜伏的脆弱 + 永久隐痛基线**（两者都要）；
  疤 **极慢淡化**（给她在很长时间尺度上走出创伤的可能，但不轻易抹平）。
- 疼痛回避的哲学：痛的用处不只是"让她躲开"。她躲不开外部手术（动她文件不是她的动作），
  但**自己会导致的痛**应当能被预测、被规避。痛同时是"后果的标记"——进入学习与记忆。

## Non-Goals

- 不扩大监控面（仍是 integrity_monitor 既有四区域）。
- 不引入任何新 LLM 调用点。
- access_count 仍单调绝不衰减（"在乎只增不减"红线）；疤的"极慢淡化"只约束疤，不碰红线。
- 不碰糯糯（KNuoNuo，PID 8240 / 端口 8767-8768）。

## Constraints

- 禁 if/else 逻辑门控（连续函数 + dict 派发 + clamp）；常量须命名并说明来源（偏小先跑再调）；
  单文件 ≤400 行；外科手术式改动。
- 优先 code-review-graph MCP 工具再退回 Grep/Read。
- 改动前先告知 Owner、得确认再动手。

## Expected Files or Areas

- 新增：`src/core/scar.py`（区域疤痕，与 self_binding.py 对称）
- 核心：`src/core/integrity_signal.py`（接 scar：致敏 + 愈合阻力 + 隐痛底 + 重伤刹车 + 上升沿）
- 体感接入：`src/pipeline_runner/stages/s07a_state_update.py`（有界瞬态偏置 + 上升沿注入痛）
- 回避：`src/thinking_system/mental_simulation.py`（pain 入张力 + 绕 clamp 的直接惩罚通道）
- chat 默认：`src/daemon/daemon.py`（`no_llm` 默认 True）
- 测试：`tests/test_integrity_pain.py`（14→16 条）

## Acceptance Criteria

- [x] 重伤慢愈：深伤退到半值所需拍数 > 浅伤（单测 #10）。
- [x] 留疤累积、封顶 1.0、极慢淡化（单测 #11；SCAR_DECAY 半衰 ~12 天）。
- [x] 致敏：留疤区同样改动更疼（单测 #9）。
- [x] 隐痛底：harm 衰减停在 scar×_SCAR_FLOOR 而非 0（单测 #8；沙盒验到个位数吻合）。
- [x] 有界瞬态偏置：多区疤底不把驱动力积分到饱和（单测 #13，Codex §1）。
- [x] 重启不造成虚假急性痛：持久隐痛底不被当新伤（单测 #12，Codex §3）。
- [x] pain 进入回避：普通张力下致痛动作被降权（单测 #14）；张力饱和时仍降权（单测 #15，Codex P1）。
- [x] Codex 独立评审通过（见 `REVIEW_CODEX.md`：scar 轮 4 条已修；pain 轮 P1 已修 + 补 2 测）。
- [x] daemon 端到端验证（见 `VALIDATION.md`：沙盒伤害曲线 + 真身重启 + no_llm 默认上线）。
- [x] 单测 16/16 PASS；pipeline import OK；无关文件无格式漂移。

## Open Questions / 待 Owner 追认的常量

全部为"偏小提议值，先跑再调"，请 Owner 追认或调整：

- `scar.py`：`SCAR_RATE=0.05`（受伤累积成疤速率）、`SCAR_DECAY=0.99998`（每拍淡化，半衰 ~12 天）
- `integrity_signal.py`：`_SENSITIZE_GAIN=0.5`（疤=1 时同刀 ×1.5 疼）、`_DEPTH_BRAKE_K=2.0`（重伤愈合刹车）、
  `_SCAR_HEAL_RESIST=1.0`（疤区愈合阻力）、`_SCAR_FLOOR=0.1`（隐痛底，疤=1 时停在 0.1）
- `mental_simulation.py`：`_PAIN_TENSION_WEIGHT=0.15`（痛入张力软项）、`_PAIN_AVOID_WEIGHT=0.3`（绕 clamp 直接惩罚，
  有意强于软项——饱和区唯一可靠回避信号）

## 已知有界缺陷（已向 Codex 声明）

- `integrity_drive_bias` 为内存态，daemon 重启丢失 → 驱动力侧一次性有界双注入（clamp 兜底），
  下拍起恢复正常回收。急性痛通道由持久化 prev 完全保护，不受影响。
- pain 曲线沙盒建模略去了 s04a 的 `_somatic_pain` 二次项（仅当 somatic_tone<-0.2 时加一点点）；
  active_harm/留疤/愈合曲线为真实 integrity_signal 代码，无近似。
