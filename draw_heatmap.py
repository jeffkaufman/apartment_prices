import Image
import sys
import math

# set boundaries in query_padmapper
from query_padmapper import MAX_LAT, MAX_LON, MIN_LAT, MIN_LON

# change these to change how detailed the generated image is
# (1000x1000 is good, but very slow)
MAX_X=100
MAX_Y=100

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

def load_prices(fs, price_per_room=False):
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

                assert bedrooms >= 0
                rooms = bedrooms + 1

                if bedrooms < 1:
                    bedrooms = 1 # singles

                if price_per_room:
                    price = rent / rooms
                else:
                    price = rent / bedrooms

                if price < 150:
                    continue

                prices.append((price, float(lat), float(lon)))

    return prices

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

def color(val, price_per_room=False):
    if val is None:
        return (255,255,255,0)

    if price_per_room:
        prices = [1600, 1500, 1400, 1300, 1200, 1100, 1000, 900,
                  800, 700, 600, 500, 400, 300, 250, 200]
    else:
        prices = [1800, 1700, 1600, 1500, 1400, 1300, 1200, 1100,
                  1000, 900, 800, 700, 600, 500, 400, 300]

    colors = [(255, 0, 0), # red
              (255, 43, 0), # redorange
              (255, 86, 0), # orangered
              (255, 127, 0), # orange
              (255, 171, 0), # orangeyellow
              (255, 213, 0), # yelloworange
              (255, 255, 0), # yellow
              (127, 255, 0), # lime green
              (0, 255, 0), # green
              (0, 255, 127), # teal
              (0, 255, 255), # light blue,
              (0, 213, 255), # medium light blue
              (0, 171, 255), # light medium blue
              (0, 127, 255), # medium blue
              (0, 86, 255), # medium dark blue
              (0, 43, 255), # dark medium blue
              (0, 0, 255), # dark blue
              ]

    assert len(prices) == len(colors) - 1

    for price, color in zip(prices, colors):
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


def start(fname, price_per_X):
    assert price_per_X in ["room", "bedroom"]
    price_per_room = price_per_X == "room"

    priced_points = load_prices([fname], price_per_room)

    I = Image.new('RGBA', (MAX_X, MAX_Y))
    IM = I.load()

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

            IM[x,y] = color(price, price_per_room)


        print "%s/%s" % (x, MAX_X)

    for _, lat, lon in priced_points:
        x, y = ll_to_pixel(lat, lon)
        if 0 <= x < MAX_X and 0 <= y < MAX_Y:
            IM[x,y] = (0,0,0)

    I.save(fname + "." + price_per_X +".png", "PNG")

if __name__ == "__main__":
    start(*sys.argv[1:])
