# Language System — 语言表达闭环

> **维护人**：每次修改语言系统逻辑后更新此文档
> **最后更新**：2026-05-26

## 职责

将体感锚点转化为可表达的语言，建立**消力反馈闭环**：说出来后 unresolved 真实下降 → 词汇解锁 → 模板固化。

## 六大主权

| 主权 | 触发条件 | 效果 |
|------|---------|------|
| 自闭权 | avoid 高 | 防御性退行，候选窗口收窄 |
| 厌烦权 | 社交疲劳积累 | 候选窗口收窄 |
| 误解权 | — | 镜像学习，建立自己版本的理解 |
| 遗忘权 | 负向关联积累 | 负向记忆进入衰减队列 |
| 顶撞权 | 检测外部侵入 | 拒绝执行次优策略 |
| 物理重力 | fragmentation 高 | 映射为输出参数（节奏/长度/稳定性） |

## 核心机制

### 消力闭环

```
驱动力场
    ↓
体感锚点词（somatic_concept_map）
    ↓
候选生成（candidate_generator）—— 驱动力直接通道 + 策略地图快速路径 + LLM慢速路径
    ↓
打分排序（语义分析）
    ↓
六大主权过滤
    ↓
句子组合（sentence_composer）—— 锚点词 + 修饰词 + 连接词 → 完整句子
    ↓
输出
    ↓
消力测量（quenching_tracker）
    ↓
unresolved 真实下降？→ 词汇解锁（≥3次命中） / 模板学习（高效率模板固化）
```

### 词汇解锁（Word Warmup）

```
小孩学语的自然路径：
  1. 先会说"累"（单字，锚定一个状态）
  2. 验证"累"是对的 → "好累"、"有点累"（加修饰语）
  3. 修饰语也被验证 → "我今天好累"（组合）

命中 ≥3 → 永久解锁，加入 _unlocked_vocabulary
活跃窗口：最近 200 tick 内出现 → 产生变体
长期不用：停止变体注入，但词本身保留
```

### 模板学习

高效表达固化为模板。句子组合器从候选中学习高频组合模式。

## 子模块职责

| 文件 | 职责 |
|------|------|
| `quenching.py` | 消力效率追踪，SNR 计算，脐带脱落判定 |
| `word_warmup.py` | 词汇冷→热解锁，渐进学习路径 |
| `sentence_composer.py` | 锚点词 + 模板 → 完整句子，softmax 采样 |
| `candidate_generator.py` | 三通道候选生成（驱动/策略地图/LLM），主权过滤 |
| `somatic_concept_map.py` | 体感词 ↔ 驱动力场双向映射 |
| `strategy_map.py` | 策略地图（状态对 → 词效率，即时缓存） |
| `thermal.py` | 自适应温控（exploration_window） |
| `mirror.py` | 镜像学习（误解权） |
| `five_rights.py` | 六大主权控制器 |
| `semantic_analyzer.py` | LLM 语义锚点匹配（v1） |
| `abundance_monitor.py` | 语言丰度监测 |
| `meta_cognitive.py` | 元认知分析 |
| `construction_grammar.py` | 构式语法学习 |
| `state_pattern_memory.py` | 内部符号涌现 |
| `stereotype_tree.py` | 定型观念树 |
| `stereotype_learner.py` | 定型观念学习器 |
| `connector_map.py` | 强度前缀/语气词/后缀评分 |
| `source_profiler.py` | 他者建模（familiarity） |
| `reply_motivator.py` | 回复动机注入 |
| `reflection_layer.py` | 反刍层（LLM 深度复盘） |
| `somatic_dictionary.py` | 体感词典 |
| `concept_graph.py` | 概念图谱 |
| `input_packet.py` | 输入数据包 |
| `preoccupation_engine.py` | 执念引擎 |
| `recursive_construction.py` | 递归构式 |
| `reading_acquisition.py` | 阅读获取 |
| `sentence_extraction.py` | 句子提取 |
| `vocabulary_acquisition.py` | 词汇获取 |
| `bge_analyzer.py` | BGE 嵌入分析 |
| `associative_recall.py` | 联想检索 |
| `language_resistance.py` | 语言阻力 |
| `syntax_parser.py` | 句法解析 |
| `seed_map.py` | 种子映射 |
| `interpretation_competition.py` | 解释竞争：张力悬置，连续竞争力计算 |
| `delayed_understanding.py` | 延迟理解：低置信度理解进入 pending 队列待激活 |

## 关键类

| 类 | 文件 | 说明 |
|---|------|------|
| `QuenchingTracker` | quenching.py | 消力效率测量 |
| `StrategyMap` | strategy_map.py | 策略地图（即时缓存层） |
| `ThermalController` | thermal.py | 自适应温控 |
| `MirrorLearner` | mirror.py | 镜像学习 |
| `FiveRightsController` | five_rights.py | 六大主权控制器 |
| `SemanticAnalyzer` | semantic_analyzer.py | LLM 语义锚点匹配 |
| `CandidateGenerator` | candidate_generator.py | 候选生成 |
| `LinguisticAbundanceMonitor` | abundance_monitor.py | 语言丰度监测 |
| `StatePatternMemory` | state_pattern_memory.py | 内部符号涌现 |
| `StereotypeTree` | stereotype_tree.py | 定型观念树 |
| `StereotypeLearner` | stereotype_learner.py | 定型观念学习器 |
| `ConstructionLearner` | construction_grammar.py | 构式学习 |
| `ExperienceCandidate` | interpretation_competition.py | 候选解释（含竞争力计算） |
| `CompetitionResult` | interpretation_competition.py | 竞争结果（含张力悬置状态） |
| `PendingUnderstanding` | delayed_understanding.py | 延迟理解条目 |

## 管线位置

`s06_language` 阶段使用 language_system 输出。
`s07c_language_finalize` 阶段执行消力闭环和模板学习。

## 设计约束

- 全部连续函数：无 if-else，无比较运算符
- softmax 随机采样，不是取最高分——保持表达多样性
- 消力效率 = Δunresolved_before - Δunresolved_after（差值越大越"省力"）
- 参数外置：所有阈值和数量从 param_snapshot 读取
