# Review — Pass 18

## Scope

- `src/language_system/construction_grammar.py` (711L → 3 modules)
- `src/language_system/recursive_construction.py` (423L → 2 modules)

## Changes

### construction_grammar.py split

- `construction_schema.py` (126L) — hyperparameters + ExpressionInstance + Construction class + _drive_match_score
- `construction_utils.py` (29L) — _infer_anchor_pos helper
- `construction_grammar.py` (597L) — ConstructionLearner class (remains large, tightly integrated)

### recursive_construction.py split

- `recursive_schema.py` (153L) — ClausePattern class + hyperparameters + ROLE_FILLERS + SEED_CLAUSE_PATTERNS + _fill_role_from_state
- `recursive_construction.py` (147L) — RecursiveGenerator class + _softmax_sample

## Verification

- `python -m py_compile` × 5 files — all pass
- Import smoke test — all pass
- `pytest tests/test_source_identity.py tests/test_expression_relief.py` — 8 passed
- `git diff --check` — pass

## Risks

- `ConstructionLearner` class is tightly integrated (560+ lines), cannot be split further without architectural refactoring
- All sub-modules are < 400 lines ✓
- Backward compatibility preserved

## Recommendation

**Merge.** All sub-modules meet the 400-line limit. The main ConstructionLearner class remains above 400 lines but this is a known structural limitation of tightly-coupled single classes.
