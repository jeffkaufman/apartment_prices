#!/usr/bin/env python3
"""Build rent map v3 outputs for every scrape.

Usage:
  python3 build_rentmap.py DATA_DIR OUT_DIR [--force]

DATA_DIR holds apts-<ts>.txt scrapes (and apts-download-<ts>.txt raw JSON
when available).  For each full scrape this writes, into OUT_DIR:

  rentmap.<date>.png    value grid (see rentmap.encode_png)
  rentmap.<date>.json   metadata: bedroom multipliers, city level, stats, ...
  dots.<date>.json      that month's new listings [lat, lon, bedrooms, rent]

plus dates.json, trends.json, rents_over_time_new.tsv, cpi.csv, and copies
of site/*.html and housing_mask.png.

Each month depends only on scrapes up to that month, so existing outputs are
reused unless the model parameters changed or --force is given.  A month is
written atomically (temp file + rename) so a crash never leaves a half-written
month that later runs would skip.
"""

import csv
import io
import json
import math
import os
import shutil
import sys
import time
import urllib.request

import rentmap

HERE = os.path.dirname(os.path.abspath(__file__))
CPI_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL"


def atomic_write(path, data, mode="w"):
    tmp = path + ".tmp"
    with open(tmp, mode) as outf:
        outf.write(data)
    os.replace(tmp, path)


def update_cpi(out_dir):
    """Fetch CPI-U (FRED CPIAUCSL); fall back to the cached copy."""
    path = os.path.join(out_dir, "cpi.csv")
    try:
        # FRED rejects some User-Agents; urllib's default works.
        with urllib.request.urlopen(CPI_URL, timeout=60) as resp:
            body = resp.read().decode()
        if body.startswith("observation_date"):
            atomic_write(path, body)
    except Exception as e:
        print("CPI fetch failed (%s); using cached copy" % e)
    cpi = {}
    if os.path.exists(path):
        with open(path) as inf:
            for row in csv.DictReader(inf):
                try:
                    cpi[row["observation_date"][:7]] = float(row["CPIAUCSL"])
                except ValueError:
                    pass
    return cpi


def cpi_for(cpi, date):
    """CPI for a YYYY-MM-DD date's month, carrying the last value forward
    (CPI is published with a lag)."""
    month = date[:7]
    if month in cpi:
        return cpi[month]
    earlier = [m for m in cpi if m <= month]
    return cpi[max(earlier)] if earlier else None


def build_months(ds, out_dir, force):
    params = rentmap.params_dict()
    fit_sm = rentmap.Smoother(rentmap.Grid(rentmap.FIT_PX))
    map_sm = rentmap.Smoother(rentmap.Grid(rentmap.MAP_PX))
    mask = rentmap.load_mask(os.path.join(HERE, "housing_mask.png"), map_sm.g)
    units = rentmap.load_units(os.path.join(HERE, "housing_units.png"),
                               map_sm.g)
    done = []
    for si, sc in enumerate(ds.scrapes):
        if sc.partial:
            continue
        base = os.path.join(out_dir, "rentmap.%s" % sc.date)
        if not force and os.path.exists(base + ".json"):
            with open(base + ".json") as inf:
                old = json.load(inf)
            if old.get("params") == params and old.get("ts") == sc.ts:
                done.append(sc.date)
                continue
        t0 = time.time()
        f = rentmap.fit_window(ds, si, fit_sm, final_smoother=map_sm)
        rentmap.encode_png(f, base + ".png.tmp")
        os.replace(base + ".png.tmp", base + ".png")
        atomic_write(os.path.join(out_dir, "dots.%s.json" % sc.date),
                     json.dumps(rentmap.dots(ds, si), separators=(",", ":")))
        meta = rentmap.summarize(f, ds, si, mask, units)
        atomic_write(base + ".json", json.dumps(meta, indent=1))  # written last
        done.append(sc.date)
        print("%s: %d new / %d listed, window %d, city 2br $%s, %.1fs" % (
            sc.date, sc.n_new, sc.n, f.n_window, meta["city_2br"],
            time.time() - t0))
    return sorted(set(done))


def build_trends(out_dir, dates, cpi):
    metas = []
    for d in dates:
        with open(os.path.join(out_dir, "rentmap.%s.json" % d)) as inf:
            metas.append(json.load(inf))
    sizes = [str(b) for b in range(6)]
    t = {
        "months": dates,
        "cpi": [cpi_for(cpi, d) for d in dates],
        "cpi_latest": cpi[max(cpi)] if cpi else None,
        "cpi_latest_month": max(cpi) if cpi else None,
        "city_2br": [m["city_2br"] for m in metas],
        "n_listed": [m["n_listed"] for m in metas],
        "n_new": [m["n_new"] for m in metas],
        "bedroom_mult": {b: [m["bedroom_mult"][b] for m in metas] for b in sizes},
        "places": {},
    }
    for kind in ("new", "all"):
        for stat in ("median", "p25", "p75", "n"):
            t["%s_%s" % (kind, stat)] = {
                b: [m["%s_stats" % kind][b].get(stat) for m in metas]
                for b in sizes}
    for name, _, _ in rentmap.PLACES:
        t["places"][name] = [m["places_2br"].get(name) for m in metas]
    atomic_write(os.path.join(out_dir, "trends.json"),
                 json.dumps(t, separators=(",", ":")))

    # TSV in the same shape as rents_over_time.tsv, but new listings only.
    labels = {"0": "studio", "1": "1br", "2": "2br", "3": "3br", "4": "4br",
              "5": "5br"}
    order = ["2", "0", "1", "3", "4", "5"]
    buf = io.StringIO()
    buf.write("\t".join(["month"] + sum([[labels[b], "", ""] for b in order],
                                        [])) + "\n")
    buf.write("\t".join(["month"] + ["median", "25th", "75th"] * len(order))
              + "\n")
    for i, d in enumerate(dates):
        row = [d]
        for b in order:
            vals = [t["new_%s" % s][b][i] for s in ("median", "p25", "p75")]
            row += ["$%s" % format(v, ",") if v is not None else ""
                    for v in vals]
        buf.write("\t".join(row) + "\n")
    atomic_write(os.path.join(out_dir, "rents_over_time_new.tsv"),
                 buf.getvalue())


def main(argv):
    force = "--force" in argv
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__)
        sys.exit(1)
    data_dir, out_dir = args
    os.makedirs(out_dir, exist_ok=True)

    t0 = time.time()
    ds = rentmap.Dataset(data_dir)
    print("loaded %d scrapes in %.0fs" % (len(ds.scrapes), time.time() - t0))
    cpi = update_cpi(out_dir)
    dates = build_months(ds, out_dir, force)
    atomic_write(os.path.join(out_dir, "dates.json"), json.dumps(dates))
    build_trends(out_dir, dates, cpi)
    for fn in os.listdir(os.path.join(HERE, "site")):
        shutil.copy(os.path.join(HERE, "site", fn), os.path.join(out_dir, fn))
    shutil.copy(os.path.join(HERE, "housing_mask.png"),
                os.path.join(out_dir, "housing_mask.png"))
    print("built %d months in %.0fs" % (len(dates), time.time() - t0))


if __name__ == "__main__":
    main(sys.argv[1:])
