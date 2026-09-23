"""Fetch hourly SHARP keywords from JSOC (hmi.sharp_cea_720s).

Queries month by month (yearly queries are ~120k rows and prone to timeouts),
saving each month to data/raw/sharp_chunks/YYYY-MM.parquet. Months whose chunk
already exists are skipped, so the script is resumable. At the end all chunks
are concatenated, untouched, into data/raw/sharp_hourly_raw.parquet.

Usage:
    python src/fetch_sharp.py --test          # one month (2014-01), print summary
    python src/fetch_sharp.py                 # full range 2010-05 .. 2018-12
"""

import argparse
import time
from pathlib import Path

import drms
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CHUNK_DIR = ROOT / "data" / "raw" / "sharp_chunks"
OUT = ROOT / "data" / "raw" / "sharp_hourly_raw.parquet"

SERIES = "hmi.sharp_cea_720s"
KEYS = [
    "HARPNUM", "NOAA_AR", "NOAA_ARS", "T_REC", "QUALITY", "LON_FWT", "LAT_FWT",
    "USFLUX", "TOTUSJH", "TOTPOT", "MEANPOT", "SAVNCPP", "R_VALUE", "MEANSHR",
    "SHRGT45", "TOTUSJZ", "AREA_ACR", "MEANGBZ",
]
START, END = "2010-05-01", "2018-12-31"
RETRIES = 5
SLEEP = 3  # seconds between successful calls


def month_query(month: pd.Period) -> str:
    # start/duration form covers [start, start + ndays) with no overlap between months
    start = month.start_time.strftime("%Y.%m.%d_00:00:00_TAI")
    return f"{SERIES}[][{start}/{month.days_in_month}d@1h]"


def fetch_month(client: drms.Client, month: pd.Period) -> pd.DataFrame:
    q = month_query(month)
    for attempt in range(1, RETRIES + 1):
        try:
            return client.query(q, key=",".join(KEYS))
        except Exception as e:  # network / JSOC errors
            wait = 10 * attempt
            print(f"  {month} attempt {attempt}/{RETRIES} failed: {e!r}; retry in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"JSOC query failed after {RETRIES} attempts: {q}")


def fetch_all(months) -> None:
    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    client = drms.Client()
    for m in months:
        path = CHUNK_DIR / f"{m}.parquet"
        if path.exists():
            print(f"{m}: already fetched, skipping")
            continue
        t0 = time.time()
        df = fetch_month(client, m)
        df.to_parquet(path, index=False)
        print(f"{m}: {len(df):6d} rows, {df['HARPNUM'].nunique() if len(df) else 0:3d} HARPs "
              f"({time.time() - t0:.0f}s)", flush=True)
        time.sleep(SLEEP)


def combine(months) -> pd.DataFrame:
    missing = [str(m) for m in months if not (CHUNK_DIR / f"{m}.parquet").exists()]
    if missing:
        raise RuntimeError(f"missing chunks, rerun fetch: {missing}")
    df = pd.concat([pd.read_parquet(CHUNK_DIR / f"{m}.parquet") for m in months],
                   ignore_index=True)
    df.to_parquet(OUT, index=False)
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="fetch one month (2014-01) only")
    args = ap.parse_args()

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)

    if args.test:
        df = fetch_month(drms.Client(), pd.Period("2014-01", "M"))
        print(df.head())
        print(df.dtypes)
        print("rows:", len(df))
        return

    months = pd.period_range(START, END, freq="M")
    fetch_all(months)
    df = combine(months)
    print(f"\nSaved {OUT.relative_to(ROOT)}: {len(df)} rows, {df['HARPNUM'].nunique()} HARPs, "
          f"T_REC {df['T_REC'].min()} .. {df['T_REC'].max()}")


if __name__ == "__main__":
    main()
