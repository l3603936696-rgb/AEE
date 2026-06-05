# Plan: repo-hygiene-pass-1

## Approach

Do a conservative file-organization pass. Prefer creating archive directories
and moving obvious non-source artifacts. Do not touch core code.

## Proposed Directories

- `docs/plans/`
- `docs/reports/`
- `docs/reports/diagnostics/`
- `scripts/diagnostics/`
- `logs/archive/`
- `workspace/tmp/`

## Move Plan

Move plan documents:

- `PLAN_*.md` -> `docs/plans/`
- `REFACTOR_PLAN.md` -> `docs/plans/`

Move reports and diagnostics output:

- `report_*.txt` -> `docs/reports/`
- `diag_output.txt` -> `docs/reports/diagnostics/`
- `_dialogue_decoded.txt` -> `docs/reports/diagnostics/`
- `_watch_*.out` -> `docs/reports/diagnostics/`

Move diagnostic/probe scripts:

- `diag_*.py` -> `scripts/diagnostics/`
- `_probe_*.py` -> `scripts/diagnostics/`
- `_watch_*.py` -> `scripts/diagnostics/`
- `_chat_drive.py` -> `scripts/diagnostics/`
- `_test_bge_local.py` -> `scripts/diagnostics/`

Move temporary files:

- `tmp_*.py` -> `workspace/tmp/`
- `tmp_*.json` -> `workspace/tmp/`

Move root logs only after checking they are not being actively written:

- `daemon.log`
- `daemon_stderr.log`
- `daemon_stdout.log`
- `daemon_verify.log`
- malformed root log file matching `E*XIAdaemon.log`

## .gitignore Updates

Add explicit root-level generated patterns if missing:

```gitignore
# Root-level runtime artifacts
/daemon*.log
/diag_output.txt
/_watch_*.out
/_dialogue_decoded.txt
/tmp_*.py
/tmp_*.json
```

Do not ignore `docs/plans/` or `scripts/diagnostics/` by default; those may be
useful project artifacts.

## Verification

Run:

```powershell
git status --short
Get-ChildItem -File
Get-ChildItem docs/plans,docs/reports,scripts/diagnostics,logs/archive,workspace/tmp -ErrorAction SilentlyContinue
```

Then write `CURSOR_RESULT.md` with exact moved files and any skipped files.
