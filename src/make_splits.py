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
OFFICIAL_DIR = ROOT / "data" / "external" / "boucheron2023"

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


def load_official_splits(path: str | Path = OFFICIAL_DIR) -> pd.DataFrame:
    """Load the image team's official AR split lists (Boucheron et al. 2023).

    The release (Dryad doi:10.5061/dryad.jq2bvq898, mirrored on Zenodo record
    7807466, CC0) ships List_of_AR_in_{Train,Validation,Test}_Data_by_AR.csv:
    one NOAA AR per line as a *four-digit* number (1325 = NOAA 11325); the
    validation file name varies in case/punctuation between mirrors. Copies are
    in data/external/boucheron2023/.

    `path` is that directory, or a single CSV with columns (NOAA_AR, split).
    Returns a DataFrame (NOAA_AR, split) with five-digit NOAA numbers.
    """
    path = Path(path)

    def read_ars(f: Path) -> pd.Series:
        t = pd.read_csv(f, header=None, comment="#", sep=r"[,\s]+", engine="python")
        return pd.to_numeric(t.stack(), errors="coerce").dropna().astype("int64").reset_index(drop=True)

    if path.is_file():
        s = pd.read_csv(path)
        s.columns = [c.strip() for c in s.columns]
        s = s.rename(columns={"AR": "NOAA_AR"})[["NOAA_AR", "split"]]
    else:
        rows = []
        for split, word in [("train", "train"), ("val", "validation"), ("test", "test")]:
            files = sorted(f for f in path.iterdir()
                           if f.name.lower().startswith((word, split, f"list_of_ar_in_{word}")))
            if len(files) != 1:
                raise FileNotFoundError(f"expected one {word} list in {path}, found {files}")
            rows.append(pd.DataFrame({"NOAA_AR": read_ars(files[0]), "split": split}))
        s = pd.concat(rows, ignore_index=True)
    s["NOAA_AR"] = s["NOAA_AR"].astype("int64")
    # SWPC four-digit AR numbers: all ARs in 2010-2018 are 11xxx/12xxx
    s.loc[s["NOAA_AR"] < 10000, "NOAA_AR"] += 10000
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
    ap.add_argument("--official", nargs="?", const=str(OFFICIAL_DIR),
                    help="use official AR lists (default dir: data/external/boucheron2023)")
    ap.add_argument("--no-stratify", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT, help="output CSV (default: data/processed/splits.csv)")
    args = ap.parse_args()

    df = pd.read_parquet(LABELED, columns=["NOAA_AR", "T_REC", "y"])
    if args.official:
        splits = load_official_splits(args.official)
    else:
        splits = random_ar_split(df, stratify=not args.no_stratify)
    check_and_report(df, splits)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    splits.to_csv(args.out, index=False)
    print(f"\nSaved {args.out}: {len(splits)} ARs")


if __name__ == "__main__":
    main()
