"""TF-IDF helpers for episode text retrieval."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List


_STOPWORDS = {
    "一个", "这个", "那个", "什么", "怎么", "为什么",
    "没有", "不是", "都是", "还是", "可以", "已经",
    "现在", "就是", "然后", "但是", "所以", "因为",
    "如果", "虽然", "或者", "以及", "而且", "只是",
    "的时候", "一下",
}


def _tokenize(text: str) -> List[str]:
    """Tokenize mixed Chinese/English text for lightweight local recall."""
    if not text:
        return []

    normalized = text.replace("\u3000", " ").replace("　", " ")
    tokens: List[str] = []

    for part in re.split(r"[^\w]+", normalized.lower()):
        if part and len(part) >= 2 and part.isalpha():
            tokens.append(part)

    for seq in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        if seq not in _STOPWORDS:
            tokens.append(seq)
        for i in range(len(seq) - 1):
            tokens.append(seq[i : i + 2])

    return tokens


def _compute_tf(tokens: List[str]) -> Dict[str, float]:
    """Compute term frequency."""
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = float(len(tokens))
    return {word: count / total for word, count in counts.items()}


def _compute_idf(documents: List[List[str]]) -> Dict[str, float]:
    """Compute inverse document frequency for a tokenized corpus."""
    n_docs = len(documents)
    if n_docs == 0:
        return {}

    df: Counter[str] = Counter()
    for tokens in documents:
        for word in set(tokens):
            df[word] += 1

    return {word: math.log(n_docs / (count + 1)) + 1.0 for word, count in df.items()}


def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Compute cosine similarity between sparse vectors."""
    common = set(a) & set(b)
    if not common:
        return 0.0

    dot = sum(a[word] * b[word] for word in common)
    norm_a = math.sqrt(sum(value * value for value in a.values()))
    norm_b = math.sqrt(sum(value * value for value in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
