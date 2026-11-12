import numpy as np
import pytest

from sandeha import data
from sandeha.twin import Twin, load_view


@pytest.mark.skipif(not data.MAD_ROOT.exists(), reason="MAD-Sim not downloaded")
def test_space_carving_builds_a_bounded_surface():
    p = data.load_mad("01Gorilla")
    views = [load_view(s.path, s.pose, p.fov_x, size=200) for s in p.train_good[:12]]
    tw = Twin(64, 1.0)
    occ = [tw.carve(v) for v in views]
    assert occ[-1] < occ[0] < 64 ** 3  # carving removes empty space
    ex = tw.export(max_points=5000)
    assert 500 < ex["count"] <= 5000
    assert np.abs(np.array(ex["positions"])).max() <= 1.0 + 1e-6
    assert 0 < tw.coverage()["covered"] <= 1
