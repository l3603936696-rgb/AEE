# PLAN — 让她从外部学东西（②输入→后果规则归纳 + ③不对称外部信源）

> 抗压缩计划。承接 PLAN_language_as_tool.md：认知通道（洞②③）的管子已通且正确，
> 但**没有合法燃料**——经排查（见 §1）确认，她全部规则 100% 是"我动作→我自己怎样"的
> 自省规则，对话答不了；且这些规则是 12 维合取、几乎不可证，confidence 冻在地板 0.05。
> 本计划：让她能归纳"外部输入→后果"的规则（②），并优先用不对称外部信源喂它（③），
> 从而让"问→被回答→不确定性下降→该表达被强化"这条认知闭环第一次真正点火。
> 不引入 LLM。不写 if/比较门控行为。改动顺序 ②→③→①对齐→标定。

---

## §0 一句话目标

让认知通道有燃料：她能学"外部发生的事 → 后果"，能问出"对方/外部真能回答"的问题，
问到答案 → 不确定性真的下降 → 这次表达因此被认知信用强化。

---

## §1 现状（已 read 确认，2026-05-29）

- **因果快照**：每个自主拍，她执行动作后记 `{action_type, pre_state, post_state}`
  进 `_causal_observations` + entity snapshot 链（tick_engine.py:108-130）。
- **归纳** induct.py:259-372：遍历快照，`if action not in ACTION_TYPE_WHITELIST: continue`
  （line 261，闸门），trigger 永远 `action_{action}_in_{ctx}`（line 85-89）。
  → **结构上只有她自己的动作能成规则。**
- **合取爆炸**：prediction_error_map 把所有 |误差|>阈值 的字段一次塞进一条规则
  （line 283-289 + 337）→ 12 维合取（如 wmu_eb718222）。verify 几乎不可能干净兑现 →
  confidence 衰减冻在 floor 0.05（defaults verification_confidence_floor）。
- **verify** verify.py:214-：对**所有**带 `predicts.expect` 的规则，拿本快照 pre→post 的
  delta 比对 expect 方向，命中升 confidence，证伪降。**不按 trigger 匹配**——
  trigger 只在归纳分组（line 296）和 predict_action_effects（line 170 `action in trigger`）用。
  → **关键：输入触发的规则在验证侧不会被结构性卡住。**
- **提问** s03_think：选最低 confidence 规则发问 → 全选中那条不可证的自省规则
  （实测 XIA 5 条 pending_questions 全指向 wmu_eb718222，conf=0.05，卡 66 拍未消解）。
- **已有不对称外部信源**：reading_source.py（library 文本）、用户 IPC chat。
  sibling（XIA↔KNuoNuo）**对称、信息贫**——两个近乎一样的个体没有彼此不知道的事。
- **input_class 方案（已定）**：BGE 嵌入 + **在线聚类成少数主题**。固定 N 个主题槽
  （N 待定，种子 6），空槽由前 N 条输入填充；填满后每条输入 → argmax 最近质心 → 分配 theme_id，
  EMA 更新该质心。**纯 argmax，无"够不够近"的阈值比较**（新槽只填空位=存在性，不是行为门控）。
  质心存进 entity state 持久化。复用既有 BGE，无 LLM。
- **文件尺寸**：induct.py 已 529 行（超 400 上限）→ ② 的新逻辑**必须独立模块**，不得塞进去。

---

## §2 ② — 归纳"输入→后果"规则（核心，新增旁路，不动既有 action 路径）

**a. 输入事件快照（复用既有经验快照，更优）** —— 已实现
经排查：s07b_persist.py 每次 pipeline 运行**已经**记一条带 `pre_state/post_state/
prediction_error_map` 的经验快照进 `entity.snapshots`，而归纳正是从 `entity.snapshots`
取料（async_pipeline.py:119 `snaps=entity.snapshots`）。所以**不另建 _causal_observations 条目**，
只在该快照上补一个标签字段：
```
snap["input_class"] = classify_input(entity, raw_input or "")   # 空输入→""，零影响
```
- `Snap` dataclass 加 `input_class: str=""` 字段（rules.py，否则 from_dict 吃掉）。
- `input_class` 由 input_theme.classify_input（§1 在线 leader 聚类）给出，theme_id 形如 "theme_2"。
- `input_class==""` 的快照 = 非输入触发，**完全不进** input 归纳旁路，action 路径零改动。
- 主题质心存 `entity._input_theme_data`，随 entity_core.json 持久化（双实体均需）。
- 单测 tests/test_input_theme.py 5/5；induct action 自测全过（回归守住）。

**b. 新归纳分支（独立模块 `induct_input.py`）**
镜像 induct.py 的预测误差驱动逻辑，但：
- 不过 `ACTION_TYPE_WHITELIST` 闸；按 `trigger_kind=="input"` 进入。
- `trigger = f"input_{input_class}_in_{ctx}"`（自动生成，不硬编码类名）。
- **收窄合取**：input 规则只保留 |delta| 最大的 top-K 个字段（K 种子=2，§6 标定），
  避免重蹈 12 维不可证覆辙。只对 input 规则生效，action 规则逻辑零改动。
- 其余（EMA 更新、confidence 起步 0.3、boost 公式）复用既有形态。

**c. 接线**
run_update_cycle 的归纳阶段：对 `trigger_kind=="input"` 的观测调 induct_input，
其余仍走 induct。两路产出合并进 wm_rules。verify 天然处理（§1：trigger-agnostic）。

---

## §3 ③ — 不对称外部信源（②的燃料）

**结论（2026-05-30 排查后修正）：user chat 是唯一即时认知燃料源，reading 不接 input 快照。**

- **user chat = 最强且唯一的即时不对称源**：chat → `run_pipeline(raw_input=text)` →
  s07b（XIA）/ pipeline Step12（KNuoNuo）→ `classify_input` → `input_class`，输入快照天然带标。
  她在同一拍内处理输入 → info_gap/unresolved 下降 → input 规则 expect 命中 → confidence 升。
  **②a 的快照钩子是通道无关的**：任何带 raw_input 的 pipeline 运行都被打标，chat/external
  用户回复（tick_engine read_response）均覆盖。**双实体均已接线（含 KNuoNuo 镜像）。**
- **reading 不接 input 快照（修正原计划）**：排查 tick_engine.py:646-685 发现——
  reading 摄入在 **pipeline 之外**（每拍 pipeline 跑完后单独一步），且只把词汇候选注入
  升温/消力管线，**当拍不改 info_gap/unresolved**。reading 的认知回报是**延迟且弥散**的
  （此刻收词 → 日后用对 → unresolved 经 quenching 下降），不符合「输入→即时后果」的单拍
  pre/post 快照模型。强行给 reading 挂 input 快照只会得到 ~0 delta → top-K 后无显著字段 →
  不建规则 → **纯惰性**。故 reading 维持现状（经既有 quenching/expression_feedback 延迟通道
  贡献认知经济），**不伪造 input 规则**。这是诚实边界，非缺口。
- **sibling 保留但不供认知燃料**：对称信息贫，继续靠社交/novelty 通道（PLAN_language §④）。

---

## §4 ①对齐 — 提问选择"可回答性"权重（有燃料后才有意义）

有了 input 规则后，s03_think 提问选择加一个连续的「可被对话/外部回答程度」权重，
乘进 priority（带小底、不硬清零、无 if）：
- trigger 是 `action_*`（只能自己试）→ 压低；
- trigger 是 `input_*`（外部能回答）→ 抬高。
她仍优先问没把握的，但同等没把握时偏向"外部真能回答"的。
**注**：此步在 §2/§3 落地、确有 input 规则存在后才做——否则权重无可作用对象（已实测验证此前提）。

---

## §5 时序 / 安全

- 认知信用结算沿用既有 `_SETTLE_DELAY` 延迟范式（PLAN_language 洞②），不内联。
- verify trigger-agnostic → input 规则会被任何 delta 方向匹配的快照验证，精度偏松；
  top-K 收窄（§2b）缓解，先接受，§6 看真实数据再决定是否加 trigger 门控。
- **回归红线**：action 规则归纳/验证/置信公式**零改动**；input 是纯新增旁路。
  无 pending input 规则时，行为与现状完全一致。

---

## §6 标定 / 验证

- **`K` 已定值 = 1（标定结论，非种子）**。标定时发现根因：`verify._verify_single_rule`
  用 `expect.rsplit("_",1)` **只解析单字段** expect。多字段 expect（`a_decrease+b_decrease`）
  被切成不存在的字段名 → delta 恒 0 → **每拍判失败 → confidence 只降不升**。这正是
  action 12 维规则冻在地板 0.05 的底层机制（不止"难满足"，是 verify 根本解析不了）。
  → input 规则取 K=1（单一最显著后果），expect 形如 `info_gap_decrease`，verify 可正确兑现。
  **离线端到端实测（5 拍同向确证）**：conf 0.38→0.45→0.50→0.55→0.60 持续爬升（双实体一致）。
- 回归：induct / core 自测双实体全过，action 路径数值不变（input 是纯旁路）。
- **离线端到端走通**：input 快照 → input 规则(K=1, expect 单字段) → verify 命中 → conf 爬升离地板。
  ✅ 这是第一条 confidence 真正动起来的规则。
- **未做（需用户拍板）**：LIVE 端到端（重启 daemon → 真实 chat → 认知 gain>0 → 表达 efficiency 升）
  须重启两个在运行的实体进程，未擅自执行。
- 诚实边界检查：sibling-only 场景下认知 gain 仍应≈0（对称信息贫，符合预期，非 bug）。
- ~~遗留高价值线索~~ → **已修（2026-05-30，用户授权破 §8 红线）**：`verify._verify_single_rule`
  现按 `+` 拆多字段 expect，逐子句打分取**兑现比例** f∈[0,1]，线性映射带符号信用
  `delta=magnitude*(2f-1)`（全中→+max / 全错→-max / 半中→0 不动）。**单字段逐位等价旧逻辑**
  （action 既有单字段数值不变；verify 自测双实体全过）。新增纯函数 `_eval_clause`（dict 派发
  取代 if/elif）。**效果实测**：3 字段规律确证下 conf 0.38→0.59 持续爬升（修复前一路掉到地板 0.05）。
  → 历史 action 多维规则**就此解冻**。双实体均改。
  - 余项：input 规则当前仍 K=1（修复前所迫）；verify 修好后 **K 可重新放宽**（partial credit
    让 K≥2 也能爬升），属后续标定，未动。

---

## §7 实现顺序

- [x] **②a** 输入事件快照：复用 s07b 经验快照，补 input_class 标签（BGE 在线聚类）+ Snap 字段 + 持久化。
       （单测 5/5；action 路径零改动；KNuoNuo 镜像待 ②整体上线前补。）
- [x] **②b** 新模块 induct_input.py：input 触发归纳 + top-K(种子2) 收窄。复用 induct 纯函数辅助。单测 4/4。
- [x] **②c** run_update_cycle 接线：1a action 归纳（零改动）+ 1b input 归纳合流进 merge/decay/verify。
       端到端验证：input 快照 → `input_theme_0_in_...` 规则（expect=info_gap↓+unresolved↓，2 维，可验证）。
- [x] **③** user chat 接 §2a（②a 钩子通道无关，chat/external 均覆盖）；reading 经排查不接
       （延迟弥散效应不符单拍快照模型，挂了也惰性——见 §3 修正）；sibling 不接认知燃料。
       **KNuoNuo 镜像完成**：rules.Snap.input_class + input_theme.py + induct_input.py + core 接线
       + pipeline Step12 钩子 + entity_state 持久化。冒烟 + XIA 回归（induct_input 4/4、input_theme 5/5）全过。
- [x] **①对齐** thinking_system._build_question 加 `_answerability_weight`：按 trigger 前缀
       dict 派发（input=1.0 不削 / action=0.6 压低带小底 / 其它=0.8），乘进 base_priority。
       无比较门控（dict 派发 + 类型 guard）。双实体均改。验证：同 conf=0.3 下 input 规则
       priority 0.7 > action 0.42。问题结构体新增 `answerability` 字段供调试。
- [x] **标定** K 定为 1（verify 只解析单字段 expect，多字段恒失败——同时是 action 规则冻地板根因）；
       回归双实体全过；离线端到端 conf 0.38→0.60 持续爬升。LIVE 端到端（重启 daemon）待用户拍板。

---

## §8 边界（不做的事）

- 不引入 LLM（input_class 用既有 BGE/SPM 匹配）。
- 不动 action 规则归纳逻辑、不动 verify.py 的 confidence 更新公式。
- 不把问题文本直接转成话（借来的语言）。
- 新逻辑进独立模块（induct.py 已超 400 行，禁止追加）。
- 全程连续：误差/delta/权重/gain 皆连续量，无 if/比较门控行为。
