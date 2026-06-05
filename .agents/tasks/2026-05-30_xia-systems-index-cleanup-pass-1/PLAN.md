# Plan: xia-systems-index-cleanup-pass-1

## Approach

Perform a documentation cleanup of `XIA_SYSTEMS.md` only. Treat it as the
canonical system index, not as a scratch report.

## Steps

1. Read `XIA_SYSTEMS.md` headings and current module list.
2. Preserve all major module sections.
3. Add `Agent Quick Navigation` near the top.
4. Normalize the top-level sections for scanability.
5. Replace unsafe punctuation and obvious mojibake only when meaning is clear.
6. Do not rewrite detailed technical claims unless they are already present.
7. Write `CURSOR_RESULT.md` with changed sections, skipped uncertain text, and
   verification output.

## Suggested Document Shape

```text
# XIA Systems Index

## Maintenance Rules
## System Overview
## Agent Quick Navigation
## System Map
  1. pipeline_runner
  2. daemon
  ...
## Data Files
## Key Data Flows
## Maintenance Checklist
```

Each system section may use:

```text
## N. system_name - short description

Responsibility:
Entry files:
Inputs:
Outputs:
Key dependencies:
Common change risks:
Recommended checks:
Notes:
```

## Verification

Run:

```powershell
git diff -- XIA_SYSTEMS.md
rg -n "\x{922B}|\x{9225}|\x{8133}|\x{5371}|\x{864F}|\x{FFFD}|\x{2014}|\x{2192}|\x{00D7}|\x{03A3}|\x{00B2}|\x{2265}|\x{26A0}" XIA_SYSTEMS.md
git status --short -- XIA_SYSTEMS.md src tests data models frontend channel net config
```

Then write:

```text
.agents/tasks/2026-05-30_xia-systems-index-cleanup-pass-1/CURSOR_RESULT.md
```

## Review Focus

Reviewers will check:

- no module coverage was lost,
- no unsupported architecture was invented,
- navigation is easier,
- encoding/mojibake is improved,
- no production files were touched.
