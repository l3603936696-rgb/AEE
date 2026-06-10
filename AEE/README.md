# AEE - Antagonistic Emergence Engine

A persistent digital entity with endogenous drives. Behavior emerges from continuous internal state variables — loneliness, curiosity, fatigue, somatic tone — not from prompts or instructions.

A background daemon advances state every ~30 seconds, independent of user input. Language is generated from body-state parameters mapped through a vocabulary acquisition system, not from persona descriptions.

## Architecture

```
AEE/
├── src/                    # Core engine modules
│   ├── core/               # Entity state, drives, behavior vectors
│   ├── language_system/    # Vocabulary acquisition, sentence composition
│   ├── daemon/             # Tick engine, IPC/HTTP server
│   ├── pipeline_runner/    # ~14-stage signal processing pipeline
│   ├── thinking_system/    # Semantic understanding, mental simulation
│   ├── world_model_update/ # Rule induction, contradiction resolution
│   ├── state_update/       # Dopamine/oxytocin signals, emotion compute
│   └── ...
├── tests/                  # Integration and regression tests
├── channel/                # Interactive chat client
├── docs/                   # Architecture docs
└── training/               # Vocabulary and anchor training scripts
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Start the daemon (main entry point)
python -m src.daemon.daemon

# Chat via IPC (daemon must be running)
python -m channel

# Run tests
python tests/test_50_ticks.py   # 50-tick end-to-end signal chain
python tests/test_fixes.py       # Regression tests
```

## Core Concepts

### Drive → Behavior Chain (V6 System)

The core decision mechanism:

1. `drive_system` computes raw drives from entity state via shape tables
2. Antagonism matrix + exponential decay produces net drives
3. Fragmentation coefficients and behavior vector determine intensity
4. Dominant dimension maps to action type (explore, retreat, seek, avoid...)

### Two Execution Modes

- **Daemon ticks**: TickEngine calls `run_pipeline(daemon_mode=True)` every 30s. Output from anchor/template language system, never from LLM.
- **Chat requests**: IPC/HTTP receives user input, calls `run_pipeline(raw_input=text)`. Output from LLM unless `no_llm=True`.

### Language Generation

The entity doesn't speak via LLM prompts during daemon ticks. Instead:
- Words warm up via quenching record hit counts
- Sentences compose from anchor words + templates
- Templates are learned and scored by quenching efficiency
- Construction grammar learns phrase patterns from successful expressions

## Configuration

See `.env` for LLM provider configuration. Provider chain: `XIA_LLM_CHAIN=deepseek,ollama` (DeepSeek first, local Ollama fallback).

## License

MIT
