import numpy as np
from PIL import Image

from sandeha.shift import Conditions, ShiftGuard, perturb


def test_no_false_alarm_on_exchangeable_stream():
    alarms = 0
    for seed in range(20):
        rng = np.random.default_rng(seed)
        g = ShiftGuard(rng.normal(size=30), rng.normal(size=30))
        for _ in range(300):
            g.update(rng.normal(), rng.normal())
        alarms += g.alarmed
    assert alarms <= 1  # empirical false-alarm rate of the median-filtered martingale


def test_alarm_on_whole_line_shift_but_not_on_defect_minority():
    rng = np.random.default_rng(0)
    g = ShiftGuard(rng.normal(size=30), rng.normal(size=30))
    for _ in range(200):  # 30% of parts are defects with extreme local scores
        g.update(rng.normal(), 5.0 if rng.random() < 0.3 else rng.normal())
    assert not g.alarmed
    for _ in range(30):  # now every part shifts
        g.update(rng.normal() + 3, rng.normal() + 3)
    assert g.alarmed


def test_perturb_identity_and_change():
    img = Image.new("RGB", (64, 64), (120, 130, 140))
    assert np.array_equal(np.asarray(perturb(img, Conditions())), np.asarray(img))
    out = perturb(img, Conditions(brightness=0.5))
    assert np.asarray(out).mean() < np.asarray(img).mean()
