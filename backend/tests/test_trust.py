import numpy as np

from sandeha.trust import Calibrator, conformal_upper, lower_quantile, outcome_stats, risk_coverage


def test_conformal_coverage_holds_on_exchangeable_data():
    rng = np.random.default_rng(0)
    misses = 0
    for _ in range(2000):
        x = rng.normal(size=31)
        misses += x[30] > conformal_upper(x[:30], 0.1)
    assert misses / 2000 <= 0.1 + 0.02


def test_lower_quantile_bounds_defect_escapes():
    d = np.arange(1, 101) / 100.0
    t = lower_quantile(d, 0.05)
    assert np.mean(d <= t) <= 0.05


def test_calibrator_spends_budget_but_never_moves_fail_line():
    rng = np.random.default_rng(1)
    good = rng.normal(0.1, 0.01, 30)
    defects = rng.normal(0.2, 0.03, 60)
    c = Calibrator(good, defects, alpha_fr=0.02, budget=0.10)
    p = c.policy
    assert p.tau_pass <= p.tau_fail
    assert p.expected_review_good <= 0.10 + 1e-9
    # an autopilot override can raise the pass line, but never above the fail line
    assert c.decide(p.tau_fail * 0.99, tau_pass=10.0)[0] == "PASS"
    assert c.decide(p.tau_fail * 1.01, tau_pass=10.0)[0] == "FAIL"


def test_review_band_catches_defects_a_single_threshold_misses():
    rng = np.random.default_rng(2)
    s = np.concatenate([rng.normal(0.1, 0.02, 900), rng.normal(0.16, 0.03, 100)])
    y = np.r_[np.zeros(900), np.ones(100)]
    single = outcome_stats(s, y, 0.14, 0.14)
    banded = outcome_stats(s, y, 0.12, 0.14)
    assert banded["escape_rate"] < single["escape_rate"]
    rc = risk_coverage(s, y, 0.14)
    assert rc["escape"][0] >= rc["escape"][-1]  # more human review -> fewer escapes
