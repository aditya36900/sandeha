import time

import numpy as np
from PIL import Image

from sandeha.imagine import DEFECT_TYPES, imagine


def _part():
    a = np.full((400, 400, 3), 30, np.uint8)
    a[80:320, 80:320] = (160, 170, 180)
    return Image.fromarray(a)


def test_every_defect_type_changes_the_part_and_has_a_mask():
    rng = np.random.default_rng(0)
    img = _part()
    for kind in DEFECT_TYPES:
        x = imagine(img, kind, 40, rng, donor=img.rotate(90))
        assert x.mask.sum() > 0, kind
        assert np.abs(np.asarray(x.image, int) - np.asarray(img, int)).sum() > 0, kind


def test_imagination_is_fast_on_large_images():
    big = _part().resize((1600, 1600))
    t = time.time()
    imagine(big, "stain", 160, np.random.default_rng(1))
    assert time.time() - t < 2.0
