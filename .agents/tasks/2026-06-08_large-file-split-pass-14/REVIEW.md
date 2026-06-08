# Review

Risk focus:
- `run_language_training_tick` still calls `match_anchor_expression`, now imported from `language_anchor_match.py`.
- Anchor matching data and helper logic moved together.

Residual risk:
- No full training tick over a real entity object was run.
