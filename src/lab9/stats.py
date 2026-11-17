"""Statistics students implement (M2 judge calibration, M4 paired bootstrap).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

from collections.abc import Sequence

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    if len(human) != len(judge) or len(human) == 0:
        raise ValueError("labels must be nonempty and paired")
    if any(x not in ("PASS", "FAIL") for x in [*human, *judge]):
        raise ValueError("labels must be PASS or FAIL")
    return {"tp": sum(h == POS and j == POS for h, j in zip(human, judge)),
            "fp": sum(h != POS and j == POS for h, j in zip(human, judge)),
            "fn": sum(h == POS and j != POS for h, j in zip(human, judge)),
            "tn": sum(h != POS and j != POS for h, j in zip(human, judge))}


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    c = confusion(human, judge)
    return (c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 0.0,
            c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 0.0)


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    c = confusion(human, judge)
    n = len(human)
    po = (c["tp"] + c["tn"]) / n
    pe = ((c["tp"] + c["fn"]) * (c["tp"] + c["fp"]) +
          (c["tn"] + c["fp"]) * (c["tn"] + c["fn"])) / n**2
    if pe == 1:
        raise ValueError("undefined kappa")
    return (po - pe) / (1 - pe)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1]."""
    import math
    if any(not math.isfinite(v) or not 0 <= v <= 1 for v in (observed_rate, sensitivity, specificity)):
        raise ValueError("rates must lie in [0, 1]")
    if sensitivity + specificity <= 1:
        raise ValueError("judge has no positive discriminating signal")
    return min(1.0, max(0.0, (observed_rate + specificity - 1) / (sensitivity + specificity - 1)))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    import numpy as np
    from scipy.stats import bootstrap
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.ndim != 1 or b.ndim != 1 or len(a) != len(b) or not len(a):
        raise ValueError("nonempty paired vectors required")
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("nonfinite observation")
    d = float(np.mean(a - b))
    if np.array_equal(a, b):
        return 0.0, 0.0, 0.0
    if len(a) == 1:
        return d, d, d
    res = bootstrap((a, b), lambda x, y, axis: np.mean(x - y, axis=axis),
                    paired=True, method="percentile", n_resamples=n_resamples,
                    confidence_level=confidence, rng=np.random.default_rng(rng))
    return d, float(res.confidence_interval.low), float(res.confidence_interval.high)


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    from math import comb
    _validate_counts(n, c, k)
    return 1 - comb(n - c, k) / comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    from math import comb
    _validate_counts(n, c, k)
    return comb(c, k) / comb(n, k)


def _validate_counts(n: int, c: int, k: int) -> None:
    if any(type(v) is not int for v in (n, c, k)) or not (n >= 1 and 0 <= c <= n and 1 <= k <= n):
        raise ValueError("require integer n >= 1, 0 <= c <= n, 1 <= k <= n")
