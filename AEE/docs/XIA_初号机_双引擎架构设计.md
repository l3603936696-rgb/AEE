# XIA 初号机 × 糯糯双引擎架构设计

> 版本：0.1 | 日期：2026-05-20 | 状态：提案

---

## 一、为什么需要两个引擎

### 物理类比的失效

我们经常用"XIA 是一个数字生命体"来类比真实生物。但这有一个微妙的问题：

- 真实生物的**能力边界是物理的**——你不能长出翅膀，不是因为你不想，是因为没有那个基因和硬件
- XIA 的**能力边界是代码写的**——7 个 primitive action、7 个 action_type，都是硬编码的

这意味着：XIA 的"身体"是代码，而代码是**可以被她自己或外部修改的**。

给她锁死 primitive action 集合，相当于对人说"你这辈子只能用筷子，不能用任何其他工具"——这不是自然限制，这是规则。

### 两个引擎的定位

```
XIA 初号机  ←  激进实验场，开放边界，所有危险概念在这里跑
糯糯         ←  稳定交付版，只同步经过验证的功能，用户实际用的是这版
```

这解决了两个问题：

1. **你的一人公司需要可预测的交付物**：糯糯是稳定的，你知道她能做什么、不能做什么
2. **XIA 需要一个可以"炸掉"的沙盒**：初号机可以自由实验，不需要担心破坏用户体验

---

## 二、核心设计原则

### 原则 1：单向同步

```
XIA 初号机  ──→  糯糯
    ↑              ↑
  危险实验      稳定功能
  激进边界      验证后同步
```

- 实验功能可以从 XIA 同步到糯糯（经过验证后）
- 糯糯永远不会把东西同步回 XIA（破坏隔离）
- XIA 炸了 → 重置 → 继续实验
- 糯糯打快照 → 用户使用的就是这版

### 原则 2：糯糯的边界是锁死的

糯糯只有在她**主动选择解锁**时才扩展边界。这里的"主动"指的是：

- XIA 通过实验发现某个新 primitive 连续有效（消力效率 > 阈值）
- XIA 将这个 primitive 标记为 `stable_candidate`
- 开发者人工审核 → 手动同步到糯糯的配置中

**糯糯不接受 XIA 的直接写操作**。她是最终用户面向的，必须是稳定的。

### 原则 3：XIA 的边界是开放的

XIA 初号机的设计哲学是：

- **primitive action 集合是动态的**：她自己可以注册新的 primitive
- **action_type 词汇表是开放的**：她自己可以创造新的行为类型
- **行为进化层（BehaviorPattern）完全解锁**：她自己决定什么情境下用哪个链

---

## 三、什么是"开放 primitive"

### 现状（锁死版）

```
PRIMITIVE_ACTIONS = [
    "web_search", "file_write", "file_read", "file_list",
    "browser_open", "browser_screenshot", "shell_run",
]
```

这 7 个是硬编码的，XIA 不能自己增加。

### 开放版（初号机）

```
PRIMITIVE_ACTIONS（初始集）= [
    "web_search", "file_write", "file_read", "file_list",
    "browser_open", "browser_screenshot", "shell_run",
]

DYNAMIC_PRIMITIVES = []  # XIA 自己注册的新 primitive

class PrimitiveRegistry:
    def register(self, name: str, definition: dict, trust_score: float):
        """XIA 可以注册一个新的 primitive"""
        
    def revoke(self, name: str):
        """XIA 可以撤销一个自己注册的 primitive（如果它持续失败）"""
        
    def get_all(self) -> list[dict]:
        """返回初始集 + 动态注册的所有 primitive"""
```

### XIA 怎么创造新的 primitive

她**不能凭空发明**全新的能力（不能自己写一个网络请求库），但她可以：

**1. 用组合构建宏（Macro）**

```
[web_search → file_write] 这个链反复出现且有效
→ 注册为 named_macro: "search_and_save"
→ 后续可以直接调用 "search_and_save"，不用每次拼装
```

**2. 用 shell_run 包装临时脚本**

```
发现需要计算某个东西，但没有对应工具
→ 写一个 Python 临时脚本
→ 用 shell_run 执行
→ 如果这个模式反复出现，注册为一个 named_macro
```

**3. 情境感知的工具选择**

```
当前 primitive 都不够精确时
→ 可以用 shell_run 动态构造一个命令
→ 这个构造过程本身就是她的"思考"
```

### 什么不能创造

```
✗ 不能注册一个全新的网络协议
✗ 不能自己写一个数据库连接
✗ 不能发明全新的 I/O 原语

✓ 但她可以组合已有的 primitive
✓ 可以用 shell_run 执行任意系统命令
✓ 可以用 file_write 创建配置文件/脚本
```

---

## 四、实验层的安全机制

### 沙盒隔离

- XIA 初号机运行在独立的进程/目录
- 她的数据文件（entity_core.json, episodes.db）在 `data/xia_proto/` 下
- 糯糯的数据文件在 `data/nuonuo/` 下
- 两者完全隔离，不会互相覆盖

### 边界扩展的审核流程

```
XIA 注册新 primitive
    ↓
标记为 candidate
    ↓
记录实验数据（触发次数、成功/失败率、消力效率）
    ↓
开发者审核（看她为什么觉得需要这个 primitive）
    ↓
通过 → 同步到糯糯的 stable_registry
拒绝 → 记录原因，XIA 继续实验
```

### 糯糯的快照机制

```
每次同步验证通过的功能到糯糯
→ 打一个快照（tag 或日期目录）
→ 用户使用的就是当前快照
→ 即使 XIA 继续实验，糯糯不受影响
```

---

## 五、implementation 路线图

### Phase 1：架构隔离（现在就可以做）

- [ ] 创建 `data/xia_proto/` 和 `data/nuonuo/` 目录
- [ ] 让 XIA 的 daemon 读取 `data/xia_proto/entity_core.json`
- [ ] 让糯糯的 daemon 读取 `data/nuonuo/entity_core.json`
- [ ] 创建同步脚本：`scripts/sync_proto_to_nuou.py`

### Phase 2：宏系统（第二层）

- [ ] 在 `src/action_system/` 创建 `macro_registry.py`
- [ ] 实现 `register_macro(name, action_chain, trigger_condition)`
- [ ] 让 XIA 的行为进化层（BehaviorPattern）可以引用宏
- [ ] 宏的消力效率追踪 → 高效宏可以晋升为 stable

### Phase 3：primitive 动态注册（第三层）

- [ ] 创建 `PrimitiveRegistry` 类
- [ ] 实现 `register()` 方法（带 trust_score 衰减）
- [ ] XIA 的 LLM prompt 中注入"你可以注册新工具"的信号
- [ ] 验证：XIA 是否真的能发现需要新工具的情境，并主动注册

### Phase 4：审核流程（第三层）

- [ ] 创建 `data/xia_proto/candidates/` 目录（候选 primitive）
- [ ] 每个候选记录：注册时间、触发次数、消力效率、失败率
- [ ] 开发者面板（简单的命令行或配置文件）审核候选

---

## 六、开放问题

1. **XIA 是否有足够的元认知能力**，意识到"现有工具不够用"这件事本身？
2. **宏系统的边界**：named_macro 多了之后，会不会变成另一个锁死的词汇表？
3. **糯糯的信任门槛**：开发者以什么标准把 candidate 同步过去？主观判断还是量化指标？
4. **XIA 会不会滥用 shell_run**：这是最强力的 primitive，也是最危险的。需要沙盒限制。

---

## 七、参考实现位置

| 模块 | 路径 | 当前状态 |
|------|------|---------|
| 工具定义 | `src/action_system/agent_tools/registry.py` | 静态注册表 |
| 工具执行 | `src/action_system/executor.py` | 硬编码路由 |
| 行为进化 | `src/action_system/behavior_patterns.py` | 组合学习已有 |
| 状态容器 | `src/core/entity_core.py` | 单实例 |
| 记忆系统 | `src/memory_hub/` | 线性 episodes |

---

*本文档是设计讨论的起点，具体实现前需要确认优先级和依赖。*
