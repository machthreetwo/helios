"""Split the labeled table by NOAA active region (never by row).

Default: 80/10/10 train/val/test over unique NOAA ARs with a fixed seed,
stratified on whether the AR ever has a y=1 row, so each split gets a similar
share of flaring regions. Saves data/processed/splits.csv (NOAA_AR, split).

To use the image team's official AR lists (Boucheron et al. 2023 Dryad
release) instead, see load_official_splits() and run with --official PATH.

Usage:
    python src/make_splits.py
    python src/make_splits.py --official path/to/official_splits
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LABELED = ROOT / "data" / "processed" / "sharp_labeled.parquet"
OUT = ROOT / "data" / "processed" / "splits.csv"

SEED = 42
FRACS = {"train": 0.8, "val": 0.1, "test": 0.1}


def random_ar_split(df: pd.DataFrame, seed: int = SEED, stratify: bool = True) -> pd.DataFrame:
    ar_pos = df.groupby("NOAA_AR")["y"].max()
    groups = [ar_pos[ar_pos == v].index.to_numpy() for v in (1, 0)] if stratify \
        else [ar_pos.index.to_numpy()]
    rng = np.random.default_rng(seed)
    parts = []
    for ars in groups:
        ars = rng.permutation(np.sort(ars))
        n_train = int(round(FRACS["train"] * len(ars)))
        n_val = int(round(FRACS["val"] * len(ars)))
        labels = np.array(["train"] * n_train + ["val"] * n_val
                          + ["test"] * (len(ars) - n_train - n_val))
        parts.append(pd.DataFrame({"NOAA_AR": ars, "split": labels}))
    return pd.concat(parts).sort_values("NOAA_AR").reset_index(drop=True)


def load_official_splits(path: str | Path) -> pd.DataFrame:
    """Load the image team's official AR split lists (Boucheron et al. 2023, Dryad).

    The exact file layout of that release should be confirmed with the image
    team; this accepts either:
      * a directory containing train/val/test files (any of .txt/.csv), each
        listing NOAA AR numbers (one per line, or a column named NOAA_AR / AR), or
      * a single CSV with columns (NOAA_AR, split).
    Returns a DataFrame (NOAA_AR, split).
    """
    path = Path(path)

    def read_ars(f: Path) -> pd.Series:
        t = pd.read_csv(f, header=None, comment="#", sep=r"[,\s]+", engine="python")
        vals = pd.to_numeric(t.stack(), errors="coerce").dropna().astype("int64")
        return vals.reset_index(drop=True)

    if path.is_file():
        s = pd.read_csv(path)
        s.columns = [c.strip() for c in s.columns]
        s = s.rename(columns={"AR": "NOAA_AR"})[["NOAA_AR", "split"]]
    else:
        rows = []
        for split in FRACS:
            files = sorted(p for p in path.iterdir() if p.stem.lower().startswith(split))
            if len(files) != 1:
                raise FileNotFoundError(f"expected one '{split}*' file in {path}, found {files}")
            rows.append(pd.DataFrame({"NOAA_AR": read_ars(files[0]), "split": split}))
        s = pd.concat(rows, ignore_index=True)
    s["NOAA_AR"] = s["NOAA_AR"].astype("int64")
    s["split"] = s["split"].str.lower().replace({"validation": "val"})
    return s.drop_duplicates().sort_values("NOAA_AR").reset_index(drop=True)


def check_and_report(df: pd.DataFrame, splits: pd.DataFrame) -> None:
    per_ar = splits.groupby("NOAA_AR")["split"].nunique()
    assert (per_ar == 1).all(), f"ARs in >1 split: {per_ar[per_ar > 1].index.tolist()}"
    m = df.merge(splits, on="NOAA_AR", how="left")
    unassigned = m["split"].isna()
    if unassigned.any():
        print(f"WARNING: {m.loc[unassigned, 'NOAA_AR'].nunique()} ARs "
              f"({unassigned.sum()} rows) not in any split")
    rep = m.groupby("split").agg(ARs=("NOAA_AR", "nunique"), rows=("y", "size"),
                                 positives=("y", "sum"), pos_pct=("y", "mean"))
    rep["flaring_ARs"] = m[m["y"] == 1].groupby("split")["NOAA_AR"].nunique()
    rep["pos_pct"] = (100 * rep["pos_pct"]).round(2)
    rep["row_frac"] = (rep["rows"] / rep["rows"].sum()).round(3)
    print(rep.reindex(["train", "val", "test"]).to_string())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--official", help="path to official AR split lists (see load_official_splits)")
    ap.add_argument("--no-stratify", action="store_true")
    args = ap.parse_args()

    df = pd.read_parquet(LABELED, columns=["NOAA_AR", "T_REC", "y"])
    if args.official:
        splits = load_official_splits(args.official)
    else:
        splits = random_ar_split(df, stratify=not args.no_stratify)
    check_and_report(df, splits)
    splits.to_csv(OUT, index=False)
    print(f"\nSaved {OUT.relative_to(ROOT)}: {len(splits)} ARs")


if __name__ == "__main__":
    main()
