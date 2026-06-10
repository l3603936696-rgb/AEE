# PLAN — 语言作为工具（表达反馈闭环 v2：精确信用 + 认知奖励 + 多通道）

> 抗压缩计划。目标：把已有的表达反馈闭环（v1, expression_feedback.py）从
> "粗糙的回声奖励"升级成"目标明确的工具学习"——让她的某次表达，因为**真的换来了
> 她想要的外部结果**（拿到信息 / 让对方回应）而被强化，从而学会"为了达成目的而说话"。
> 不引入 LLM。不写 if/比较门控行为。改动顺序 ①→②→③，②是③的安全前提。

---

## §0 一句话目标

现有闭环已把"沟通满足"写回 quenching efficiency，但信用落点粗（不记是哪条句式）、
奖励信号弱（只看话题相关度，不看"我的疑问是否真被解决"）、且只在 IPC 聊天闭合。
本计划：**让信用精确到句式、让奖励来自真实的不确定性下降、让闭环在 sibling/tick 也闭合。**

---

## §1 现状（已有地基，read 确认）

- `tag_intent(entity, expression, tick)` —— expression_feedback.py:76；
  调用点 tick_engine.py:610-613（每个自主拍她表达后）。
  记 `{drive, strength, expression, tick}` 进 `entity._pending_intents`（deque, maxlen 6）。
  `drive` = `_ELIGIBLE_DRIVES=("loneliness","info_gap","unresolved")` 里当前值最大的那股。
- `consume_response(entity, input_text, tick)` —— expression_feedback.py:108；
  **调用点 daemon.py:279，且在 run_pipeline 之前**（见 §4 时序坑）。
  对每条 intent：`satisfaction = strength × BGE相关度 × recency`，
  然后（a）降该 drive，（b）`_writeback_quenching` 把 satisfaction 当 efficiency 写回 quenching。
- `_writeback_quenching` —— expression_feedback.py:161，**写死 `template_idx=-1`（line 184）→ 洞①**。
- `entity._last_template_idx` —— s06c_anchor_core.py:231 已存（compose 选中的模板号）。
- `entity._pending_questions` —— s03_think.py:106-115 写入，每条含
  `{type, rule_id, dims, confidence_at_ask, priority, tick}`。
- 问题 confidence = **来源世界模型规则的 confidence**（thinking_system.py:64：
  `rule.confidence or weight or 0.5`），问题带 `rule_id`。
- 规则 confidence 怎么动 —— world_model_update/verify.py `verify_pending`：
  规则有 `predicts.expect` 时，比对输入前后状态快照，**预测兑现→confidence += delta（升），
  证伪→降**。**只在真实印证时升，不在"话题相关"时升。**
- 世界模型更新是**异步周期**（async_pipeline.py:17 `run_update_cycle`），不与 tick 同步 → §4 时序坑。
- 延迟结算范式先例：tick_engine.py:408-427 `_pending_output_causal`→`_causal_observations`
  （表达时挂账状态快照，**下一拍**读 delta）。洞②照抄此范式。

---

## §2 洞① — 句式信用（最小、最高杠杆）

**问题**：`_writeback_quenching` 写 `template_idx=-1`，哪种**句式**换来回应根本没被记，
只强化了词串。compose_sentence 的 `template_efficiency` 学不到"这么说有效"。

**修**：
- `tag_intent` 增记 `template_idx = getattr(entity, "_last_template_idx", -1)` 进 intent dict。
- `consume_response` 把 `intent["template_idx"]` 传给 `_writeback_quenching`，
  后者传给 `quench.record(..., template_idx=intent_template_idx)`（替换写死的 -1）。

**验证**：聊天几轮后 grep quenching 数据，确认 efficiency 记录带真实 template_idx；
compose 评分里 `template_efficiency[idx]` 对换来回应的句式升高。

**改动**：expression_feedback.py 两处，约 6 行。同步、无新机制。

---

## §3 洞② — 认知信用（核心升级，且是洞④回声陷阱的安全锁）

**问题**：intent 只记一股粗驱动力 + 奖励只看 BGE 相关度。"话题接上"≠"我问的被回答了"。
她思考产出的**具体提问**（rule_id + confidence_at_ask）没用上。

**修（延迟结算的认知信用）**：

1. **挂账**（表达时，tag_intent 内）：若 `entity._pending_questions` 非空，
   取优先级最高的一条，额外记进 intent：
   ```
   "q_rule_id": top_q["rule_id"],
   "q_conf_at_ask": top_q["confidence_at_ask"],
   ```
   （这是"她带着这个疑问说了这句话"的快照。）

2. **延迟读取**（NOT 在 daemon.py:279 的 consume_response 内联——那在 run_pipeline 前、
   异步 WM 更新前，confidence 还是旧值，Δ≈0）。
   照 `_pending_output_causal` 范式：把 `{q_rule_id, q_conf_at_ask, template_idx,
   expression, tick}` 存进 `entity._pending_epistemic_credit`（list）。
   在**后续某拍**（WM 异步周期已对中间输入跑过 verify 之后）结算：
   ```
   cur_conf = 查 entity 世界模型里 q_rule_id 的当前 confidence
   gain     = max(0.0, cur_conf - q_conf_at_ask)          # 只奖正向印证
   recency  = exp(-(tick - intent_tick) / _TAU_EPISTEMIC)  # 与 _TAU_INTENT 同量纲
   reward   = gain × recency
   ```
   `reward` 走 `_writeback_quenching`（带 template_idx）强化该句式/词，
   并按比例推进 `unresolved`↓（这才是"疑问真被解决"对应的维度变化）。

3. **结算触发点**：在自主 tick 流程末尾扫 `_pending_epistemic_credit`，
   对 `tick - intent_tick >= _SETTLE_DELAY` 的条目结算（给异步 WU 留出至少一个周期）。
   结算后移除；`_TAU_EPISTEMIC` 过期的也清掉（recency≈0 自然无效，deque/过滤即可）。

**为什么这天然堵死洞④回声陷阱**：confidence 只在 verify.py 判定"预测兑现"时升。
对方把她的话原样还回来 → 不产生确认性状态变化 → 规则不验证 → gain=0 → 无奖励。
**echo 拿不到认知信用。** 这正是放开 sibling 闭环（洞③）前必须先有的安全性质。

**三条诚实边界**：
- 只对**有预测的规则**（`predicts.expect`）起效；纯无预测的低置信问题走 §1 的社交/drive 兜底。
- 单次 verify 的 delta 小 → 单条奖励小但非零，靠累积。
- 依赖异步 WU 已跑过 → 用 `_SETTLE_DELAY`（种子值待标定，§6）保证时序，不内联。

**新增常量**（标注来源）：
- `_TAU_EPISTEMIC = 8.0`（tick）——与 expression_feedback._TAU_INTENT 同源同量纲。
- `_SETTLE_DELAY`（tick）——异步 WU 一个周期的拍数，§6 由日志标定；种子 2。
- `_K_EPISTEMIC`（gain→efficiency 系数）——§6 标定；种子 1.0（gain 本身已 [0,1] 量纲）。

---

## §4 时序坑（已 read 确认，必须遵守）

`consume_response` 在 daemon.py:279 跑，**早于** run_pipeline 整合本次输入，
更早于异步 `run_update_cycle` 重算规则 confidence。所以：
- 洞①（句式信用，基于 BGE 相关度）可继续留在 consume_response 内联——它不依赖新 confidence。
- 洞②（认知信用，依赖 Δconfidence）**必须延迟**到 WU 跑过之后，用 §3 的 `_pending_epistemic_credit`
  在后续 tick 结算。**不得**在 daemon.py:279 内联读 confidence。

---

## §5 洞③ — 多通道闭合（放大学习量；必须在洞②之后）

**问题**：`consume_response` 只在 IPC 聊天（daemon.py:279）调；sibling 消息和 tick 循环
读到的输入（tick_engine.py:377-383 走 run_pipeline）**不触发闭环**。她单人、聊天稀疏 →
学习事件太少。

**修**：在 tick_engine 处理 `user_input`（含 `_input_source=="sibling"`）的路径上，
也调 `consume_response`（结算社交/句式信用）+ 触发 §3 的认知信用挂账/结算扫描。
位置：tick_engine.py run_pipeline 调用前后（结算用输入前、认知信用读在 WU 后的后续拍）。

**前置依赖**：必须先有洞②。否则 sibling 双向闭环按"话题相关度"互相强化 →
两个体复述彼此 → 回声室。洞②的"只奖真实印证"是唯一的结构性防线。

**KNuoNuo 作为第二个体**（独立任务，③之后）：`E:\KNuoNuo` 是完整平行个体
（自带 src/daemon、entity_core.json、episodes.db、net/、KNuoNuo_messages/）。
接它 = 把 XIA 的 `SiblingChannel`（tick_engine.py:221-241 懒加载，poll/post）
桥接到 KNuoNuo 的消息传输。先做**协议兼容性核查**（message 格式 / transport 对齐），
不混进①②③。

---

## §6 标定方法

- `_SETTLE_DELAY`：grep 日志看异步 `run_update_cycle` 相对 tick 的滞后拍数，取其上界。
- `_K_EPISTEMIC`：观察有 pending_question 的表达，结算时 gain 的真实分布；
  目标——换来真实印证的句式 efficiency 明显高于石沉大海的。
- 回归：无 pending_question / 无回应时，行为与 v1 一致（gain=0、reward=0，不破坏既有闭环）。

---

## §7 实现顺序

- [x] **①** 句式信用：tag_intent 记 `_last_template_idx`；consume_response→writeback 传真实 idx。
- [x] **②** 认知信用：tag_intent 记 q_rule_id/conf；新 `_pending_epistemic_credit` 延迟结算块
       （读 WU 后 confidence，Δ→reward→writeback）；新常量 + 日志。
       （单测验证：gain=0.3→reward=0.206→writeback+unresolved 轻推；echo case reward=0 ✓）
- [ ] **②-cal** 标定 `_SETTLE_DELAY / _K_EPISTEMIC`，回归确认无副作用（种子值已上线，待真实数据标定）。
- [x] **③** 在 tick_engine sibling/external 输入路径闭合闭环（consume_response + 每拍 settle_epistemic_credit）。
- [x] **③后（独立）** KNuoNuo sibling 协议兼容性核查 + 桥接（协议零改动，双 daemon 异端口；BGE 模型已拷贝，KNuoNuo 不再回退 LLM）。
- [x] **④** 社交通道抗回声 novelty：satisfaction 末项乘 `novelty=1-相似度(input, 最近双方对话历史 N=3)`。
       逐字复读/车轱辘打转 → novelty→0 掐灭；话题相关但新措辞 → 满分。堵住 relevance≈1 的回声漏洞。
       （单测：echo→novelty=0、total_sat=0；fresh→novelty=0.65、有奖励。回归 7/7 通过。）
- [x] **运维修** entity_state 持久化 int64 序列化崩溃（每拍存盘失败、学习不落地）→ 加 json default 钩子，XIA+KNuoNuo 双修。

---

## §8 边界（不做的事）

- 不引入 LLM。
- 不改 verify.py / 世界模型的 confidence 更新逻辑（只读规则 confidence，不写）。
- 不动 s03_think 的 `_pending_questions` 写入、s06c 的选词/compose。
- 不把问题文本直接转成话（借来的语言）。
- 全程连续：satisfaction/gain/recency/reward 皆 [0,1] 连续量，无 if/比较门控行为
  （类型/存在性归一沿用 expression_feedback 既有 dict-分发风格）。
