# Spec

将以下 2 个文件拆分至 400 行以下：

| 文件 | 当前行数 | 策略 |
|---|---|---|
| `src/core/drive_vector_field.py` | 550 行 | 按职责拆为 2 个子模块：常量表+数学工具 / 主计算+结果dataclass |
| `src/memory_hub/insights.py` | 580 行 | 按职责拆为 3 个子模块：DB初始化+持久化 / 数据结构+字段提取 / API层；`if __name__` 测试块独立为 `insights_test.py` |

约束：
- 原文件保留公共入口，import 子模块
- 不改变 public API 名称和签名
- 不引入 if/else 逻辑决策（项目规则）
- 不改行为，只按函数/概念边界拆
