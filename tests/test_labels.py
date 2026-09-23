import numpy as np
import pandas as pd
import pytest

from build_labels import add_labels, goes_class_to_flux, tai_to_utc, window_max
from make_splits import random_ar_split


def test_goes_class_to_flux():
    got = goes_class_to_flux(pd.Series(["A1.0", "B2.5", "C1.0", "M1.0", "X9.3", " m2.3 ", "", "Z1"]))
    want = [1e-8, 2.5e-7, 1e-6, 1e-5, 9.3e-4, 2.3e-5, np.nan, np.nan]
    np.testing.assert_allclose(got.to_numpy(dtype=float), want, rtol=1e-12)


def test_tai_to_utc_leap_seconds():
    t = pd.Series(pd.to_datetime(["2011-01-01 00:00:34", "2016-01-01 00:00:36", "2018-01-01 00:00:37"]))
    assert (tai_to_utc(t) == pd.to_datetime(["2011-01-01", "2016-01-01", "2018-01-01"])).all()


def test_window_is_half_open():
    h = np.timedelta64(1, "h")
    t0 = np.datetime64("2014-01-01T00:00")
    t = np.array([t0])
    peaks = np.array([t0, t0 + 24 * h])  # one exactly at t, one exactly at t+24h
    flux = np.array([5e-5, 2e-6])
    # label window (t, t+24h]: excludes peak at t, includes peak at t+24h
    assert window_max(t, peaks, flux, np.timedelta64(0, "h"), 24 * h)[0] == 2e-6
    # prior window (t-48h, t]: includes peak at t
    assert window_max(t, peaks, flux, -48 * h, np.timedelta64(0, "h"))[0] == 5e-5


def test_add_labels_per_ar_and_no_overlap():
    t = pd.date_range("2014-01-01", periods=4, freq="h")  # TAI
    df = pd.DataFrame({"NOAA_AR": [1] * 4 + [2] * 4, "T_REC": list(t) * 2})
    # M2 flare for AR 1 at 02:30 UTC; nothing for AR 2
    flares = pd.DataFrame({"ar": [1], "peak": [pd.Timestamp("2014-01-01 02:30")],
                           "flux": [2e-5], "fl_goescls": ["M2.0"]})
    out = add_labels(df, flares)
    ar1, ar2 = out[out.NOAA_AR == 1], out[out.NOAA_AR == 2]
    assert ar1.y.tolist() == [1, 1, 1, 0]
    assert ar1.prior_flare_48h.tolist() == [0, 0, 0, 2e-5]
    assert (ar2.y == 0).all() and (ar2.max_flux_24h == 0).all()
    # a flare is never in both the label and prior window of the same row
    assert not ((out.max_flux_24h > 0) & (out.prior_flare_48h > 0)).any()


@pytest.mark.parametrize("stratify", [True, False])
def test_split_disjoint_and_deterministic(stratify):
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"NOAA_AR": np.repeat(np.arange(200), 5), "y": rng.random(1000) < 0.05})
    df["y"] = df["y"].astype(int)
    a = random_ar_split(df, stratify=stratify)
    b = random_ar_split(df, stratify=stratify)
    assert a.equals(b)
    assert a.NOAA_AR.is_unique and set(a.NOAA_AR) == set(df.NOAA_AR)
    assert a.split.value_counts().to_dict() == pytest.approx({"train": 160, "val": 20, "test": 20}, abs=2)
