"""Clean hourly SHARP rows and attach GOES flare labels.

Inputs (untouched raw pulls):
    data/raw/sharp_hourly_raw.parquet
    data/raw/goes_flares_raw.parquet
Output:
    data/processed/sharp_labeled.parquet, keyed by (NOAA_AR, T_REC)

Labels for a row (NOAA_AR, t):
    max_flux_24h    = max GOES peak flux of flares from NOAA_AR with peak in (t, t+24h]; 0 if none
    y               = max_flux_24h >= 1e-5 (>= M1.0)
    prior_flare_48h = max GOES peak flux of flares from NOAA_AR with peak in (t-48h, t]; 0 if none
The two windows are half-open at t, so they never overlap.

Time scales: T_REC is TAI (kept as-is for the key so it matches JSOC / the
image track); HEK flare times are UTC. Matching is done on T_REC converted to
UTC via the leap-second table below.

Options for decisions still open with the image team (defaults = spec):
    --allow-quality 0x80     keep rows whose only QUALITY bits are in this mask
    --label-ars all          label a row with flares from every NOAA AR in the
                             HARP (NOAA_ARS), not only the primary NOAA_AR

Usage:
    python src/build_labels.py [--allow-quality MASK] [--label-ars primary|all]
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SHARP_RAW = ROOT / "data" / "raw" / "sharp_hourly_raw.parquet"
FLARES_RAW = ROOT / "data" / "raw" / "goes_flares_raw.parquet"
OUT = ROOT / "data" / "processed" / "sharp_labeled.parquet"

FEATURES = ["USFLUX", "TOTUSJH", "TOTPOT", "MEANPOT", "SAVNCPP", "R_VALUE",
            "MEANSHR", "SHRGT45", "TOTUSJZ", "AREA_ACR", "MEANGBZ",
            "ABSNJZH", "MEANGAM", "MEANGBT", "MEANGBH", "MEANJZD", "MEANJZH", "MEANALP"]
LON_MAX = 60.0
M_CLASS = 1e-5
CLASS_FLUX = {"A": 1e-8, "B": 1e-7, "C": 1e-6, "M": 1e-5, "X": 1e-4}

# TAI - UTC (seconds), effective from the given UTC instant
LEAP_SECONDS = [("2009-01-01", 34), ("2012-07-01", 35), ("2015-07-01", 36), ("2017-01-01", 37)]


def tai_to_utc(t_tai: pd.Series) -> pd.Series:
    edges = pd.to_datetime([d for d, _ in LEAP_SECONDS])
    offs = np.array([s for _, s in LEAP_SECONDS])
    idx = np.searchsorted(edges.values, t_tai.values, side="right") - 1
    if (idx < 0).any():
        raise ValueError("T_REC before leap-second table start")
    return t_tai - pd.to_timedelta(offs[idx], unit="s")


def goes_class_to_flux(cls: pd.Series) -> pd.Series:
    s = cls.str.strip().str.upper()
    letter = s.str[:1]
    mult = pd.to_numeric(s.str[1:], errors="coerce")
    return letter.map(CLASS_FLUX) * mult


def clean_sharp(raw: pd.DataFrame, allow_quality: int = 0) -> pd.DataFrame:
    df = raw.copy()
    df["T_REC"] = pd.to_datetime(df["T_REC"].str.replace("_TAI", ""), format="%Y.%m.%d_%H:%M:%S")

    print(f"raw SHARP rows:                    {len(df):8d}")
    steps = [
        (f"QUALITY bits outside {allow_quality:#x}" if allow_quality else "QUALITY != 0",
         (df["QUALITY"] & ~allow_quality) != 0),
        ("NOAA_AR == 0", df["NOAA_AR"] == 0),
        ("NaN in features", df[FEATURES].isna().any(axis=1)),
        (f"|LON_FWT| > {LON_MAX:g} (or NaN)", ~(df["LON_FWT"].abs() <= LON_MAX)),
    ]
    keep = pd.Series(True, index=df.index)
    for name, bad in steps:
        dropped = (keep & bad).sum()
        keep &= ~bad
        print(f"  drop {name:28s} {dropped:8d}  -> {keep.sum():8d}")
    df = df[keep]

    # A NOAA AR can be the primary AR of more than one HARP at the same T_REC.
    # Keep the larger patch so (NOAA_AR, T_REC) is a unique key.
    dup = df.duplicated(["NOAA_AR", "T_REC"], keep=False)
    n_before, n_ars = len(df), df.loc[dup, "NOAA_AR"].nunique()
    df = df.sort_values("AREA_ACR", ascending=False).drop_duplicates(["NOAA_AR", "T_REC"])
    print(f"  drop duplicate (NOAA_AR, T_REC)  {n_before - len(df):8d}  -> {len(df):8d}"
          f"  ({n_ars} ARs affected, kept larger AREA_ACR)")
    return df.sort_values(["NOAA_AR", "T_REC"]).reset_index(drop=True)


def clean_flares(raw: pd.DataFrame) -> pd.DataFrame:
    cols = ["event_starttime", "event_peaktime", "event_endtime", "fl_goescls", "ar_noaanum"]
    f = raw.drop_duplicates(subset=cols)[cols].copy()
    print(f"\nraw flare rows: {len(raw)}, after dedup across yearly queries: {len(f)}")
    f["peak"] = pd.to_datetime(f["event_peaktime"])
    f["flux"] = goes_class_to_flux(f["fl_goescls"])
    bad_cls = f["flux"].isna()
    no_ar = f["ar_noaanum"].isna() | (f["ar_noaanum"] <= 0)
    print(f"  drop unparseable class:        {bad_cls.sum():6d}")
    print(f"  drop missing/zero AR number:   {(no_ar & ~bad_cls).sum():6d} "
          f"(of which >=M1.0: {(no_ar & ~bad_cls & (f['flux'] >= M_CLASS)).sum()})")
    f = f[~bad_cls & ~no_ar].copy()
    f["ar"] = f["ar_noaanum"].astype("int64")
    print(f"  usable flares: {len(f)} (>=M1.0: {(f['flux'] >= M_CLASS).sum()})")
    return f[["ar", "peak", "flux", "fl_goescls"]]


def window_max(t: np.ndarray, peaks: np.ndarray, flux: np.ndarray,
               lo_off: np.timedelta64, hi_off: np.timedelta64) -> np.ndarray:
    """Max flux of flares with peak in (t + lo_off, t + hi_off], 0 if none.

    peaks must be sorted. Uses searchsorted to find each row's flare index
    range [lo, hi), then a masked max over the (small) per-AR flare list.
    """
    if len(peaks) == 0:
        return np.zeros(len(t))
    lo = np.searchsorted(peaks, t + lo_off, side="right")
    hi = np.searchsorted(peaks, t + hi_off, side="right")
    j = np.arange(len(peaks))
    mask = (j >= lo[:, None]) & (j < hi[:, None])
    return np.where(mask, flux[None, :], 0.0).max(axis=1)


def row_ars(df: pd.DataFrame, label_ars: str) -> pd.DataFrame:
    """(row, ar) pairs saying whose flares count for each row."""
    if label_ars == "primary":
        return pd.DataFrame({"row": np.arange(len(df)), "ar": df["NOAA_AR"].to_numpy()})
    ars = df["NOAA_ARS"].astype(str).str.split(",")
    pairs = pd.DataFrame({"row": np.arange(len(df)), "ar": ars.to_numpy()}).explode("ar")
    pairs["ar"] = pd.to_numeric(pairs["ar"].str.strip(), errors="coerce")
    primary = pd.DataFrame({"row": np.arange(len(df)), "ar": df["NOAA_AR"].to_numpy()})
    pairs = pd.concat([primary, pairs.dropna()]).astype("int64").drop_duplicates()
    return pairs[pairs["ar"] > 0]


def add_labels(df: pd.DataFrame, flares: pd.DataFrame, label_ars: str = "primary") -> pd.DataFrame:
    t_utc = tai_to_utc(df["T_REC"]).to_numpy()
    h24, h48, zero = np.timedelta64(24, "h"), np.timedelta64(48, "h"), np.timedelta64(0, "h")
    max24 = np.zeros(len(df))
    prior48 = np.zeros(len(df))
    fl_by_ar = {ar: g.sort_values("peak") for ar, g in flares.groupby("ar")}
    pairs = row_ars(df, label_ars)
    for ar, g_rows in pairs.groupby("ar")["row"]:
        g = fl_by_ar.get(ar)
        if g is None:
            continue
        idx = g_rows.to_numpy()
        t = t_utc[idx]
        peaks, flux = g["peak"].values, g["flux"].values
        np.maximum.at(max24, idx, window_max(t, peaks, flux, zero, h24))      # (t, t+24h]
        np.maximum.at(prior48, idx, window_max(t, peaks, flux, -h48, zero))   # (t-48h, t]
    out = df.copy()
    out["max_flux_24h"] = max24
    out["y"] = (max24 >= M_CLASS).astype("int8")
    out["prior_flare_48h"] = prior48
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-quality", type=lambda x: int(x, 0), default=0,
                    help="QUALITY bit mask to tolerate, e.g. 0x80 (default: none)")
    ap.add_argument("--label-ars", choices=["primary", "all"], default="primary",
                    help="whose flares label a row: primary NOAA_AR or all ARs in NOAA_ARS")
    args = ap.parse_args()
    print(f"config: allow_quality={args.allow_quality:#x}, label_ars={args.label_ars}\n")

    raw = pd.read_parquet(SHARP_RAW)
    df = clean_sharp(raw, args.allow_quality)
    flares = clean_flares(pd.read_parquet(FLARES_RAW))

    # how many usable >=M flares have no matching primary NOAA_AR in the cleaned table
    big = flares[flares["flux"] >= M_CLASS]
    in_table = big["ar"].isin(df["NOAA_AR"].unique())
    print(f"  >=M1.0 flares whose AR has no cleaned SHARP rows: {(~in_table).sum()} of {len(big)} "
          f"(on disk far side / beyond +-60 deg / secondary AR in a HARP / out of date range)")

    df = add_labels(df, flares, args.label_ars)
    assert not df.duplicated(["NOAA_AR", "T_REC"]).any()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)

    print(f"\nSaved {OUT.relative_to(ROOT)}: {len(df)} rows, {df['NOAA_AR'].nunique()} unique NOAA ARs")
    print(f"positives (y=1): {df['y'].sum()} ({df['y'].mean():.2%})")
    print(f"rows with prior_flare_48h >= M1.0: {(df['prior_flare_48h'] >= M_CLASS).mean():.2%}")
    by_year = df.groupby(df["T_REC"].dt.year).agg(rows=("y", "size"), positives=("y", "sum"),
                                                   pos_pct=("y", "mean"), ARs=("NOAA_AR", "nunique"))
    by_year["pos_pct"] = (100 * by_year["pos_pct"]).round(2)
    print("\nrows per year:\n" + by_year.to_string())


if __name__ == "__main__":
    main()
