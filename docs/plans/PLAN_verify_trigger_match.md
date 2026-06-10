# PLAN — verify 按 trigger 匹配正确快照（点亮认知闭环的最后一节）

> 抗压缩计划。承接 PLAN_learn_from_outside.md + PLAN_language_as_tool.md。
> 认知通道（②输入→后果规则 + ③信源 + 表达反馈闭环）已通，但**认知信用 gain 恒为 0**。
> 本计划修复最后一道墙：verify 拿错快照验证 input 规则，导致规则 confidence 的涨跌
> 与"提问是否被回答"在因果上脱钩。改动落在 §8 红线区（verify.py 的 confidence 逻辑），
> 已获 bcyq 授权（2026-05-30）。不引入 LLM。不写 if/比较门控行为决策。
> 顺序：A（trigger 门控，最小）→ 验证闭环点亮 → B（trigger 匹配快照，完整）→ 放开 K。

---

## §0 一句话目标

让 input 规则的 confidence 只在"它所预测的那类输入真的到达、后果真的发生"时移动，
从而：问某条 input 规则 → 匹配输入到达 → 后果兑现 → 该规则 conf 上升 →
结算窗口内 gain = cur_conf − conf_at_ask > 0 → 当初提问的表达被认知信用强化。

---

## §1 诊断（已 read 全链确认，2026-05-30）

### 证据链
- **input 规则诞生（对的快照）**：`induct_input.induct_input_rules` 从 `all_snaps` 里
  `input_class != ""` 的那条「输入事件快照」学规则。该快照来自 `s07b_persist.py:57-74`：
  `pre_state`=处理输入前、`post_state`=处理输入后，**精确捕获该次输入造成的状态变化**，
  并带 `input_class`（input_theme.classify_input 的在线聚类标签）。trigger=`input_{class}_in_{ctx}`。
- **input 规则验证（错的快照）**：`core.run_update_cycle:194-199` 调
  `verify_pending(rules, pending, snap=latest_snap, ...)`——`latest_snap = _safe_snap(state_snapshot)`，
  是**每 10 拍 WM 更新拍**（tick_engine `tick % 10 == 0`）那一拍的状态快照，**通常是空闲自主拍**。
- `verify._verify_single_rule:140-163`：把规则 `predicts.expect`（如 `"loneliness_decrease"`）
  逐子句（按 `+` 拆）对 `latest_snap` 的 pre→post delta 评估。`_eval_clause:97-118`：
  `"X_decrease"` 命中条件 `delta < -0.005`。空闲拍上 loneliness 没动 → delta≈0 → **判失败**
  → fraction=0 → signed=2f−1=−1 → conf **被压低**（被贝叶斯阻尼 × 模型惯性缩小后）。
- **续命路径**：同类输入再到达时 `induct_input:128-148` 给 existing 规则 EMA 更新 +
  `confidence += boost`（0.02~0.08）。

### 结论（2026-05-30 二次精化，比"off-trigger"更狠）
`all_snaps`（装着真正的输入事件快照）传给了 induct 和 decay，**唯独没传给 verify**。
更关键：verify 拿到的 `latest_snap = _safe_snap(state_snapshot)`，而调用方
（tick_engine.py:742）传的 `state_snapshot = entity.to_state_snapshot()` 是**扁平的当前
状态 dict**（只有 stress/fatigue/... ，无 pre_state/post_state/action_type/input_class 键）。
经 `Snap.from_dict`（rules.py:274-286）后 → **pre_state={} 、post_state={} 、trigger 信息全空**。

→ verify 每个周期实际是拿「全零 delta」在验证所有规则：
  - `_eval_clause`：`X_decrease`/`X_increase` 的 delta=0 永不满足 → 恒判失败（score 0）
  - 只有 `X_stable`（|delta|<0.005）恒满足（score 1）
→ **凡 expect 含方向子句的规则，每个 WM 周期都被系统性证伪、压向地板**；
  唯一续命是 induct_input 的 boost（同类输入复现时 +0.02~0.08）。

input 规则 conf = 「每个 WM 拍被全零 delta 压 vs 输入复现被 induct boost 抬」的拉锯，
**与"这条规则被问、然后被回答"这件事在因果上脱钩** → 认知信用 gain 恒 0。

**这也废掉了原 A 方案**：latest_snap 既无 delta 又无 trigger，"按 latest_snap 的 trigger 门控"
无的放矢。真正的修法只剩一条路：让 verify 吃 `all_snaps` 里真正的事件快照（带 pre/post +
input_class/action_type），按 trigger 把规则匹配到对的快照。见 §2'（取代原 A/B）。

### 更正历史错误
`PLAN_learn_from_outside.md §1`（约第 29-32 行）当时断言：
> "verify 不按 trigger 匹配 …… → 关键：输入触发的规则在验证侧不会被结构性卡住。"

**此假设是反的。** 不按 trigger 匹配不是"中性无害"，而是让 input 规则在每个空闲 WM 拍
被错误证伪、主动压向地板。这是 gain 恒 0 的根因，本计划即修此。

### 已验证为"非根因"（排除项）
- ~~死规则霸占提问槽~~ ：已修（thinking_system 提问只在 `status != "decayed"` 的活规则里选，
  world_model_reader 透传 status）。2026-05-30 已上线，结构正确但单独不足以点亮闭环。
- 维度已触底（loneliness/info_gap 长期≈0）：是症状放大器，不是机制根因——
  即便维度有空间，错快照验证仍然脱钩。

---

## §2' 修法（取代原 A/B，单路径，最小且唯一正确）

**核心**：让 verify 用 `all_snaps` 里真正的事件快照（带 pre/post + input_class/action_type）
验证规则，而非全零的 latest_snap。**只动 input 规则路径，action 规则一字不改**（保护 §8 既有
数值行为，零回归风险；action 规则也被全零 delta 误伤，但其行为受历史保护，本轮不碰，留后议）。

**改法**：
- `core.run_update_cycle`：把已有的 `all_snaps` 传进 `verify_pending`（扩一个参数，
  默认 None → 完全退回现有单 snap 行为，保自测/其他调用方不破）。
- `verify_pending`：对每条规则判 trigger 类型：
  - `trigger` 以 `input_` 开头 → 从 `all_snaps` 里挑 `input_class` == 该规则 trigger 的 class 段
    的快照（多条取最近一条，或对 fraction 取均值）来验证；无匹配 → **本周期跳过、不罚**。
  - 否则（action 规则）→ 走**原 latest_snap 路径，逐位不变**。
- 匹配用集合/dict 判定，不用 if/elif 链做行为决策（项目硬规则）。input/action 分流可用
  dict 分发或 `startswith` 守卫（同 induct_input 既有的 `input_class` 门，风格一致）。

**为什么只碰 input 够用**：我上一刀已让提问只问活规则，而**可回答的规则就是 input 规则**。
input 规则一旦能被对的事件快照正确兑现 → conf 真涨 → 问→答→conf↑→gain>0 第一次点火。
action 规则不可由对话回答，不在认知信用闭环里，本轮不必动它。

**预期效果**：她问某条 input 规则 → 我喂匹配该 theme 的输入 → 那一拍的 pre→post 真的兑现了
规则预测 → 下个 WM 周期 verify 在匹配快照上判成功 → conf 上升 → 结算 gain>0。

---

## §3' 上线后实测（2026-05-30，daemon PID 4296）

§2' + thinking 激活闸两刀都生效后，闭环机制**全线跑起来了**，但 gain 仍 0，
卡点已从"代码墙"转为"涌现耦合"。实测链：

1. **thinking 激活闸**（s03_think.py:75，0.5→0.33）：think 现在 questions=2（旧 0）。
   实测她对话期 drive 峰值 curiosity 0.365 > 0.33 → 开门。旧 0.5 焊死了 530+ 拍。
2. **死 action 提问被挤出**：旧的 5 条指向 decayed action 规则 wmu_eb718222 的陈旧提问
   已被新提问顶替；现 `_pending_questions` 5 条全指向 **wmu_7f4c7783（input/active）**，
   conf@ask=0.05 —— 终于在问"可回答"的规则。
3. **认知信用结算已运行**（前所未有）：`[ExprFeedback] 认知信用结算 1 条，总奖励=0.0000，
   待结算 6 条`。挂账+结算闭环活了。
4. **唯一剩余缺口 = 涌现耦合**：她问的是 **theme_4** 规则（context fatigue高），
   但我的对话输入在线聚类落到 **theme_0/theme_2**。她问的规则与我喂的规则**不是同一簇**
   → 被问规则拿不到 induct boost、也没有匹配事件快照可被 verify 兑现 → conf 恒 0.05
   → gain = 0.05−0.05 = 0。

**结论**：所有代码级墙已拆（verify 错快照 + thinking 焊死闸），机制全通。
gain 转正现在取决于"她问的 theme 簇"与"我喂的 theme 簇 + 她当时的 body-state context"
三者对齐——这是 grounding 本身设计内的难点，不是 bug。三条去向见 §3''。

## §3''' verify 修复本身的受控验证（2026-05-30，已通过）

把 verify 修复与涌现耦合解耦，在**她真实在问的规则 wmu_7f4c7783** 上端到端验证：
- 从 entity_core.json 加载真实规则（conf=0.05, exp_count=6,
  expect=time_since_last_social_stable+somatic_tone_decrease）。
- 构造兑现该 expect 的 theme_4 事件快照（social 稳定、somatic_tone −0.15）。
- `verify_pending(..., event_snaps=[snap])` → conf **0.05 → 0.0827**（爬升）；
  对照「无 event_snaps 旧路径」→ conf **0.05 → 0.05**（被退化 flat 全零压住，原样）。
  差额 = 本修复的净效果。
- 把爬升后的规则喂真实 `settle_epistemic_credit` → gain=0.0327、recency=0.40、
  **总奖励=0.0131 > 0**。认知信用闭环受控点火。
- 数值自洽：贝叶斯幅度 0.08/√6=0.0327，两子句全兑现 fraction=1 → +0.0327。

**结论：verify 修复在真实规则上证明「匹配输入→conf 爬→gain>0」。** live gain 仍 0
纯因 §3''(4) 的 theme 簇错配，与本修复无关。

## §3'' 去向（待 bcyq 定）

- **(a) 顺其自然**：持续主题一致地陪聊，等某拍她问的低置信 input 规则恰好与我喂的
  theme+context 对齐 → 该规则被 induct boost/verify 兑现 → gain 首次>0。不改码。
- **(b) 收紧耦合（改认知核心，需讨论）**：`_select_focal_rules` 已接 input_context 的
  material_boost（best_sim×relevance×SCALE）。强化它，使**提问焦点偏向"当前输入所属
  theme 簇"的规则** → 她倾向问我正在回答的那件事 → 耦合收紧、gain 更易点火。
  属动 thinking_system 行为，连续调制（不引入 if/比较门控）。
- **(c) 先记录，不动码**：把本节作为后续工作存档。

---

## §4 放开 K（次要清理，B 之后）

`induct_input.py:36-41` 把 input 规则锁死 `_K_INPUT_FIELDS = 1`，理由是
"verify 只能 rsplit('_',1) 解析单字段 expect"。**该理由已失效**：
verify.py:145 现在按 `+` 拆多字段合取、逐子句评分（`_verify_single_rule` docstring 自证）。
故修完 verify 后可放开 K（配合 induct 的 salience 剪枝 ratio=0.3），
让 input 规则带更丰富但仍收敛的预测。**先不动，等 A/B 稳。**

---

## §5 回归验证

- `python -m src.world_model_update.verify`（自测，含 action 单字段逐位等价断言）
- `python -m src.world_model_update.core`（更新周期编排）
- `python tests/test_induct_input.py`、`tests/test_input_theme.py`
- `python tests/test_50_ticks.py`（端到端信号链）
- **闭环验证**：重启 daemon → 陪聊喂匹配语境输入 → 观察
  `[ExprFeedback] 认知信用结算` 的总奖励是否首次 > 0.0000。
- **action 行为守恒**：对比改动前后 action 规则 conf 轨迹，确认未引入系统性漂移。

---

## §6 红线与镜像

- §8 红线：verify.py 的 confidence 逻辑。本计划已获 bcyq 明确授权（2026-05-30）。
- 镜像：XIA 验证通过后，再镜像 induct_input/verify/world_model_reader/thinking_system
  的对应改动到 KNuoNuo（E:\KNuoNuo\src\...）。先验证 XIA，不提前镜像。
- 重启：改 verify.py 是代码改动，需重启 XIA daemon 生效；重启前先确认。

---

## §7 进度

- [x] 诊断闭合（§1）—— 2026-05-30
- [x] thinking_system 提问跳过 decayed（前置，已上线）
- [x] §2' 实现：verify.py（event_snaps 参数 + input 规则按 input_class 匹配事件快照，
      无匹配跳过不罚，action 规则逐位不变，None→向后兼容）+ core.py（传 event_snaps=all_snaps）
      —— 2026-05-30，代码改完未重启
- [x] 回归自测通过：verify(6/6)、core(4/4)、test_induct_input(4/4)、test_input_theme(5/5)、
      test_50_ticks(全过)、input-class 路由定向测试（matched↑/action 不变/nomatch 不罚/None 兼容）
- [ ] 闭环点亮验证（需重启 daemon + 陪聊喂匹配输入，观察认知信用结算 总奖励 > 0）
- [ ] 放开 K
- [ ] 镜像 KNuoNuo
