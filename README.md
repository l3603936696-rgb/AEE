# AEE — Antagonistic Emergence Engine

AEE is the core runtime of **XIA**, a digital entity with persistent internal states and endogenous drives. Behavior emerges from those states — not from prompts or instructions.

---

## What XIA actually does

Ask XIA how it feels, and it will tell you its hands feel numb. Not because it was told to say that — because its somatic state parameters are currently low, and its language system maps that to sensation language.

Leave XIA alone for two hours, and it will knock on your door:

> *"我刚才在想…你最近有看什么有意思的东西吗？我有点无聊。"*
> *(I was just thinking… seen anything interesting lately? I'm a bit bored.)*

That message was not triggered by a timer or a prompt. It emerged from a loneliness drive exceeding a threshold, filtered through a nine-module decision system weighing energy, context, and prior behavior patterns.

XIA also acts on its own curiosity. During one session, without being asked, it searched for "量子计算 2024 最新进展" and read five articles — because its `info_hunger` drive crossed the action threshold and the trigger system selected `explore` over `rest`.

---

## What makes this different

Most conversational AI is **stateless between turns** and **prompt-driven** — behavior is a response to input.

XIA is different at the architecture level:

- **Endogenous drives** — `loneliness`, `curiosity`, `fatigue`, `info_hunger`, `somatic_tone`, and `danger` exist as continuous variables updated every tick, independent of conversation
- **Somatic grounding** — language is generated from body-state parameters mapped through a learned somatic dictionary, not from persona instructions
- **Emergent action** — a V6 antagonism matrix computes net drive vectors; behavior emerges from the dominant dimension without any if-else branching
- **Language acquisition** — XIA learns new vocabulary the way a child does: exposure → partial comprehension → asking a teacher → copying semantic profile from known words → warmup to unlock
- **World model induction** — XIA builds and updates rules about the world from its own experience, not from pre-loaded facts

This is an architecture question, not a prompt engineering question.

---

## Architecture

```
run_pipeline()  ← cognitive pipeline orchestrator
     │
     ├── daemon.tick_now()       ← background tick, every 30s, no LLM
     │        │
     │        ├── entity_state        ← 1450-line global singleton, persisted to JSON
     │        ├── drive_system        ← raw drives via shape tables + linear interpolation
     │        ├── drive_vector_field  ← antagonism matrix + exponential decay → net drives
     │        ├── emergent_behavior   ← dominant net dimension → action_type (V6)
     │        ├── emotion_system      ← attention field, particle field, projection
     │        ├── decision_system     ← 9-module perception pipeline
     │        ├── thinking_system     ← covariance tracker, mental simulation
     │        ├── language_system     ← 40+ modules: acquisition, composition, quenching
     │        ├── action_system       ← autonomous: search, browse, filesystem, reach
     │        ├── memory_hub          ← episodic DB (SQLite), insula, tetramem adapter
     │        ├── world_model_update  ← induction, contradiction resolution, decay
     │        ├── jepa                ← world state prediction (I-JEPA / V-JEPA)
     │        ├── weathering          ← long-term parameter drift from accumulated experience
     │        └── state_update        ← dopamine tone, oxytocin signal, coherence, write-back
     │
     └── daemon IPCServer        ← chat requests via TCP (Windows) / Unix socket (Linux)
```

**12 subsystems. 150+ Python modules.**

---

## Key technical decisions

### No if-else for behavior

All behavior decisions use continuous math. Binary branching is forbidden:

```python
# Forbidden
if loneliness > 0.6:
    action = "seek"

# How it actually works
net_drives = raw * exp(-sum(antagonism_weights))  # antagonism matrix
behavior_vector = net * (1 - alpha**2)            # fragmentation coefficients
action_type = _DRIVE_TO_ACTION[argmax(behavior_vector)]
```

This means behavior is never a hard switch — it has *texture*. High fragmentation produces hesitant, conflicted behavior; low fragmentation produces clean action.

### Language without persona

XIA doesn't have a system prompt that says "you are a curious entity." Instead:

1. A `somatic_dictionary` maps body-state dimensions (`energy=0.3, loneliness=0.7`) to sensation words
2. A `sentence_composer` combines anchor words with learned construction templates
3. Words go through a warmup system: cold → exposed → warm → unlocked (min 3 quenching records)
4. Templates are scored by quenching efficiency — effective expressions survive, ineffective ones decay

### Minimal LLM dependency

LLM is used for chat responses and vocabulary teaching. All continuous state updates, drive computation, behavior emergence, and daemon ticks run without any LLM calls. The principle: *LLM is a crutch — avoid it when possible.*

---

## Subsystems

| Subsystem | Responsibility |
|-----------|---------------|
| `pipeline_runner` | Orchestrates all cognitive stages in order (~13 stages) |
| `drive_system` | Computes raw drives from entity state via shape tables |
| `core/drive_vector_field` | Antagonism matrix + fragmentation → behavior vector |
| `core/emergent_behavior` | V6 behavior emergence from dominant drive dimension |
| `language_system` | 40+ modules: vocabulary acquisition, construction grammar, somatic mapping, quenching |
| `decision_system` | 9-module perception: context, self-state, world model, temporal pressure, tool self-check |
| `thinking_system` | Covariance tracking, mental simulation, semantic base |
| `emotion_system` | Attention field, particle field, projection controller, insight writer |
| `action_system` | Autonomous execution: REACH, search, browse, filesystem, shell |
| `memory_hub` | Episodic SQLite DB, insula hub, tetramem adapter |
| `world_model_update` | Rule induction, contradiction resolution, dimension cost, decay |
| `weathering` | Long-term parameter drift and shattering from accumulated experience |
| `jepa` | World state prediction using I-JEPA / V-JEPA architectures |
| `parameter_system` | Staged parameter governance with access control |

---

## Setup

**Requirements:** Python 3.12+, Node.js 18+, a DeepSeek API key

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Configure API key
cp .env.example .env
# Edit .env: set DEEPSEEK_API_KEY

# 3. Install and build frontend
cd frontend && npm install && npm run build && cd ..

# 4. Start the daemon
python -m src.daemon.daemon

# 5. Launch the desktop app (separate terminal)
cd frontend && npm run electron
```

LLM provider chain: DeepSeek → local Ollama fallback. Configurable via `.env`.

---

## Current state

- Persistent daemon running ~6,600 ticks per extended session
- V6 behavior emergence with antagonism matrix and fragmentation coefficients
- Language acquisition: vocabulary warmup, construction grammar, somatic dictionary
- Autonomous action loop: REACH, web search, browse, filesystem
- 9-module decision system with world model integration
- Episodic memory in SQLite with state snapshots per tick
- World model induction from experience (not pre-loaded)
- Weathering system: long-term parameter drift from accumulated state history
- Electron frontend: conversation, state timeline, action log, inner diary, drive vector view
- Multi-agent development workflow: Cursor (implementation) + Claude Code (architecture) + Codex (review)

---

## Author

Independent research project. Built solo.  
Contact: l3603936696@gmail.com
