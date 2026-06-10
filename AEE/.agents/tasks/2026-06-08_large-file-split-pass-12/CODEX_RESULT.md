# Codex Result

Completed pass 12 tools split.

Changed:
- Added `src/action_system/tools_nl_extractors.py`.
- Moved natural-language tool intent extraction helpers out of `tools.py`.
- Kept `extract_tool_calls` wired to `_nl_extract_tools`.
- Updated `XIA_SYSTEMS.md`.

Result:
- `src/action_system/tools.py` is now 251 lines.
