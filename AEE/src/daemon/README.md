# daemon

Long-running runtime process for XIA.

## Responsibility

The daemon owns background tick advancement and local IPC/HTTP access. It keeps
the entity moving when no user is chatting, accepts chat/status/training
requests, and connects autonomous action results back into memory.

## Main Files

| File | Responsibility |
| --- | --- |
| `daemon.py` | Starts IPC, HTTP, shutdown handling, and the tick engine. |
| `http_server.py` | Serves the Windows-compatible HTTP API and forwards requests to IPC. |
| `ipc_chat_handler.py` | Handles IPC chat requests, cache probing, pipeline dispatch, and source profiling. |
| `tick_engine.py` | Orchestrates each daemon tick and autonomous action trigger flow. |
| `action_execution.py` | Bridges pipeline decisions into daemon-triggered autonomous actions. |
| `async_updates.py` | Submits fire-and-forget experience/world-model update coroutines. |
| `autonomous_action_memory.py` | Records autonomous action results as episodes, snapshots, and behavior-rule evidence. |
| `causal_observation.py` | Records source/state-delta causal observations with rolling retention. |
| `covariance_update.py` | Updates covariance tracker state and attention weights. |
| `environment_vector.py` | Maintains semantic residue and social prediction tension across daemon ticks. |
| `expression_postprocess.py` | Applies expression feedback, self-counsel, and epistemic credit settling. |
| `output_causal_observation.py` | Opens and closes output-caused state-delta observations across ticks. |
| `periodic_maintenance.py` | Runs scheduled causal learning, weathering drift, and tension snapshots. |
| `reading_cycle.py` | Runs reading intake and sentence-pattern extraction from reading history. |
| `reflection_jepa_tick.py` | Runs inner diary, reflection, and JEPA learning steps. |
| `response_prewarm.py` | Stores response-cache entries from drive vectors and output text. |
| `sibling_tick.py` | Applies sibling-channel social credit, stereotype fork checks, and anchor posting. |
| `source_tick.py` | Updates source profiles, reply drive, semantic residue, and familiarity effects. |
| `state_pattern_tick.py` | Runs StatePatternMemory internal symbol emergence. |
| `tick_input.py` | Prepares reach/sibling input, source identity, and input-side feedback hooks. |
| `tick_status.py` | Builds daemon status summaries. |
| `world_model_tick.py` | Runs world-model induction, question tension release, and reading taste updates. |
| `ipc_client.py` | Sends requests to the local daemon over TCP or Unix socket. |
| `protocol.py` | Defines IPC request and response serialization. |
| `reading_source.py` | Reads library text for vocabulary acquisition. |
| `reading_taste.py` | Tracks reading preference signals. |

## Data Flow

1. `TickEngine.tick_now()` prepares tick context and optional external input.
2. `decay_environment_vector()` advances ambient semantic/social context.
3. `close_pending_output_causal()` closes the previous output observation.
4. It calls `run_pipeline(..., daemon_mode=True)`.
5. The pipeline updates state, language traces, memory, and decision outputs.
6. `update_source_tick()` updates source profiles, reply drive, semantic residue, and familiarity effects.
7. `record_pending_output_causal()` opens a new output observation when text was emitted.
8. `update_response_cache()` pre-warms cached responses when drive-vector data exists.
9. `run_expression_postprocess()` applies expression feedback and credit settling.
10. `update_covariance_tracker()` records state/prediction-error covariance.
11. `run_reading_intake()` and `extract_sentence_patterns_from_reading()` advance reading-based learning.
12. `run_state_pattern_memory_tick()` advances internal symbol emergence.
13. `run_world_model_tick()` and periodic maintenance helpers run scheduled learning/drift work.
14. `run_action_execution()` may execute autonomous action triggers after the tick.
15. `record_causal_observation()` appends the tick-level state delta.
16. `record_autonomous_action()` writes action outcomes back into memory and
   behavior-rule snapshots.

## Change Notes

- Keep `tick_engine.py` focused on orchestration.
- Put episode/snapshot construction helpers in separate modules.
- Do not add LLM calls to daemon ticks unless the task explicitly approves the
  dependency and documents why deterministic paths are insufficient.
