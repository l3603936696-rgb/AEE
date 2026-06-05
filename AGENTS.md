# XIA Agent Instructions

Shared instruction file for all agents working in this repository.
Other agent-specific files (`.cursorrules`, `.windsurfrules`, `GEMINI.md`, `QODER.md`)
are adapters that point here. Claude Code should also read `CLAUDE.md` for
project overview and architecture detail.

## Project Context

**XIA** (Antagonistic Emergence Engine) is a persistent digital entity with
endogenous drives. Behavior emerges from continuous internal state variables
(loneliness, curiosity, fatigue, somatic tone), not from prompts or instructions.
A background daemon advances state every ~30s independent of user input.

## Graph-First Exploration

**This project has a knowledge graph. ALWAYS use code-review-graph MCP tools
BEFORE using Grep/Glob/Read when available.** The graph is faster, cheaper
(fewer tokens), and gives structural context (callers, dependents, test coverage)
that file scanning cannot.

| Tool | Use when |
| --- | --- |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `detect_changes` + `get_review_context` | Code review with risk-scored analysis |
| `get_architecture_overview` | Understanding high-level codebase structure |

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

## Multi-Agent Workflow

Task packages live under `.agents/tasks/YYYY-MM-DD_short-name/`, each containing
`SPEC.md`, `PLAN.md`, `CURSOR_PROMPT.md`, and `REVIEW.md`.

- **Cursor**: Primary implementation agent. Reads `CURSOR_PROMPT.md`, implements
  scoped changes, updates `CURSOR_RESULT.md` in the task directory.
- **Codex / Claude Code**: Planning, architecture review, risk review, and final
  synthesis. Use graph tools before file scanning.
- **Owner**: Human product and technical decision maker. Reviews diffs and decides
  merge/revision/abandon.

Do not store secrets, API keys, tokens, or private credentials in task files.

## Coding Rules

### No if-else for logic decisions

All control flow must be continuous:

- **Forbidden**: `if`/`elif`/`else` branching, ternary expressions, comparison
  operators (`<`, `>`, `==`, `!=`) to gate behavior, `and`/`or` short-circuit
  value selection
- **Allowed**: dict dispatch tables, softmax over scores, continuous functions
  (`exp(-x)`, `clamp(x, 0, 1)`, `max`/`min`), `try`/`except` for error handling
- **Refactor pattern**: `if x > t: a else: b` -> `a * sigmoid(x-t) + b * (1-sigmoid(...))`

### Hardcoded constants require discussion

Every magic number, fixed coefficient, or threshold must be extracted to a named
constant. Before introducing one, ask: "Where does this value come from?"

### Module size limit

**Hard limit: 400 lines per file.** When a file approaches this limit, extract
the next self-contained concept into a new module. Do not add new logic to
oversized legacy files (`pipeline_runner/__init__.py`, `entity_state.py`);
create a new module instead.

### Surgical changes only

Touch only what the task requires. Don't improve adjacent code, comments, or
formatting. Match existing style. If you notice unrelated dead code, mention it
- don't delete it.

### LLM dependency minimization

**LLM is a crutch - avoid it when possible.**

- Prefer rules/lookup tables/BGE embeddings for cognitive tasks
- Do not introduce new LLM call sites without Owner approval
- Existing LLM call sites (`output_layer`, `llm_synthesizer`, `reflection_layer`)
  are known exceptions

## Workspace Hygiene

Do not edit:

- Generated logs, caches, model artifacts, or runtime data
- Files under `src/`, `tests/`, `data/`, `models/`, `frontend/`, `channel/`,
  `net/`, `config/` unless explicitly within task scope
- Secrets, `.env`, or unrelated memory files

Keep diffs small. If a task grows, split it.

## Review Expectations

Reviewers check for:

- Bugs, risks, missing tests, behavioral regression
- Changes are scoped to the task
- No unrelated refactoring or formatting
