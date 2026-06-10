# XIA — AI Agent Rules

> 所有 AI 代理（CURSOR / CODEX / CLAUDE / GEMINI / QODER / WINDSURF）统一规则。
> 先读此文件，再读 `AGENTS.md` 和 `CLAUDE.md`。

---

## 项目背景

**XIA** (Antagonistic Emergence Engine) 是一个具有内生驱动力、持续运行的数字实体。
行为来自内部状态变量（孤独感、好奇心、疲劳度驱），不是来自 prompt 或指令。
后台 daemon 每 30s 推进一次状态，独立于用户输入运行。

语言系统使用锚词/模板生成（非 LLM），除非在 chat 对话中才调用 DeepSeek LLM。

**关键约束：LLM 依赖最小化**
- 默认优先用规则/查表/BGE 嵌入等确定性方法
- 禁止擅自引入新的 LLM 调用点
- 已有例外：`output_layer`、`llm_synthesizer`、`reflection_layer`

---

## 探索原则

**本项目有知识图谱。始终优先使用 code-review-graph MCP 工具。**

| 工具 | 用途 |
|------|------|
| `semantic_search_nodes` | 按名称/关键词找函数/类 |
| `query_graph` | 追踪调用者、被调用者、依赖关系 |
| `get_impact_radius` | 理解改动的爆炸半径 |
| `get_affected_flows` | 找到受影响的执行路径 |
| `detect_changes` + `get_review_context` | 带风险评分的代码审查 |
| `get_architecture_overview` | 高层代码结构 |

**只有当图谱覆盖不了时，才用 Grep/Glob/Read。**

---

## 编码规则

### 禁止用 if-else 做逻辑分支

所有控制流必须连续：
- **禁止**：`if`/`elif`/`else`、三元表达式、`and`/`or` 短路值选择
- **允许**：dict 分派表、softmax 评分、连续函数（`exp(-x)`、`clamp(x,0,1)`、`max`/`min`）、`try`/`except`
- **重构示例**：`if x > t: a else: b` → `a * sigmoid(x-t) + b * (1-sigmoid(...))`

### 禁止魔数

每个硬编码常数必须提取为命名常量。引入前先问："这个值从哪里来的？"

### 模块行数限制

**硬上限：400 行/文件**。接近时提取为新模块，不要继续追加到超大文件。

### 最小改动原则

只做任务要求的改动。不要改善相邻代码、不要加注释或格式改进、不要修无关的 lint 问题。

---

## 多代理工作流

任务包放在 `.agents/tasks/YYYY-MM-DD_short-name/`，每个包含：
`SPEC.md` · `PLAN.md` · `CURSOR_PROMPT.md` · `REVIEW.md`

- **Cursor**：主要实现代理，读 `CURSOR_PROMPT.md`，更新 `CURSOR_RESULT.md`
- **Codex / Claude Code**：规划、架构审查、风险审查
- **Owner**：人类决策者，审 diff，决定合并/打回

---

## 工作区卫生

**禁止编辑**：
- 生成文件（日志、缓存、模型产物、运行时数据）
- `AEE/src/`、`AEE/tests/`、`data/`、`models/` 下的文件（除非任务明确要求）
- `.env` 或其他包含密钥的文件

**不要存储**：API keys、token、私人凭证到任务文件中。

---

## 长期记忆

每次对话开始时读取 `MEMORY.md`，了解用户上下文和项目状态。
对话结束时，如有新决策/里程碑/偏好/状态变化，**必须更新** `MEMORY.md`。

---

## 模块组织（XIA/ — GitHub 仓库根目录）

```
XIA/
├── src/daemon/         # TickEngine，后台进程
├── src/pipeline_runner/ # run_pipeline()，7阶段认知管线
├── src/core/           # 驱动力场、涌现行为、体感信号
├── src/language_system/ # 9个子系统（消力、热身、模板等）
├── src/memory_hub/     # 情景记忆、洞察、insula hub
├── src/world_model_update/ # 归纳世界模型
├── src/drive_system/   # 纯传感器驱动力
├── src/action_system/  # V7自主行动执行器
├── src/evaluation/     # Life Protocol 基准测试
├── channel/            # CLI 对话入口
├── net/                # 网络工具（搜索等）
├── lib/                # 第三方库
└── config/             # 配置文件
```

> 注意：`.agents/`、`.cursor/`、MEMORY.md 等工具配置在 `XIA/` 内部，不 push 到 GitHub。
