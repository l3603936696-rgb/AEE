"""
Response pre-warming cache.
Stores (drive_vector, response_text, tick) triples from recent daemon ticks.
On chat arrival, returns the best match by cosine similarity in 5-D drive space.

No if/else: all routing via max() over continuous weighted dicts.
"""

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_DIMS = ("curiosity", "info_hunger", "obsolescence_anxiety", "loneliness_drive", "fatigue_avoid")


@dataclass
class CachedResponse:
    drive_vector: Dict[str, float]
    response_text: str
    tick: int
    captured_at: float = field(default_factory=time.time)


def _cache_weight(similarity: float, threshold: float = 0.90, steepness: float = 20.0) -> float:
    """Sigmoid gate: approaches 1.0 when similarity >> threshold, 0.0 when below."""
    try:
        exp = max(-700.0, min(700.0, -steepness * (similarity - threshold)))
        return 1.0 / (1.0 + math.exp(exp))
    except Exception:
        return 0.0


def _cosine_similarity(a: Dict[str, float], b: Dict[str, float]) -> float:
    try:
        av = tuple(float(a.get(d, 0.0)) for d in _DIMS)
        bv = tuple(float(b.get(d, 0.0)) for d in _DIMS)
        dot = sum(x * y for x, y in zip(av, bv))
        mag = math.sqrt(sum(x * x for x in av)) * math.sqrt(sum(x * x for x in bv))
        return dot / mag if mag > 1e-9 else 0.0
    except Exception:
        return 0.0


class ResponseCache:
    """Thread-safe ring buffer of recent daemon tick responses."""

    def __init__(self, capacity: int = 3) -> None:
        self._capacity = capacity
        self._entries: List[CachedResponse] = []
        self._lock = threading.Lock()

    def update(self, drive_vector: Dict[str, float], response_text: str, tick: int) -> None:
        """Add a daemon tick response to the cache.

        write_w: sigmoid over text length — 空文本 ≈0, 5字 ≈0.5, 15字以上 ≈0.99。
        太短的响应（单字感叹词等）代表性不足，不值得作为缓存锚点。
        """
        try:
            text = str(response_text).strip()
            # 长度门控：中心点 8 字，steepness=0.5（平缓过渡，不是硬截断）
            write_w = 1.0 / (1.0 + math.exp(-0.5 * (len(text) - 8)))
            skip_w = 1.0 - write_w
            strategies = {
                "write": (write_w, lambda: self._write(drive_vector, text, tick)),
                "skip":  (skip_w,  lambda: None),
            }
            max(strategies.items(), key=lambda kv: kv[1][0])[1][1]()
        except Exception:
            pass

    def match(self, query_vector: Dict[str, float]) -> Tuple[Optional[str], float]:
        """Return (response_text, similarity) for the best matching cached entry."""
        try:
            with self._lock:
                entries = list(self._entries)
            scored = [
                (e.response_text, _cosine_similarity(query_vector, e.drive_vector))
                for e in entries
            ]
            scored.append((None, 0.0))  # sentinel miss
            best_text, best_sim = max(scored, key=lambda x: x[1])
            hit_w  = _cache_weight(best_sim)
            miss_w = 1.0 - hit_w
            result = max(
                {
                    "hit":  (hit_w,  (best_text, best_sim)),
                    "miss": (miss_w, (None, 0.0)),
                }.items(),
                key=lambda kv: kv[1][0],
            )[1][1]
            return result
        except Exception:
            return (None, 0.0)

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def _write(self, drive_vector: Dict[str, float], text: str, tick: int) -> None:
        with self._lock:
            self._entries.append(CachedResponse(dict(drive_vector), text, tick))
            excess = max(0, len(self._entries) - self._capacity)
            self._entries = self._entries[excess:]
