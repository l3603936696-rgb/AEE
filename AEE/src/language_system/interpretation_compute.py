"""
Interpretation Compute — scoring and candidate building for interpretation competition.

Submodules of src.language_system.interpretation_competition:
    interpretation_schema.py  — dataclass definitions
    interpretation_compute.py — scoring & candidate building
"""

import math
from typing import Any, Dict, List, Optional

from .interpretation_schema import (
    ExperienceCandidate,
    _COMPETITION_EPS,
    _BASE_EXPERIENCE_CONFIDENCE,
)

MAX_CANDIDATES: int = 8


def compute_competitive_score(
    candidate: ExperienceCandidate,
    state_snapshot: Dict[str, float],
) -> float:
    """
    Competitiveness = experience_strength * f(state) * conversion_coefficient.

    State modulation:
        loneliness ↑ → emotional experience competitiveness increases
        stress ↑ → analytical experience competitiveness decreases
        somatic_tone negative → pain experience weight increases
    """
    strength = candidate.confidence

    loneliness = float(state_snapshot.get("loneliness", 0.3))
    stress = float(state_snapshot.get("stress", 0.1))
    somatic_tone = float(state_snapshot.get("somatic_tone", 0.0))
    boredom = float(state_snapshot.get("boredom", 0.2))

    emotion_boost = loneliness * 0.3
    stress_decay = 1.0 - stress * 0.25
    pain_amplify = 1.0 + max(0.0, -somatic_tone) * 0.2
    boredom_decay = 1.0 - boredom * 0.1

    f_state = (1.0 + emotion_boost) * stress_decay * pain_amplify * boredom_decay
    conversion = candidate.conversion

    score = strength * f_state * conversion
    return max(0.0, min(3.0, score))


def _softmax_weights(scores: List[float], temperature: float = 0.1) -> List[float]:
    """
    Softmax weight distribution: scores -> probability distribution.

    Low temperature -> winner takes most weight (approaches argmax)
    High temperature -> uniform distribution
    """
    if not scores or all(s <= _COMPETITION_EPS for s in scores):
        n = len(scores) if scores else 1
        return [1.0 / n] * n

    max_s = max(scores)
    exps = [math.exp((s - max_s) / temperature) for s in scores]
    total = sum(exps)
    if total < 1e-9:
        n = len(scores)
        return [1.0 / n] * n
    return [e / total for e in exps]


def build_candidates_from_stereotype(
    input_text: str,
    stereotype_context: Optional[Any],
    spm_resonance: Dict[str, float],
    named_patterns: List[Dict[str, Any]],
) -> List[ExperienceCandidate]:
    """
    Build candidate interpretations from stereotype tree and SPM resonance.

    Sources:
    1. Stereotype tree active_tags (high-level priors)
    2. SPM resonance symbols (internal state matching)
    3. Named internal symbols (experiential associations)

    Each candidate's confidence comes from:
    - Stereotype node confidence
    - SPM symbol hit_count normalization
    """
    candidates: List[ExperienceCandidate] = []

    # Source 1: Stereotype active_tags
    if stereotype_context:
        tags = getattr(stereotype_context, "active_tags", []) or []
        depth = getattr(stereotype_context, "depth", 0)
        tag_confidence = getattr(stereotype_context, "confidence", _BASE_EXPERIENCE_CONFIDENCE)

        for tag in tags[:4]:
            depth_bonus = min(0.2, depth * 0.05)
            candidates.append(ExperienceCandidate(
                interpretation=f"刻板印象[{tag}]视角：{input_text}",
                source_id=f"stereotype:{tag}",
                experience_id=f"st_{tag}",
                confidence=min(1.0, tag_confidence + depth_bonus),
                emotion_mod=0.5,
                conversion=1.0,
            ))

    # Source 2: SPM resonance symbols
    for symbol, resonance in spm_resonance.items():
        candidates.append(ExperienceCandidate(
            interpretation=f"内部共鸣'{symbol}'触发",
            source_id="spm_resonance",
            experience_id=f"spm_{symbol}",
            confidence=min(1.0, resonance * 0.8),
            emotion_mod=resonance,
            conversion=1.0,
        ))

    # Source 3: Named internal symbols
    for pattern in named_patterns:
        symbol = pattern.get("symbol", "")
        named_as = pattern.get("named_as", "")
        hit_count = pattern.get("hit_count", 1)

        if not symbol:
            continue

        experience_depth = min(1.0, hit_count / 20.0)

        candidates.append(ExperienceCandidate(
            interpretation=f"经验'{named_as or symbol}'匹配",
            source_id="spm_named",
            experience_id=f"named_{symbol}",
            confidence=experience_depth * _BASE_EXPERIENCE_CONFIDENCE,
            emotion_mod=0.5,
            conversion=1.0,
        ))

    # Deduplicate (same experience_id keeps highest confidence)
    seen: Dict[str, ExperienceCandidate] = {}
    for c in candidates:
        if c.experience_id not in seen or c.confidence > seen[c.experience_id].confidence:
            seen[c.experience_id] = c

    result = list(seen.values())
    result.sort(key=lambda c: c.confidence, reverse=True)
    return result[:MAX_CANDIDATES]
