# CURSOR_RESULT: repo-hygiene-pass-1

## Summary

Conservative root-directory hygiene pass: moved 23 files across 5 destination directories. No source code moved, no application behavior changed. daemons logs were skipped because `daemon_stderr.log` had recent writes (2026-05-30 18:13) making active-writing status uncertain.

## Directories Created

- `docs/plans/`
- `docs/reports/`
- `docs/reports/diagnostics/`
- `scripts/diagnostics/`
- `logs/archive/` (empty, prepared for future log archiving)
- `workspace/tmp/`

## Files Moved

### → `docs/plans/` (11 files, untracked)

| Source | Destination |
| --- | --- |
| `PLAN_integrity_pain_revival.md` | `docs/plans/PLAN_integrity_pain_revival.md` |
| `PLAN_self_counsel.md` | `docs/plans/PLAN_self_counsel.md` |
| `PLAN_honest_reward_somatic_coupling.md` | `docs/plans/PLAN_honest_reward_somatic_coupling.md` |
| `PLAN_verify_trigger_match.md` | `docs/plans/PLAN_verify_trigger_match.md` |
| `PLAN_learn_from_outside.md` | `docs/plans/PLAN_learn_from_outside.md` |
| `PLAN_language_as_tool.md` | `docs/plans/PLAN_language_as_tool.md` |
| `PLAN_template_scale_normalization.md` | `docs/plans/PLAN_template_scale_normalization.md` |
| `PLAN_thinking_to_language.md` | `docs/plans/PLAN_thinking_to_language.md` |
| `PLAN_expression_feedback_loop.md` | `docs/plans/PLAN_expression_feedback_loop.md` |
| `PLAN_input_as_material.md` | `docs/plans/PLAN_input_as_material.md` |
| `REFACTOR_PLAN.md` | `docs/plans/REFACTOR_PLAN.md` |

### → `docs/reports/` (1 file, untracked)

| Source | Destination |
| --- | --- |
| `report_2026-05-17.txt` | `docs/reports/report_2026-05-17.txt` |

### → `docs/reports/diagnostics/` (3 files, untracked)

| Source | Destination |
| --- | --- |
| `diag_output.txt` | `docs/reports/diagnostics/diag_output.txt` |
| `_dialogue_decoded.txt` | `docs/reports/diagnostics/_dialogue_decoded.txt` |
| `_watch_prune.out` | `docs/reports/diagnostics/_watch_prune.out` |

### → `scripts/diagnostics/` (7 files, untracked)

| Source | Destination |
| --- | --- |
| `diag_loneliness.py` | `scripts/diagnostics/diag_loneliness.py` |
| `diag_updateengine.py` | `scripts/diagnostics/diag_updateengine.py` |
| `diag_step84.py` | `scripts/diagnostics/diag_step84.py` |
| `_probe_loop.py` | `scripts/diagnostics/_probe_loop.py` |
| `_watch_prune.py` | `scripts/diagnostics/_watch_prune.py` |
| `_chat_drive.py` | `scripts/diagnostics/_chat_drive.py` |
| `_test_bge_local.py` | `scripts/diagnostics/_test_bge_local.py` |

### → `workspace/tmp/` (2 files, untracked)

| Source | Destination |
| --- | --- |
| `tmp_chat.py` | `workspace/tmp/tmp_chat.py` |
| `tmp_xia_chat.json` | `workspace/tmp/tmp_xia_chat.json` |

## `.gitignore` Changes

Added root-level runtime artifact patterns to `.gitignore`:

```gitignore
# Root-level runtime artifacts (moved to archive dirs, keep tracked)
/daemon*.log
/diag_output.txt
/_watch_*.out
/_dialogue_decoded.txt
/tmp_*.py
/tmp_*.json
```

Existing `data/`, `logs/`, `workspace/` directory ignores already cover the new subdirectories created.

## Files Intentionally Skipped

| File | Reason |
| --- | --- |
| `daemon_stderr.log` | Last written 2026-05-30 18:13 — today. Cannot rule out active writing. |
| `daemon_stdout.log` | Last written 2026-05-30 18:13 — today. Cannot rule out active writing. |
| `daemon.log` | Last written 2026-05-21 — historical, but same daemon process concern. |
| `daemon_verify.log` | Last written 2026-05-18 — historical, but same daemon process concern. |
| `E:XIA~` (malformed log) | Cannot determine its active status; filename may confuse shell move commands. |

All skipped files should be archived in a future pass once daemon lifecycle is confirmed inactive.

## Verification Commands

```powershell
git status --short
# Confirmed: 23 moved files no longer appear at root level
# Confirmed: new directories docs/plans/, docs/reports/, docs/reports/diagnostics/,
#            scripts/diagnostics/, workspace/tmp/ visible as untracked
# Confirmed: .gitignore modified

Get-ChildItem docs/plans | Measure-Object  # Count: 11
Get-ChildItem docs/reports | Measure-Object  # Count: 1 (+ 1 subdirectory)
Get-ChildItem docs/reports/diagnostics | Measure-Object  # Count: 3
Get-ChildItem scripts/diagnostics | Measure-Object  # Count: 7
Get-ChildItem workspace/tmp | Measure-Object  # Count: 2
Test-Path workspace/tmp/tmp_chat.py  # True
Test-Path workspace/tmp/tmp_xia_chat.json  # True
```

## Follow-up Recommendations

1. **Daemon log archival**: Confirm daemon is stopped, then move `daemon*.log` to `logs/archive/` in a follow-up pass.
2. **Malformed log**: Inspect `E:XIA~` (likely `E:XIA-daemon.log` or similar) before moving.
3. **Root `test_*.py` files**: SPEC.md noted these are out-of-scope for pass 1; consider a `tests/root/` subdirectory in a future pass.
4. **Git add new dirs**: The new directories are currently untracked. Decide whether to `git add` them (they contain project artifacts) or leave them gitignored alongside the files they hold.
