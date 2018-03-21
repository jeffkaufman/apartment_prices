""" Forked version of draw_heatmap.py for comparing across years

This version is simplified:
* Hardcoded buckets
* Only looks at 2brs

Arguments:
  1st argument: title
  remaining arguments: files to read

Good to call this with a whole year's worth of data (with any bad months
removed).
"""

from PIL import Image
import sys
import math
import numpy
import json

# set boundaries in query_padmapper
from query_padmapper import MAX_LAT, MAX_LON, MIN_LAT, MIN_LON

# change these to change how detailed the generated image is
# (1000x1000 is good, but very slow)
MAX_X=1000
MAX_Y=1000

DRAW_DOTS=False

# at what distance should we stop making predictions?
IGNORE_DIST=0.01

def pixel_to_ll(x,y):
    delta_lat = MAX_LAT-MIN_LAT
    delta_lon = MAX_LON-MIN_LON

    # x is lon, y is lat
    # 0,0 is MIN_LON, MAX_LAT

    x_frac = float(x)/MAX_X
    y_frac = float(y)/MAX_Y

    lon = MIN_LON + x_frac*delta_lon
    lat = MAX_LAT - y_frac*delta_lat


    calc_x, calc_y = ll_to_pixel(lat, lon)

    if abs(calc_x-x) > 1 or abs(calc_y-y) > 1:
        print "Mismatch: %s, %s => %s %s" % (
            x,y, calc_x, calc_y)

    return lat, lon

def ll_to_pixel(lat,lon):
    adj_lat = lat-MIN_LAT
    adj_lon = lon-MIN_LON

    delta_lat = MAX_LAT-MIN_LAT
    delta_lon = MAX_LON-MIN_LON

    # x is lon, y is lat
    # 0,0 is MIN_LON, MAX_LAT

    lon_frac = adj_lon/delta_lon
    lat_frac = adj_lat/delta_lat

    x = int(lon_frac*MAX_X)
    y = int((1-lat_frac)*MAX_Y)

    return x,y

def load_prices(fs):
    prices = []
    seen = set()
    for f in fs:
        with open(f) as inf:
            for line in inf:
                if not line[0].isdigit():
                    continue

                rent, bedrooms, apt_id, lon, lat = line.strip().split()

                if apt_id in seen:
                    continue
                else:
                    seen.add(apt_id)

                rent, bedrooms = int(rent), int(bedrooms)
                if bedrooms != 2:
                    continue

                prices.append((rent, float(lat), float(lon)))
    return prices

def distance_squared(x1,y1,x2,y2):
    return (x1-x2)*(x1-x2) + (y1-y2)*(y1-y2)

def color(val, buckets):
    if val is None:
        return (255,255,255,0)

    colors = [(255, 0, 0),
              (255, 91, 0),
              (255, 127, 0),
              (255, 171, 0),
              (255, 208, 0),
              (255, 240, 0),
              (255, 255, 0),
              (218, 255, 0),
              (176, 255, 0),
              (128, 255, 0),
              (0, 255, 0),
              (0, 255, 255),
              (0, 240, 255),
              (0, 213, 255),
              (0, 171, 255),
              (0, 127, 255),
              (0, 86, 255),
              (0, 0, 255),
              ]
    assert len(colors) == len(buckets)
    for price, color in zip(buckets, colors):
        if val > price:
            return color
    return colors[-1]

gaussian_variance = IGNORE_DIST/2
gaussian_a = 1 / (gaussian_variance * math.sqrt(2 * math.pi))
gaussian_negative_inverse_twice_variance_squared = -1 / (2 * gaussian_variance * gaussian_variance)

def gaussian(prices, lat, lon, ignore=None):
    num = 0
    dnm = 0
    c = 0

    for price, plat, plon in prices:
        if ignore:
            ilat, ilon = ignore
            if distance_squared(plat, plon, ilat, ilon) < 0.0001:
                continue

        weight = gaussian_a * math.exp(distance_squared(lat,lon,plat,plon) *
                                       gaussian_negative_inverse_twice_variance_squared)

        num += price * weight
        dnm += weight

        if weight > 2:
            c += 1

    # don't display any averages that don't take into account at least five data points with significant weight
    if c < 5:
        return None

    return num/dnm


def start(title, *fnames):
    print "loading data..."
    priced_points= load_prices(fnames)

    print "pricing all the points..."
    prices = {}
    for x in range(MAX_X):
        print "  %s/%s" % (x, MAX_X)
        for y in range(MAX_Y):
            lat, lon = pixel_to_ll(x,y)
            prices[x,y] = gaussian(priced_points, lat, lon)

    buckets = [
        4000,
        3800,
        3600,
        3400,
        3200,
        3000,
        2800,
        2700,
        2600,
        2500,
        2400,
        2300,
        2200,
        2100,
        2000,
        1900,
        1800,
        1700]

    print "buckets: ", buckets

    # color regions by price
    I = Image.new('RGBA', (MAX_X, MAX_Y))
    IM = I.load()
    for x in range(MAX_X):
        for y in range(MAX_Y):
            IM[x,y] = color(prices[x,y], buckets)

    if DRAW_DOTS:
        for _, lat, lon, _ in priced_points:
            x, y = ll_to_pixel(lat, lon)
            if 0 <= x < MAX_X and 0 <= y < MAX_Y:
                IM[x,y] = (0,0,0)

    out_fname = title + ".2br-static." + str(MAX_X)
    I.save(out_fname + ".png", "PNG")

if __name__ == "__main__":
    start(*sys.argv[1:])
