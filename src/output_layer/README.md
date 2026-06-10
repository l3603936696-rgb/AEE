# Output Layer

## Responsibility

Receives EntityCore state snapshot + emergent_behavior + somatic_signals, calls state_to_context to generate system_prompt, invokes LLM to produce final natural language response.

## Submodules

| File | Lines | Responsibility |
| --- | ---: | --- |
| `output_layer_schema.py` | ~280 | Constants, instruction tables, helper functions, prompt builders |
| `output_layer.py` | ~230 | Main entry: `generate_response()` + self-test |

## Entry Point

```python
from src.output_layer import generate_response

result = generate_response(
    state_snapshot={...},
    semantic_packet_biased={...},
    params={"temperature": 0.7, "max_tokens": 300},
    emergent_behavior={...},
)
# Returns: {"text": str, "confidence": float, "generation_time_ms": int}
```

## Key Design

- **Fallback chain**: `state_to_context` → `_build_system_prompt_fallback` (no exception)
- **Rendering params**: derived from `emergent_behavior` + `entity_state`
- **Emotion particle modulation**: flow rate affects text rhythm
- **Non-invasive**: never modifies external state
