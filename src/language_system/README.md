# Language System

`src/language_system/` turns state, source context, and semantic signals into
language candidates and feedback. It is not only an LLM wrapper: most files are
deterministic support systems for anchor matching, sentence composition,
expression relief, source modeling, and learning from interaction.

## Main Data Flow

```text
EntityState + semantic/input context
        |
        v
anchor matching / candidate generation
        |
        v
sentence composition / construction grammar
        |
        v
expression feedback + quenching + memory write-back
```

## Core Files

| File | Purpose |
| --- | --- |
| `candidate_generator.py` | Candidate expression generation |
| `semantic_analyzer.py` | Semantic scoring and anchor matching support |
| `sentence_composer.py` | Public sentence composition entry |
| `sentence_composer_schema.py` | Composition constants/schema |
| `sentence_composer_helpers.py` | Composition math helpers |
| `sentence_composer_patterns.py` | Sentence/template pattern table |
| `somatic_anchors.py` | Public somatic anchor API/re-export |
| `somatic_anchors_data.py` | Somatic anchor data table |
| `somatic_concept_map.py` | Somatic concept mapping API |
| `somatic_concept_map_helpers.py` | Concept propagation and helper logic |
| `expression_relief.py` | Relief scoring for expressions |
| `expression_feedback.py` | Feedback from response relevance into state |
| `quenching.py` | Quenching tracker public API |
| `quenching_schema.py` | Quenching dataclasses |
| `quenching_helpers.py` | Quenching serialization/hash helpers |
| `five_rights.py` | Six-rights controller public API |
| `five_rights_helpers.py` | Five/six-rights helper implementation |
| `source_identity.py` | Source identity classification |
| `source_profiler.py` | Source profile/familiarity tracking |
| `speaker_model.py` | Speaker-model support |
| `reply_motivator.py` | Reply-drive modulation |

## Learning and Grammar

| File | Purpose |
| --- | --- |
| `construction_grammar.py` | Construction grammar learner/public API |
| `construction_schema.py` | Construction grammar schema |
| `construction_helpers.py` | Construction helper functions |
| `construction_utils.py` | Utility functions for construction grammar |
| `recursive_construction.py` | Recursive construction generation |
| `recursive_schema.py` | Recursive construction schema |
| `template_learner.py` | Learns effective language templates |
| `state_pattern_memory.py` | Internal state-symbol emergence API |
| `state_pattern_memory_schema.py` | State-pattern dataclasses/bootstrap data |
| `state_pattern_memory_helpers.py` | State-pattern math and forge helpers |
| `word_warmup.py` | Vocabulary warmup/unlock process |
| `word_warmup_helpers.py` | Word-warmup helpers |

## Interpretation and Understanding

| File | Purpose |
| --- | --- |
| `interpretation_competition.py` | Public interpretation competition entry |
| `interpretation_compute.py` | Competition scoring implementation |
| `interpretation_schema.py` | Interpretation dataclasses/schema |
| `delayed_understanding.py` | Pending low-confidence understanding |
| `clarification_memory.py` | Clarification memory ledger |
| `clarification_learning.py` | Clarification evidence learning |
| `clarification_evidence.py` | Evidence dataclasses |
| `proposition_frame.py` | Proposition-frame extraction |
| `uncertainty_expression.py` | Honest uncertainty expression support |
| `input_packet.py` | Input packet construction |
| `pronoun_direction.py` | Pronoun/source direction matching |

## Narrative, Social, and Source Context

| File | Purpose |
| --- | --- |
| `narrative_fragments.py` | Narrative fragment scoring |
| `narrative_context.py` | Narrative context construction |
| `reflection_layer.py` | Reflection-layer hooks |
| `self_counsel.py` | Self-counsel relief loop |
| `social_comprehension.py` | Social comprehension helpers |
| `mirror.py` | Mirror learning |
| `preoccupation_engine.py` | Preoccupation tracking |
| `concept_graph.py` | Concept activation/exposure |
| `associative_recall.py` | Associative recall |
| `reading_acquisition.py` | Reading-based acquisition |
| `sentence_extraction.py` | Sentence extraction from text |
| `vocabulary_acquisition.py` | Vocabulary acquisition |

## Stereotype/Speaker Tree

| File | Purpose |
| --- | --- |
| `stereotype_tree.py` | Public stereotype tree API |
| `stereotype_tree_nodes.py` | Tree dataclasses |
| `stereotype_tree_schema.py` | Tree constants/schema |
| `stereotype_tree_helpers.py` | Tree traversal/context helpers |
| `stereotype_tree_api.py` | Convenience API |
| `stereotype_tree_stage3.py` | Stage-3 similarity/fork methods |
| `stereotype_tree_stage3_helpers.py` | Stage-3 helper functions |
| `stereotype_forks.py` | Fork handling |
| `stereotype_learner.py` | Public stereotype learner API |
| `stereotype_learner_core.py` | Learner implementation |
| `stereotype_markers.py` | Marker extraction |
| `stereotype_memory.py` | Stereotype memory helpers |

## Change Risks

- Public paths are used by `language_training.py`, `language_anchor_match.py`,
  `pipeline_runner/stages/s06*.py`, and daemon source hooks.
- Keep data-heavy modules (`*_data.py`, `*_patterns.py`) separate from public
  API modules.
- When moving a function, preserve compatibility imports or update
  `src/language_system/__init__.py`.
