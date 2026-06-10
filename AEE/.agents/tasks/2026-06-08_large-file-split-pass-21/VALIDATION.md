# VALIDATION.md — Large File Split Pass 21

## 编译检查

```bash
$ python -m py_compile src/language_system/stereotype_learner.py
exit: 0

$ python -m py_compile src/language_system/stereotype_learner_core.py
exit: 0

$ python -m py_compile src/language_system/construction_grammar.py
exit: 0

$ python -m py_compile src/language_system/construction_helpers.py
exit: 0
```

## Import Smoke Test

```bash
$ python -c "from src.language_system import ConstructionLearner, StereotypeLearner"
OK
```

## 测试套件

```bash
$ python -m pytest tests/test_source_identity.py tests/test_expression_relief.py -q
........                                                                 [100%]
8 passed in 0.18s
```

## 行数验证

| 文件 | 行数 | 限 |
|---|---|---|
| `stereotype_learner.py` | 204 | <400 OK |
| `stereotype_learner_core.py` | 133 | <400 OK |
| `construction_grammar.py` | 376 | <400 OK |
| `construction_helpers.py` | 216 | <400 OK |

## 未做

- 未启动 daemon
- 未触发 autonomous action
- 未做 end-to-end integration test
