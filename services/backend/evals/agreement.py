"""Agreement statistics for the eval gate (D15, D38). Pure functions, no I/O.

Labels are per (item, criterion): "1".."5" or "insufficient_evidence" (IE). Kappa and MAE are
computed on pairs where both sides gave a number; IE agreement is reported separately, because
"no evidence" is not a point on the 1-5 scale.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from itertools import combinations
from statistics import median

IE = "insufficient_evidence"
SCALE = (1, 2, 3, 4, 5)
Labels = Mapping[tuple[str, str], str]  # (item_id, criterion_id) -> outcome


def quadratic_weighted_kappa(pairs: Iterable[tuple[int, int]]) -> float | None:
    pairs = list(pairs)
    if not pairs:
        return None
    k = len(SCALE)
    observed = [[0.0] * k for _ in range(k)]
    for a, b in pairs:
        observed[a - 1][b - 1] += 1
    n = len(pairs)
    row = [sum(r) for r in observed]
    col = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = (i - j) ** 2 / (k - 1) ** 2
            num += w * observed[i][j]
            den += w * row[i] * col[j] / n
    # All labels identical on both sides: perfect agreement with zero chance-variance.
    return 1.0 if den == 0 else 1.0 - num / den


def numeric_pairs(a: Labels, b: Labels) -> list[tuple[int, int]]:
    return [(int(a[key]), int(b[key])) for key in a.keys() & b.keys()
            if a[key] != IE and b[key] != IE]


def mae(pairs: list[tuple[int, int]]) -> float | None:
    return sum(abs(x - y) for x, y in pairs) / len(pairs) if pairs else None


def ie_agreement(a: Labels, b: Labels) -> float | None:
    keys = a.keys() & b.keys()
    return sum((a[k] == IE) == (b[k] == IE) for k in keys) / len(keys) if keys else None


def ie_rate(labels: Labels) -> float | None:
    return sum(v == IE for v in labels.values()) / len(labels) if labels else None


def consensus(raters: list[Labels]) -> dict[tuple[str, str], str]:
    """Majority IE wins; otherwise the median of the numeric labels (ties round up)."""
    out: dict[tuple[str, str], str] = {}
    for key in set().union(*(r.keys() for r in raters)):
        votes = [r[key] for r in raters if key in r]
        numeric = [int(v) for v in votes if v != IE]
        if len(votes) - len(numeric) > len(votes) / 2 or not numeric:
            out[key] = IE
        else:
            out[key] = str(int(median(numeric) + 0.5))
    return out


def compare(a: Labels, b: Labels) -> dict[str, float | int | None]:
    pairs = numeric_pairs(a, b)
    return {"qwk": quadratic_weighted_kappa(pairs), "mae": mae(pairs), "n": len(pairs),
            "ie_agreement": ie_agreement(a, b)}


def ceiling(raters: list[Labels]) -> dict[str, float | int | None]:
    """Mean pairwise rater agreement: the best a model can be expected to reach (D14)."""
    if len(raters) < 2:
        return {"qwk": None, "mae": None, "n": 0, "ie_agreement": None, "pairs": 0}
    stats = [compare(x, y) for x, y in combinations(raters, 2)]
    def avg(key: str) -> float | None:
        vals = [s[key] for s in stats if s[key] is not None]
        return sum(vals) / len(vals) if vals else None
    return {"qwk": avg("qwk"), "mae": avg("mae"), "n": sum(int(s["n"] or 0) for s in stats),
            "ie_agreement": avg("ie_agreement"), "pairs": len(stats)}
