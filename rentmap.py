"""Rent map model, v3.

Overview
--------
For each monthly scrape t we estimate a surface S_t(x) of log "2br-equivalent"
rent at every map pixel, from listings that first appeared on the market in the
year up to and including t:

  log(rent_i) = S_t(x_i) + bedroom_effect[b_i] + period_offset[p_i] + noise

* Only *new* listings count (first appearance; see Dataset), so a unit that
  sits on the market for months is counted once instead of once per month.
  Lingering listings are systematically pricier, so counting the whole stock
  biases prices up.
* bedroom_effect is a multiplier per bedroom count (studio .. 5br, 6+),
  relative to 2br, estimated jointly with the surface (backfitting), so it
  measures the premium for an extra bedroom *at the same location*.  This
  replaces the affine rent-vs-bedrooms conversion and the per-size correction
  factors.
* period_offset puts older listings into month-t dollars, so the map can pool a
  year of data.  Listings are also down-weighted by age (half-life
  HALF_LIFE_DAYS), so the map still responds to change.
* Listings at the same building are down-weighted (1/sqrt(n)) so one big
  complex doesn't dominate its neighborhood.
* The surface is a Gaussian-kernel weighted average (Nadaraya-Watson) computed
  in meters, not degrees, with an adaptive bandwidth: at each pixel we use the
  smallest kernel that holds K_MASS listings' worth of weight, so dense areas
  get detail and sparse areas stay stable.  Computed by FFT convolution of
  gridded sums, which takes seconds instead of an hour.
* We also compute the effective sample size (Kish n_eff) at each pixel, which
  the front end uses to fade out estimates that rest on too little data, and a
  Census-based housing mask hides places nobody lives.

Outputs are value grids (not pre-colored images) so the front end can color
them in nominal dollars, inflation-adjusted dollars, relative to the city, or
as change between two dates, and show exact values on click.
"""

import json
import math
import os
import re
from datetime import datetime, timezone

import numpy as np
from scipy import fft as sfft

from query_padmapper import MAX_LAT, MAX_LON, MIN_LAT, MIN_LON

# ---------------------------------------------------------------------------
# Parameters, chosen by cross-validation with tune_rentmap.py (see
# README-v3.md).  Error is flat in HALF_LIFE_DAYS between 60 and 240.  For
# K_MASS, a same-building holdout prefers K=2-4 while excluding everything
# within 150m prefers 8-16; 8 is within ~3% of the best under each.
# Building weighting and the minimum bandwidth barely move the error (<3%),
# so they're set for the look of the map: counting a building as at most one
# listing, with kernels no narrower than 100m, avoids bullseyes around single
# big complexes.

K_MASS = 8                 # weighted listings the adaptive kernel must cover
HALF_LIFE_DAYS = 120       # age weighting of pooled listings
WINDOW_DAYS = 365          # how far back to pool listings
SIGMA0_M = 100
SIGMA_RATIO = 1.3
SIGMA_LEVELS_M = [SIGMA0_M * SIGMA_RATIO ** i for i in range(14)]  # to ~3km
BUILDING_ROUND = 4         # lat/lon decimals defining "same building" (~10m)
BUILDING_POWER = 1.0       # listings in a building of n get weight n**-power
TRIM_SIGMAS = 4            # drop listings this many robust SDs off the fit
OFFSET_PRIOR_W = 3         # shrink period offsets toward 0 for thin months
BACKFIT_ITERS = 4
MIN_RENT_PER_ROOM = 150    # same sanity filter as v2
MAX_BEDROOMS_CATEGORY = 6  # 6 means "6+"

MAP_PX = 1000              # output resolution (same bounds as v2 overlay)
FIT_PX = 500               # resolution used while fitting / tuning

# Dedup lookbacks: a listing is "new" unless one of its keys was seen in an
# earlier scrape within this many days.
ID_LOOKBACK_DAYS = 180
LOCPRICE_LOOKBACK_DAYS = 120   # (bedrooms, rent, exact location)
ADDRESS_LOOKBACK_DAYS = 120    # (address incl. unit, bedrooms); raw JSON only

# Scrapes with fewer listings than this are treated as partial: their listings
# feed dedup and the pooled model, but they don't get their own map.
MIN_FULL_SCRAPE = 1000

# Known-bad scrapes (from generate_tsv.py), excluded entirely.
BAD_SCRAPES = {
    1384776122,  # 2013-11-18
    1385024431,  # 2013-11-21
    1387368122,  # 2013-12-18
    1390046522,  # 2014-01-18
    1437184922,  # 2015-07-17
}

# Value encoding for output PNGs: R,G = 16-bit log rent code, B = n_eff.
LOG_LO = math.log(250)
LOG_HI = math.log(25000)
VALUE_STEP = 0.0025   # quantization of log rent in output PNGs

M_PER_DEG_LAT = 111132.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians((MIN_LAT + MAX_LAT) / 2))

# Places tracked on the trends page.
PLACES = [
    ("Back Bay", 42.3503, -71.0810),
    ("Beacon Hill", 42.3588, -71.0675),
    ("South End", 42.3410, -71.0740),
    ("North End", 42.3647, -71.0542),
    ("Seaport", 42.3500, -71.0440),
    ("Fenway", 42.3440, -71.0990),
    ("Allston", 42.3539, -71.1337),
    ("Brighton", 42.3487, -71.1538),
    ("Jamaica Plain", 42.3097, -71.1151),
    ("Roxbury", 42.3293, -71.0842),
    ("South Boston", 42.3334, -71.0495),
    ("Dorchester", 42.3002, -71.0606),
    ("East Boston", 42.3750, -71.0390),
    ("Charlestown", 42.3782, -71.0602),
    ("Roslindale", 42.2866, -71.1296),
    ("West Roxbury", 42.2830, -71.1590),
    ("Mattapan", 42.2700, -71.0924),
    ("Harvard Sq", 42.3736, -71.1190),
    ("Central Sq", 42.3654, -71.1037),
    ("Kendall Sq", 42.3625, -71.0862),
    ("Inman Sq", 42.3741, -71.1003),
    ("Porter Sq", 42.3884, -71.1191),
    ("North Cambridge", 42.3956, -71.1340),
    ("Davis Sq", 42.3967, -71.1223),
    ("Union Sq", 42.3796, -71.0935),
    ("Assembly Sq", 42.3923, -71.0773),
    ("Coolidge Corner", 42.3420, -71.1212),
    ("Brookline Village", 42.3328, -71.1166),
    ("Arlington Center", 42.4153, -71.1569),
    ("Medford Sq", 42.4184, -71.1062),
    ("Malden Center", 42.4265, -71.0743),
    ("Everett", 42.4084, -71.0537),
    ("Chelsea", 42.3918, -71.0328),
    ("Revere Beach", 42.4080, -70.9940),
    ("Winthrop", 42.3751, -70.9828),
]
PLACE_RADIUS_M = 300


def utc_date(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def params_dict():
    return {
        "version": 3,
        "K_MASS": K_MASS,
        "HALF_LIFE_DAYS": HALF_LIFE_DAYS,
        "WINDOW_DAYS": WINDOW_DAYS,
        "SIGMA_LEVELS_M": [round(s, 1) for s in SIGMA_LEVELS_M],
        "BUILDING_ROUND": BUILDING_ROUND,
        "BUILDING_POWER": BUILDING_POWER,
        "TRIM_SIGMAS": TRIM_SIGMAS,
        "OFFSET_PRIOR_W": OFFSET_PRIOR_W,
        "BACKFIT_ITERS": BACKFIT_ITERS,
        "MAP_PX": MAP_PX,
        "FIT_PX": FIT_PX,
        "ID_LOOKBACK_DAYS": ID_LOOKBACK_DAYS,
        "LOCPRICE_LOOKBACK_DAYS": LOCPRICE_LOOKBACK_DAYS,
        "ADDRESS_LOOKBACK_DAYS": ADDRESS_LOOKBACK_DAYS,
        "MIN_FULL_SCRAPE": MIN_FULL_SCRAPE,
        "BAD_SCRAPES": sorted(BAD_SCRAPES),
        "VALUE_STEP": VALUE_STEP,
        "SUMMARY_WEIGHTING": "housing_units",
    }


# ---------------------------------------------------------------------------
# Geometry


class Grid:
    """Pixel grid over the map bounds.  Pixel (0, 0) is the NW corner; pixel
    edges line up with the bounds, same as the v2 overlay."""

    def __init__(self, n):
        self.nx = self.ny = n
        self.m_per_px_x = (MAX_LON - MIN_LON) * M_PER_DEG_LON / n
        self.m_per_px_y = (MAX_LAT - MIN_LAT) * M_PER_DEG_LAT / n

    def lonlat_to_fpixel(self, lon, lat):
        x = (lon - MIN_LON) / (MAX_LON - MIN_LON) * self.nx
        y = (MAX_LAT - lat) / (MAX_LAT - MIN_LAT) * self.ny
        return x, y

    def pixel_index(self, lat, lon):
        x, y = self.lonlat_to_fpixel(np.asarray(lon), np.asarray(lat))
        ix = np.clip(np.floor(x).astype(int), 0, self.nx - 1)
        iy = np.clip(np.floor(y).astype(int), 0, self.ny - 1)
        return ix, iy

    def in_bounds(self, lat, lon):
        lat = np.asarray(lat)
        lon = np.asarray(lon)
        return ((lat >= MIN_LAT) & (lat < MAX_LAT) &
                (lon >= MIN_LON) & (lon < MAX_LON))

    def disk(self, lat, lon, radius_m):
        """Boolean mask of pixels whose centers are within radius_m."""
        x, y = self.lonlat_to_fpixel(lon, lat)
        yy, xx = np.mgrid[0:self.ny, 0:self.nx]
        d2 = (((xx + 0.5 - x) * self.m_per_px_x) ** 2 +
              ((yy + 0.5 - y) * self.m_per_px_y) ** 2)
        return d2 <= radius_m ** 2


class Smoother:
    """Adaptive-bandwidth Gaussian Nadaraya-Watson smoother on a Grid.

    Listings are binned to pixels; for each bandwidth in SIGMA_LEVELS_M we
    convolve the binned weight, weight*value, and weight^2 sums with a
    (peak-1) Gaussian via FFT.  At each pixel the bandwidth is the smallest at
    which the kernel-weighted mass D reaches K_MASS, interpolating between
    levels in log(D).
    """

    def __init__(self, grid, levels=SIGMA_LEVELS_M, cache_kernels=None):
        self.g = grid
        self.levels = list(levels)
        smax = max(self.levels)
        ry = int(math.ceil(4 * smax / grid.m_per_px_y))
        rx = int(math.ceil(4 * smax / grid.m_per_px_x))
        self.fy = sfft.next_fast_len(grid.ny + ry, real=True)
        self.fx = sfft.next_fast_len(grid.nx + rx, real=True)
        dy = np.minimum(np.arange(self.fy), self.fy - np.arange(self.fy))
        dx = np.minimum(np.arange(self.fx), self.fx - np.arange(self.fx))
        self.dy2 = ((dy * grid.m_per_px_y) ** 2)[:, None]
        self.dx2 = ((dx * grid.m_per_px_x) ** 2)[None, :]
        if cache_kernels is None:
            cache_kernels = self.fy * self.fx <= 1200 * 1200
        self._cache = {} if cache_kernels else None

    def _kernels(self, sigma):
        if self._cache is not None and sigma in self._cache:
            return self._cache[sigma]
        d2 = self.dy2 + self.dx2
        k = np.exp(-d2 / (2 * sigma * sigma))
        k[d2 > (4 * sigma) ** 2] = 0
        out = (sfft.rfft2(k, workers=-1), sfft.rfft2(k * k, workers=-1))
        if self._cache is not None:
            self._cache[sigma] = out
        return out

    def _binned(self, ix, iy, vals):
        g = self.g
        flat = np.bincount(iy * g.nx + ix, weights=vals,
                           minlength=g.nx * g.ny).reshape(g.ny, g.nx)
        return flat

    def smooth(self, ix, iy, z, w, k_mass=None, loo_points=None,
               loo_pairs=None):
        """Returns dict with grids S, neff, sigma (ny x nx); and if loo_points
        (ix, iy) is given, S_loo at those pixels excluding everything binned in
        that same pixel (a leave-building-out prediction).  If loo_pairs
        (t, j, d2_m) is also given, instead exclude listing j from target t's
        prediction for each pair (a leave-neighborhood-out prediction)."""
        if k_mass is None:
            k_mass = K_MASS
        g = self.g
        Wb = self._binned(ix, iy, w)
        Nb = self._binned(ix, iy, w * z)
        Qb = self._binned(ix, iy, w * w)

        def fwd(a):
            pad = np.zeros((self.fy, self.fx))
            pad[:g.ny, :g.nx] = a
            return sfft.rfft2(pad, workers=-1)

        Wf, Nf, Qf = fwd(Wb), fwd(Nb), fwd(Qb)

        def inv(f):
            return sfft.irfft2(f, s=(self.fy, self.fx),
                               workers=-1)[:g.ny, :g.nx]

        acc = _Adaptive((g.ny, g.nx), k_mass)
        acc_loo = None
        if loo_points is not None:
            lix, liy = loo_points
            acc_loo = _Adaptive(lix.shape, k_mass)
            own_W, own_N, own_Q = Wb[liy, lix], Nb[liy, lix], Qb[liy, lix]

        for sigma in self.levels:
            K1, K2 = self._kernels(sigma)
            D = inv(Wf * K1)
            N = inv(Nf * K1)
            Q = inv(Qf * K2)
            acc.add(sigma, D, N, Q)
            if acc_loo is not None:
                if loo_pairs is None:
                    acc_loo.add(sigma,
                                D[liy, lix] - own_W,
                                N[liy, lix] - own_N,
                                Q[liy, lix] - own_Q)
                else:
                    pt, pj, pd2 = loo_pairs
                    kk = np.exp(-pd2 / (2 * sigma * sigma))
                    nt = len(lix)
                    sD = np.bincount(pt, w[pj] * kk, nt)
                    sN = np.bincount(pt, w[pj] * z[pj] * kk, nt)
                    sQ = np.bincount(pt, w[pj] ** 2 * kk * kk, nt)
                    acc_loo.add(sigma,
                                np.maximum(D[liy, lix] - sD, 0),
                                N[liy, lix] - sN,
                                np.maximum(Q[liy, lix] - sQ, 0))
        out = acc.finish()
        if acc_loo is not None:
            out["S_loo"] = acc_loo.finish()["S"]
        return out


class _Adaptive:
    TINY = 1e-6

    def __init__(self, shape, k_mass):
        self.k = k_mass
        self.S = np.full(shape, np.nan)
        self.neff = np.zeros(shape)
        self.sigma = np.full(shape, np.nan)
        self.done = np.zeros(shape, bool)
        self.prev = None

    def add(self, sigma, D, N, Q):
        ok = D > self.TINY
        with np.errstate(invalid="ignore", divide="ignore"):
            S = np.where(ok, N / np.where(ok, D, 1), np.nan)
            neff = np.where(ok, D * D / np.where(Q > self.TINY, Q, np.inf), 0)
        newly = ~self.done & (D >= self.k)
        if self.prev is None:
            f = np.ones(D.shape)
            Sp, np_, sp, Dp = S, neff, sigma, D
        else:
            Dp, Sp, np_, sp = self.prev
            with np.errstate(invalid="ignore", divide="ignore"):
                f = (math.log(self.k) - np.log(np.maximum(Dp, self.TINY))) / (
                    np.log(np.maximum(D, self.TINY)) -
                    np.log(np.maximum(Dp, self.TINY)))
            f = np.clip(np.nan_to_num(f, nan=1.0), 0, 1)
            f = np.where(np.isnan(Sp), 1.0, f)
        Sp0 = np.where(np.isnan(Sp), 0, Sp)
        S0 = np.where(np.isnan(S), 0, S)
        self.S[newly] = (Sp0 + f * (S0 - Sp0))[newly]
        self.neff[newly] = (np_ + f * (neff - np_))[newly]
        self.sigma[newly] = np.exp(
            math.log(sp) + f * (math.log(sigma) - math.log(sp)))[newly]
        self.done |= newly
        self.prev = (D, S, neff, sigma)

    def finish(self):
        D, S, neff, sigma = self.prev
        rest = ~self.done
        self.S[rest] = S[rest]
        self.neff[rest] = neff[rest]
        self.sigma[rest] = sigma
        return {"S": self.S, "neff": self.neff, "sigma": self.sigma}


# ---------------------------------------------------------------------------
# Data


class Scrape:
    def __init__(self, ts, path):
        self.ts = ts
        self.path = path
        self.date = utc_date(ts)
        self.n = 0          # listings after filtering
        self.n_new = 0
        self.partial = False
        self.raw = False    # whether raw JSON was available

    def __repr__(self):
        return "Scrape(%s, n=%d, new=%d%s)" % (
            self.date, self.n, self.n_new, ", partial" if self.partial else "")


def _norm_addr(a):
    return re.sub(r"[^a-z0-9#]", "", a.lower()) if a else None


def _read_scrape(path, ts):
    """Yield (listing_id, rent, bedrooms, lat, lon, address) for a scrape.
    Prefers the raw padmapper JSON when present: it lets us drop building-level
    rows (many floorplans summarized as min price at min bedrooms) and gives us
    addresses for dedup."""
    d = os.path.dirname(path)
    raw_path = os.path.join(d, "apts-download-%d.txt" % ts)
    if os.path.exists(raw_path):
        with open(raw_path) as inf:
            data = json.load(inf)
        rows = []
        for l in data:
            # building-level rows summarize several units; 2016-2018 scrapes
            # call this "count", later ones "floorplan_count"
            if (l.get("floorplan_count") or l.get("count") or 1) > 1:
                continue
            if l.get("min_bedrooms") != l.get("max_bedrooms"):
                continue
            if l.get("min_price") is None or l.get("min_bedrooms") is None:
                continue
            rows.append((str(l["listing_id"]), int(l["min_price"]),
                         int(l["min_bedrooms"]), float(l["lat"]),
                         float(l["lng"]), _norm_addr(l.get("address"))))
        return rows, True
    rows = []
    with open(path) as inf:
        for line in inf:
            if not line[:1].isdigit():
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            rent, br, apt_id, lon, lat = parts[:5]
            rows.append((apt_id, int(rent), int(br), float(lat), float(lon),
                         None))
    return rows, False


class Dataset:
    """All scrapes, with each listing flagged as new (first appearance) or
    not.  Arrays (one row per listing per scrape) are in self.a."""

    def __init__(self, data_dir):
        paths = []
        for fn in os.listdir(data_dir):
            m = re.fullmatch(r"apts-(\d+)\.txt", fn)
            if m:
                paths.append((int(m.group(1)), os.path.join(data_dir, fn)))
        paths.sort()

        grid = Grid(MAP_PX)
        cols = {k: [] for k in ("scrape", "ts", "rent", "br", "lat", "lon",
                                "new")}
        self.scrapes = []
        last_seen = {}
        lookback = {"id": ID_LOOKBACK_DAYS * 86400,
                    "loc": LOCPRICE_LOOKBACK_DAYS * 86400,
                    "addr": ADDRESS_LOOKBACK_DAYS * 86400}
        for ts, path in paths:
            if ts in BAD_SCRAPES:
                continue
            rows, raw = _read_scrape(path, ts)
            sc = Scrape(ts, path)
            sc.raw = raw
            seen_here = set()
            kept = []
            for apt_id, rent, br, lat, lon, addr in rows:
                if apt_id in seen_here or br < 0:
                    continue
                seen_here.add(apt_id)
                if rent / (br + 1) < MIN_RENT_PER_ROOM:
                    continue
                if not grid.in_bounds(lat, lon):
                    continue
                keys = [("id", apt_id),
                        ("loc", br, rent, round(lat, 5), round(lon, 5))]
                if addr:
                    keys.append(("addr", addr, br))
                is_new = not any(
                    k in last_seen and ts - last_seen[k] <= lookback[k[0]]
                    for k in keys)
                kept.append((rent, br, lat, lon, is_new, keys))
            for rent, br, lat, lon, is_new, keys in kept:
                for k in keys:
                    last_seen[k] = ts
            sc.n = len(kept)
            sc.n_new = sum(1 for r in kept if r[4])
            sc.partial = sc.n < MIN_FULL_SCRAPE
            idx = len(self.scrapes)
            self.scrapes.append(sc)
            for rent, br, lat, lon, is_new, _ in kept:
                cols["scrape"].append(idx)
                cols["ts"].append(ts)
                cols["rent"].append(rent)
                cols["br"].append(br)
                cols["lat"].append(lat)
                cols["lon"].append(lon)
                cols["new"].append(is_new)
        self.a = {k: np.array(v) for k, v in cols.items()}
        self.a["new"] = self.a["new"].astype(bool)
        self.a["brc"] = np.minimum(self.a["br"], MAX_BEDROOMS_CATEGORY)

    def window(self, scrape_idx, window_days=WINDOW_DAYS):
        """Indices (into self.a) of new listings in the pooling window."""
        t = self.scrapes[scrape_idx].ts
        a = self.a
        return np.nonzero(a["new"] & (a["ts"] <= t) &
                          (a["ts"] > t - window_days * 86400))[0]


# ---------------------------------------------------------------------------
# Model


def _wmedian(x, w):
    if len(x) == 0:
        return 0.0
    o = np.argsort(x)
    cw = np.cumsum(w[o])
    return float(x[o][np.searchsorted(cw, cw[-1] / 2)])


class Fit:
    pass


def fit_window(ds, scrape_idx, smoother, final_smoother=None,
               k_mass=None, half_life_days=None, loo_target=False,
               window_days=WINDOW_DAYS, loo_radius_m=None,
               building_power=None, min_sigma_m=None):
    """Fit the model for scrape scrape_idx.

    smoother: Smoother used for backfitting (usually FIT_PX).
    final_smoother: if given, the final surface is computed on its grid.
    loo_target: also return leave-own-pixel-out predictions of log rent for the
      new listings in the target scrape (for tuning).
    """
    if k_mass is None:
        k_mass = K_MASS
    if half_life_days is None:
        half_life_days = HALF_LIFE_DAYS
    if building_power is None:
        building_power = BUILDING_POWER
    a = ds.a
    idx = ds.window(scrape_idx, window_days)
    t = ds.scrapes[scrape_idx].ts
    y = np.log(a["rent"][idx].astype(float))
    brc = a["brc"][idx]
    lat, lon = a["lat"][idx], a["lon"][idx]
    ts = a["ts"][idx]

    # periods = distinct scrapes in the window; target is period of ts == t
    periods, p = np.unique(ts, return_inverse=True)
    tp = int(np.nonzero(periods == t)[0][0])

    w_time = 0.5 ** ((t - ts) / (half_life_days * 86400.0))
    bkey = np.round(lat, BUILDING_ROUND) * 1000 + np.round(lon, BUILDING_ROUND)
    _, binv, bcount = np.unique(bkey, return_inverse=True, return_counts=True)
    w_bldg = bcount[binv] ** -float(building_power)
    w0 = w_time * w_bldg

    g = smoother.g
    ix, iy = g.pixel_index(lat, lon)

    ncat = MAX_BEDROOMS_CATEGORY + 1
    be = np.zeros(ncat)
    for b in range(ncat):
        m = brc == b
        if m.any():
            be[b] = _wmedian(y[m], w0[m])
    be -= be[2]
    off = np.zeros(len(periods))
    w = w0.copy()

    for it in range(BACKFIT_ITERS):
        z = y - be[brc] - off[p]
        sm = smoother.smooth(ix, iy, z, w, k_mass=k_mass)
        S_pts = sm["S"][iy, ix]
        S_pts = np.where(np.isnan(S_pts), np.nanmedian(S_pts), S_pts)

        # robust trimming against the current fit, from scratch each time
        e = y - S_pts - be[brc] - off[p]
        med = _wmedian(e, w0)
        scale = 1.4826 * _wmedian(np.abs(e - med), w0)
        keep = np.abs(e - med) <= TRIM_SIGMAS * max(scale, 0.05)
        w = np.where(keep, w0, 0.0)

        r = y - S_pts
        for b in range(ncat):
            m = brc == b
            if w[m].sum() > 0:
                be[b] = np.sum(w[m] * (r[m] - off[p][m])) / w[m].sum()
        be -= be[2]
        rr = r - be[brc]
        num = np.bincount(p, weights=w * rr, minlength=len(periods))
        den = np.bincount(p, weights=w, minlength=len(periods))
        off = num / (den + OFFSET_PRIOR_W)
        off -= off[tp]

    f = Fit()
    f.scrape = ds.scrapes[scrape_idx]
    f.bedroom_effect = be
    f.periods = periods
    f.offsets = off
    f.n_window = len(idx)
    f.n_trimmed = int((w == 0).sum())
    f.robust_scale = float(scale)
    f.idx = idx
    f.weights = w

    z = y - be[brc] - off[p]
    target = ts == t
    if loo_target:
        pairs = None
        if loo_radius_m:
            from scipy.spatial import cKDTree
            xy = np.c_[lat * M_PER_DEG_LAT, lon * M_PER_DEG_LON]
            ti = np.nonzero(target)[0]
            nbrs = cKDTree(xy).query_ball_point(xy[ti], loo_radius_m)
            pt = np.repeat(np.arange(len(ti)), [len(n) for n in nbrs])
            pj = np.concatenate([np.array(n, int) for n in nbrs])
            pd2 = ((xy[ti][pt] - xy[pj]) ** 2).sum(1)
            pairs = (pt, pj, pd2)
        sm = smoother.smooth(ix, iy, z, w, k_mass=k_mass,
                             loo_points=(ix[target], iy[target]),
                             loo_pairs=pairs)
        f.loo_pred = sm["S_loo"] + be[brc[target]]
        f.loo_y = y[target]
        f.loo_brc = brc[target]
        f.loo_ix, f.loo_iy = ix[target], iy[target]
    if final_smoother is not None:
        fg = final_smoother.g
        fix, fiy = fg.pixel_index(lat, lon)
        sm = final_smoother.smooth(fix, fiy, z, w, k_mass=k_mass)
        f.S, f.neff, f.sigma = sm["S"], sm["neff"], sm["sigma"]
        f.grid = fg
    return f


# ---------------------------------------------------------------------------
# Output


def load_mask(path, grid):
    from PIL import Image
    if not os.path.exists(path):
        return np.ones((grid.ny, grid.nx), bool)
    m = np.array(Image.open(path).convert("L")) > 0
    assert m.shape == (grid.ny, grid.nx), m.shape
    return m


def load_units(path, grid):
    """Housing units per pixel (from build_mask.py), or None."""
    from PIL import Image
    if not os.path.exists(path):
        return None
    u = np.array(Image.open(path), dtype=float) / 10
    assert u.shape == (grid.ny, grid.nx), u.shape
    return u


def _wmedian_grid(vals, weights):
    v, w = vals.ravel(), weights.ravel()
    o = np.argsort(v)
    cw = np.cumsum(w[o])
    return float(v[o][np.searchsorted(cw, cw[-1] / 2)])


def encode_png(f, path):
    """R,G: 16-bit code.  Low 11 bits v: 0 = no data, otherwise
    log_rent = LOG_LO + (v - 1) * VALUE_STEP.  High 5 bits q: kernel width
    sigma = SIGMA0_M * SIGMA_RATIO ** (q / 2).
    B: n_eff, capped at 255.  Alpha is always opaque so browsers don't
    premultiply and corrupt the values."""
    from PIL import Image
    S = f.S
    ok = ~np.isnan(S) & (f.neff >= 1)
    code = np.zeros(S.shape, np.uint32)
    # Quantize to steps of 0.25% (~$8 on $3000), far below what the map can
    # resolve; this makes the PNGs ~4x smaller than full 16-bit precision.
    steps = np.round(
        np.clip(S[ok] - LOG_LO, 0, LOG_HI - LOG_LO) / VALUE_STEP)
    code[ok] = 1 + steps.astype(np.uint32)
    assert code.max() < 2048
    # high 5 bits: kernel width, in half-steps of the sigma ladder
    sq = np.round(2 * np.log(np.nan_to_num(f.sigma, nan=SIGMA0_M) / SIGMA0_M)
                  / math.log(SIGMA_RATIO))
    code[ok] |= (np.clip(sq[ok], 0, 31).astype(np.uint32) << 11)
    rgba = np.zeros(S.shape + (4,), np.uint8)
    rgba[..., 0] = code >> 8
    rgba[..., 1] = code & 0xFF
    rgba[..., 2] = np.clip(np.round(f.neff), 0, 255).astype(np.uint8)
    rgba[..., 3] = 255
    Image.fromarray(rgba, "RGBA").save(path, format="PNG", optimize=True)


def summarize(f, ds, scrape_idx, mask, units=None):
    """Metadata JSON for one month.  City and neighborhood levels are
    weighted by housing units when available (else by area), so they
    describe the typical home rather than the typical acre."""
    a = ds.a
    sc = ds.scrapes[scrape_idx]
    g = f.grid
    good = mask & ~np.isnan(f.S) & (f.neff >= 3)
    wt = units if units is not None else np.ones(f.S.shape)
    city_log = (_wmedian_grid(f.S[good], wt[good])
                if good.any() and wt[good].sum() > 0 else None)

    places = {}
    for name, plat, plon in PLACES:
        d = g.disk(plat, plon, PLACE_RADIUS_M) & good
        if d.sum() >= 5 and wt[d].sum() > 0:
            places[name] = round(math.exp(
                float(np.sum(f.S[d] * wt[d]) / wt[d].sum())))

    def stats(sel):
        out = {}
        for b in range(6):
            r = a["rent"][sel & (a["br"] == b)]
            if len(r) >= 10:
                q = np.percentile(r, [25, 50, 75])
                out[str(b)] = {"n": int(len(r)), "p25": int(q[0]),
                               "median": int(q[1]), "p75": int(q[2])}
            else:
                out[str(b)] = {"n": int(len(r))}
        return out

    this = a["scrape"] == scrape_idx
    return {
        "date": sc.date,
        "ts": int(sc.ts),
        "params": params_dict(),
        "n_listed": int(sc.n),
        "n_new": int(sc.n_new),
        "n_window": int(f.n_window),
        "n_trimmed": int(f.n_trimmed),
        "raw_json": bool(sc.raw),
        "bedroom_mult": {str(b): round(math.exp(v), 4)
                         for b, v in enumerate(f.bedroom_effect)},
        "period_offsets": {utc_date(int(ts)): round(float(o), 4)
                           for ts, o in zip(f.periods, f.offsets)},
        "city_2br": round(math.exp(city_log)) if city_log is not None else None,
        "places_2br": places,
        "new_stats": stats(this & a["new"]),
        "all_stats": stats(this),
        "encoding": {"log_lo": LOG_LO, "step": VALUE_STEP,
                     "sigma0_m": SIGMA0_M, "sigma_ratio": SIGMA_RATIO},
    }


def dots(ds, scrape_idx):
    a = ds.a
    sel = (a["scrape"] == scrape_idx) & a["new"]
    return [[round(float(la), 5), round(float(lo), 5), int(b), int(r)]
            for la, lo, b, r in zip(a["lat"][sel], a["lon"][sel],
                                    a["br"][sel], a["rent"][sel])]
