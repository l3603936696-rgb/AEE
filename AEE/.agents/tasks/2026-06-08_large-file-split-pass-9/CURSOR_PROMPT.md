# Cursor Prompt

Review the pass-9 daemon split for behavioral regressions.

Check:
- `tick_engine.py` ordering against the old inline tick sequence.
- `tick_input.py` source identity defaults for external and sibling input.
- `action_execution.py` action trigger behavior and training override cleanup.
- `periodic_maintenance.py` scheduled maintenance intervals and constants.

Do not edit runtime data, logs, caches, models, or secrets.
