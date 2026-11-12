"""Stage DOUBT ENGINE: calibrated abstention.

Two calibrated thresholds split every part into three outcomes:

    score <= tau_pass            -> PASS   (auto)
    tau_pass < score <= tau_fail -> DOUBT  (human review)
    score >  tau_fail            -> FAIL   (auto)

* tau_fail comes from split-conformal calibration on held-out (leave-one-out) GOOD scores:
  P(good part auto-FAILed) <= alpha_fr  (finite-sample, distribution-free).
* tau_pass comes from the lower tail of DEFECT scores (real few-shot defects plus synthetic
  "imagined" defects): estimated P(defect auto-PASSed) <= beta. With only a handful of real
  defects this is an *estimate*, reported as such together with its uncertainty.
* If the review band would exceed the human budget, tau_pass is raised until it fits and the
  promised escape rate is updated honestly.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np


def conformal_upper(scores: np.ndarray, alpha: float) -> float:
    """Smallest t with (n+1)-corrected coverage: P(new good score > t) <= alpha."""
    s = np.sort(np.asarray(scores, dtype=np.float64))
    n = len(s)
    k = math.ceil((n + 1) * (1 - alpha))
    return float(s[-1] * 1.0001) if k > n else float(s[k - 1])


def lower_quantile(scores: np.ndarray, beta: float) -> float:
    """Conservative lower quantile: at most ~beta of defect scores fall at or below it."""
    s = np.sort(np.asarray(scores, dtype=np.float64))
    n = len(s)
    k = math.floor((n + 1) * beta)  # number of defects allowed below
    return float(s[0] * 0.9999) if k < 1 else float(s[k - 1])


def p_value(score: float, calib: np.ndarray) -> float:
    calib = np.asarray(calib)
    return float((1 + np.sum(calib >= score)) / (len(calib) + 1))


def wilson_upper(k: int, n: int, z: float = 1.645) -> float:
    if n == 0:
        return 1.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    rad = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return float(min(1.0, (centre + rad) / den))


@dataclass
class Policy:
    tau_pass: float
    tau_fail: float
    alpha_fr: float
    beta: float
    budget: float
    expected_review_good: float
    promised_escape: float
    escape_upper_90: float
    n_good_calib: int
    n_defect_calib: int
    budget_limited: bool

    def to_dict(self) -> dict:
        return asdict(self)


class Calibrator:
    def __init__(self, good_scores, defect_scores, alpha_fr: float = 0.02, beta: float = 0.05,
                 budget: float = 0.10, spend_budget: bool = True, target_prevalence: float = 0.03):
        self.good = np.asarray(good_scores, dtype=np.float64)
        self.defect = np.asarray(defect_scores, dtype=np.float64)
        self.alpha_fr, self.beta, self.budget = alpha_fr, beta, budget
        self.spend_budget, self.prev = spend_budget, target_prevalence
        self.policy = self._fit()

    def _fit(self) -> Policy:
        tau_fail = conformal_upper(self.good, self.alpha_fr)
        tau_pass = lower_quantile(self.defect, self.beta) if len(self.defect) else tau_fail
        if self.spend_budget:
            # Unused review capacity is wasted safety: widen the review band until the expected
            # share of GOOD parts sent to a human uses ~65% of the budget (test-time good parts vary
            # more than leave-one-out references; measured on VisA, 90% overshot the budget).
            q = max(0.0, 1 - self.alpha_fr - 0.65 * self.budget / max(1 - self.prev, 1e-9))
            tau_pass = min(tau_pass, float(np.quantile(self.good, q)))
        tau_pass = min(tau_pass, tau_fail)
        limited = False
        # budget: share of GOOD parts landing in the review band must fit the human budget
        review_good = float(np.mean((self.good > tau_pass) & (self.good <= tau_fail)))
        if review_good > self.budget:
            limited = True
            # raise tau_pass to the (1 - budget - alpha_fr) quantile of good scores
            q = np.quantile(self.good, max(0.0, 1 - self.budget - self.alpha_fr))
            tau_pass = float(min(max(tau_pass, q), tau_fail))
            review_good = float(np.mean((self.good > tau_pass) & (self.good <= tau_fail)))
        k = int(np.sum(self.defect <= tau_pass))
        n = len(self.defect)
        return Policy(tau_pass=tau_pass, tau_fail=tau_fail, alpha_fr=self.alpha_fr, beta=self.beta,
                      budget=self.budget, expected_review_good=review_good,
                      promised_escape=(k / n) if n else float("nan"), escape_upper_90=wilson_upper(k, n),
                      n_good_calib=len(self.good), n_defect_calib=n, budget_limited=limited)

    def decide(self, score: float, tau_pass: float | None = None) -> tuple[str, float]:
        """Returns (decision, uncertainty in [0,1]). `tau_pass` overrides the calibrated pass line
        (review-budget autopilot); the fail line is never moved."""
        p = self.policy
        tp = p.tau_pass if tau_pass is None else min(tau_pass, p.tau_fail)
        if score > p.tau_fail:
            margin = math.log(score / p.tau_fail)
            return "FAIL", float(math.exp(-6 * margin))
        if score <= tp:
            margin = math.log(tp / max(score, 1e-9))
            return "PASS", float(math.exp(-6 * margin))
        lo, hi = math.log(max(tp, 1e-9)), math.log(p.tau_fail)
        mid = (lo + hi) / 2
        u = 1 - abs(math.log(max(score, 1e-9)) - mid) / max((hi - lo) / 2, 1e-9) * 0.4
        return "DOUBT", float(np.clip(u, 0.6, 1.0))


# --------------------------------------------------------------------------- evaluation
def outcome_stats(scores, labels, tau_pass, tau_fail) -> dict:
    s, y = np.asarray(scores), np.asarray(labels)
    passed, failed = s <= tau_pass, s > tau_fail
    review = ~passed & ~failed
    nd, ng = max(int(y.sum()), 1), max(int((1 - y).sum()), 1)
    rg = float(review[y == 0].mean()) if (y == 0).any() else 0.0
    rd = float(review[y == 1].mean()) if (y == 1).any() else 0.0
    return {
        "review_rate": float(review.mean()),
        "review_good": rg,
        "review_defect": rd,
        # what the line would see at a realistic 3% defect prevalence
        "review_rate_at_3pct": 0.97 * rg + 0.03 * rd,
        "escape_rate": float((passed & (y == 1)).sum() / nd),  # defects auto-passed / defects
        "false_reject_rate": float((failed & (y == 0)).sum() / ng),  # good auto-failed / good
        "auto_accuracy": float(((passed & (y == 0)) | (failed & (y == 1))).sum() / max((~review).sum(), 1)),
    }


def risk_coverage(scores, labels, tau_fail: float, points: int = 41) -> dict:
    """Defect-escape rate as a function of the share of parts sent to a human.

    For each review budget b, the b-fraction of parts with the highest scores *below* tau_fail
    (the ones most likely to be hidden defects) is reviewed; the rest of the sub-threshold parts
    are auto-passed. Risk = defects auto-passed / all defects.
    """
    s, y = np.asarray(scores), np.asarray(labels)
    n, nd = len(s), max(int(y.sum()), 1)
    below = np.where(s <= tau_fail)[0]
    order = below[np.argsort(-s[below])]
    budgets = np.linspace(0, 0.3, points)
    risk = []
    for b in budgets:
        k = int(round(b * n))
        auto = order[k:]
        risk.append(float((y[auto] == 1).sum() / nd))
    risk = np.array(risk)
    aurc = float(np.trapezoid(risk, budgets) / (budgets[-1] - budgets[0]))
    return {"review": budgets.tolist(), "escape": risk.tolist(), "aurc": aurc}


def random_abstention(scores, labels, tau: float, budget: float, rng=None) -> float:
    rng = rng or np.random.default_rng(0)
    s, y = np.asarray(scores), np.asarray(labels)
    n, nd = len(s), max(int(y.sum()), 1)
    rev = rng.random(n) < budget
    return float(((s <= tau) & ~rev & (y == 1)).sum() / nd)
