# Core

`src/core/` contains the low-level behavior emergence and drive-field support
used by the pipeline. It turns continuous entity state into behavior pressure,
rendering parameters, and compatibility wrappers for older V5/V6 behavior
logic.

## Files

| File | Purpose |
| --- | --- |
| `emergent_behavior.py` | Main behavior emergence entry with V6 logic and fallback behavior |
| `emergent_behavior_v5.py` | Historical V5 fallback behavior logic |
| `drive_vector_field.py` | Drive-field interaction and antagonism calculation |
| `drive_tables.py` | Static drive/antagonism data extracted from drive vector field |
| `behavior_vector.py` | Behavior vector utilities and rule-effect biasing |
| `behavior_patterns.py` | Behavior pattern API |
| `behavior_patterns_pool.py` | Behavior pattern data |
| `behavior_patterns_schema.py` | Behavior pattern dataclasses/schema |
| `entity_core.py` | Lightweight state container used by core behavior logic |
| `somatic_signals.py` | Somatic signal calculation |
| `state_to_context.py` | Public state-to-context entry and compatibility layer |
| `state_to_context_data.py` | Static bands/rules/constants for state-to-context |
| `state_to_context_helpers.py` | State-to-context implementation helpers |
| `action_dispatcher.py` | Dispatches primitive behavior/action candidates |
| `integrity_monitor.py` | Integrity monitoring logic |
| `integrity_signal.py` | Integrity signal utilities |
| `scar.py` | Scar/tension support logic |
| `self_binding.py` | Self-binding support logic |

## Data Flow

```text
EntityState / EntityCore snapshot
        |
        v
drive_vector_field / behavior_vector
        |
        v
emergent_behavior
        |
        +--> action_type / target / priority
        +--> fragmentation and tension metadata
        +--> rendering parameters for language/output
```

## Main Interfaces

```python
from src.core import emerge_behavior, derive_rendering_params

emergent = emerge_behavior(entity_core, drive_vector=drive_vector)
params = derive_rendering_params(emergent, entity_state)
```

## Change Risks

- Drive names are consumed by `drive_system`, `state_update`, and language
  modules. Rename only with a repo-wide search.
- Behavior output shape is used by `pipeline_runner/stages/s04b_emerge.py` and
  downstream language/state-update stages.
- Static tables should stay in `*_data.py`, `*_tables.py`, or `*_schema.py`
  modules so the public entry files remain readable.
