# Task Package: repo-hygiene-pass-1

## Goal

Make the XIA repository easier for humans and agents to navigate by reducing
root-directory noise without changing runtime behavior.

This is a hygiene pass, not a refactor. The implementation agent should organize
obvious planning documents, reports, diagnostic scripts, temporary probes, and
root-level logs into named directories, then update ignore rules where needed.

## Background

- Why this matters: complex XIA work now involves multiple agents. A noisy root
  directory makes context gathering expensive and increases the chance of
  reviewing or editing the wrong file.
- Current behavior: root contains production entrypoints, plans, reports,
  diagnostics, temporary probes, logs, and generated files mixed together.
- Desired behavior: root keeps project entrypoints and core docs; historical and
  generated artifacts move into predictable archive directories.

## Non-Goals

- Do not refactor source code.
- Do not change application behavior.
- Do not delete files.
- Do not modify files under `src/`, `data/`, `models/`, `frontend/`, `channel/`,
  `net/`, `config/`, or `tests/`.
- Do not move files that are likely user-facing entrypoints unless explicitly
  called out in the plan.

## Constraints

- Follow `AGENTS.md`, `CLAUDE.md`, and `.agents/workflow/README.md`.
- Use code-review-graph MCP tools first if available; fall back to file listing
  for this documentation-only task.
- Preserve git history as much as practical by using moves instead of copy/delete.
- Keep the pass reversible and obvious.
- If unsure whether a file is important, leave it in place and mention it in
  `CURSOR_RESULT.md`.

## Files Safe To Organize

These root-level groups are in scope:

- `PLAN_*.md` -> `docs/plans/`
- `report_*.txt` -> `docs/reports/`
- `diag_*.py`, `_probe_*.py`, `_watch_*.py`, `_chat_drive.py` ->
  `scripts/diagnostics/`
- `diag_output.txt`, `_watch_*.out`, `_dialogue_decoded.txt` ->
  `docs/reports/diagnostics/`
- `daemon*.log`, malformed root log names like `E*:XIAdaemon.log` ->
  `logs/archive/` if not currently being written.
- `tmp_*.py`, `tmp_*.json` -> `workspace/tmp/` if clearly temporary.

## Files To Leave In Root For This Pass

- `README.md`
- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`
- `QODER.md`
- `XIA_SYSTEMS.md`
- `.cursorrules`, `.windsurfrules`, `.gitignore`
- `.env.example`, `requirements.txt`, `docker-compose.yml`
- `run_daemon.sh`, `daemon_watchdog.sh`
- `channel.bat`, `start_xia.ps1`, `xia_admin.py`
- `start_ollama.*`, `check_*.ps1`, `create_shortcut.ps1`, `read_docx.ps1`
- `test_*.py`, `verify_*.py`, `train_*.py`, `reach_client.py`
- Chinese launch/admin `.bat` files.

## Acceptance Criteria

- [ ] Root directory has fewer historical plan/report/log/temp files.
- [ ] No production source files are moved or edited.
- [ ] `.gitignore` covers generated root logs and local temp outputs if needed.
- [ ] `CURSOR_RESULT.md` lists every moved file.
- [ ] `git status --short` is easier to read after the pass.
- [ ] No tests are required unless a tracked executable path is moved.

## Open Questions

- Question: Should root-level `test_*.py` eventually move into `tests/`?
- Decision: Not in pass 1. Leave them in root to avoid breaking unknown commands.
