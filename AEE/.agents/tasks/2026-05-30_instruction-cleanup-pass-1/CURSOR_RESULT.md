# CURSOR_RESULT: instruction-cleanup-pass-1

## Summary

Transformed the instruction file hierarchy into a single canonical source (`AGENTS.md`)
plus concise per-agent adapters. Removed ~200 lines of duplicated code-review-graph
content from 5 files. `CLAUDE.md` retained its project-specific content (architecture,
commands, coding rules) but lost the duplicate graph section.

## Files Changed

| File | Action | Lines before/after |
| --- | --- | --- |
| `AGENTS.md` | **Rewritten** | 38 → 104 |
| `CLAUDE.md` | **Edited** (graph section replaced with inline reference) | 154 → 145 |
| `.cursorrules` | **Rewritten** | 38 → 53 |
| `.windsurfrules` | **Rewritten** | 38 → 17 |
| `GEMINI.md` | **Rewritten** | 38 → 17 |
| `QODER.md` | **Rewritten** | 38 → 17 |

## Important Rules Preserved

All rules from the original files were preserved:

- **Graph-first rule**: code-review-graph MCP tools must be used before Grep/Glob/Read
- **No if-else for logic**: continuous-control style enforced throughout
- **Module size limit**: 400 lines hard cap
- **LLM minimization**: no new LLM call sites without Owner approval
- **Surgical changes only**: scope creep rules for Cursor
- **Multi-agent workflow**: task packages under `.agents/tasks/`, `CURSOR_PROMPT.md` → `CURSOR_RESULT.md` lifecycle
- **Workspace hygiene**: do not edit `src/`, `tests/`, `data/`, `models/`, `frontend/`, `channel/`, `net/`, `config/` unless explicitly scoped
- **CLAUDE.md Chinese**: `所有思考链...必须用中文` preserved
- **CLAUDE.md LLM constraint**: `LLM 是拐杖...` section preserved

## Mojibake / Encoding Issues

No obvious mojibake was found in the instruction files during this pass. The Chinese
text in `CLAUDE.md` (e.g. `所有思考链（thinking/reasoning）和回复必须用**中文**` and
`LLM 是拐杖，能不用就不用`) rendered correctly as UTF-8.

## What Was NOT Changed

- `XIA_SYSTEMS.md` — not in scope
- `.cursor/rules/agent-workflow.mdc` — not in scope (Cursor-specific workflow was captured in `.cursorrules`)
- `.agents/workflow/README.md` — not in scope

## Verification Commands

```powershell
git diff -- AGENTS.md CLAUDE.md .cursorrules .windsurfrules GEMINI.md QODER.md
git status --short -- AGENTS.md CLAUDE.md .cursorrules .windsurfrules GEMINI.md QODER.md src tests data models frontend channel net config
```

**Result**: Only the 6 instruction files were modified. No files under
`src/`, `tests/`, `data/`, `models/`, `frontend/`, `channel/`, `net/`, or `config/`
were touched by this pass.

## Follow-up Recommendations

1. **CLAUDE.md `## Language` section**: Currently mixed Chinese/English. The SPEC
   noted keeping Chinese "only where already clear and needed by the Owner." The
   Chinese `所有思考链...必须用中文` is functional but could be made bilingual if
   future non-Chinese agents are expected.
2. **Graph tool reference duplication**: The compact `| Tool | Use when |` table
   in `AGENTS.md` is still partially duplicated in `CLAUDE.md`'s `## Graph Tools`
   section. Consider making `AGENTS.md` the only source of truth and replacing the
   table in `CLAUDE.md` with only the "Use before Grep/Glob/Read" directive.
3. **Agent-specific adapters**: `.windsurfrules`, `GEMINI.md`, and `QODER.md`
   are currently identical. If the agents have different needs, they can diverge
   in a future pass. For now they are kept consistent.
