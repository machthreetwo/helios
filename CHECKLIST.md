# Helios checklist

## Data pipeline (v1)
- [x] Project setup: folders, venv, pinned requirements
- [x] Fetch SHARP keywords, 2010-05 → 2018-12, hourly
- [x] Fetch the GOES flare list from HEK
- [x] Clean the data and add labels (`y`, `max_flux_24h`, `prior_flare_48h`)
- [x] Split 80/10/10 by active region
- [x] Sanity-check notebook
- [x] README with caveats

## Repo
- [x] Public repo, tests, CI, license

## Data completeness (v2)
- [x] Add the 7 missing SHARP parameters (ABSNJZH, MEANGAM, MEANGBT, MEANGBH, MEANJZD, MEANJZH, MEANALP), plus NPIX, NACR, SIZE_ACR and CALVER64
- [ ] Re-fetch SHARP with the new keywords
- [ ] Rebuild the labels, splits and notebook; commit and push
- [ ] Right page of the notes: identify "TOTF…". Lorentz-force keywords aren't in `hmi.sharp_cea_720s`

## Decisions (you + image team): evidence in [docs/data_decisions.md](docs/data_decisions.md)
- [x] Get the official AR splits (Boucheron et al. 2023) and the image team's flare list
- [x] Research what QUALITY `0x80` means (JSOC: "awaiting reprocessing"; CALVER64 suggests the rows were reprocessed)
- [x] Check whether JSOC can fill the Aug–Sep 2014 NOAA gap (it can't)
- [x] Compare the flare lists (758 of 763 M/X match; timing differences documented)
- [x] Decide: flare threshold (M1.0)
- [x] Decide: position cut (±60° latitude and longitude)
- [x] Decide: keep QUALITY `0x80` rows with the reprocessed CALVER64
- [x] Decide: official splits as `splits.csv`; ours kept as `splits_random.csv`
- [ ] Decide: secondary ARs in a HARP (`--label-ars all`)?

## Modelling (not started)
- [ ] Preprocessing
- [ ] Baselines
- [ ] LightGBM
- [ ] Evaluation
- [ ] Fusion output format
