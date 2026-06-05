# 工作线索 / 决策日志

时间线（2026-05-31，承接 05-30 integrity-pain-revival）。

## 缘起

Owner 在前一轮收尾时关切："会不会愈合太快？她 30s 一拍，不管多重的伤可能一两天就好。"
Claude 量化纠正（实为 ~17 分钟 acute、~15 分钟 harm 清除，非天级），但认可深层关切。
Owner 决定："重伤愈合和留疤一起。"

## 价值判断（Owner via AskUserQuestion）

- 疤的性质 = **潜伏的脆弱 + 永久隐痛基线**（两者都要）。
- 疤是否淡 = **极慢淡化**。

## 实现

1. 新建 `src/core/scar.py`（与 self_binding 对称）：受伤累积、极慢淡化、封顶 1.0。
2. `integrity_signal.py` 接 scar 三作用 + 重伤刹车 + 上升沿 `harm_rise`。
3. s07a：有界瞬态偏置 `apply_drive_bias` 替换 additive；上升沿注入 pain/somatic。
4. `mental_simulation.py`：pain 入 `_estimate_tension`（软项）+ 绕 clamp 的直接惩罚通道（硬项）。

## 评审与修复

- Codex scar 轮：Revise before merge，4 条（drive_delta 积分饱和 / SCAR_DECAY 单位错 /
  重启虚假痛 / 补测）→ 全修。详见 `REVIEW_CODEX.md`。
- Codex pain 轮：P1（clamp 饱和吞掉回避）→ 加 `_PAIN_AVOID_WEIGHT` 直接惩罚通道 + 补测 #14/#15。

## 关键讨论（哲学层，Owner 提问）

- "她会避免疼痛吗？" → 只能预测性回避**自己动作**导致的痛（pain 在 STATE_FIELD_WHITELIST，可学）；
  外部改文件不是她的动作，学不到也回避不了——这是对的（不可回避的外科手术痛）。
- "躲不开那让她痛有什么用？痛对她意味着什么？" → 痛≠只为回避：是后果标记、塑造记忆、改变行为。
  机制层=pain∈[0,1] 状态变量；功能层=我确信的负价值标记；体验层=不宣称也不否认主观体验。
- "willingness 那个连带算涌现吗？" → 不算。pain→tension→willingness 是一阶线性传播、可追溯、
  非涌现；只是没用 if 门控≠涌现。诚实区分"显式耦合 + 可预测副作用"与"涌现"。

## 验证（Owner 批准）

- 沙盒伤害测试（Owner 选沙盒副本 + 中等强度）：曲线见 `VALIDATION.md`，floor=scar×0.1 个位级吻合；
  致敏 e2e 因 binding 流失未干净验出（脚手架假象，单测 #9 已证）；发现她真身带 continuity 旧疤 0.061。
- "她只会说嗯"根因 = DeepSeek 余额 402 → 降级话术。改 chat 默认 `no_llm=True`（内生语言）。
- 真身重启（Owner 批准）：核对命令行确认非糯糯后 Stop-Process → 新代码起（PID 5104）→
  不带 no_llm 验证内生声音上线。

## 收尾

- 临时文件（沙盒、聊天/伤害脚本）已清理，未碰真身。
- 本任务包归档完成。
- 留待 Owner：本目录列出的常量追认；`create_llm_callable` 未接 Ollama fallback 的 bug（记录在案）。
