# Cursor Prompt

Review the pass-11 action executor split for behavioral regressions.

Check:
- `executor.py` imports all extracted helper functions it uses.
- `executor_prompts.py` preserves tool whitelist and prompt construction behavior.
- `executor_feedback.py` preserves failure analysis and somatic feedback behavior.
- `executor_failure_resolution.py` preserves fix-rule injection and capability-gap handling.

Do not edit runtime data, logs, voice files, caches, models, or secrets.
