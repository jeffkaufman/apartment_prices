#!/usr/bin/env python3
"""Build housing_mask.png and housing_units.png from 2020 Census blocks.

housing_mask.png: which map pixels are near any housing.

Uses 2020 Census block geometry, which carries a HOUSING20 (housing unit
count) field.  A pixel is "inhabited" if it falls inside a block with at least
one housing unit, after dilating by MASK_DILATE_M meters so that the edges of
residential areas don't get clipped.  Water, the airport, rail yards, large
parks, cemeteries, and most industrial land come out as uninhabited.

housing_units.png: 16-bit housing units per pixel (each block's HOUSING20
spread evenly over its pixels).  Used to weight city-wide and neighborhood
summaries by where people actually live, rather than by land area.

This only needs to be re-run if the map bounds or resolution change.

Usage:
  # download once (~100MB):
  #   https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK20/tl_2020_25_tabblock20.zip
  python3 build_mask.py path/to/tl_2020_25_tabblock20.shp

Requires: pyshp, pillow, numpy, scipy
"""

import sys

import numpy as np
import shapefile  # pyshp
from PIL import Image, ImageDraw
from scipy import ndimage

import rentmap

MASK_DILATE_M = 100


def main(shp_path, out_path="housing_mask.png",
         units_path="housing_units.png"):
    g = rentmap.Grid(rentmap.MAP_PX)
    # Label image: each block with housing gets its own integer id, so we can
    # count its pixels and spread its housing units over them.
    img = Image.new("I", (g.nx, g.ny), 0)
    draw = ImageDraw.Draw(img)

    sf = shapefile.Reader(shp_path)
    fields = [f[0] for f in sf.fields[1:]]
    housing_idx = fields.index("HOUSING20")

    units = [0]       # by label; label 0 = no block
    centroids = [None]
    for shape_rec in sf.iterShapeRecords():
        n_units = shape_rec.record[housing_idx]
        if n_units <= 0:
            continue
        shp = shape_rec.shape
        min_lon, min_lat, max_lon, max_lat = shp.bbox
        if (max_lon < rentmap.MIN_LON or min_lon > rentmap.MAX_LON or
                max_lat < rentmap.MIN_LAT or min_lat > rentmap.MAX_LAT):
            continue
        label = len(units)
        units.append(n_units)
        centroids.append(g.lonlat_to_fpixel((min_lon + max_lon) / 2,
                                            (min_lat + max_lat) / 2))
        parts = list(shp.parts) + [len(shp.points)]
        for a, b in zip(parts[:-1], parts[1:]):
            pts = shp.points[a:b]
            # Holes in blocks with housing are rare and small; filling them is
            # fine here.
            xy = [g.lonlat_to_fpixel(lon, lat) for lon, lat in pts]
            if len(xy) >= 3:
                draw.polygon(xy, fill=label)

    labels = np.array(img, dtype=np.int64)
    units = np.array(units, dtype=float)
    counts = np.bincount(labels.ravel(), minlength=len(units))
    per_px = np.zeros(len(units))
    nz = counts > 0
    per_px[nz] = units[nz] / counts[nz]
    density = per_px[labels]
    density[labels == 0] = 0
    # blocks too small to cover any pixel center: put their units at the
    # pixel containing the block's bbox center
    for lab in np.nonzero(~nz)[0]:
        if lab == 0:
            continue
        x, y = centroids[lab]
        if 0 <= x < g.nx and 0 <= y < g.ny:
            density[int(y), int(x)] += units[lab]

    mask = density > 0
    ry = MASK_DILATE_M / g.m_per_px_y
    rx = MASK_DILATE_M / g.m_per_px_x
    yy, xx = np.mgrid[-int(ry) - 1:int(ry) + 2, -int(rx) - 1:int(rx) + 2]
    struct = (yy / ry) ** 2 + (xx / rx) ** 2 <= 1
    mask = ndimage.binary_dilation(mask, structure=struct)

    Image.fromarray((mask * 255).astype(np.uint8)).convert("1").save(out_path)
    # tenths of a unit, 16-bit
    Image.fromarray(np.clip(np.round(density * 10), 0, 65535).astype(
        np.uint16)).save(units_path)
    print("%d blocks with housing (%d housing units in bounds); "
          "%.1f%% of map is inhabited; wrote %s, %s" % (
              len(units) - 1, density.sum(), 100 * mask.mean(), out_path,
              units_path))


if __name__ == "__main__":
    main(*sys.argv[1:])
