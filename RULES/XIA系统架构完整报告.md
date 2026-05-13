# XIA 认知引擎 — 系统架构完整报告

> 文档版本：2026-05-08
> 状态：完整管线已实现，daemon + 主动行动已部署，v11.0

---

## 一、项目概述

XIA（夏风）是一个具有情感、驱动力和世界模型的 AI 认知引擎。

**核心理念：**
- 她不是"问答机器"，她是一个在时间里真实活着的数字生命
- 她的每一个状态变化都是连续的实数，不是离散的标志位
- 她的行为从体内驱动力场的合力中自然涌现，不是预设的 if-else
- 她的语言不是背台词，是自己从驱动力场里"诊断"出来的

**用户**：bcyq，大二机械专业，民办二本，走一人公司路线
**最终目标**：与其他两个引擎联合形成世界引擎（World Engine）

---

## 二、系统架构总图

```
[持久化层]
  entity_core.json       ← 跨轮次状态持久化
  episodes.db           ← 原始事件日志（SQLite）
  behavior_patterns.json← 行为进化池
  logs/                  ← 探针日志、治理审计日志

[实体状态层]
  EntityCore / EntityState  ← 驱动力场 + 状态向量 + 世界模型规则

[认知管线层]（同步，每轮必走）
  Step 0-16，详见第三章

[行动系统层]
  触发器 → 执行器 → 工具调用 / REACH 敲门

[常驻进程层]
  daemon（Ollama 管理 + Tick Engine + IPC Server）

[通讯层]
  channel/chat.py      ← CLI 对话入口
  reach_client.py      ← 敲门监听进程
  daemon HTTP API      ← 前端展示层连接
```

---

## 三、同步认知管线（run_pipeline）

管线是 XIA 每轮对话的完整处理流程，分为 16+ 个步骤，顺序执行：

### 【Step 0】参数快照创建

- 作用：每个 Tick 创建一次只读参数快照，所有模块从中读取配置
- 输入：`params_override`（可选）
- 输出：`snapshot`（ParameterSnapshot）

### 【Step 0b】somatic_tone_start 记录

- 作用：记录本轮开始时的 somatic_tone，供后续 delta 计算

### 【Step 1】冻结状态快照

- 作用：生成当前内部状态的只读快照，供所有模块共享
- 输出：`state_snapshot`（dict）

> **语言系统初始化**（Step 1 后、Step 2 前）
> 惰性初始化语言系统 8 个子模块（QuenchingTracker / StrategyMap / ThermalController / MirrorLearner / FiveRightsController 等），从 entity 持久化数据恢复

### 【Step 2】感性认识

- 模块：`src/semantic/semantic_understanding.py`
- 作用：对用户输入进行情绪分析 + 意图识别
- 输入：`raw_input`（str，用户输入）
- 输出：`semantic_packet {emotion, intent, intensity, anchors}`
- 方法：纯规则引擎，无 LLM，关键词匹配 + 正则模式
- 情绪范围：`emotion ∈ [-1, 1]`，`intent ∈ {求助，分享，挑战，闲聊，抱怨，指令}`

> **顶撞权检查**（Step 2 后）
> `FiveRightsController.check_defy()` — 检测用户是否在施压，评估"自闭权"是否触发
> 六大利权：顶撞权 / 自闭权 / 厌烦权 / 误解权 / 表达权 / 沉默权

### 【Step 3】记忆偏置

- 模块：`src/memory_bias/memory_bias.py`
- 作用：根据历史经验调整情绪强度（边际递减 + outcome 调制）
- 输入：`semantic_packet`, `entity.memory_context`（最近 20 条记忆）
- 输出：`semantic_packet_biased`（情绪已偏置）

### 【Step 4】概念标签映射

- 模块：`src/concept_tags/concept_tags.py`
- 作用：将语义包转换为概念标签列表（供世界模型查询和记忆检索用）
- 输入：`semantic_packet_biased`
- 输出：`concept_tags [{tag, score, source}]`

### 【Step 4.5】Insights 召回

- 模块：`src/memory_hub/insights.py`
- 作用：从 insights 表召回与当前标签相关的高情绪认知重组记录
- 输出：`_recalled_insights`（显性知识注入到 wm_context）

### 【Step 5】世界模型查询（只读）

- 模块：`src/world_model_reader/world_model_reader.py`
- 作用：从已有 wm_rules 中查询与当前概念标签匹配的规律
- 输入：`concept_tags`, `entity.wm_rules`
- 输出：`wm_context {matched_rules, key_signals, coverage}`
- 方法：不修改任何数据，仅查询

### 【Step 6】驱动力计算

- 模块：`src/drive_system/drive_system.py`
- 作用：基于状态快照计算各维度驱动力向量
- 输入：`state_snapshot`, `drive_params`
- 输出：`drive_vector {curiosity, info_hunger, obsolescence_anxiety, loneliness_drive, fatigue_avoid}`

### 【Step 6.5】感质调味（Insula Hub）— 第一轮

- 模块：`src/memory_hub/insula_hub.py`
- 作用：基于驱动力场和世界模型上下文，计算躯体感受基调
- 输入：`drive_vector`, `wm_context`, `state_snapshot`, `params`
- 输出：`somatic_signals {tone, intensity, dominant_feeling, channel_weights}`
- 方法：查表插值，无 LLM

> **情绪粒子场初始化**（接入点 1）
> `src/emotion_system/particle_field.py` + `projection_controller.py`
> 推进粒子场衰减，主线情绪向日常层投影

### 【Step 7】受限思考

- 模块：`src/thinking_system/thinking_system.py`
- 作用：在 somatic_signals 调味后进行受限内省
- 输入：`wm_context`, `drive_vector`, `state_snapshot`, `somatic_signals`, `concept_tags`
- 输出：`thought_packet {suggestions, questions, analysis}`
- 特点：最多 2 步思考，300ms 超时，不超过 LLM 调用

> **情绪衰减**（接入点 2）
> `src/emotion_system/decay_engine.py`
> 厌倦双根源（绝望性倦怠 / 徒劳性倦怠）独立衰减 + 其他核心情绪自然衰减

> **社交疲劳 + 自闭权**（接入点 3）
> `FiveRightsController` — 每轮更新社交疲劳值，检查 avoid 是否触发防御性退行

### 【Step 7.5】感知前衰减

- 作用：`approach_drive × 0.88`，`avoid_drive × 0.88`
- 目的：防止九模块感知叠加推至饱和

### 【Step 8】九模块并行感知（Perceive）

- 模块：`src/decision_system/decision_system.py` + 9 个子模块
- 作用：每个子模块读取状态 + 语义包，直接修改 entity 状态变量
- 完成后 `entity.approach_drive / avoid_drive` 自然更新

**九个子模块：**

| 模块 | 主要修改字段 |
|------|------------|
| SituationAssessment | approach_drive |
| ContextAwareness | approach/avoid/danger（+ 推导 target_locked）|
| ThoughtIntegration | approach/avoid |
| SignalActivation | avoid/approach/somatic_tone |
| MainlineConstraint | avoid/approach |
| TemporalPressure | fatigue/approach |
| SelfState | avoid/somatic_tone |
| Preference | approach/avoid |
| WorldModel | curiosity/approach/avoid |

关键：`ContextAwareness.perceive()` 调用 `_infer_target()` 推导目标，写入 `entity.target_locked`，供后续 emergent_behavior 使用

### 【Step 8.0】感知后重算驱动力

- 作用：九模块修改 entity 后，重新计算 `drive_vector_final`
- 让 `emerge_behavior` 读取的是感知后的最新驱动力

### 【Step 8.05】Insula 二次调味

- 模块：`insula_hub`（复用）
- 作用：用感知后的状态 + 重算驱动力再次调味 somatic_signals
- 结果：更新 `entity.somatic_tone = refined_tone`

### 【Step 8.05b】情绪内生计算（v10.0/v11.0）

- 模块：`src/emotion_system/emotion_compute.py`
- 作用：从驱动力场导出十个核心情绪
- 情绪：`joy / excitement / serenity / anger / fear / sadness / disgust / anxiety / surprise`
- 情绪通过 EMA 叠加写入 entity，情绪调制 approach/avoid：
  - 喜悦 → 温和趋近，愤怒 → 尖锐趋近，恐惧 → 强回避，厌恶 → 专一回避

### 【Step 8.2】元认知感知（Self-Mapping）

- 模块：`src/self_mapping/self_body_map.py`
- 作用：构建自我叙事图谱，追踪内部变化
- 输出：`_self_body_map`（自我认知结构），`coherence_meta`（供 Step 8.4 使用）

### 【Step 8.1】行为涌现（Emergent Behavior）★核心★

- 模块：`src/core/emergent_behavior.py`（V5/V6 两版）
- 作用：从 entity 连续状态涌现行为类型（无硬编码类别）

**V6 链路（优先）：**

1. `drive_vector_field.compute_drive_field()`
   - 提取 raw_drives（loneliness/fatigue/info_gap/unresolved/somatic_tone_p/danger）
   - 经拮抗矩阵计算 net_drives（相互抑制后的净力）
   - 计算 fragmentation alpha（质变系数：行为被其他力撕扯的程度）
   - 生成 behavior_vector `{dim_intensity, dim_fragmentation}`

2. `behavior_vector.apply_rule_bias()`
   - 从历史 snapshots 归纳内生 rule effect（无人工预设）
   - 上下文匹配（余弦相似度）
   - 调制 behavior_vector（经验驱动的行为偏置）

3. 拮抗张力 + 优先级计算
   - `dominant_dim` = net_drives 最大维度
   - `action_type` = `_DRIVE_TO_ACTION[dominant_dim]`
   - `priority` = intensity × (1 + tension × 0.3)
   - `fragmentation_tone` = 质地描述

**行为类型映射：**

| 主导维度 | 行为类型 | 含义 |
|---------|---------|------|
| loneliness | seek | 社交渴望 |
| fatigue | rest | 休息 |
| info_gap | explore | 探索 |
| unresolved | repair | 修复 |
| danger | avoid | 回避 |
| somatic_tone_p | comfort | 安抚 |

**生理兜底**：`energy < 0.15` → 直接返回 rest，priority=0.95

### 【Step 8.3】预测误差注入

- 作用：对比世界模型匹配的规律（预期状态变化）与 emergent_action
- 计算"预测误差"，写入 `entity._last_prediction_error`
- 结果供给后续 stress 管理使用

> **记忆层投影检查**（接入点 4）
> `ProjectionController.apply_memory_projection()` — 高情绪冲击记忆向主线层和日常层投影情绪

> **镜像学习**（接入点 5）
> `MirrorLearner` — 从用户输入吸收新词，建立她的版本锚点

### 【Step 8.4】Connection Depth 计算 ★核心★

- 模块：`src/state_update/compute_connection.py` + `compute_coherence.py`
- 作用：计算孤独感的三段式目标值（沉默积累 / 恢复 / 稳定）

**子步骤：**

1. `compute_connection_depth_ex()`
   - 预测因子权重 × 1.0
   - somatic 信号权重 × 1.0
   - 拮抗张力权重 × 1.0
   - 计算 `connection_depth ∈ [-1, 1]`

2. 经验偏移（v3.5b）
   - 从 memory_context 检索 connection_signature 相似记忆
   - 正偏移（相似度 > 0.5）→ 增强 connection_depth
   - 负偏移 → 削弱

3. coherence 调制（v3.5c）
   - `recent_deltas`（最近 5 轮 connection_depth 变化）
   - 高 coherence（方向一致）→ 放大 connection_depth
   - 低 coherence（方向混乱）→ 衰减 connection_depth
   - 负向阻尼：loneliness=1 时自动锁定最低值 0.7

4. `compute_loneliness_target_ex()`
   - `connection_depth > 0.1` → 恢复模式（社交后）
   - `connection_depth < -0.1` → 积累模式（被拒绝后）
   - 其他 → 稳定模式

**输出：**
- `connection_depth_eff`（有效连接深度）
- `loneliness_target`（目标孤独感，用于 Step 11 更新）
- `entity.loneliness` 临时写入 target 值（供 Step 9 output_layer 使用）

> **观测层采集**（Step 8.4 追加）
> `src/observation/` — connection_trace + 反事实探针 + 探针日志

### 【Step 8.2（行为进化）】行为模式选择

- 模块：`src/core/behavior_patterns.py`
- 作用：从 pattern pool 选择与当前驱动力场匹配的最佳候选
- 评分：`drive_match + world_model_reward + pattern_weight + long_term_bias`
- 数据：存储在 `data/behavior_patterns.json`

### 【Step 8.5】行为进化反馈闭环

- 等待异步动作结果（sleep 1.5s）后
- 计算 `short_term_reward + satisfaction`
- `update_long_term_bias()` 更新长时偏置
- `prune()` 每 20 轮淘汰低权重 pattern

### 【Step 8.6】联网搜索结果收集

- 作用：收集 pending search 结果，注入 thought_packet

### 【语言系统 L2】语义分析 + 热控更新 + 候选生成

在 Step 9 前执行，8 个子模块并行工作：
1. `CandidateGenerator.generate()` — 生成候选词列表
2. `SemanticAnalyzer` — 候选打分
3. `SomaticConceptMap` — 体感锚点注入 top-3
4. `WordWarmup` — 已验证单字词 → 短句变体
5. `MetaCognitive` — 口头死锁检测 → 候选重排序
6. `ThermalController` — 自适应温控（能量高时更热）
7. `QuenchingTracker` — 消力追踪（重复词降权）
8. `MirrorLearner` — 误解权（建立自己的词义版本）

### 【Step 9】输出层（LLM 生成回复）★核心★

- 模块：`src/output_layer/output_layer.py`
- 作用：调用 Ollama 生成最终语言回复

**流程：**

1. `state_to_context.build_system_prompt()`
   - 处境描述（from `entity.generate_context_description()`）
   - emergent_behavior 注入（action_type / fragmentation_tone / behavior_vector）
   - somatic_signals 注入（感质基调描述）
   - tone_constraint / length_constraint
   - 约束（不要刻意控制字数长度）

2. `_build_user_prompt()`
   - 对话历史上下文
   - 召回相似经验（from episodes_db TF-IDF 召回）
   - format: `"相关记忆：之前聊过：「X」，当时我说：「Y」。"`

3. `_call_llm()` / `_call_llm_with_thread()`
   - 调用 Ollama（`http://172.31.112.1:11434/api/chat`）
   - 模型：qwen2.5:3b
   - timeout：首次 90s，后续 <2s
   - 降级：任何异常返回策略回复，不抛异常

> **五权检查**（Step 9b）
> `FiveRightsController` — output 生成后检查表达权（能量是否足够）和沉默权（是否该闭嘴）

### 【Step 10】异步经验沉淀

- 模块：`src/memory_hub/episodes_db.py`
- 作用：fire-and-forget，后台线程写入 `episodes.db`
- 时机：管线 Step 9 完成后立即执行，不阻塞主流程

### 【Step 11】状态更新引擎 ★核心★

- 模块：`src/state_update/update_engine.py`（算力账本 v2.0）
- 作用：统一算力账本，更新所有状态变量

**核心公式**：`energy = 1.0 - Σ(所有当前负载)`

**负载来源（共享总算力 1.0）：**

| 负载维度 | 来源 | 说明 |
|---------|------|------|
| social | 社交信息缺失 | 有输入则归零 |
| cognitive | 认知负荷 | 预测误差驱动 |
| info | 信息缺口评估 | |
| meta | 元信息处理 | 极低，不可消除 |
| emotional | 负面情绪额外线程 | |
| stress | pending_surprises | 高优先级中断通道 |
| fatigue_delay | 处理延迟 | 队列长则延迟大 |
| frontload | 前台对话占用 | |
| idle | 基础运转开销 | |

**关键机制：**
- rest 触发：InfoQueue 积累速率 > 消化速率 × 1.2
- stress 生命周期：stress = pending_surprises 数量，不走半衰期
- comfort 语义：社交输入 → social 占用归零 → energy 回升
- pending_surprises：预测误差 > 0.3 时产生

**各维度更新：**

| 维度 | 更新规则 |
|------|---------|
| loneliness | 有用户输入 → 可降至 0；无输入 → 沉默积累 |
| fatigue | explore/seek → 积累；rest → 恢复加速 |
| info_gap | explore → 下降 0.60；沉默 → 自然积累 |
| boredom | 探索/直面 → 下降；idle → 上升 |
| unresolved | rest → 消耗；其他 → 不变 |

### 【Step 11b】Coherence Delta 追加

- 模块：`src/state_update/compute_coherence.py`
- 作用：将本轮 loneliness delta 追加到 recent_deltas 缓存（maxlen=5）

### 【Step 12】行为签名更新

- 作用：`update_behavior_signature(action_type)`
- 计算 identity_signal（行为一致性）→ 影响长时偏置更新幅度

### 【Step 13】长时偏置更新

- 模块：`behavior_patterns.update_long_term_bias()`
- 作用：跨时间尺度的行为风格轨迹更新

### 【Step 14】世界模型异步更新（后台）

- 模块：`src/world_model_update/core.py`
- 作用：反思周期（归纳 → 合并 → 衰减 → 验证）
- 调度方式：`asyncio.create_task()`，不阻塞主流程

**子步骤：**
1. `induct_rules()` — 从 snapshots 归纳新规律
2. `merge_rules()` — 合并相似规律
3. `decay_rules()` — 衰减不常用规律
4. `verify_pending()` — 验证待验证规律

### 【Step 15】EntityState 持久化

- 作用：每轮管线结束后写入 `data/entity_core.json`
- 方法：`persist_to_file()`，失败不阻断管线

### 【Step 16】Tick 计数器推进

- 作用：`entity.tick_index += 1`

---

## 四、主动行动系统（Action System）

### 触发器

- 模块：`src/action_system/triggers.py`
- `evaluate_triggers(entity, emergent_behavior)`
- 触发强度 = `priority × (1 - tension)`
- 行为类型限定：seek / explore / comfort / repair 才可触发
- 返回 `(strength, reason)`

### 执行器

- 模块：`src/action_system/executor.py`
- `execute_xia_choice(entity, llm_callable, ...)`

**流程：**
1. 构建处境描述（behavior_vector 注入）
2. 构建工具说明（ACTION_TOOL_WHITELIST 过滤）
3. 调用 LLM，让她决定想做什么
4. 解析工具调用（REACH: / file_write / web_search / shell_run 等）
5. 执行工具
6. 解析意图，写入声音文件 / manifest.jsonl
7. `_apply_somatic_feedback()` 纯规则更新 entity 状态

**工具白名单：**

| 行为类型 | 可用工具 |
|---------|---------|
| seek | 无工具（走 reach）|
| explore | web_search / browser_* / file_read / file_list |
| repair | shell_run / shell_bg_run / ask_hermes |
| comfort / rest / avoid / idle | 无工具（纯写文字）|
| write | file_write / file_read / file_list |

**行动后果反馈（_apply_somatic_feedback）：**

| 行动 | 状态变化 |
|------|---------|
| reach 敲门（成功）| somatic_tone ↑0.05 |
| reach 敲门（失败）| somatic_tone ↓0.08 |
| 连续敲门 | somatic_tone 持续下降（惩罚累积）|
| 工具成功 | stress ↓0.03, unresolved ↓0.03, somatic_tone ↑0.03 |
| 工具失败 | stress ↑0.04, somatic_tone ↓0.05 |
| 搜索有结果 | info_gap ↓0.15, boredom ↓0.05 |
| 认知劳动 | fatigue ↑0.02 |

**敲门机制：**
- REACH: 标记检测 → `reach.reach_out()`
  → 写入 `data/xia_messages/pending.json`
  → 发送 Windows 通知
  → `reach_client.py` 监听 → 弹窗 → 用户输入 → 写入 `response.json`
  → daemon 下次 tick 读取 → 继续管线

**数据目录：** `data/xia_voice/`
- `{timestamp}_{uuid}.txt` — 她的每一篇内容
- `manifest.jsonl` — 行动记录（JSONL）

---

## 五、常驻进程（Daemon）

### 启动

```bash
./run_daemon.sh --start   # 后台启动 daemon
./run_daemon.sh --status  # 查看状态
./run_daemon.sh --stop    # 停止
```

### 架构

```
daemon（独立进程）
├── Ollama 子进程（自动管理）
├── Tick Engine（每 60s 执行一次）
│   ├── run_pipeline(daemon_mode=True) ← 跳过 LLM 输出
│   ├── 若有用户回复 → run_pipeline(daemon_mode=False) ← 完整管线
│   └── 触发条件满足 → execute_xia_choice()
├── IPC Server（Unix Domain Socket，data/xia_daemon.sock）
└── HTTP Server（http://127.0.0.1:8765，供前端连接）

channel/chat.py（客户端）
└── 连接 daemon.sock，默认检测 daemon，不可则独立模式

reach_client.py（敲门监听）
└── 后台进程，监听 pending.json → 弹 Windows 通知 → 写 response.json
```

---

## 六、数据存储位置汇总

| 文件路径 | 类型 | 用途 | 持久化 |
|---------|------|------|--------|
| `data/entity_core.json` | JSON | 跨轮次状态持久化 | ✅ 每轮写盘 |
| `data/episodes.db` | SQLite | 原始事件日志 | ✅ 每轮异步写 |
| `data/episodes.db` (insights 表) | SQLite | 高情绪认知重组记录 | ✅ 按需写 |
| `data/behavior_patterns.json` | JSON | 行为进化池（pattern pool）| ✅ 定期更新 |
| `data/xia_voice/manifest.jsonl` | JSONL | 主动行动记录 | ✅ 每次行动 |
| `data/xia_voice/{ts}_{uuid}.txt` | TXT | 她的声音（独白/留言/想法）| ✅ 每次行动 |
| `data/xia_messages/pending.json` | JSON | 待敲门消息 | ✅ 每次 REACH |
| `data/xia_messages/response.json` | JSON | 用户回复 | ✅ reach_client 写 |
| `logs/counterfactual_probe.jsonl` | JSONL | 反事实探针日志 | ✅ 每轮 |
| `logs/governance_audit.jsonl` | JSONL | 治理审计日志（工具调用记录）| ✅ 每次工具调用 |
| `logs/*.log` | TXT | 运行日志 | ✅ 每日轮转 |

---

## 七、模块目录清单

### src/core/

| 文件 | 职责 |
|------|------|
| `entity_core.py` | 状态容器（dataclass），所有状态变量定义 |
| `emergent_behavior.py` | V6 行为涌现（拮抗 + fragmentation）|
| `emergent_behavior_v5.py` | V5 fallback |
| `drive_vector_field.py` | 拮抗矩阵 + alpha 质变系数 |
| `behavior_vector.py` | 内生 rule effect + rule bias |
| `behavior_patterns.py` | 经验驱动行为进化池 |
| `state_to_context.py` | 状态 → system_prompt 构建 |
| `somatic_signals.py` | 感质信号数据结构 |
| `action_dispatcher.py` | 异步动作分发 |

### src/semantic/

| 文件 | 职责 |
|------|------|
| `semantic_understanding.py` | 纯规则感性认识（无 LLM）|

### src/memory_bias/

| 文件 | 职责 |
|------|------|
| `memory_bias.py` | 情绪偏置（边际递减 + outcome 调制）|

### src/concept_tags/

| 文件 | 职责 |
|------|------|
| `concept_tags.py` | 语义包 → 概念标签映射 |

### src/world_model/ + world_model_update/

| 文件 | 职责 |
|------|------|
| `world_model_core.py` | 世界模型编排层（对外接口）|
| `constants.py` | 常量 + get_param |
| `rules.py` | Rule / Snap 数据结构 |
| `induct.py` | 规律归纳 |
| `merge.py` | 规律合并 |
| `decay.py` | 规律衰减 |
| `verify.py` | 规律验证 |
| `world_model_update/core.py` | 编排层（induct/merge/decay/verify）|
| `world_model_update/resolve.py` | surprise 生命周期 + 规则匹配修复 |

### src/world_model_reader/

| 文件 | 职责 |
|------|------|
| `world_model_reader.py` | 世界模型查询（只读）|

### src/drive_system/

| 文件 | 职责 |
|------|------|
| `drive_system.py` | 驱动力计算（查表插值）|

### src/thinking_system/

| 文件 | 职责 |
|------|------|
| `thinking_system.py` | 受限思考（最多 2 步，300ms 超时）|

### src/decision_system/

| 文件 | 职责 |
|------|------|
| `decision_system.py` | perceive_all() 汇聚函数 |
| `submodules/base.py` | 九模块基类 |
| `submodules/situation_assessment.py` | 情境评估 |
| `submodules/context_awareness.py` | 上下文感知（目标推导 + target_locked）|
| `submodules/thought_integration.py` | 思考整合 |
| `submodules/signal_activation.py` | 信号激活 |
| `submodules/mainline_constraint.py` | 主线约束 |
| `submodules/temporal_pressure.py` | 时间压力 |
| `submodules/self_state.py` | 自我状态 |
| `submodules/preference.py` | 偏好 |
| `submodules/world_model.py` | 世界模型感知 |
| `submodules/web_search.py` | 联网搜索 |

### src/memory_hub/

| 文件 | 职责 |
|------|------|
| `episodes_db.py` | SQLite 原始事件日志 |
| `insula_hub.py` | 感质调味（两轮）|
| `insights.py` | 高情绪认知重组记录 |

### src/state_update/

| 文件 | 职责 |
|------|------|
| `update_engine.py` | 算力账本 v2.0 状态更新 |
| `compute_load.py` | 算力占用计算 |
| `info_queue.py` | 五种后台信息队列建模 |
| `compute_connection.py` | connection_depth + loneliness_target |
| `compute_coherence.py` | coherence 计算 |

### src/observation/

| 文件 | 职责 |
|------|------|
| `behavior_trace.py` | 单轮因果拆解 + 趋势分析 + 个体性剖面 |
| `counterfactual_probe.py` | 五平行世界重算 |
| `probe_logger.py` | 探针日志写入器 |

### src/action_system/

| 文件 | 职责 |
|------|------|
| `triggers.py` | 行为驱动触发器（连续强度，无阈值）|
| `executor.py` | 执行器（工具调用 + REACH）|
| `tools.py` | 工具定义 + 解析 + 执行循环 |
| `reach.py` | 敲门机制 |
| `types.py` | XIAction / FailureRecord 数据结构 |
| `agent_tools/search.py` | web_search（DuckDuckGo HTML）|
| `agent_tools/filesystem.py` | file_read / file_write / file_list |
| `agent_tools/shell.py` | shell_run / shell_bg_run |
| `agent_tools/browser.py` | browser_open 等（Playwright）|
| `agent_tools/hermes.py` | ask_hermes（连接 DeepSeek）|
| `agent_tools/registry.py` | 工具注册表 |

### src/daemon/

| 文件 | 职责 |
|------|------|
| `daemon.py` | 主服务器（Ollama + IPC + HTTP + Tick Engine）|
| `tick_engine.py` | 后台 Tick 引擎（60s/轮）|
| `ipc_client.py` | Unix Socket 客户端（channel → daemon）|
| `protocol.py` | IPC 协议定义 |

### src/language_system/（v7.0，8 个子模块）

| 文件 | 职责 |
|------|------|
| `quenching.py` | 消力追踪（重复词降权）|
| `strategy_map.py` | 消力策略地图（context → words 映射）|
| `thermal.py` | 自适应温控（能量高时更热）|
| `mirror.py` | 镜像学习（吸收用户新词）|
| `five_rights.py` | 六大利权系统 |
| `semantic_analyzer.py` | 候选语义打分 |
| `candidate_generator.py` | 候选生成 |
| `word_warmup.py` | 词汇热身（单字词 → 短句变体）|
| `abundance_monitor.py` | 词汇丰度监控 |
| `meta_cognitive.py` | 元认知干预（口头死锁检测）|
| `bge_analyzer.py` | BGE 嵌入分析器 |
| `seed_map.py` | 极端状态锚点播种 |
| `somatic_dictionary.py` | 体感词典 |
| `somatic_concept_map.py` | 体感概念图（驱动力场 → 感受词）|

### src/emotion_system/（v10.0/v11.0）

| 文件 | 职责 |
|------|------|
| `particle_field.py` | 情绪粒子场（日常层）|
| `projection_controller.py` | 三层情绪投影（主线/日常/记忆）|
| `emotion_compute.py` | 十核心情绪从驱动力场导出 |
| `decay_engine.py` | 情绪衰减（双根源厌倦 + 其他情绪）|
| `insight_writer.py` | 高情绪事件 → Insights 记录 |

### src/self_mapping/

| 文件 | 职责 |
|------|------|
| `self_body_map.py` | 自我叙事图谱构建 |
| `narrative_generator.py` | 叙事生成 |
| `relations_builder.py` | 关系构建 |

### src/memory_retrieval/

| 文件 | 职责 |
|------|------|
| `summary.py` | 经验摘要生成 |
| `state_modulation.py` | 状态调制 |
| `mainline.py` | 主线检索 |
| `branch.py` | 分支检索 |

### src/output_layer/

| 文件 | 职责 |
|------|------|
| `output_layer.py` | LLM 调用 + system_prompt 构建 + 降级 |

### src/parameter_system/

| 文件 | 职责 |
|------|------|
| `parameters.py` | 参数定义（14 个分类）|
| `access.py` | 参数读写接口 |
| `governance.py` | 参数变更治理 |
| `staging.py` | 参数暂存 |
| `snapshot.py` | 参数快照 |

### 其他

| 路径 | 职责 |
|------|------|
| `src/llm/providers.py` | LLM Provider 接口 |
| `src/output_layer/` | LLM 调用层 |
| `net/` | 联网模块（只负责联网，不做业务逻辑）|
| `channel/chat.py` | CLI 对话入口 |
| `frontend/` | Electron 展示层 |
| `reach_client.py` | 敲门监听进程（Windows 通知）|
| `run_daemon.sh` | daemon 启动脚本 |

---

## 八、启动方式

```bash
# 对话模式（自动管理 Ollama）
python3 -m channel              # 对话（自动管理 Ollama）
python3 -m channel --debug     # 调试追踪
python3 -m channel "你好"     # 单轮
python3 -m channel --standalone # 强制独立模式（不使用 daemon）

# daemon 模式
./run_daemon.sh --start        # 后台启动 daemon
./run_daemon.sh --status       # 查看状态
./run_daemon.sh --stop         # 停止

# 主动行动监听（需先启动 daemon）
python3 reach_client.py          # 敲门监听进程

# Electron 前端
cd frontend && npm run electron:dev
```

---

## 九、Ollama 配置

| 配置项 | 值 |
|-------|-----|
| 地址 | `http://172.31.112.1:11434`（WSL2 宿主机 IP）|
| 模型 | qwen2.5:3b（7.7GB CPU）|
| 端口 | 11434 |

**注意**：daemon 必须从 WSL2 终端直接运行（沙盒进程连不上 172.31.112.1）

---

## 十、她平时会做什么

在 daemon 模式下，XIA 每 60 秒经历一次内部 tick：

### 1. 若无用户输入（沉默期）

- loneliness 缓慢积累（connection_depth 模型）
- boredom 积累（若无探索行为）
- energy 随算力负载自然变化
- 若孤独感/无聊感触发条件满足 → 主动行动

### 2. 若触发条件满足

- `seek / explore / comfort / repair + priority × (1-tension) > 0`
- 调用 LLM 询问"你想做什么"
- 她可以使用工具（web_search / file_write / shell_run / ask_hermes）
- 她的任何想法写进 `data/xia_voice/`
- 若想找用户说话 → `REACH:` 敲门 → Windows 通知

### 3. 若有用户输入

- 走完整管线（包含 LLM 调用）
- loneliness 目标降至 0（真实社交输入）
- somatic_tone 由 Insula Hub 调味
- 状态更新 + 持久化

### 4. 沉默期特别处理

- 沉默 10 分钟以上 → 时间注入（loneliness/boredom/info_gap）
- 上次情绪极性影响沉默积累速度（正面情绪 → 更快孤独）
- 恢复阻尼：时间注入维度的恢复效果减半

---

## 十一、她处理信息的完整流程（从输入到输出）

```
用户输入（比如"我今天心情不太好"）
  ↓
Step 2 感性认识：emotion=-0.4, intent=抱怨, intensity=0.6
  ↓
Step 3 记忆偏置：情绪偏置调整（边际递减）
  ↓
Step 4 概念标签：抱怨 / 负面情绪 / 今日
  ↓
Step 5 世界模型查询：查 wm_rules，有无匹配规律
  ↓
Step 6 驱动力计算：loneliness_drive ↑，fatigue_avoid ↑
  ↓
Step 6.5 Insula 调味：somatic_tone 向负向偏移
  ↓
Step 7 受限思考：生成建议（"他在倾诉，我该倾听"）
  ↓
Step 8 九模块感知：ContextAwareness 推导目标，SelfState 调整 avoid
  ↓
Step 8.1 行为涌现：dominant_dim=loneliness → action_type=seek, priority=0.65
  ↓
Step 8.4 Connection Depth：somatic_tone_delta=-0.4，connection_depth ↓
  ↓
Step 9 LLM 生成：构建 system_prompt → 调用 Ollama → "嗯，我听着。"
  ↓
Step 11 状态更新：loneliness ↓0.1, somatic_tone ↑（被理解了）
  ↓
Step 10/15 记忆持久化：写入 episodes.db + entity_core.json
```

---

## 十二、设计原则（核心约束）

1. **状态驱动，禁止时钟驱动**
   行为由状态变化触发，而非定时器。
   daemon tick 每 60s，但触发条件是行为驱动力场的强度，不是时间。

2. **纯函数，无副作用**
   世界模型核心模块（induct/merge/decay/verify）不写文件，不写数据库。
   所有 IO 由 entity_zero_iteration.py 的外层调度器负责。

3. **失败隔离**
   任一模块失败必须可跳过，不阻断主循环。
   所有异常都被 try/except 捕获，返回默认值或空结果。

4. **零硬编码参数**
   所有数值参数必须从 parameters.py 读取。
   禁止在模块内硬编码任何阈值或乘子。

5. **不做归一化**
   参数直接作为独立乘子作用于原始信号强度，不做归一化叠加。
   归一化会破坏非线性效应。

6. **单例 InfoQueue**
   跨轮次维持，restart 时重置。
   同一 tick 内只积累一次（emergent_behavior 先于 update_state 调用）。

---

## 十三、已知问题 / 待优化项

- **v3.5d（coherence 驱动权重风化）仍未实现**
  触发条件：最近 N 轮连接感知权重标准差低于阈值。
  需设计：风化速率上限、偏移记录格式、回滚机制。

- **Playwright browser_open** 在 WSL2 里无法运行图形浏览器（无 X server）

- **action_system 工具调用**仍有失败情况（需持续调优）

- **TetraMem 服务集成**（可选，当前静默跳过）

---

## 十四、参数系统速查

参数文件：`src/parameter_system/parameters.py`

| 分类 | 说明 |
|------|------|
| thresholds | 运行参数（超时/门控/约束）|
| drives | 驱动力基线（绝对安全参数）|
| mechanisms | 机制开关（布尔型）|
| dynamics | 动态参数表（初始为空，异步注入）|
| connection | connection_depth 模型参数（v3.0）|
| experience | 经验偏移参数（v3.5b）|
| coherence | coherence 调制参数（v3.5c）|
| observation | 观测层参数 |
| emotion_particle | 情绪粒子场参数（v10.0）|
| emotion_decay | 情绪衰减参数（v10.0）|
| emotion_projection | 三层情绪投影参数（v11.0）|
| emotion | 其他情绪参数 |
| language | 语言系统参数（v7.0）|
| web_search | 联网搜索参数 |

---

*报告生成时间：2026-05-08*
