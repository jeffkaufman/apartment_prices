# Rent map v3

A rewrite of the modeling and front end, addressing the issues in the v2
review.  Everything here is local and not deployed; `draw_heatmaps.sh` on
ps and the live site are untouched.

## Files

| File | What it is |
|---|---|
| `rentmap.py` | Model: data loading and dedup, backfitting, adaptive FFT smoother, output encoding |
| `build_rentmap.py` | Incremental pipeline: `python3 build_rentmap.py DATA_DIR OUT_DIR [--force]` |
| `build_area_income.py` | Yearly: builds `area_income.json` (median household income for the map area) from Census ACS; needs a free API key |
| `area_income.json` | Its output (checked in) |
| `build_mask.py` | One-off: builds `housing_mask.png` and `housing_units.png` from 2020 Census blocks |
| `housing_mask.png`, `housing_units.png` | Its outputs (checked in; only change if the bounds change) |
| `tune_rentmap.py` | Cross-validation for parameters, and comparison against the v2 method |
| `site/index.html` | New map page |
| `site/trends.html` | New trends page |
| `draw_rentmap.sh` | Draft replacement for `/home/jefftk/draw_heatmaps.sh` (not installed) |
| `legacy-index-legend-fix.diff` | One-line fix for the live v2 page's legend, if you want it before switching |

I also copied the scripts that were untracked in ps's checkout
(`calc_price_delta_by_size.py`, `diff_heatmap.py`, `draw_heatmap2.py`,
`draw_heatmap_const.py`, `draw_heatmap_n_br.py`, `static-cmds*.sh`) into
the working tree so you can decide whether to commit them.  ps's checkout is
also three commits behind `master`.

## What changed, by issue

**Legend bug (v2).** `adjustForSize` divided by the per-size correction where
it should multiply.  At the Nov 2026 listings' locations, the studio legend
was 26% low, 3BR 12% high, and 5BR 18% low.  v3 has no correction factors (see
below); `legacy-index-legend-fix.diff` fixes v2 in place.

**Lat/lng space.** Distances are now in meters.  v2's 0.005° kernel was 556m
north-south but 411m east-west.

**Fixed bandwidth.** v3 uses an adaptive bandwidth: at each pixel, the
smallest Gaussian (100m to 3km) that holds K_MASS = 8 listings' worth of
weight.  Downtown gets ~150m detail, sparse areas stay stable.

**Affine bedroom conversion and correction factors.** Replaced by
`log(rent) = location surface + bedroom effect`, fitted jointly by
backfitting.  Bedroom effects are multipliers relative to 2BR *at the same
location* (Nov 2026: studio 0.66, 1BR 0.79, 3BR 1.23, 4BR 1.54, 5BR 1.92).
Raw citywide medians give different ratios (studio 0.72, 3BR 1.15) because
bigger units are in cheaper places.  That confound is what v2's correction
factors were patching.  Each size's map is the 2BR map times a constant, so
the legend is exact.  Averaging in log space also limits the pull of outliers,
and listings more than 4 robust SDs off the fit are dropped (1–4% per month,
median 3%; this catches most of the $600 "studio" room shares).

**Each month uses only that month's data.** Each month now pools the new
listings from the past year:
- older listings are weighted by age, with a 120-day half-life;
- they're put into the current month's dollars with period offsets estimated
  in the same fit;
- each month depends only on earlier data, so maps never get revised, and the
  pipeline only computes new months.

**Lingering listings counted many times.** Each listing counts once, in the
month it first appears.  A listing is "new" unless an earlier scrape had the
same listing ID (180 days), the same bedrooms+rent+exact location (120 days),
or the same address+unit+bedrooms (120 days; raw JSON only).  Lingering
listings are pricier: in Nov 2026 the median 2BR is $3,100 among new
listings vs $3,400 among everything listed.  Interestingly, through 2025 the
two medians were nearly identical, so this bias is mostly recent.

**Big buildings, building summary rows.**
- Building weighting: each building (listings within ~10m) counts as at most
  one listing.
- Building summary rows: when the raw `apts-download-<ts>.txt` is next to a
  scrape, rows that summarize a whole building (`floorplan_count`/`count` > 1,
  or min ≠ max bedrooms) are dropped.  v2 recorded these as one unit at the
  building's minimum price and minimum bedrooms.

**Uninhabited areas.** `housing_mask.png` hides pixels more than 100m from any
2020 Census block with housing: water, the airport, rail yards, big parks,
cemeteries, most industrial land.  It can be toggled on the page.  The page
also fades estimates where the kernel had to grow past 700m to find data, and
they're gone by 1.5km.

**Speed.** FFT convolution of gridded sums: about 2s per month locally versus
72 minutes on ps for v2.  The full 2013–2026 history (158 months) builds in
about 6 minutes.

**Output format.** Instead of pre-colored images, each month is a PNG value
grid (R,G = log rent and kernel width, B = effective sample size) plus JSON
metadata.  The page colors it client-side, which enables:
- nominal dollars, today's dollars (CPI-U from FRED), relative to the city,
  or change since any other month, adjusted for nothing, inflation (CPI-U),
  non-housing prices (CPI-U less shelter, also from FRED), or median
  household income in the map area (`area_income.json`; refresh it each
  fall with `build_area_income.py` when new 1-year ACS data comes out,
  otherwise later months are extrapolated at the long-run growth rate);
- exact values on click for every size, with how much data they rest on;
- this month's new listings as dots, opacity, fade and mask toggles.

Old `#2026-11-20&2` links still work.

**Trends page.** All from the same build:
- typical rent: the map estimate vs median new listing vs median of
  everything listed, for any size, nominal or real;
- size premiums over time;
- listing counts;
- 35 neighborhoods as small multiples;
- a data table, plus `trends.json` and `rents_over_time_new.tsv` (the
  `rents_over_time.tsv` format, new listings only) for blog posts.

The citywide "typical rent" is the median over all 2020 housing units of the
map value at their location, so it describes the typical home rather than the
typical listing or acre.  It's lower than listing medians ($3,016 vs $3,100
for a 2BR in Nov 2026) because listings cluster in pricier neighborhoods.

## Accuracy

`tune_rentmap.py` predicts each new listing in 12 months spread across
2014–2026, without using anything binned in its ~40m pixel.  It scores mean
absolute error in log rent (0.15 ≈ typical miss of 15%):

| Method | Mean abs. error (log rent) |
|---|---|
| v2 as deployed (this month's listings, 0.005° kernel, affine sizes) | 0.191 |
| v2 with its correction factors applied correctly (in-sample, flattering) | 0.177 |
| v3, a single month of data | 0.160 |
| **v3 as configured** | **0.156** |

v3 beats v2 in all 12 months.  The single-month row isolates the gain from
pooling (about 2%); most of the gain comes from the log-multiplier model,
the adaptive kernel in meters, and dedup.

Choosing K_MASS depends on the holdout.  With only the listing's own pixel
held out, smaller is always better, because the building next door is very
informative.  Excluding everything within 150–300m favors 8–16:

| K_MASS | same pixel | within 75m | within 150m | within 300m |
|---|---|---|---|---|
| 2 | 0.154 | 0.161 | 0.171 | 0.195 |
| 4 | 0.155 | 0.161 | 0.170 | 0.183 |
| **8** | 0.156 | 0.163 | **0.170** | 0.177 |
| 16 | 0.159 | 0.165 | 0.171 | 0.176 |
| 32 | 0.164 | 0.168 | 0.172 | 0.177 |

(All with HALF_LIFE_DAYS = 120.  Error is flat between 60 and 240 days.)  Full
output: run `python3 tune_rentmap.py DATA_DIR` (~5 min).

## Reviewing locally

```
python3 build_rentmap.py DATA_DIR OUT_DIR      # needs numpy, scipy, pillow
cd OUT_DIR && python3 -m http.server 8765
# http://localhost:8765/index.html, http://localhost:8765/trends.html
```

The map page uses Google Maps like the live site.  If the API key rejects
the origin (likely on localhost), it falls back to Leaflet with OSM tiles.
Add `?leaflet` to force that.

## Deployment

v3 replaced the v2 page on 2026-11-20.
- `draw_rentmap.sh` is installed on ps as `/home/jefftk/draw_heatmaps.sh` (the
  v2 script is saved next to it as `draw_heatmaps.sh.v2`).
- It writes into `jtk/apartment_prices/`, where the new `index.html`
  replaced the v2 one (saved as `index.html.pre_v3`).
- The v2 images and metadata are still there, untouched.
- Copy each month's `apts-download-<ts>.txt` to ps along with the `.txt`, so
  building summary rows get filtered.
- The value PNGs are ~0.5MB each, versus ~0.1MB for v2 images.  If that's too
  much, a 500px grid would make them ~4x smaller at some cost in sharpness.
  That means `MAP_PX = 500` in `rentmap.py`, re-running `build_mask.py`, and
  changing `W`/`H` in `site/index.html`.

## Things I'd like your eye on

- K_MASS = 8 makes the map noticeably more detailed than v2.  Change maps
  ("change since...") are busy at that detail, because differencing two
  detailed maps amplifies noise.  Raising K_MASS to 16 costs ~2% accuracy and
  is smoother.
- Studios from late 2013 to mid 2015 still come out cheap (multiplier ~0.5
  vs ~0.65 since).  The trimming catches the worst room shares but not all.
- Months right after a gap in scraping (e.g. Sept 2022, July 2024) or the
  2016 Padmapper API change have more "new" listings than usual.  The
  location+price dedup key softens this; the pooled model absorbs it.
- The "today's dollars" mode uses headline CPI-U.  The change view can also
  adjust by CPI less shelter or by area median income.
