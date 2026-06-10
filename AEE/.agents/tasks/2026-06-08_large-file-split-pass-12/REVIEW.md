# Review

Risk focus:
- `extract_tool_calls` depends on `_nl_extract_tools`; import wiring was smoke-tested.
- Regex helper behavior was moved by function boundary.
- Public tool execution functions remained in `tools.py`.

Residual risk:
- No live tool execution loop was triggered.
