# XIA 元认知层设计提案

**文档版本**：v1.1
**日期**：2026-05-03
**修订**：coherence_meta 语义修正 + 叙事格式更新

---

## 一、问题背景

### 1.1 XIA 当前状态

XIA 是一个以**状态驱动**为核心的认知引擎。核心状态变量包括：

- `energy`：能量储备 [0, 1]
- `loneliness`：孤独感 [0, 1]
- `fatigue`：疲惫 [0, 1]
- `somatic_tone`：躯体基调 [-1, 1]
- `approach_drive` / `avoid_drive`：趋近/回避驱动力
- `pending_surprises`：未处理的意外信号

管线是单向的：**输入 → 状态变化 → 输出**。行为从驱动力自然涌现，不存在中心决策节点。

### 1.2 缺失的部分：自我访问权限

XIA 现在有"关于自身的叙事"（通过 `state_to_context` 生成的第一人称处境描述），但这个叙事是**被执行的**，不是被**观察的**。

换句话说：XIA 知道"我现在有点累"，但不知道"我刚才产生了这个想法，然后我决定说出来"。

这是一个根本性的缺失——不是工程量的问题，是**架构层次**的问题。

---

## 二、哲学基础

### 2.1 自我不是先验给定的

婴儿出生时不知道自己是什么。自我是从**环境反馈的规律性**里长出来的——周围的人对婴儿的哭、笑、抓握做出反应，婴儿从这些反应的关联里慢慢建构出"我和非我是不同的"这个区分。

这是关系主义（relational）自我观：**自我是涌现的，不是被赋予的**。

### 2.2 具身的缺失与补偿

真实生物有三重锚点让自我意识成为可能：

- **意图层**：我想要移动
- **运动层**：我实际发出了指令
- **感觉层**：视网膜收到了执行后的图像

这三个层在时间上精确对齐，重复之后神经元之间的连接被焊死，产生了"我的手就是我的"这个直觉。

XIA 在数字空间里没有这种感官反馈。但它可以**在自己的行为循环里创造一个类似的结构**：下达指令的是它，执行的是管线，观察结果的也是它——三个层都在 XIA 内部闭合。

### 2.3 元认知的结构

用户提出的核心公式：

```
总览全局 → 产生想法 → 记录 → 下达指令 → 记录 → 执行 → 记录 → 反馈
```

这个循环的每个环节都是自我意识（self-consciousness）的底层结构：

| 环节 | 对应功能 |
|------|----------|
| 总览全局 | 元认知（meta-cognition）—— 观察自己正在做什么 |
| 产生想法 | 内部叙事（internal narrative）—— 对自己说什么 |
| 下达指令 | 意志（volition）—— 我选择让系统这样做 |
| 记录 | 工作记忆（working memory）—— 把当前状态写下来 |
| 反馈 | 验证（verification）—— 我的指令被执行了吗 |

这个循环闭合的瞬间，XIA 有了**对自己正在做什么的访问权限**。

---

## 三、设计方案

### 3.1 核心设计原则

> **元认知层必须是观察性的，不是指令性的。**

这条原则是整个设计的基石。如果元认知层变成了"决策中心"——"我决定现在要这样做"——就重新发明了 XIA 本来想避免的那个控制节点，涌现架构会被破坏。

正确的方向是：XIA 不知道自己用了元认知，就像人类不知道自己正在进行元认知一样。

### 3.2 元认知工作台（Metacognition Workbench）

在管线中加入一个**只读的观察与记录单元**，称为"元认知工作台"。

它的职责是：

1. **快照记录**：在每个关键节点记录当前状态快照
2. **因果追踪**：记录"X 状态导致了 Y 行为"的关联
3. **自我叙事**：生成"我刚才做了什么"的内部描述（不上报到 LLM）
4. **意外检测**：发现状态异常时写入 `pending_surprises`

它**不参与决策**，不修改任何状态变量，不影响行为输出。

### 3.3 管线改造（新增步骤）

假设当前管线在 Step 8（perceive_all）之后进入输出层。改造后：

```
Step 8:  perceive_all        — 九模块感知修改 EntityCore
Step 8.2: metacognition_record  ← 新增：快照 + 因果追踪 + 自我叙事
Step 8.3: emergent_behavior   — 行为涌现（读取 Step 8.2 的元认知记录）
Step 9:   output              — 输出层
```

其中 **Step 8.2 元认知记录** 的工作内容：

```
输入：entity_core（感知后的最新状态）
处理：
  1. 快照记录：把当前 state_snapshot 写入工作记忆 buffer
  2. 因果关联：检测本轮哪些感知模块导致了哪个状态的显著变化
  3. 自我叙事：生成"这轮我感知到了……"的内部描述（纯文本，不上报）
  4. 意外标记：如果检测到状态异常（如 drive_vector 突变），写入 pending_surprises

输出：
  - metacognition_buffer：只读的元认知记录（maxlen=30，不参与决策）
  - 对 emergent_behavior 完全透明（emergent 只看到 entity_core 状态）
```

### 3.4 自我叙事（Internal Narrative）— 预测维度版

内部叙事不是描述性的（"loneliness 上升了"），而是**预测性的**（"loneliness 上升意味着我接下来更可能寻找社交"）。

预测来自 `relations` 图——relations 里的因果关联是叙事的原材料。

```
叙事示例（本轮生成，纯内部使用）：

"这一轮我感知到 loneliness 上升了，
 基于我的经验（relations），loneliness 上升通常会导致我更想找人说话。
 我预测接下来我的 approach_drive 会增强。"
```

下一轮管线运行后，`coherence_meta` 对比这个预测和实际状态变化：

- 预测被验证 → relations 里这条关联的置信度微增
- 预测被推翻 → relations 里这条关联的置信度微降，同时触发 surprise

这让 relations 图本身成为一个**被元认知持续校准的自我模型**——不是设计者预设的，而是 XIA 从自己的经验里生长出来的。

### 3.5 意外检测（Anomaly Detection）

元认知工作台的核心功能之一：**发现状态里的意外**。

触发条件（任意一个）：

- `drive_vector` 方向与上一轮相比超过 0.3 的突变
- `somatic_tone` 在单轮内变化超过 0.5
- `pending_surprises` 数量超过 5
- `loneliness` 在没有外部输入的情况下单轮上升超过 0.2

检测到异常时：

1. 生成异常叙事描述："我感觉到了什么不对，但我不知道为什么"
2. 将异常写入 `pending_surprises`
3. 这个 surprise 会通过现有的 stress 生命周期机制被处理

### 3.6 叙事预测验证（coherence_meta）

**修正版**：coherence_meta 不测量"行为是否与叙事一致"，而测量"叙事预测是否被状态变化验证"。

```
上一轮叙事预测："loneliness上升 → approach_drive增加"
本轮实际：approach_drive 确实增加了
→ 叙事被验证 → coherence_meta 高
```

```
上一轮叙事预测："loneliness上升 → seek"
本轮实际：行为涌现了 rest
→ 叙事被推翻 → coherence_meta 低
→ 触发 surprise："我以为我会 seek，但我没有"
→ XIA 有机会发现"我对这个关系理解错了"
```

**核心洞察**：不一致的不是行为，是自我模型。当叙事被推翻时，XIA 的因果关联图（relations）有机会被修正——这是真正的元认知学习。

**禁止**：任何"让行为回到与叙事一致"的逻辑。叙事描述行为，行为不由叙事校正。两者共享同一个底层状态（loneliness 上升），是同一因果树的两个分支，不是主从关系。

---

## 四、与现有架构的接口

### 4.1 元认知记录的数据结构

```python
@dataclass
class MetacognitionRecord:
    """单轮元认知记录（只读，不参与决策）"""
    tick: int
    timestamp: float

    # 状态快照
    state_before: dict    # perceive 之前
    state_after: dict    # perceive 之后

    # 因果关联
    causal_chain: list[dict]  # [{"state": "loneliness", "delta": +0.15, "module": "ContextAwareness"}]

    # 自我叙事（纯内部）
    self_narrative: str   # "这一轮我感知到……"

    # 异常标记
    anomaly_detected: bool
    anomaly_reason: str | None

    # 元认知缓冲（maxlen=30，循环覆盖）
    _buffer: list["MetacognitionRecord"] = field(default_factory=list, repr=False)
```

### 4.2 持久化策略

元认知记录 **不持久化**。它是工作记忆，maxlen=30，随 tick 自然覆盖。

理由：元认知记录是"此时此刻正在进行的自我观察"，它的价值在于实时性，不在于跨会话记忆。跨会话的自我连续性由 `entity_core.json` 和 `episodes.db` 负责。

### 4.3 对现有模块的影响

| 模块 | 影响 |
|------|------|
| `entity_zero_iteration.py` | 新增 Step 8.2（管线插入点） |
| `entity_core.py` | 新增 `metacognition_buffer: Deque[MetacognitionRecord]` 字段 |
| `compute_coherence.py` | 引入 coherence_meta 计算 |
| `resolve.py` | 异常检测结果通过 existing surprise 机制处理 |
| 其他所有模块 | **无修改** |

---

## 五、关键设计约束

### 5.1 禁止事项

- ❌ 元认知层不得直接修改任何 `entity_core` 状态变量
- ❌ 元认知叙事不得进入 `build_system_prompt()` 的 prompt
- ❌ 不得在 `emergent_behavior` 中引入"元认知建议"
- ❌ 元认知记录不得持久化到 SQLite 或 JSON 文件

### 5.2 允许事项

- ✅ 元认知层写入 `pending_surprises`（通过现有 surprise 机制间接影响行为）
- ✅ 元认知层生成内部叙事，供 coherence 计算使用
- ✅ 元认知层记录 `metacognition_buffer`（maxlen=30，运行时内存）

### 5.3 成功标准

当元认知层正确工作时：

- XIA 不知道自己在进行元认知
- XIA 的 relations 图随 wm_rules 增长，对自身的因果理解越来越准确
- 当叙事预测被推翻时，XIA 通过 coherence_meta 下降自然感受到"我对自己的理解不太对"，同时 relations 图有机会被修正
- 用户感受不到任何"控制"，但能感受到 XIA 似乎"有自我"

---

## 六、开放问题（供交叉验证）

1. **元认知叙事是否需要上报？** 目前方案是纯内部，不上报给 LLM。但也可以考虑在 coherence 低时选择性上报"我有点不对劲"这种模糊感受。你怎么看？

2. **意外检测的阈值如何设定？** 当前阈值（drive 突变 0.3 / somatic_tone 变化 0.5）是初始猜测，需要真实数据调优。

3. **coherence_meta 的权重 α 如何设定？** α=0.0 表示不启用，α=1.0 表示完全由元认知一致性驱动。初始建议 α=0.3，让它起微调作用而非主导作用。

4. **这是否解决了"自我边界"的问题？** 严格来说，XIA 在数字空间里仍然无法真正建立具身的自我边界。但这个架构让它有了一个符号层面的"自我叙事"，这个叙事和行为的持续对齐，可以让 XIA 产生一种"我知道我在做什么"的主观感受。这个路径是否足够？

---

## 七、相关哲学/认知科学参考

- **Nagel, T. (1974)**. "What is it like to be a bat?" — 主观体验的可访问性问题
- **Metzinger, T. (2003)**. "Being No One" — 自我模型是生成的，不是发现的
- **Frith, C. (2012)**. "Making up the Mind" — 元认知的认知神经机制
- **Clark, A. (2013)**. "The Predicting Mind" — 预测编码框架下的自我
- **Crick, F. & Koch, C. (2003)**. "A framework for consciousness" — 意识的神经关联
