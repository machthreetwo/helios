# Data decisions to agree with the image team

Helios (the SHARP tabular track) and the image track have to build their
datasets the same way before their results can be compared or fused. This
document lists the choices that are still open, what we found, and the
options. Each option can be switched in the code without rewriting anything.

The image dataset referred to below is Boucheron et al. 2023, *Sci Data* 10, 825,
arXiv:2305.09492 (Dryad `doi:10.5061/dryad.jq2bvq898`, CC0).

## Summary

| # | Decision | Helios now | Image dataset | Recommendation |
|---|---|---|---|---|
| 1 | Flare threshold | ≥ M1.0 | ≥ C1.0 (preconfigured; can be changed) | Agree on one. M1.0 is standard for SHARP work, and the image data can be relabelled from its event list |
| 2 | Label window | peak in (t, t+24 h] | "within 24 hours of the peak flare time" | Same window; confirm the image team's code uses the peak time (see §5) |
| 3 | Position cut | \|LON_FWT\| ≤ 60° (hourly, from the SHARP patch) | \|lat\| ≤ 60° **and** \|lon\| ≤ 60° (daily, from SWPC SRS) | Add \|LAT_FWT\| ≤ 60° to Helios |
| 4 | Which ARs | every NOAA AR with a SHARP patch | only ARs whose whole disk passage falls in 2010-05-01 … 2018-12-31, minus 13 named ARs | Use the official split lists and drop ARs that aren't in them |
| 5 | Flare list | HEK, SWPC reports | SWPC event reports, parsed by the image team | Same source; see the timing differences in §5 |
| 6 | QUALITY `0x80` rows (2016-04 … 2017-03, 2017-08) | dropped | not applicable (they use hmi.M_720s with `quality>=0`) | Keep them when CALVER64 shows the current calibration (see §1) |
| 7 | Flares from secondary ARs in a HARP | not counted | not applicable (the image is centred on one NOAA AR) | Keep `primary`; this matches the one-AR-per-image setup |
| 8 | Aug–Sep 2014 HARPs with no NOAA number | dropped | present (their images are cut out by NOAA AR number) | Known gap in Helios (see §2) |

## 1. QUALITY `0x80`

- **What we see:** from April 2016 to March 2017, and again in August 2017,
  about 100% of SHARP rows have `QUALITY = 0x80`. Elsewhere about 10% of rows
  have a non-zero QUALITY.
- **What JSOC says:** `QUALITY.txt` defines 0x80 on existing records as
  `QUAL_TEMPERROR`, "Code error discovered, will be corrected in later
  versions". `QUALITY.notes` adds that from September 2017, 0x80 was set on
  "the initial year+ of modL data … while waiting for reprocessing … The
  records with this QUALITY bit set should not be visible once the
  reprocessing is done."
- **Why we think the data are fine:** we checked the calibration version
  (`CALVER64`) directly.

  | Sample | QUALITY | CALVER64 |
  |---|---|---|
  | 2016-02 | mostly 0 | `0x2012` |
  | 2016-06 | 0x80 | `0x42012` |
  | 2017-06 | mostly 0 | `0x42012` |
  | 2017-08 | 0x80 | `0x42012` |
  | 2018-06 | mostly 0 | `0x42012` |

  The flagged rows carry the same calibration version as the clean data after
  them. This suggests they were reprocessed and the flag was never cleared.
  That's our inference; JSOC doesn't state it.
- **Effect of keeping them:** measured on the v1 build, it adds about 14.8k
  rows and 95 ARs but only 35 positive rows.
- **Switch:** `python src/build_labels.py --allow-quality 0x80`

## 2. HARPs with no NOAA number, Aug–Sep 2014

- 121 HARPs have `NOAA_ARS = "MISSING"`. They cover roughly NOAA 12135–12176.
- JSOC's own mapping file (`all_harps_with_noaa_ars.txt`) has no entries for
  them either, so this is a gap in JSOC.
- About 15 M/X flares are lost from Helios as a result, including the X1.6
  from AR 12158 on 2014-09-10.
- **Possible fix, not built:** match each flare's heliographic position (HEK
  gives one) to the HARP whose bounding box contains it.

## 3. Position cut

- The image dataset keeps an image when the AR centroid is within ±60° in
  **both** latitude and longitude, using the daily SRS position.
- Helios keeps a row when the hourly patch longitude `LON_FWT` is within ±60°.
- The two cohorts overlap closely but not exactly, so rows near the limb
  differ a little. Adding a `LAT_FWT` cut is easy.

## 4. AR coverage and splits

The official lists contain 1,256 / 157 / 157 ARs (train/val/test). Measured on
the v1 build (1,197 ARs):

- 1,133 of our ARs are in the lists: train 887 / val 121 / test 125, with
  positive rates of 2.97% / 2.48% / 3.17%.
- 64 of our ARs (5.4k rows, 5 of them flaring) aren't in any list. These are
  the date-boundary ARs and the named exclusions in the paper.
- 437 listed ARs have no Helios rows, mostly small regions without a usable
  SHARP patch.
- `python src/make_splits.py --official` builds `splits.csv` from the lists.
  Our own stratified split can be written alongside it with
  `--out data/processed/splits_random.csv`.

## 5. Flare-list comparison

We compared the image team's `eventList.txt` with our HEK list over
2010-04-30 … 2017-12-28. Of their 763 M/X flares, 758 match one of ours on
class, with the peak within 26 h.

| Pattern | Count | Effect |
|---|---|---|
| Same peak time | 716 | none |
| Their time equals our event **start** time | 37 | their label window begins ~5–20 min early |
| Same clock time, one day early (events around 00:0x) | 5 | their label window is shifted by a full day |
| They have an AR number where HEK has 0 | 6 | they can label these flares and we can't |
| Neighbouring AR number (e.g. 11302 vs 11301) | 4 | the flare is attributed to a different region |

The start-time and one-day patterns look like parsing issues in the image
team's event list: begin time or begin date taken instead of the maximum. Worth
raising with them.

## 6. GOES scaling

Both tracks use operational SWPC classes, which are on the pre-2020 scale that
includes the 0.7 factor. Nothing to change, as long as neither side switches
to reprocessed GOES fluxes.
