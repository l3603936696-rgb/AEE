"""
Interpretation Schema — dataclass definitions for interpretation competition.

Submodules of src.language_system.interpretation_competition:
    interpretation_schema.py  — dataclass definitions
    interpretation_compute.py — scoring & candidate building
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

_COMPETITION_EPS: float = 0.001
_BASE_EXPERIENCE_CONFIDENCE: float = 0.5


@dataclass
class ExperienceCandidate:
    """
    Candidate interpretation.

    Fields:
        interpretation  : Human-readable interpretation text
        source_id      : Source identifier (stereotype node / individual profile)
        experience_id  : Unique experience identifier
        confidence     : Experience confidence [0, 1]
        emotion_mod   : How much this experience activates current emotion
        conversion     : Conversion coefficient, entity's innate amplification factor
        competitive_score : Computed competitiveness score (filled by the competition logic)
    """
    interpretation: str
    source_id: str
    experience_id: str
    confidence: float = _BASE_EXPERIENCE_CONFIDENCE
    emotion_mod: float = 0.5
    conversion: float = 1.0
    competitive_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "interpretation": self.interpretation,
            "source_id": self.source_id,
            "experience_id": self.experience_id,
            "confidence": round(self.confidence, 4),
            "emotion_mod": round(self.emotion_mod, 4),
            "conversion": round(self.conversion, 4),
            "competitive_score": round(self.competitive_score, 4),
        }


@dataclass
class CompetitionResult:
    """
    Competition result.

    Fields:
        winner        : Winning interpretation (None if no clear winner)
        tension_level : Tension level [0, 1]
        tension_type  : "suspended" | "attractor" | "none"
        candidates    : All candidates with their competitiveness scores
        top_scores    : Top-2 scores (for debugging)
    """
    winner: Optional[ExperienceCandidate]
    tension_level: float
    tension_type: str
    candidates: List[ExperienceCandidate]
    top_scores: Tuple[float, float]

    def to_dict(self) -> dict:
        return {
            "winner": self.winner.to_dict() if self.winner else None,
            "tension_level": round(self.tension_level, 4),
            "tension_type": self.tension_type,
            "top_scores": [round(s, 4) for s in self.top_scores],
            "candidates": [c.to_dict() for c in self.candidates],
        }
