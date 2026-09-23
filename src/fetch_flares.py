"""Fetch the GOES (SWPC) flare list from HEK via sunpy Fido, year by year.

Saves data/raw/goes_flares_raw.parquet with columns
event_starttime, event_peaktime, event_endtime, fl_goescls, ar_noaanum, query_year.

NOTE: fl_goescls values are the *operational* NOAA/SWPC GOES classes. For events
before 2020 they are on the old scale, i.e. they include the 0.7 SWPC scaling
factor applied to GOES-13/14/15 fluxes (true 1-8 A flux = class flux / 0.7).
Do not mix these with reprocessed GOES-R / science-quality (rescaled) fluxes
or classes from other catalogues -- thresholds like >=M1.0 would shift.

HEK matches events that overlap the query window, so a flare straddling a year
boundary can appear in two yearly queries. The raw file keeps both copies
(tagged by query_year); build_labels.py deduplicates.

Usage:
    python src/fetch_flares.py
"""

import time
from pathlib import Path

import pandas as pd
from sunpy.net import Fido
from sunpy.net import attrs as a

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "goes_flares_raw.parquet"

COLS = ["event_starttime", "event_peaktime", "event_endtime", "fl_goescls", "ar_noaanum"]
YEARS = range(2010, 2019)  # 2010 from Jan 1 so labels near 2010-05-01 see prior flares
RETRIES = 5


def fetch_year(year: int) -> pd.DataFrame:
    for attempt in range(1, RETRIES + 1):
        try:
            res = Fido.search(
                a.Time(f"{year}-01-01", f"{year + 1}-01-01"),
                a.hek.EventType("FL"),
                a.hek.FRM.Name == "SWPC",
            )
            t = res["hek"]
            df = pd.DataFrame({
                "event_starttime": t["event_starttime"].isot,
                "event_peaktime": t["event_peaktime"].isot,
                "event_endtime": t["event_endtime"].isot,
                "fl_goescls": [str(x) for x in t["fl_goescls"]],
                "ar_noaanum": pd.array(t["ar_noaanum"].filled(0) if hasattr(t["ar_noaanum"], "filled")
                                       else t["ar_noaanum"], dtype="Int64"),
            })
            df["query_year"] = year
            return df
        except Exception as e:
            wait = 15 * attempt
            print(f"  {year} attempt {attempt}/{RETRIES} failed: {e!r}; retry in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"HEK query failed after {RETRIES} attempts for {year}")


def main() -> None:
    parts = []
    for y in YEARS:
        df = fetch_year(y)
        print(f"{y}: {len(df)} flares", flush=True)
        parts.append(df)
        time.sleep(3)
    df = pd.concat(parts, ignore_index=True)
    df.to_parquet(OUT, index=False)

    print(f"\nSaved {OUT.relative_to(ROOT)}: {len(df)} rows")
    dup = df.duplicated(subset=COLS).sum()
    print(f"duplicate rows across yearly queries: {dup}")
    uniq = df.drop_duplicates(subset=COLS)
    print(f"total unique flares: {len(uniq)}")
    letter = uniq["fl_goescls"].str[:1].replace("", "<empty>")
    print("count by class letter:\n" + letter.value_counts().sort_index().to_string())
    no_ar = uniq["ar_noaanum"].isna() | (uniq["ar_noaanum"] == 0)
    print(f"missing/zero AR number: {no_ar.sum()} ({no_ar.mean():.1%})")
    big = uniq["fl_goescls"].str[:1].isin(["M", "X"])
    print(f"  of which >=M: {(no_ar & big).sum()} of {big.sum()} M/X flares")


if __name__ == "__main__":
    main()
