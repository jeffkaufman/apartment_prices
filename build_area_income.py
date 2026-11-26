#!/usr/bin/env python3
"""Median household income for the rent map's area, for the "adjust for
median income" option.  Run about once a year, after the Census releases new
1-year ACS data (September).  Writes area_income.json, which build_rentmap.py
reads.

Usage:
  python3 build_area_income.py TIGER_DIR CENSUS_KEY_FILE

TIGER_DIR holds the unzipped 2020 Census shapefiles for Massachusetts:
  https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK20/tl_2020_25_tabblock20.zip
  https://www2.census.gov/geo/tiger/TIGER2020/COUSUB/tl_2020_25_cousub.zip
Needs pyshp and matplotlib.  A Census API key is free:
  https://api.census.gov/data/key_signup.html

Method:
 1. Assign each 2020 Census block with housing to its municipality (county
    subdivision) and count housing units inside the map bounds.
 2. A town's weight is in-map units / town's total units (assumes the
    town's income distribution is the same in and out of the map).
 3. For each year, sum the weighted ACS household-income distributions and
    take the median of the combined distribution.  1-year ACS only covers
    towns over 65k people, so the annual series uses the towns with 1-year
    data every year (Boston, Cambridge, Somerville, Quincy, Newton: ~70% of
    in-map housing) and corrects for the rest with 5-year ACS, which covers
    every town.  There is no standard 2020 1-year release.
"""
import json, math, os, sys, urllib.request
import numpy as np
import shapefile
from matplotlib.path import Path

tiger_dir, keyfile = sys.argv[1:3]
KEY = open(keyfile).read().strip()
from query_padmapper import MIN_LAT, MAX_LAT, MIN_LON, MAX_LON
HERE = os.path.dirname(os.path.abspath(__file__))
COUNTIES = ("009", "017", "021", "025")

# --- municipalities and their polygons
cs = shapefile.Reader(os.path.join(tiger_dir, "tl_2020_25_cousub"))
cf = [x[0] for x in cs.fields[1:]]
towns = {}
for sr in cs.iterShapeRecords():
    r = dict(zip(cf, sr.record))
    if r["COUNTYFP"] not in COUNTIES:
        continue
    bb = sr.shape.bbox
    if bb[0] > MAX_LON + .05 or bb[2] < MIN_LON - .05 or bb[1] > MAX_LAT + .05 or bb[3] < MIN_LAT - .05:
        continue
    pts, parts = sr.shape.points, list(sr.shape.parts) + [len(sr.shape.points)]
    paths = [Path(pts[parts[i]:parts[i + 1]]) for i in range(len(parts) - 1)]
    towns[(r["COUNTYFP"], r["COUSUBFP"])] = {"name": r["NAME"], "paths": paths, "bbox": bb,
                                             "in": 0, "total": 0}

# --- blocks -> towns
rd = shapefile.Reader(os.path.join(tiger_dir, "tl_2020_25_tabblock20"))
f = [x[0] for x in rd.fields[1:]]
ic, ih, ila, ilo = (f.index(k) for k in ("COUNTYFP20", "HOUSING20", "INTPTLAT20", "INTPTLON20"))
for rec in rd.iterRecords():
    if rec[ih] == 0 or rec[ic] not in COUNTIES:
        continue
    lat, lon = float(rec[ila]), float(rec[ilo])
    for k, t in towns.items():
        if k[0] != rec[ic]:
            continue
        bb = t["bbox"]
        if not (bb[0] <= lon <= bb[2] and bb[1] <= lat <= bb[3]):
            continue
        if sum(p.contains_point((lon, lat)) for p in t["paths"]) % 2:
            t["total"] += rec[ih]
            if MIN_LAT <= lat <= MAX_LAT and MIN_LON <= lon <= MAX_LON:
                t["in"] += rec[ih]
            break
towns = {k: t for k, t in towns.items() if t["in"] > 0}
tot_in = sum(t["in"] for t in towns.values())
print(f"{tot_in} housing units in map bounds")
for k, t in sorted(towns.items(), key=lambda kv: -kv[1]["in"]):
    print(f"  {t['name']:20s} {t['in']:7d} in map  ({t['in']/t['total']:.0%} of town)")

# --- ACS
VARS = ",".join(f"B19001_{i:03d}E" for i in range(2, 18))
EDGES = [0, 10e3, 15e3, 20e3, 25e3, 30e3, 35e3, 40e3, 45e3, 50e3, 60e3, 75e3, 100e3,
         125e3, 150e3, 200e3, 300e3]  # last bin open-ended; 300k is a placeholder


def acs(year, ds):
    url = (f"https://api.census.gov/data/{year}/acs/{ds}?get=NAME,{VARS}"
           f"&for=county%20subdivision:*&in=state:25&in=county:{','.join(COUNTIES)}&key={KEY}")
    try:
        rows = json.load(urllib.request.urlopen(url, timeout=60))
    except Exception as e:
        print("  no data", year, ds, e)
        return {}
    h = rows[0]
    res = {}
    for r in rows[1:]:
        d = dict(zip(h, r))
        k = (d["county"], d["county subdivision"])
        try:
            res[k] = np.array([float(d[f"B19001_{i:03d}E"]) for i in range(2, 18)])
        except (TypeError, ValueError):
            pass
    return res


def median(bins):
    c = np.cumsum(bins)
    half = c[-1] / 2
    i = int(np.searchsorted(c, half))
    lo, hi = EDGES[i], EDGES[i + 1]
    prev = c[i - 1] if i else 0
    frac = (half - prev) / bins[i]
    # Census-style: linear within the bin, except Pareto-ish for wide bins isn't
    # needed here since the median lands in $75k-$150k.
    return lo + frac * (hi - lo)


result = {"towns": {t["name"]: {"in_map_units": t["in"], "share_of_town": t["in"] / t["total"]}
                    for t in towns.values()}, "big": {}, "all": {}}
FIXED = {"Boston", "Cambridge", "Newton", "Quincy", "Somerville"}  # 1-year data every year
result["fixed1"] = {}; result["fixed5"] = {}
cache = {}
for ds, label, years, sub in [("acs1", "big", range(2013, 2026), None), ("acs1", "fixed1", range(2013, 2026), FIXED),
                              ("acs5", "all", range(2013, 2025), None), ("acs5", "fixed5", range(2013, 2025), FIXED)]:
    for y in years:
        if (y, ds) not in cache:
            cache[y, ds] = acs(y, ds)
        data = cache[y, ds]
        if not data:
            continue
        have = [k for k in towns if k in data and (sub is None or towns[k]["name"] in sub)]
        cov = sum(towns[k]["in"] for k in have) / tot_in
        comb = sum(data[k] * towns[k]["in"] / towns[k]["total"] for k in have)
        med = median(comb)
        result[label][y] = {"median": med, "coverage": cov,
                            "towns": sorted(towns[k]["name"] for k in have) if label in ("big", "fixed1") else len(have)}
        print(f"{label} {y}: median ${med:,.0f}, covers {cov:.0%} of in-map housing")

# Final series: the fixed set's annual 1-year medians, times the (all towns /
# fixed set) ratio from 5-year data, treating a 5-year estimate ending in Y
# as centered on Y-2 and holding the ratio constant past the ends.
corr = {y - 2: result["all"][y]["median"] / result["fixed5"][y]["median"] for y in result["all"]}
cy = sorted(corr)
annual = {}
for y, v in sorted(result["fixed1"].items()):
    c = corr[min(max(y, cy[0]), cy[-1])]
    annual[str(y)] = round(v["median"] * c)
out = {
    "description": "Median household income for the rent map area, by year. "
                   "Built by build_area_income.py from Census ACS household "
                   "income distributions (B19001) for each municipality, "
                   "weighted by 2020 housing units inside the map bounds.",
    "annual": annual,
    "towns": result["towns"],
}
with open(os.path.join(HERE, "area_income.json"), "w") as outf:
    json.dump(out, outf, indent=1)
print("wrote area_income.json:", annual)
