# Language Blindness Map

Generated from `scripts/diagnostics/language_blindness_map.py`.
The JSON report is the machine-readable evidence source. This note records the
interpretation boundary: a changed signature means the parser noticed a
difference, not that XIA understood the sentence.

## Confirmed Capabilities

- Role reversal is represented: `我担心你` and `你担心我` swap actor and patient.
- Single and double negation are distinguishable in the proposition frame.
- Past, present, and future markers are exposed as a tense slot.
- Opaque technical sentences receive low familiarity confidence.
- Unresolved external actor and patient slots remain low-confidence instead of
  becoming confident merely because jieba extracted noun-like strings.

## Remaining Blind Spots

- Nested mental-state clauses are still flattened. In
  `我担心你以为我在责怪你`, the inner proposition is not represented.
- Conditional and correction forms expose surface modality but not linked
  antecedent, consequent, correction target, or replacement value.
- Predicate extraction remains heuristic. For example, an opaque sentence can
  yield a syntactic predicate without semantic familiarity.
- The proposition frame is observational only. It does not yet affect state,
  interpretation competition, or reply selection.

## Next Step

Route low-confidence or missing proposition slots into clarification candidate
scoring. Keep the behavior continuous: uncertainty should increase the weight
of a targeted question such as `你说的是谁？` or `你是说现在，还是之前？`,
without forcing a hard branch.
