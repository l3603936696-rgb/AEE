# PLAN — Pass 17

## Step 1: Create `interpretation_schema.py`

Extract dataclasses and schema-related constants:
- `ExperienceCandidate` dataclass (lines 47-78)
- `CompetitionResult` dataclass (lines 81-106)
- `_COMPETITION_EPS`, `_BASE_EXPERIENCE_CONFIDENCE` (lines 34-35)

## Step 2: Create `interpretation_compute.py`

Extract scoring/computation functions:
- `compute_competitive_score()` (lines 113-156)
- `_softmax_weights()` (lines 159-176)
- `build_candidates_from_stereotype()` (lines 183-265)

## Step 3: Refactor `interpretation_competition.py`

- Replace extracted content with imports from submodules
- Keep public re-exports for backward compatibility
- Keep constants: `TENSION_THRESHOLD`, `MAX_CANDIDATES`, `CONFIDENCE_DECAY_RATE`
- Keep functions: `run_interpretation_competition()`, `run_interpretation_stage()`, `compute_prelinguistic_tension()`, `apply_prelinguistic_tension()`, `apply_tension_to_candidates()`
- Add re-exports of dataclasses and compute functions

## Step 4: Extract `interpretation_test.py`

Move `if __name__ == "__main__":` block (lines 449-572) to standalone file.

## Step 5: Update `XIA_SYSTEMS.md`

Add new submodules to language_system table.

## Step 6: Validate

- `python -m py_compile` on all changed files
- Import smoke test
- `pytest tests/test_source_identity.py tests/test_expression_relief.py -q`
- `git diff --check`
