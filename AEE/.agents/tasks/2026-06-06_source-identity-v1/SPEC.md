# Task Package: source-identity-v1

## Goal

Stop mixing Owner input with generic external text.

Before this task, most user-facing input entered the system as source id
`external`. That means bcyq, random pasted text, and other external content
shared familiarity, trust, and status-belief history.

v1 separates:

- who delivered the message (`speaker_id`)
- what kind of content it is (`content_origin`)
- who originally authored the content (`author_id`)
- which persistent profile bucket should be updated (`source_id`)

## Scope

- New module: `src/language_system/source_identity.py`
- Source profiler update: `src/language_system/source_profiler.py`
- Pipeline context accepts `source_identity`.
- IPC chat and tick-engine external replies default to `bcyq/direct_chat`.
- `s02_perception` passes `speaker_id` into construction parsing and stereotype
  matching.
- Tests: `tests/test_source_identity.py`
- Diagnostics: `scripts/diagnostics/source_relief_validation.py`

## Identity Mapping

Direct Owner chat:

```text
input_source = external or ipc_chat
speaker_id = bcyq
content_origin = direct_chat
author_id = bcyq
source_id = bcyq
```

Pasted or third-party text delivered by Owner:

```text
speaker_id = bcyq
content_origin = pasted_text
author_id = unknown
source_id = pasted_text:unknown
```

Sibling channel:

```text
input_source = sibling
speaker_id = sibling:<peer>
content_origin = sibling_channel
author_id = sibling:<peer>
source_id = sibling:<peer>
```

## Non-Goals

- No processing-depth logic.
- No perspective-taking or "if I were bcyq" inference.
- No truth boost for trusted speakers.
- No data migration beyond safe in-place profile field initialization.
- No daemon restart required for offline validation.

## Design Principle

Trust means "worth spending more understanding effort on", not "automatically
true". v1 only creates the identity substrate. It does not change conclusions.
