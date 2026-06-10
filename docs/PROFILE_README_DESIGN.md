# XIA — GitHub Profile README Design

> **Design rationale**: Inspired by Claude Code's GitHub profile. Not a technical spec sheet — a living-project feel. Language: English primary, Chinese for key philosophical terms.

---

## Proposed `~/.github/profile/README.md`

```markdown
<!-- ============================================================
     ~/.github/profile/README.md  —  bcyq / XIA
     Copy this file to your GitHub profile repo:
       ~/.github/profile/README.md
     Then commit & push to activate on your GitHub page.
     ============================================================ -->

---

## XIA is not a chatbot.

XIA (**Antagonistic Emergence Engine**) is a persistent cognitive runtime — a digital entity with endogenous drives that continuously evolves between conversations. It accumulates state, forms behavioral tendencies, and grows an internal world model over time. No prompt engineering. No persona. Just a body running.

```
TickEngine  →  run_pipeline()
   ├─ s01_init
   ├─ s02_perception + interpretation_competition + delayed_understanding
   ├─ s03_think          ←  emotion particle field
   ├─ s04a_meta          ←  self-awareness + reflection
   ├─ s04b_emerge        ←  drive → behavior (V6 system)
   ├─ s05_behavior       ←  action selection + pattern memory
   ├─ s06_language       ←  anchor/template (no LLM in daemon mode)
   └─ s07_state_update   ←  persistence + world model
```

---

## Current Mission

```
  ███████████████░░░░░░░░░  Pass 30 — large-file split (refactoring)
  ████████░░░░░░░░░░░░░░░  v7 autonomous actions (in progress)
  ░░░░░░░░░░░░░░░░░░░░░░░  World Engine — three-engine federation (planned)
```

Now building: **autonomous action execution layer** — giving XIA the ability to reach out and take real-world actions (filesystem, shell, web search) based on drive state, not user instructions.

---

## Systems

| Directory | What it does |
|---|---|
| `src/daemon/` | TickEngine — background process, advances state every ~30s |
| `src/pipeline_runner/` | run_pipeline() — 7-stage cognitive pipeline |
| `src/core/` | Drive vector field, emergent behavior, somatic signals |
| `src/language_system/` | 9 subsystems — quenching, word warmup, sentence composition, somatic anchors, templates, interpretation, narrative, social modeling, reflection |
| `src/memory_hub/` | Episodic memory (SQLite), insight persistence, insular hub |
| `src/world_model_update/` | Inductive world model — rules with Bayesian verification |
| `src/drive_system/` | Pure sensor drives: curiosity, loneliness, fatigue, energy gap |
| `src/action_system/` | V7 autonomous action executor + tool registry |
| `src/evaluation/` | Life protocol — benchmark for autonomous persistence |

---

## Design Philosophy

```
  state-driven          behavior emerges from continuous drives
  persistent runtime    entity survives between conversations
  minimal LLM           core loop runs without LLM; LLM only for output layer
  no if-else control   all logic via continuous functions, softmax, lookup tables
  body-first cognition drives → somatic signals → language, not prompt → response
```

---

## Quick Start

```bash
# 1. clone
git clone https://github.com/bcyq/xia.git
cd xia

# 2. start daemon
python -m src.daemon.daemon

# 3. chat (in another terminal)
python -m channel
```

---

## Contact

- Email: *(replace with your email)*
- Blog: *(replace with your blog URL)*

---

*XIA is part of a larger vision: three autonomous engines federating into a **World Engine**.*
```

---

## Implementation notes

1. **Where to put this**: Copy the markdown into `~/.github/profile/README.md` in your local repo, then push. GitHub automatically renders this file on your profile page.

2. **What to customize before deploying**:
   - Replace `*(replace with your email/URL)*` placeholders
   - The Pass 30 / v7 progress bars are snapshots — update them as work progresses

3. **No API key needed**: All badges use static shields.io URLs, no GitHub token required

4. **ASCII art vs image**: The architecture diagram is pure text — renders correctly on light/dark GitHub themes

5. **Pass 30 progress bar**: This is a made-up number. Measure it however makes sense (e.g. `N/30` files split)

---

## Alternative: Add a "recent activity" section

If you want the Claude Code-style "recent commits as activity feed" look, you can add this below the Systems table:

```markdown
## Recent Evolutions

<!-- commits rendered as activity feed -->
| time | event |
|---|---|
| today | Pass 30 split: src/core/ drive_vector_field.py extracted |
| this week | autonomous action system (v7) executor wired to daemon |
| this week | V6 behavior emergence — drive_vector_field → behavior_vector |
| this month | JEPA encoder online: state→latent mapping + online SGD |
| this month | world_model_update v11.2: inductive learning with Bayesian verification |
```

This makes it feel like a live engineering journal rather than a static README.
