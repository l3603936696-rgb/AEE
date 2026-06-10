# Observability

The observability package records module-level runtime activity and provides
lightweight reports for health checks. It is designed to be safe inside daemon
ticks: instrumentation should never break the main pipeline.

## Files

| File | Purpose |
| --- | --- |
| `__init__.py` | Public exports for observation helpers |
| `registry.py` | Compatibility entry and high-level observation API |
| `observer_registry.py` | Registry implementation for module call tracking |
| `observer_registry_schema.py` | Dataclasses and schema helpers |
| `observer_registry_utils.py` | Time, health, and serialization utilities |
| `events.py` | Structured event dataclasses |
| `event_log.py` | JSONL event writer |
| `llm_wrapper.py` | Wrapper for tracking LLM calls and fallback behavior |
| `report.py` | Human-readable observability report generation |

## Data Flow

```text
instrumented function / LLM call
        |
        v
observe / observe_block / observe_llm
        |
        v
observer registry
        |
        +--> call counts
        +--> success/failure counts
        +--> duration statistics
        +--> last error summary
        |
        v
report.py
```

## Design Rules

- Observation must be best-effort. Failures are swallowed or recorded, not
  propagated into the pipeline.
- Do not add heavy dependencies to this package.
- Keep event schemas backward compatible with existing JSONL logs.
- If a new subsystem gets instrumentation, add its category/name to the relevant
  report or registry code.

## Quick Checks

```powershell
python -m compileall -q src\observability
```
