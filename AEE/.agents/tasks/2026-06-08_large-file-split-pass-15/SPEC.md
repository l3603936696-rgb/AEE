# Spec

将以下 3 个文件拆分至 400 行以下：

| 文件 | 当前行数 | 策略 |
|---|---|---|
| `src/quenching_system.py` | 556 行 | 按职责拆为 3 个子模块：数据层（event/dataclass）、通道层（6个quench函数）、主入口（apply_all） |
| `src/thinking_system/semantic_base.py` | 477 行 | 按职责拆为 2 个子模块：常量表（dim/action semantics, causal seeds）、查询接口（query functions） |
| `src/memory_hub/tetramem_adapter.py` | 532 行 | 按职责拆为 2 个子模块：持久层（降级读写memories_staged.json）、API层（TetraMem HTTP调用） |

约束：
- 原文件保留公共入口，import 子模块
- 不改变 public API 名称和签名
- 不引入 if/else 逻辑决策（项目规则）
- 不改行为，只按函数/概念边界拆
