# CLAUDE.md

**WARNING: 首次接触 XIA？先读这里 -> [XIA_SYSTEMS.md](./XIA_SYSTEMS.md)**

---

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language

所有思考链（thinking/reasoning）和回复必须用**中文**。

## Project Overview

XIA (Antagonistic Emergence Engine) is a persistent digital entity with endogenous drives. Behavior emerges from continuous internal state variables (loneliness, curiosity, fatigue, somatic tone), not from prompts or instructions. A background daemon advances state every ~30s independent of user input. Language is generated from body-state parameters mapped through a vocabulary acquisition system, not from persona descriptions.

## Commands

```bash
# Start the daemon (main entry point)
python -m src.daemon.daemon
python -m src.daemon.daemon --tick-interval 30 --http-port 8765 --ipc-port 8766
python -m src.daemon.daemon --train-only  # language training mode, no pipeline

# Run tests
python tests/test_50_ticks.py        # 50-tick end-to-end signal chain
python tests/test_integration_language.py  # language generation
python tests/test_fixes.py           # regression tests

# Chat via IPC (daemon must be running)
python -m channel

# Optional active reach-out listener
python reach_client.py
```

## Architecture

### Two execution modes

1. **Daemon ticks** (`daemon_mode=True`): TickEngine calls `run_pipeline(daemon_mode=True)` every 30s. Output comes from the anchor/template language system, never from LLM. This is the entity's autonomous "inner life."

2. **Chat requests**: IPC/HTTP receives user input, calls `run_pipeline(raw_input=text)`. Output comes from LLM (DeepSeek) unless `no_llm=True`, in which case it falls back to the anchor path like daemon mode.

### Pipeline flow (`src/pipeline_runner/__init__.py`)

`run_pipeline()` is a ~2700-line synchronous pipeline. Key stages in order:

1. **State snapshot** - freeze entity state at start of tick
2. **Semantic analysis** - parse input (BGE embeddings or LLM heuristic fallback)
3. **Memory retrieval** - mainline (conversation history) + branch (associative recall)
4. **Perception** - context awareness, attention field, somatic signals
5. **State update** - dopamine/oxytocin signals, emotion compute, info queue processing
6. **Drive computation** - v1 drive_system produces `drive_vector` (curiosity, fatigue_avoid, loneliness_drive, etc.)
7. **Input->Drive mapping** - input text matched to SPM named symbols via BGE embedding, finding experiential resonance
8. **Interpretation competition** - multiple experience candidates compete continuously; competitiveness = experience_strength * f(state) * conversion_coefficient; tension suspension permeates language output
9. **Delayed understanding** - low-confidence interpretations enter pending queue, reactivated on future similar input
10. **V6 behavior emergence** - drive_vector -> antagonism matrix -> exponential decay -> fragmentation -> behavior_vector -> dominant action type
11. **Language training** - anchor word matching, sentence composition, template learning
12. **Output generation** - LLM response (chat) or anchor/template text (daemon)
13. **Post-output** - quenching records, episode writing, world model updates

### Drive -> Behavior chain (the V6 system)

This is the core decision mechanism. Files involved:

- `src/drive_system/drive_system.py` - Computes raw drives from entity state via shape tables (lookup + linear interpolation). Pure sensor, no decisions.
- `src/core/drive_vector_field.py` - Antagonism matrix + exponential decay: `net[dst] = raw[dst] * exp(-sum(raw[src] * weight[src->dst]))`. Then fragmentation coefficients (alpha) and behavior_vector: `intensity = net * (1 - alpha^2)`.
- `src/core/emergent_behavior.py` - Maps dominant intensity dimension to action type via `_DRIVE_TO_ACTION` dict. Returns `EmergentBehavior` with action_type, priority, tension_level, behavior_vector.
- `src/core/behavior_vector.py` - Applies rule-based bias from world model learned rules.

### Entity state

- `src/entity_state.py` - `EntityState` class (~1450 lines). Global singleton via `get_entity_state()`. Persisted to `data/entity_core.json` every tick. Contains all continuous state variables (energy, fatigue, loneliness, info_gap, somatic_tone, etc.), world model rules, and snapshots history.
- `src/core/entity_core.py` - `EntityCore`, lighter state container used by the V6 drive system. Has its own `take_snapshot()`.

### Language system (`src/language_system/`)

21 modules. The entity doesn't speak via LLM prompts during daemon ticks - it builds vocabulary through a training loop:

- **Word warmup** (`word_warmup.py`) - Tracks cold->warm progression via hit counts. Words need >=3 quenching records to become "warm" (usable).
- **Sentence composer** (`sentence_composer.py`) - Combines anchor words with templates. Templates are learned and scored by quenching efficiency.
- **Construction grammar** (`construction_grammar.py`) - Learns phrase patterns from successful expressions.
- **Somatic dictionary** (`somatic_dictionary.py`) - Maps body-state dimensions to sensation words.
- **Narrative fragments** (`narrative_fragments.py`) - Longer self-expression attempts using learned vocabulary.

### Daemon infrastructure (`src/daemon/`)

- `daemon.py` - IPCServer (TCP:8766 on Windows, Unix socket on Linux) + HTTPServer (:8765) + TickEngine
- `tick_engine.py` - Runs pipeline each tick, handles reading intake from library files, trigger evaluation, sibling channel (multi-entity communication)
- `protocol.py` - IPC request/response format. Chat payload: `{"type":"chat", "payload":{"text":"...", "no_llm": false}}`
- `reading_source.py` - Feeds text from `data/library/` files for vocabulary acquisition

### Key data files

- `data/entity_core.json` - Persisted entity state (energy, fatigue, drives, wm_rules, etc.)
- `data/episodes.db` - SQLite episodic memory. Table `episodes` with columns: iteration_id, timestamp, raw_input, output_text, decision, state_snapshot, drive_vector, etc.
- `data/world_model_db.json` - Learned world model rules
- `data/behavior_patterns.json` - Behavior pattern database

### LLM configuration

Provider chain in `.env`: `XIA_LLM_CHAIN=deepseek,ollama` (try DeepSeek first, fallback to local Ollama). Provider abstraction in `src/llm/providers.py`.

## Coding Rules

### No if-else for logic decisions

This is the project's most important constraint. All control flow must be continuous:

- **Forbidden**: `if`/`elif`/`else` branching, ternary expressions, comparison operators (`<`, `>`, `==`, `!=`) to gate behavior, `and`/`or` short-circuit value selection
- **Allowed**: dict dispatch tables, softmax over scores, continuous functions (`exp(-x)`, `clamp(x, 0, 1)`, `max`/`min`), `try`/`except` for error handling
- **Refactor pattern**: `if x > t: a else: b` -> `a * sigmoid(x - t) + b * (1 - sigmoid(...))`

### Hardcoded constants require discussion

Every magic number, fixed coefficient, or threshold must be extracted to a named constant. Before introducing one, ask: "Where does this value come from?" Do not invent constants without reason.

### Module size limit

Each file must represent a single, named responsibility that can be described in one sentence. **Hard limit: 400 lines per file.** When a file approaches this limit, extract the next self-contained concept into a new module - do not continue appending. Existing oversized files (e.g. `pipeline_runner/__init__.py`, `entity_state.py`) are under active refactoring; do not add new logic to them, create a new module instead.

### Surgical changes only

Touch only what the task requires. Don't improve adjacent code, comments, or formatting. Match existing style. If you notice unrelated dead code, mention it - don't delete it.

### LLM 依赖最小化

XIA 的核心哲学之一：**LLM 是拐杖，能不用就不用**。

- **默认优先**用规则/查表/BGE 嵌入等确定性方法解决认知任务
- **严禁擅自引入**任何新的 LLM 调用点，即使只是"简单调用一次"也不行
- 如果某个认知功能**必须依赖 LLM** 才能实现，必须先和用户（bcyq）商量，说明：
  1. 为什么现有的确定性方法不够用
  2. 依赖 LLM 的具体边界在哪里
  3. 是否有可行的非 LLM 替代路径
- 已有 LLM 调用点（`output_layer`、工具合成 `llm_synthesizer`、反射层 `reflection_layer`）为已知例外，不需重复讨论
- 语言系统成熟后，工具合成路径应迁移到模板组合或内生合成

## Graph Tools

**Use code-review-graph MCP tools before Grep/Glob/Read when available.**
Full tool reference and workflow are in `AGENTS.md`.
