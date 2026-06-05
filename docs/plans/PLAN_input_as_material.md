# 计划：输入重定位为材料（Input as Material）

**背景对话结论（2026-05-28）**

当前架构有一个根本性的错误假设：
> 用户输入必须影响 XIA 的内部 drive 状态。

这个假设导致了 s02b_input_drive_map 把输入文本强制映射到 drive 空间，
s03_think 的软混合进一步把这个映射混入思考方向。

正确的模型是：

**输入 = 材料。**  
材料是被加工的对象，不是改变加工动力的原因。  
她的内部 drive（curiosity、loneliness 等）决定她是否"注意"这些材料、怎么处理它们。  
材料本身不改变 drive。

输入不局限于对话——阅读材料、环境信号都是材料。  
区别只是**对话输入引起说话的概率更高**，不是处理机制本质不同。

---

## 当前状态（开始执行前确认）

### 已做但需要撤销的改动
- `E:\XIA\src\pipeline_runner\stages\s03_think.py`  
  在第 19-23 行加了两个常量：
  ```python
  INPUT_DRIVE_BLEND_SCALE: float = 0.3
  INPUT_DRIVE_BLEND_MAX: float = 0.25
  ```
  在调用 `thinking_think()` 前加了约 15 行软混合逻辑（将 _input_drive_map["drive_vector"] 混入 drive_vector）。  
  **这整块要撤掉。**

### 不需要撤销但需要重新定位的模块
- `E:\XIA\src\pipeline_runner\stages\s02b_input_drive_map.py`  
  三层映射（somatic keyword / BGE / drive space）产出的信息是有价值的，  
  但它们应该是"对输入材料的描述"，不应该直接改变 drive。  
  **不删除，重新定位产出的用途。**

### 保持不变的部分
- `E:\XIA\src\pipeline_runner\stages\s02b_input_drive_map.py` 的计算逻辑本身
- SPM（State Pattern Memory）符号和 named_as（暂时作为脚手架保留）
- 语言输出层（s06_language 等）
- reading_source.py（library 材料的处理，本来就是正确的材料处理模式）

---

## 三步计划

### 步骤一：撤销 s03_think 的软混合（最小改动）

**文件**：`E:\XIA\src\pipeline_runner\stages\s03_think.py`

**具体操作**：
1. 删除文件头的两个常量：
   ```python
   # 删除这两行
   INPUT_DRIVE_BLEND_SCALE: float = 0.3
   INPUT_DRIVE_BLEND_MAX: float = 0.25
   ```

2. 恢复 think() 调用之前的状态，删除软混合块（从 `# ---- 输入驱动软混合 ----` 到 `_thinking_drive` 那段），  
   恢复为直接用 `drive_vector`：
   ```python
   thought_packet = thinking_think(
       wm_context, drive_vector, state_snapshot, thinking_params,
       somatic_signals, entity_state=entity, concept_tags=concept_tags,
       attention_weights=_attn_weights,
   )
   ```

**完成标志**：s03_think.py 里没有 `INPUT_DRIVE_BLEND` 字样，think() 接收原始 drive_vector。

---

### 步骤二：重新定位 s02b 的产出为 input_context

**设计**：

s02b 的产出（SPM 共鸣分数、somatic hits、BGE 最佳符号）保留，  
但把它们包装成 `ctx.input_context`（不是 drive delta，是"这段输入材料在 drive 空间的标签"）。

`input_context` 的结构：
```python
{
    "text": str,                    # 原始输入文本
    "spm_resonance": dict,          # {symbol: score}，这段材料和哪些内部符号共鸣
    "best_symbol": str | None,      # 共鸣最强的符号
    "best_similarity": float,       # 共鸣强度
    "somatic_hits": list,           # 体感词命中
    "layers_used": list,            # 哪些层参与了
}
```

**文件**：`E:\XIA\src\pipeline_runner\stages\s02b_input_drive_map.py`

**具体操作**：
1. 在 `run_input_drive_mapping()` 函数末尾，新增：
   ```python
   ctx.input_context = {
       "text": str(ctx.raw_input or ""),
       "spm_resonance": all_resonances,
       "best_symbol": map_result.get("best_symbol"),
       "best_similarity": map_result.get("best_similarity", 0.0),
       "somatic_hits": map_result.get("somatic_hits", []),
       "layers_used": map_result.get("layers_used", []),
   }
   ```
2. 保留 `ctx._input_drive_map` 和 `ctx._spm_resonance`（其他地方还在用），  
   只是**新增** `ctx.input_context`，不删除已有字段。

**完成标志**：pipeline context 里有 `input_context` 字段，包含对输入材料的标签描述。

---

### 步骤三：让 think() 以 drive 为引导处理 input_context

**设计原则**：

```
drive 高的维度 → 她对相关方向的材料更"敏感"
input_context 描述了这段材料的方向
两者对齐程度 → 决定这段材料能引发多少"注意"
注意 ≠ drive 改变，注意 = 思考时倾向于以这段材料为素材
```

**具体机制**：

在 `think()` 里，接收 `input_context` 作为可选参数。  
当某个维度既是活跃 drive 维度，又在 input_context 的 spm_resonance 里有高分，  
则该维度对应的焦点规则优先级提升（连续函数，不用 if/else）：

```python
# 伪代码
resonance_score = input_context.get("spm_resonance", {}).get(best_symbol, 0.0)
# 活跃维度和材料方向的对齐度，作为规则优先级的调制因子
# 不改变 drive_vector，只影响 focal_rules 的选择权重
alignment = drive_on_this_dim * resonance_score  # 连续，无阈值
focal_rule.priority *= (1.0 + alignment * MATERIAL_ATTENTION_SCALE)
```

常量 `MATERIAL_ATTENTION_SCALE`（待讨论，建议初始值 0.5）：  
控制材料对思考焦点的最大影响程度。

**文件**：
- `E:\XIA\src\thinking_system\thinking_system.py` — 给 `think()` 加 `input_context` 参数
- `E:\XIA\src\pipeline_runner\stages\s03_think.py` — 传入 `ctx.input_context`

**完成标志**：
- think() 有 `input_context` 参数（可选，默认 None，不影响 daemon tick）
- 当输入材料和活跃 drive 方向对齐时，相关焦点规则优先级有所提升
- drive_vector 本身没有被修改

---

## 执行顺序

1 → 2 → 3，按步骤来。每步完成后可以独立测试，不影响 pipeline 的整体运行。

步骤一和步骤二可以同时做（相互独立）。  
步骤三依赖步骤二的 `input_context` 已经存在。

---

## 关键约束

- 所有逻辑连续，无 if/else 控制分支（`alignment * MATERIAL_ATTENTION_SCALE` 是连续的）
- daemon tick 时 `ctx.raw_input` 为空，`input_context` 的 text 为空字符串，spm_resonance 为空 dict，  
  所有相关逻辑自然退化为 0，不影响内生行为
- `MATERIAL_ATTENTION_SCALE` 是新常量，需要和用户确认后再写入代码
- 不修改 entity 的持久化字段，不改 entity_core.json 格式
- 每个文件改动前先确认内容（用 Read 工具）

---

## 完成后的验证方式

用和之前相同的 5 句测试：
```
帮我查资料 / 你还在吗 / 不知道怎么办 / 我今天有点累 / 薛定谔的猫
```

检查 `thought_packet.suggestions` 里：
- drive_vector 没有被输入改变（curiosity 等维度值不变）
- 当 drive 方向和输入材料对齐时，对应焦点规则的 priority 有所提升
- 当 drive 方向和输入材料不对齐时，thought_packet 和无输入时基本相同
