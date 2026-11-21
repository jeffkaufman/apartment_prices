#!/usr/bin/env python3
"""Cross-validate rent map parameters, and compare against the v2 method.

For a spread of target months we predict the rent of each listing that newly
appeared that month, without using any listing binned in the same ~40m pixel
(so a building can't predict itself), and score log-rent error.

The v2 baseline is what draw_heatmap.py does: one month of all active
listings, a 0.005-degree Gaussian in lat/lng space, affine bedroom
conversion, optionally with the per-size correction factors applied the
right way round.

Usage: python3 tune_rentmap.py DATA_DIR
"""

import math
import sys
import time

import numpy as np
from scipy.spatial import cKDTree

import rentmap

K_GRID = [2, 4, 8, 16, 32, 64]
H_GRID = [30, 60, 120, 240]


def pick_targets(ds, n=12):
    full = [i for i, s in enumerate(ds.scrapes)
            if not s.partial and s.ts >= 1393000000]  # 2014-03 onwards
    return [full[int(round(j))] for j in np.linspace(0, len(full) - 1, n)]


def v2_predict(ds, si, grid, target_mask):
    """Leave-own-pixel-out v2 predictions (log rent) for target listings."""
    a = ds.a
    sel = np.nonzero(a["scrape"] == si)[0]
    br = a["br"][sel].astype(float)
    rent = a["rent"][sel].astype(float)
    lat, lon = a["lat"][sel], a["lon"][sel]
    slope, icpt = np.polyfit(br, rent, 1)
    p2 = rent * (icpt + 2 * slope) / (icpt + slope * br)
    ix, iy = grid.pixel_index(lat, lon)
    pix = iy * grid.nx + ix
    sig = 0.005
    amp = 1 / (sig * math.sqrt(2 * math.pi))
    tree = cKDTree(np.c_[lat, lon])
    tgt = np.nonzero(target_mask[sel])[0]
    pred2 = np.full(len(tgt), np.nan)
    for j, i in enumerate(tgt):
        nb = np.array(tree.query_ball_point([lat[i], lon[i]], 4 * sig), int)
        nb = nb[pix[nb] != pix[i]]
        d2 = (lat[nb] - lat[i]) ** 2 + (lon[nb] - lon[i]) ** 2
        w = amp * np.exp(-d2 / (2 * sig * sig))
        if (w > 2).sum() < 5:
            continue
        pred2[j] = np.sum(w * p2[nb]) / w.sum()
    conv = (icpt + slope * br[tgt]) / (icpt + 2 * slope)
    pred = np.log(pred2 * conv)
    # correction factors computed on the same predictions (in-sample, which
    # flatters v2), applied by multiplying as intended
    adj = np.ones(len(tgt))
    for b in np.unique(br[tgt]):
        m = (br[tgt] == b) & ~np.isnan(pred2)
        if m.any():
            adj[br[tgt] == b] = p2[tgt][m].sum() / pred2[m].sum()
    pred_adj = np.log(pred2 * conv * adj)
    return pred, pred_adj, np.log(rent[tgt])


def score(e):
    e = e[~np.isnan(e)]
    ec = np.clip(e, -1, 1)
    return {"MAE": float(np.mean(np.abs(e))),
            "RMSE_clip": float(np.sqrt(np.mean(ec ** 2))),
            "n": int(len(e))}


def main(data_dir):
    t0 = time.time()
    ds = rentmap.Dataset(data_dir)
    print("loaded %d scrapes in %.0fs" % (len(ds.scrapes), time.time() - t0))
    targets = pick_targets(ds)
    print("targets:", ", ".join(ds.scrapes[i].date for i in targets))
    sm = rentmap.Smoother(rentmap.Grid(rentmap.FIT_PX))
    grid = sm.g

    # Baseline and new method evaluated on the same listings: new listings
    # in the target month that v2 can make a prediction for.
    print("\n== v2 baseline vs v3 (default params), per target ==")
    base = {"v2": [], "v2+adj": [], "v3": [], "v3 single-month": []}
    common_by_target = {}
    for si in targets:
        a = ds.a
        tmask = (a["scrape"] == si) & a["new"]
        p_v2, p_v2a, y_v2 = v2_predict(ds, si, grid, tmask)
        f = rentmap.fit_window(ds, si, sm, loo_target=True)
        f1 = rentmap.fit_window(ds, si, sm, loo_target=True, window_days=20)
        # fit_window's target order = order of new listings in this scrape
        assert np.allclose(f.loo_y, y_v2)
        common = ~np.isnan(p_v2) & ~np.isnan(f.loo_pred)
        common_by_target[si] = common
        row = {}
        for name, pred in (("v2", p_v2), ("v2+adj", p_v2a),
                           ("v3", f.loo_pred), ("v3 single-month", f1.loo_pred)):
            s = score((pred - y_v2)[common])
            base[name].append(s)
            row[name] = s["MAE"]
        print("  %s n=%5d  " % (ds.scrapes[si].date, common.sum()) +
              "  ".join("%s %.4f" % kv for kv in row.items()))
    print("  mean MAE:  " + "  ".join(
        "%s %.4f" % (k, np.mean([s["MAE"] for s in v])) for k, v in base.items()))
    print("  mean RMSE (errors clipped at +-1):  " + "  ".join(
        "%s %.4f" % (k, np.mean([s["RMSE_clip"] for s in v])) for k, v in base.items()))

    print("\n== v3 grid search: mean MAE over targets (log rent) ==")
    print("  K\\H " + "".join("%9d" % h for h in H_GRID))
    best = None
    for k in K_GRID:
        cells = []
        for h in H_GRID:
            maes = []
            for si in targets:
                f = rentmap.fit_window(ds, si, sm, k_mass=k, half_life_days=h,
                                       loo_target=True)
                e = (f.loo_pred - f.loo_y)[common_by_target[si]]
                maes.append(score(e)["MAE"])
            m = float(np.mean(maes))
            cells.append(m)
            if best is None or m < best[0]:
                best = (m, k, h)
        print("  %3d " % k + "".join("%9.4f" % c for c in cells))
    print("best: K_MASS=%d HALF_LIFE_DAYS=%d (MAE %.4f)" % (best[1], best[2], best[0]))

    # A same-pixel holdout lets the building next door (often the same
    # landlord or development) predict a listing, which rewards very local
    # estimates.  Also score with everything within a radius excluded, which
    # measures how well the map captures neighborhood-level prices.
    for holdout_m in (75, 150, 300):
        print("\n== excluding all listings within %dm (H=%d): mean MAE ==" % (
            holdout_m, best[2]))
        for k in K_GRID:
            maes = []
            for si in targets:
                f = rentmap.fit_window(ds, si, sm, k_mass=k,
                                       half_life_days=best[2],
                                       loo_target=True, loo_radius_m=holdout_m)
                e = (f.loo_pred - f.loo_y)[common_by_target[si]]
                maes.append(score(e)["MAE"])
            print("  K=%3d  %.4f" % (k, np.mean(maes)))
    print("done in %.0fs" % (time.time() - t0))


if __name__ == "__main__":
    main(*sys.argv[1:])
