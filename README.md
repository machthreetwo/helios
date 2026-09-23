# Solar flare prediction — SHARP tabular track: data pipeline

Builds a clean, labeled, hourly table of SHARP magnetic parameters for
2010-05-01 → 2018-12-31, keyed by `(NOAA_AR, T_REC)` and split by active
region. No model preprocessing or training lives here.

## Setup

```bash
uv venv --python 3.14 .venv            # or: python -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

`requirements.txt` pins the direct dependencies; `requirements.lock.txt` is the
full `pip freeze` of the environment used to build the data.

## Running the pipeline

| Step | Command | Output |
|---|---|---|
| 2. SHARP keywords | `python src/fetch_sharp.py --test` (one month), then `python src/fetch_sharp.py` | `data/raw/sharp_chunks/YYYY-MM.parquet`, `data/raw/sharp_hourly_raw.parquet` |
| 3. GOES flare list | `python src/fetch_flares.py` | `data/raw/goes_flares_raw.parquet` |
| 4. Clean + label | `python src/build_labels.py` | `data/processed/sharp_labeled.parquet` |
| 5. AR splits | `python src/make_splits.py` (or `--official PATH`) | `data/processed/splits.csv` |
| 6. Sanity checks | `jupyter nbconvert --to notebook --execute --inplace notebooks/data_checks.ipynb` | executed notebook |

`fetch_sharp.py` queries JSOC one month at a time, with retries. It skips any
month whose chunk already exists, so if it's interrupted you can rerun it and it
picks up where it stopped. The full pull takes roughly 45–90 minutes.
`fetch_flares.py` takes roughly 5 minutes per year because HEK paginates its results.

Raw files are never modified after fetching. All cleaning happens in `build_labels.py`.

## Data sources

- **SHARP**: JSOC series `hmi.sharp_cea_720s`, queried with `drms` at 1-hour
  cadence (`hmi.sharp_cea_720s[][<start>/<ndays>d@1h]`). Keywords: HARPNUM,
  NOAA_AR, NOAA_ARS, T_REC, QUALITY, LON_FWT, LAT_FWT, USFLUX, TOTUSJH, TOTPOT,
  MEANPOT, SAVNCPP, R_VALUE, MEANSHR, SHRGT45, TOTUSJZ, AREA_ACR, MEANGBZ.
- **Flares**: HEK via `sunpy.net.Fido`, `EventType("FL")`, `FRM.Name == "SWPC"`
  (the NOAA/SWPC GOES event list), 2010-01-01 → 2019-01-01. Columns kept:
  event_starttime, event_peaktime, event_endtime, fl_goescls, ar_noaanum.

## Cleaning (`build_labels.py`)

1. Parse `T_REC` (`2014.01.01_00:00:00_TAI`) to a datetime. The value stays in
   **TAI** so it matches JSOC and the image track.
2. Drop rows with `QUALITY != 0`, `NOAA_AR == 0`, or a NaN in any of the 11
   physics features (USFLUX … MEANGBZ).
3. Keep `|LON_FWT| <= 60°`, the same ±60° cohort the image team uses.
4. If two HARPs have the same primary `NOAA_AR` at the same `T_REC`, keep the
   one with the larger `AREA_ACR` so that `(NOAA_AR, T_REC)` stays unique.

The script prints how many rows each filter drops.

## Label definition

For each row `(NOAA_AR, t)`, where `t` is T_REC converted TAI→UTC with the
leap-second table, since HEK times are UTC:

- `max_flux_24h` = max GOES peak flux of SWPC flares attributed to that NOAA AR
  with peak time in **(t, t+24h]**; 0 if none.
- `y = 1` if `max_flux_24h >= 1e-5` (≥ M1.0), else 0.
- `prior_flare_48h` = max peak flux from the same AR with peak in **(t−48h, t]**.
  Both windows are half-open at `t`, so they never overlap.

Class → flux: A=1e-8, B=1e-7, C=1e-6, M=1e-5, X=1e-4, multiplied by the number
(M2.3 → 2.3e-5).

## Splits

`make_splits.py` assigns each NOAA AR to exactly one of train/val/test
(80/10/10, seed 42). By default the split is stratified on whether the AR ever
has a positive row; `--no-stratify` gives a plain random split. The script
asserts that no AR appears in more than one split.

`load_official_splits()` / `--official PATH` loads the image team's AR lists
from the Boucheron et al. 2023 Dryad release instead. **The exact file layout of
that release is not verified here.** The loader accepts either a directory with
`train*`/`val*`/`test*` files of AR numbers, or a single CSV with columns
`(NOAA_AR, split)`. Confirm the format with the image team before relying on it.

## Known caveats

- **GOES scaling.** `fl_goescls` holds operational SWPC classes. Before 2020
  these are on the old scale, which includes the 0.7 factor applied to
  GOES-13/14/15 fluxes. Reprocessed (science-quality) GOES fluxes are about
  1/0.7 ≈ 1.43× larger, so an operational M1.0 is roughly M1.4 in reprocessed
  units. Do not mix the two scales, and make sure the image team uses the same one.
- **Flares without an AR number are dropped.** SWPC events with a missing or
  zero `ar_noaanum` can't be attributed to a region. This mostly affects limb
  and far-side events, and some M/X flares are among them (`build_labels.py`
  prints the count).
- **HARPs covering several ARs.** A HARP can contain several NOAA ARs
  (`NOAA_ARS`). Labels use only the primary `NOAA_AR`, so flares from secondary
  ARs inside a HARP are not counted for that row.
- **Limb flares.** Rows are limited to ±60°, but flares are not. A region's
  biggest flares can happen after it rotates past 60° (e.g. AR 12673's X8.2 on
  2017-09-10 at the west limb), so the rows ≤24 h earlier get y=1 while no rows
  exist near the flare itself.
- **End of range.** Flares are fetched up to 2019-01-01 00:00, so label windows
  for rows on 2018-12-31 are truncated by up to 24 h. This is solar minimum, so
  it has negligible impact.
- **QUALITY.** Drops every non-zero QUALITY bit, which is strict; some bits are
  benign.
