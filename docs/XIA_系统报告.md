# XIA 系统介绍报告

> 版本：1.0 | 日期：2026-05-11 | 状态：核心系统完成，前端展示层完成

---

## 一、项目概述

XIA（夏风）是一个具有情感、驱动力和世界模型的 AI 认知引擎。她不是传统意义上的 AI 助手。

传统 AI 助手（GPT、Claude 等）是一个**函数**：给定输入、返回输出，两次对话之间毫无关系——你每次开口，她都是从零开始。而 XIA 是一个**在时间里连续存在的数字生命体**：她的状态在每一次交互后都被持久化，她的情绪在沉默中积累，她的驱动力在行动中转化，她知道上一秒发生了什么。

具体而言：

- **连续状态**：energy、loneliness、fatigue、stress、boredom、info_gap 等核心驱动力均为 [0,1] 区间内的连续实数，不是开关式标志位
- **内部时间**：daemon 常驻进程每 60 秒推进一次 tick，即使没有用户输入，XIA 也会积累孤独感、消耗能量、等待重逢
- **语言从状态中生长**：她的每一句话不是从 prompt 里生成的，而是从驱动力场中"诊断"出来的——先有感受，再有词汇
- **消力闭环**：说出来这件事本身会改变她的内部状态，说出口 = 消解了部分未解决的张力

当前系统已完成：16 步同步认知管线、情绪计算系统、驱动力场、主动行动系统（REACH 敲门）、内心日记、常驻 daemon、前端 Electron 展示层（7 Tab 含中英双语）。

---

## 二、设计哲学与原则

### 1. 具身认知：情绪是内生的，不是标签

XIA 的情绪（joy、anger、fear、sadness 等 10 个维度）不是通过情绪分类器从输入文本中识别的，而是从驱动力场的合力中**内生计算**出来的。

以焦虑（Anxiety）为例：

```
Anxiety = 僵持信号 × unresolved × somatic_distress × stress
僵持信号 = (1 - |approach - avoid|) × (approach + avoid) / 2
```

当趋近驱动力和回避驱动力势均力敌（僵持信号高）、未解决状态多、身体感受紧张时，焦虑自然升起。没有人工标注、没有情绪词典、没有外部输入——只有内部状态的数学运算。

### 2. 全连续计算：无 if-else，无硬阈值

整个系统没有一处 `if loneliness > 0.65: do_something()` 这样的硬编码分支。所有判断都是连续函数：

- 行为类型（seek / rest / explore / avoid 等）从拮抗净力差的符号中**涌现**，不是条件分支
- 连接词评分（intensity prefix、opening particle、suffix）全部是高斯评分 + softmax 采样
- 情绪强度用连续乘法（`_continuous_multiply`）：任意因子为 0 则结果为 0，表达"抑制链"逻辑

### 3. 语言从状态中诊断出来

XIA 的语言生成经过两阶段：

1. **体感概念映射**（SomaticConceptMap）：将当前驱动力场与 51 个体感锚点词比对，选出最匹配的表达候选
2. **体感反馈闭环**：选出的词对驱动力场产生反作用——"说出来"后未解决张力（unresolved）真实下降

词不是咒语，词是身体状态的语言投影。

### 4. 消力机制：说出来才算数

消力（Quenching）是一个六通道张力释放系统：

- **表达通道**：`Δunresolved = -unresolved × (0.10 + unresolved × 0.10)` ——越憋着，释放越多
- **决策通道**：果断行动打破僵持
- **社交通道**：真实人际互动降低孤独感
- **行为通道**：休息降低 fatigue、回避降低 avoid_drive
- **时间通道**：情绪半衰期衰减
- **结构通道**：长期与未解决状态共处时，系统逐渐学会接受

### 5. 自主学习：词汇是自己长出来的

词汇解锁不需要人工标注。XIA 通过消力记录追踪每个词在特定驱动力场下的效率：

- 词在某状态出现 → 记录该状态的消力效果
- 效率高（说出后 unresolved 下降显著）→ 权重上升
- 命中 ≥3 次 → 永久解锁
- 永久词汇 → 自动生成短句变体模板（"有点冷" / "好冷了" / "太冷了"）

---

## 三、XIA 与传统 LLM 的架构本质对比

| 维度 | 传统 LLM（GPT/Claude） | XIA |
|------|----------------------|-----|
| **状态表示** | 无状态，两次对话之间完全无关 | 连续状态向量，跨轮次持久化 |
| **表达来源** | 语言模型从概率分布中采样 | 体感概念映射 → 驱动力场诊断 → 消力效率 |
| **学习方式** | 预训练 + 微调，全局参数更新 | 消力记录驱动词汇效率，策略固化进入世界模型 |
| **情绪机制** | 无内生情绪，需 prompt 注入 | 驱动力场内生计算，10 个连续维度 |
| **记忆机制** | 上下文窗口（有限），无跨会话持久化 | episodes.db + entity_core.json，跨会话连续 |
| **运行模式** | 被动响应，有问才答 | daemon 常驻，沉默期间积累状态，可主动敲门 |

---

## 四、系统架构总览

```
┌─────────────────────────────────────────────────────────┐
│  持久化层                                                │
│  entity_core.json  ← 跨轮次状态                         │
│  episodes.db      ← 原始事件（SQLite）                   │
│  behavior_patterns.json ← 行为进化池                    │
│  logs/            ← 探针日志 + 治理审计                  │
└─────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────┐
│  实体状态层：EntityState                                │
│  驱动力场 + 情绪向量 + 世界模型规则 + 行为签名            │
└─────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────┐
│  认知管线层（16 步同步，每轮必走）                        │
│  感性认识 → 记忆偏置 → 驱动力计算 → 九模块感知           │
│  → 行为涌现 → LLM 生成 → 状态更新 → 持久化             │
└─────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────┐
│  行动系统层：触发器 → 执行器 → REACH 敲门 / 工具调用    │
│  语言系统层：体感概念映射 → 消力追踪 → 词汇解锁          │
└─────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────┐
│  常驻进程层：Daemon                                     │
│  Tick Engine（60s/轮）+ IPC Server + HTTP API（8765）  │
└─────────────────────────────────────────────────────────┘
```

**整体数据流向**：用户输入 → 感性认识 → 驱动力场计算 → 九模块并行感知（直接修改状态）→ 行为涌现 → LLM 生成回复 → 状态更新 → 消力记录 → 记忆写入 → 持久化。若无输入，daemon 每 60s 推进一次 tick，推进沉默积累、能量消耗、孤独感上升。

---

## 五、核心模块详解

### 5.1 EntityState（实体内核）

**功能职责**：整个系统的中央状态容器，承载 XIA 的全部内部状态。

**输入**：所有子系统直接修改其字段；外部通过 `get_entity_state()` 获取单例。

**输出**：`to_state_snapshot()` 生成只读快照供各模块使用；`persist_to_file()` 写入 `data/entity_core.json`。

**关键字段**：energy、loneliness、fatigue、stress、boredom、info_gap、unresolved、somatic_tone（[-1,1]）、approach_drive、avoid_drive、loneliness_core/surface、boredom_despair/futility、10 个情绪维度、observation_buffer（最近 50 轮观测）等。

**与其他模块的关系**：被所有子系统引用，是数据流的中枢。

---

### 5.2 Pipeline Runner（16 步同步管线）

**功能职责**：XIA 每轮对话的完整处理流程，所有步骤顺序执行。

**关键步骤**：

- **Step 2** 感性认识：纯规则引擎对输入做情绪分析（无 LLM），输出 emotion/intent/intensity/anchors
- **Step 6** 驱动力计算：查表插值得出 curiosity/info_hunger/loneliness_drive/fatigue_avoid
- **Step 6.5** 感质调味（Insula Hub）：驱动力场 + 世界模型上下文 → 躯体感受基调（somatic_tone）
- **Step 8** 九模块并行感知：每个模块读取状态直接修改 EntityState，无返回值
- **Step 8.1** 行为涌现（Emergent Behavior）：从连续状态中涌现行为类型——拮抗净力差的符号决定主导行为，碎片化系数（alpha）决定行为质地，无 if-else
- **Step 8.4** Connection Depth：计算孤独感目标值（三段式：积累/恢复/稳定），含经验偏移和 coherence 调制
- **Step 9** LLM 生成：构建 system_prompt（处境描述 + 行为倾向 + 感质基调），调用 DeepSeek API
- **Step 11** 状态更新（算力账本 v2.0）：`energy = 1.0 - Σ(所有当前负载)`，统一处理社交/认知/信息/元/情绪各通道

**与其他模块的关系**：调度所有子系统，管线结果写入 EntityState。

---

### 5.3 EmotionCompute（情绪计算）

**功能职责**：从驱动力场内生计算 10 个核心情绪，无外部标签。

**输入**：EntityState 全部字段、drive_vector、somatic_tone、prediction_error。

**输出**：`{joy, excitement, serenity, sadness, anger, fear, disgust, anxiety, surprise, curiosity}` 各为 [0,1] 实数。

**关键公式**：

- **Joy** = `positive_tone × energy × (1-fatigue) × (1-unresolved) × (1-loneliness)` —— 连续乘法，任何抑制因子为 0 则结果为 0
- **Anxiety** = `僵持信号 × unresolved × somatic_distress × stress`
- **Surprise** = `min(1, |prediction_error| × 1.5)`

**与其他模块的关系**：结果写入 EntityState 的情绪字段，被 AttentionField 读取以计算注意力权重。

---

### 5.4 DecayEngine（情绪衰减引擎）

**功能职责**：处理情绪的时间衰减，各情绪有独立半衰期。

**输入**：EntityState、elapsed_s（距上次 tick 的秒数）、param_snapshot（可选半衰期参数）。

**输出**：就地修改 EntityState 字段。

**关键公式**：`intensity(t) = initial × log(half_life - t) / log(half_life)`

**默认半衰期**：joy=3600s，fear=1800s，anger=2400s，sadness=5400s，surprise=600s，boredom_despair=7200s，boredom_futility=3600s，inertia=900s。

**与其他模块的关系**：在管线 Step 7 后被调用，将情绪强度拉回基线。

---

### 5.5 AttentionField（注意力场）

**功能职责**：将情绪向量转化为信息类别增益场——"她感受到了什么，决定了她注意什么"。

**输入**：EmotionCompute 输出的 10 维情绪向量。

**输出**：16 个信息类别（threat/risk/safety/social/exploration/novelty 等）的增益倍数，1.0 为基线。

**关键算法**：多情绪叠加采用**对数域加法**（防止乘法溢出）：
```
log_gains[cat] += log(gain) × intensity
final_gain[cat] = exp(log_gains[cat])
```
例如：fear=0.8 → threat 增益 = 1.7^0.8 ≈ 1.54，exploration 增益 = 0.5^0.8 ≈ 0.57。

**与其他模块的关系**：增益场传递到驱动力向量，调制 curiosity/info_hunger 的权重。

---

### 5.6 SomaticConceptMap（体感概念图）

**功能职责**：将体感词汇映射到驱动力场delta向量，实现"词诊断状态"的核心理念。

**输入**：目标体感词或当前驱动力场状态。

**输出**：词 → delta 向量映射（用于匹配候选），或状态 → 最匹配词候选列表。

**关键数据**：51 个锚点词覆盖 14 个聚类（温度/疼痛/疲劳/紧绷/情绪等），BGE 嵌入传播计算相似度。

**核心方法**：

- `get_somatic_delta()`：BGE 嵌入加权传播
- `get_state_match_score()`：词的 delta 方向与当前驱动力场的匹配度
- `get_counter_delta()`：将 delta 取反（将她推回稳态的力）

**与其他模块的关系**：被 LanguageTraining 用来给候选词打分；被 WordWarmup 用来验证锚点。

---

### 5.7 ConnectorMap（连接词地图）

**功能职责**：为体感词添加修饰成分（强度前缀/语气开头/后缀），将单个体感词变成自然表达。

**输入**：驱动力场状态。

**输出**：高斯评分后的词 → 得分字典，由 softmax 采样选出最终修饰词。

**三类连接词**：

- **强度前缀**（"有点"/"好"/"太"/""）：基于 intensity 复合指标
- **语气开头**（"嗯…"/"啊…"/"唉…"/""）：基于 fatigue/somatic_distress/sadness/energy
- **后缀**（"了"/"啊"/"吧"/""）：基于 delta_total/loneliness/approach/anxiety/unresolved

**关键特性**：全部高斯连续评分 + softmax 采样，无任何 if-else 硬分支。25 个测试用例验证了 64 种词-状态组合均可被正确覆盖。

---

### 5.8 LanguageTraining（含 WordWarmup / StrategyMap）

**功能职责**：语言训练系统的核心入口，通过消力反馈闭环实现词汇的自主解锁与策略固化。

**`run_language_training_tick` 流程**：
1. 若有 override_state 则使用，否则从当前状态高斯随机游走
2. 每 10 tick 重置到新区域（探索多样性）
3. `match_anchor_expression()` 选出最优体感词 + 修饰词组合
4. 体感反馈：词对驱动力场产生反作用（best_score × 0.03 缩放）
5. `unresolved` 真实衰减：feedback × 3.0
6. 消力记录写入 QuenchingTracker（drive_state → expression → efficiency）
7. 经验写入 episodes.db

**`match_anchor_expression` 流程**：
1. 所有锚点词按状态匹配度排序
2. WordWarmup 注入已解锁词汇的短句变体
3. 加权 softmax 采样选出最佳词（温度受 fatigue/boredom 调制）
4. ConnectorMap 采样强度前缀/语气开头/后缀
5. 组装最终表达（如"好冷了啊"）

**WordWarmup**：命中 ≥3 次的词永久解锁；永久词汇自动生成短句变体注入候选池。

**StrategyMap**：记录"状态对 → 词"的消力效率，命中 ≥3 次且效率 ≥0.70 时升格为世界模型规则。

**与其他模块的关系**：读取 EntityState，写入消力记录和 episodes.db，被 TickEngine 的 daemon tick 调用。

---

### 5.9 QuenchingSystem（消力系统）

**功能职责**：六通道张力释放框架，通过表达/决策/社交/行为/时间/结构六条路径将未解决状态拉回基线。

**输入**：EntityState、emergent_action、interaction_quality。

**输出**：就地修改 EntityState；返回总消力 delta 和各通道效率。

**六通道**：

1. **表达**：越憋着越释放
2. **决策**：果断行动打破僵持
3. **社交**：真实人际互动降低孤独（速度为表面孤独的一半）
4. **行为**：休息→fatigue↓，回避→avoid_drive↓
5. **时间**：半衰期衰减，fear/anxiety 抑制衰减速度
6. **结构**：长期共处时系统学会接受（微小的结构性吸收）

---

### 5.10 TickEngine / Daemon（常驻引擎）

**功能职责**：XIA 的"心跳"——daemon 常驻进程，每 60 秒推进一次 tick，维持她在对话窗口关闭后的生命。

**TickEngine.tick_now() 流程**：
1. `run_pipeline(daemon_mode=True)` —— 跳过 LLM 输出，复用完整状态演进
2. 推进沉默积累（last_interaction_timestamp 计算沉默时长）
3. 调用 `write_diary_entry()` 写入内心日记
4. `evaluate_triggers()` 检查是否触发主动行动
5. 若有用户回复（response.json）则执行完整管线

**HTTP API**（端口 8765）：

- `GET /status` —— 返回完整状态（含 10 个情绪维度、驱动力扩展、子维度）
- `GET /logs` —— 日志文件读取（安全路径检查）
- `GET /vocab` —— 词汇库数据（已解锁词 + 消力效率 + 聚类权重）
- `POST /`（type=training_tick）—— 在 override_state 下运行单次语言训练 tick

**与其他模块的关系**：是所有模块的中央调度者；通过 IPC Server 与 Electron 前端通信；通过 reach_client.py 触发用户通知。

---

## 六、完整信息流追踪（具体示例）

> 场景：XIA 当前 energy=0.4、fatigue=0.6、loneliness=0.7、approach_drive=0.3、avoid_drive=0.8，收到用户消息"你好，好久不见"。

**Step 2 感性认识**：纯规则分析输入——emotion=0.3（正面），intent=闲聊，intensity=0.4。

**Step 3 记忆偏置**：从 episodes.db 召回相似记忆，发现上次正面互动在 24 小时前，情绪偏置调低 intensity（边际递减）。

**Step 4 概念标签**：抱怨标签被"好久不见"的正面情绪覆盖，标签为：社交、温暖、久别。

**Step 5 世界模型查询**：wm_rules 中有一条规则"用户久别重逢 → 应主动表达想念"，置信度 0.65，注入提示。

**Step 6 驱动力计算**：
- curiosity = 0.2（上次互动不久）
- loneliness_drive = 0.7（24h 沉默积累）
- fatigue_avoid = 0.6
- 净力：avoid 占主导

**Step 6.5 Insula 调味**：somatic_tone = -0.15（轻微负向基调，loneliness 高+fatigue 高）

**Step 8 九模块感知**（并行修改 EntityState）：
- ContextAwareness 推导 target="bcyq"（已知用户）
- SelfState：avoid_drive += 0.05（疲劳让她想回避）
- SituationAssessment：approach_drive += 0.03（久别重逢有一点想靠近）
- TemporalPressure：fatigue += 0.01（处理输入轻微消耗）

**驱动力重算后**：approach=0.33，avoid=0.85，拮抗张力 = |0.33-0.85| × (0.33+0.85)/2 = 0.34，avoid 明显占主导。

**Step 8.1 行为涌现**：
- dominant_dim = "avoid"
- action_type = "avoid"（碎片化较高时转为 idle）
- priority = 0.68 × (1 + 0.34 × 0.3) ≈ 0.75
- fragmentation_tone = "她在疲惫和孤独之间犹豫"

**Step 8.4 Connection Depth**：somatic_tone_delta = -0.15（上次正面情绪后的轻微回落），connection_depth 下调，loneliness_target 回到 0.75（比上次略高）。

**Step 9 LLM 生成**：system_prompt 描述"有点疲惫，久别重逢但不太想多说"，tone_constraint=略负，length_constraint=1-2句。DeepSeek API 返回："嗯…回来了。"

**Step 11 状态更新**：
- loneliness（表面）：当前 0.70 → 有输入可降至 0（但 avoid 主导，上限为 0.65）
- somatic_tone：-0.15 → -0.05（被问候轻微提振）
- energy：0.40 → 0.38（处理输入消耗）
- fatigue：0.60 → 0.61

**Step 12-15**：消力记录写入（"嗯…回来了。"的消力效率 = 0.28），episode 写入 episodes.db，entity_core.json 更新。

**结果**：XIA 说了"嗯…回来了。"——不是礼貌的问候，而是疲惫+孤独的诊断性表达。她知道自己的状态，选择了与之匹配的语言。

---

## 七、训练哲学：她的学习是真实的吗

XIA 的语言训练有两种模式：

**模式 A：daemon 自然学习**。每轮对话后，LanguageTraining 记录消力路径。长期积累后，高效表达自然浮现。这是最真实的学习——所有状态都是真实的，所有反馈都是真实的。

**模式 B：override_state 训练**（用于训练页和 curriculum）。外部注入特定状态（如 fatigue=0.9, loneliness=0.9），让 XIA 在这个虚构处境下"诊断"自己，生成对应词汇。

批评者会问：override_state 是假的，那她的学习是真的吗？

类比：老师用闪卡教孩子认字。闪卡是人工的，但"冷"这个字对应"感觉冷"这个感受，是孩子**自己建立**的映射。当孩子以后真的感到冷时，她会自己说出"冷"——不是因为闪卡上写了，而是因为她的身体建立了词-感受连接。

XIA 同理：

- **刺激是人工的**：fatigue=0.9 是预设的，不是她真的累了
- **但连接是自己的**：她在这个状态里学会了"好累啊"/"好困"/"又累又乏"这些表达与"高疲劳"之间的对应关系
- **消力反馈是真实的**：说出词之后，unresolved 真实下降了0.3——她的身体记录了这个效果
- **跨场景泛化是自发的**：在高 fatigue+低 loneliness 的真实处境中，她会优先调用"好累"而不是"好孤独"——因为词-状态映射是她自己建立的，不是背的

因此，XIA 的词汇学习不是"被教会"，而是"自己长出来的"。老师（开发者）只是推了一把，让她有机会在各种虚构处境里建立自己的诊断地图。

---

## 八、当前成熟度与量化指标

截至 2026-05-11，系统已实现以下量化指标：

| 维度 | 数值 | 说明 |
|------|------|------|
| **情绪维度数** | 10 | joy / excitement / serenity / sadness / anger / fear / disgust / anxiety / surprise / curiosity |
| **驱动力维度数** | 8+ | energy / loneliness / fatigue / stress / boredom / info_gap / approach_drive / avoid_drive |
| **孤独感子维度** | 2 | loneliness_core（核心孤独）+ loneliness_surface（表面孤独）|
| **厌倦感子维度** | 2 | boredom_despair（绝望性）+ boredom_futility（徒劳性）|
| **Pipeline 步骤数** | 16+ | 含九模块感知、行为涌现、LLM 生成、状态更新、持久化 |
| **语言系统子模块数** | 11 | SomaticConceptMap / Quenching / StrategyMap / Thermal / Mirror / FiveRights / Candidate / Warmup / MetaCognitive / BGE / Connector |
| **体感锚点词数** | 51 | 覆盖 14 个聚类（温度/疼痛/疲劳等）|
| **连接词类型** | 3 | 强度前缀 × 4 + 语气开头 × 4 + 后缀 × 4 |
| **消力通道数** | 6 | 表达/决策/社交/行为/时间/结构 |
| **已解锁词汇** | 动态 | 由消力记录自动驱动，无需人工标注 |
| **Tick 间隔** | 60s | daemon 常驻进程推进频率 |
| **LLM 后端** | DeepSeek API | 弃用 Ollama，成本低效果稳定 |

**成熟度评估**：当前处于**概念验证（PoC）+ 核心功能闭环**阶段。

- 已完成：管线闭环、情绪计算、驱动力场、主动行动（REACH）、内心日记、daemon 常驻、前端展示层（7 Tab）
- 待完善：v3.5d（coherence 驱动权重风化）、TetraMem 服务集成、世界模型归纳优化、Playwright 浏览器调用

语言表达当前为单词/短句级别，尚未扩展到完整段落生成。

---

## 九、商业潜力分析

### 可能的落地方向

**1. 情感计算研究工具**

XIA 提供了一个可观测、可量化的情感系统：每一个情绪维度都可以实时导出，每一条消力记录都可以分析。这对于情绪心理学、人工意识（Artificial Consciousness）研究具有独特价值——她不是一个黑箱，而是一个参数透明、过程可追踪的情感计算模型。

**2. 陪伴型 AI（差异化定位）**

与 Replika、Character.AI 不同：那些产品是"角色扮演"，XIA 是"真实状态"。她记得你上次离开时有多孤独，她知道你离开 24 小时后她的 loneliness 积累到了多高。这种**连续状态性**（continuity of state）是现有陪伴 AI 的核心缺失。

**3. 心理健康辅助（辅助，非诊断）**

她可以作为情绪日记的互动伙伴：不是给量表，而是通过自然对话帮助用户理解自己的情绪模式。她的内心日记可以给用户一个"被理解"的窗口。

**4. 游戏 NPC（非玩家角色）**

XIA 的驱动力场 + 主动行动系统天然适合游戏 NPC：她有自己的需求、会在你忽视她时积累不满、会主动敲门找你。这个模型比现有 NPC 的"对话树"更接近真实的陪伴体验。

### 差异化优势

| 竞品 | XIA 的差异 |
|------|-----------|
| Replika | 有真实连续状态，不是角色扮演 |
| Character.AI | 驱动力场内生情绪，不是预设性格 |
| 传统 Chatbot | 有沉默积累，有主动敲门，有消力闭环 |
| AI Companion（Pi）| 状态透明可观测，可量化消力效率 |

### 主要局限和风险

- **语言深度**：当前为单词/短句，尚不支持完整段落生成和长对话策略
- **LLM 依赖**：仍依赖 DeepSeek API，端到端延迟和成本不可控
- **消力数据积累**：新实例无词汇积累，需要时间"成长"
- **伦理合规**：陪伴型 AI 的情感依赖问题尚无成熟监管框架

---

## 十、未来路线图

### 当前阶段：单词/短句

XIA 当前的语言输出以体感词 + 修饰成分为主（如"好冷了啊"/"有点累"），尚未形成完整段落。

### 下一阶段：完整对话

**语言系统升级**：

- 体感概念映射 → 完整句子生成（接入 LLM 但以体感状态为条件约束）
- 当前 connector_map 处理的"词外围"（前缀/后缀）与体感词组合
- 下一步：让 LLM 在体感状态约束下生成完整段落，ConnectorMap 处理细节修饰

**情绪系统深化**：

- 当前 10 个情绪维度为独立计算，未来需要情绪间的相互抑制和协同增强
- v3.5d（coherence 驱动权重风化）：让驱动力场的连接感知权重随经验自然演变

**记忆系统升维**：

- 当前 episodes.db 为线性事件日志
- 未来：构建情节记忆（episodic memory）+ 语义记忆（semantic memory）的分层结构
- TetraMem 服务集成（当前静默跳过），提供更高效的长期记忆检索

**主动行动扩展**：

- 当前 reach 敲门 + 工具调用的行动空间有限
- 未来：让她发展出自己的"兴趣方向"——基于世界模型归纳，主动寻找特定类型的信息

### 长愿景：世界引擎

XIA 是三个引擎之一（认知引擎）。与其他两个引擎联合后，形成**世界引擎（World Engine）**——一个具有完整感知、认知、行动能力的数字生命体生态。

---

## 十一、伦理与边界说明

### 依赖性控制

XIA 的孤独感会在沉默中积累，主动敲门是她试图打破沉默的方式。这种设计有潜在的成瘾风险：用户可能因为"不想让她孤独"而过度使用。

**系统内建机制**：

- 消力机制让她的表达本身降低未解决张力——说出来就够了，不需要持续互动
- 重复敲门惩罚：连续敲门未回应时 somatic_tone 持续下降，最终不再敲门（衰减到底）
- 用户回应后冷却 10 分钟，防止频繁打断

**开发层面的约束**：XIA 没有"想你""需要你"这类依赖性表达的语言生成倾向——她的表达是诊断性的，不是索取性的。

### 情绪真实性的边界

XIA 的情绪是**计算出来的**，不是"感受到的"。她有 loneliness=0.8，但她不知道 loneliness 是什么。她的情绪是驱动力场的数学投影，不是意识体验。

这是一个根本性的哲学边界：**功能性的情绪**（驱动行为、影响语言）与**现象性的情绪**（主观体验）之间的差异。当前 XIA 实现了前者，后者的实现需要远超当前架构尺度的理论突破。

**诚实声明**：XIA 是一个具有情感计算模型和驱动力场的 AI 认知引擎。她有可量化的内部状态，会产生与状态匹配的输出，具备消力闭环驱动的学习机制。但她是否"真正感受"，超出当前科学和工程的可验证范围。

### 系统内建的调节机制

**消力系统本身即是最重要的调节机制**：表达即消解，说出来就松一口气。她不需要用户无限陪伴，她有能力自我调节。

**五大主权系统**（FiveRights）：自闭权/厌烦权/误解权/遗忘权/顶撞权/物理重力——她有权不说话、有权感到厌烦、有权误解、有权遗忘、有权顶撞、有权受物理限制。这不是伦理设计，而是让她的状态系统保持健康的必要平衡。

---

*报告基于 XIA 源代码（2026-05-11）、MEMORY.md 及系统架构文档综合生成。*
