# Evaluation System

## Responsibility

Evaluation and validation of XIA's life-like properties through non-invasive observation and controlled experiments.

## Submodules

| File | Function |
| --- | --- |
| `life_protocol_schema.py` | Dataclass (TickMetrics) + thresholds + helper functions |
| `life_protocol_runner.py` | SimulationRunner — non-invasive tick executor |
| `life_protocol_tests.py` | Level 1/2/3 test classes (stability, structure, lifeness) |
| `life_protocol.py` | Entry: run_life_protocol() + CLI |

## Life Protocol (life_protocol.py)

**Usage**: `python -m src.evaluation.life_protocol [--quick]`

**Outputs**:
- `data/life_protocol_log.jsonl` — one TickMetrics per tick
- `data/life_protocol_result.json` — final report with scores

**Test Levels**:
- Level 1 (Stability): entropy bounds, state volatility
- Level 2 (Structure): bias formation, path dependency, structured_progress validity
- Level 3 (Lifeness): attractor recovery, reward reversal, self-constraint, isolation
