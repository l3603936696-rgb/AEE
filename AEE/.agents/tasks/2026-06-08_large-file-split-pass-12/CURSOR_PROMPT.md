# Cursor Prompt

Review the pass-12 tools split for behavioral regressions.

Check:
- `tools.py` imports `_nl_extract_tools` from `tools_nl_extractors.py`.
- `extract_tool_calls` still handles JSON tool calls, explicit text patterns, and natural-language fallbacks.
- `tools_nl_extractors.py` preserves the old `_nl_extract_*` helper behavior.

Do not edit runtime data, logs, voice files, caches, models, or secrets.
