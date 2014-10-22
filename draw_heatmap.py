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

# at what distance should we stop making predictions?
IGNORE_DIST=0.01

# this is a good waty
MODE = "INVERTED_DISTANCE_WEIGHTED_AVERAGE"
#MODE = "K_NEAREST_NEIGHBORS"

# this only affects k_nearest mode
K=5

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
    raw_prices = []
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

                assert bedrooms >= 0
                rooms = bedrooms + 1

                assert bedrooms >= 0

                if rent / (bedrooms + 1) < 150:
                    continue

                raw_prices.append((bedrooms, rent, float(lat), float(lon)))

    slope, y_intercept = linear_regression([(bedrooms, rent) for (bedrooms, rent, lat, lon) in raw_prices])
    print "slope =", slope
    print "y intercept =", y_intercept
    x_intercept = -(y_intercept)/slope
    print "x intercept =", x_intercept
    num_phantom_bedrooms = -x_intercept # positive now

    prices = [(rent / (bedrooms + num_phantom_bedrooms), lat, lon) for (bedrooms, rent, lat, lon) in raw_prices]
    return prices, num_phantom_bedrooms

def linear_regression(pairs):
  xs = [x for (x,y) in pairs]
  ys = [y for (x,y) in pairs]

  A = numpy.array([xs, numpy.ones(len(xs))])
  w = numpy.linalg.lstsq(A.T,ys)[0]
  return w[0], w[1]

def distance(x1,y1,x2,y2):
    return math.sqrt((x1-x2)*(x1-x2) + (y1-y2)*(y1-y2))

def k_nearest(prices, lat, lon):
    distances = [(distance(lat,lon,plat,plon), price)
                 for (price, plat, plon) in prices]
    distances.sort()
    prices = [price for (dist, price) in distances[:K]
              if dist < IGNORE_DIST]
    if len(prices) != K:
        return None
    return prices

def greyscale(price):
    grey = int(256*float(price)/3000)
    return grey, grey, grey

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

    for price, color in zip(buckets, colors):
        if val > price:
            return color
    return colors[-1]

def inverted_distance_weighted_average(prices, lat, lon):
    num = 0
    dnm = 0
    c = 0

    for price, plat, plon in prices:
        dist = distance(lat,lon,plat,plon) + 0.0001

        if dist > IGNORE_DIST:
            continue

        inv_dist = 1/dist

        num += price * inv_dist
        dnm += inv_dist
        c += 1

    # don't display any averages that don't take into account at least five data points
    if c < 5:
        return None

    return num/dnm


def start(fname):
    priced_points, num_phantom_bedrooms = load_prices([fname])

    # price all the points
    prices = {}
    for x in range(MAX_X):
        for y in range(MAX_Y):
            lat, lon = pixel_to_ll(x,y)

            if MODE == "K_NEAREST_NEIGHBORS":
                nearest = k_nearest(priced_points, lat, lon)
                if not nearest:
                    price = None
                else:
                    price = float(sum(nearest))/K
            elif MODE == "INVERTED_DISTANCE_WEIGHTED_AVERAGE":
                price = inverted_distance_weighted_average(priced_points, lat, lon)
            else:
                assert False

            prices[x,y] = price

    # determine buckets
    # we want 18 buckets (17 divisions) of equal area
    all_priced_areas = [x for x in sorted(prices.values()) if x is not None]
    total_priced_area = len(all_priced_areas)

    buckets = []
    divisions = 17.0
    stride = total_priced_area / (divisions + 1)
    next_i = int(stride)
    error_i = stride - next_i
    for i, val in enumerate(all_priced_areas):
      if i == next_i:
        buckets.append(val)
        delta_i = stride + error_i
        next_i += int(delta_i)
        error_i = delta_i - int(delta_i)
    
    buckets.reverse()

    print "buckets: ", buckets

    # color regions by price
    I = Image.new('RGBA', (MAX_X, MAX_Y))
    IM = I.load()
    for x in range(MAX_X):
        for y in range(MAX_Y):
            IM[x,y] = color(prices[x,y], buckets)

    # add the dots
    for _, lat, lon in priced_points:
        x, y = ll_to_pixel(lat, lon)
        if 0 <= x < MAX_X and 0 <= y < MAX_Y:
            IM[x,y] = (0,0,0)

    out_fname = fname + ".phantom." + str(MAX_X)
    I.save(out_fname + ".png", "PNG")
    with open(out_fname + ".metadata.json", "w") as outf:
      outf.write(json.dumps({
          "num_phantom_bedrooms": num_phantom_bedrooms,
          "buckets": buckets}))

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print "usage: python draw_heatmap.py apts.txt"
    else:
        fname = sys.argv[1]
        start(fname)
