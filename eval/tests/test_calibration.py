import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import calibration as C


def test_perfectly_calibrated_has_zero_ece():
    conf = [0.5] * 10
    correct = [1] * 5 + [0] * 5
    assert C.ece(conf, correct) == 0.0 and C.brier(conf, correct) == 0.25


def test_overconfident_model_has_large_ece():
    conf, correct = [0.95] * 20, [1] * 10 + [0] * 10
    assert C.ece(conf, correct) == 0.45


def test_isotonic_is_monotone_and_reduces_error():
    rng = np.random.default_rng(0)
    conf = rng.uniform(0.5, 1.0, 400)
    correct = (rng.uniform(size=400) < (conf - 0.25)).astype(int)         # the model is overconfident by 0.25
    iso = C.Isotonic.fit(conf, correct)
    grid = iso(np.linspace(0.5, 1, 50))
    assert np.all(np.diff(grid) >= -1e-12)
    assert C.ece(iso(conf), correct) < C.ece(conf, correct) / 2


def test_pav_merges_violations():
    iso = C.Isotonic.fit([0.1, 0.2, 0.3, 0.4], [0, 1, 0, 1])
    assert iso(0.25) == iso(0.25) and list(np.round(iso([0.1, 0.4]), 2)) == [0.0, 1.0]
    assert all(b >= a for a, b in zip(iso.ys, iso.ys[1:], strict=False))


def test_save_and_load(tmp_path):
    iso = C.Isotonic.fit([0.2, 0.6, 0.9], [0, 1, 1])
    iso.save(tmp_path / "c.json")
    assert list(C.Isotonic.load(tmp_path / "c.json")([0.6])) == list(iso([0.6]))
    assert C.Isotonic.load(tmp_path / "missing.json") is None
