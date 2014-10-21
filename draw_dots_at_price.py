import Image
import sys
import math

# set boundaries in query_padmapper
from query_padmapper import MAX_LAT, MAX_LON, MIN_LAT, MIN_LON

# change these to change how detailed the generated image is
# (1000x1000 is good, but very slow)
MAX_X=1000
MAX_Y=1000

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

def load_positions(fs, n_br):
    points = []
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

                if bedrooms != n_br:
                    continue

                points.append((float(lat), float(lon)))

    return points

def distance(x1,y1,x2,y2):
    return math.sqrt((x1-x2)*(x1-x2) + (y1-y2)*(y1-y2))

def start(fname, n_bedrooms):
    points = load_positions([fname], int(n_bedrooms))

    I = Image.new('RGBA', (MAX_X, MAX_Y))
    IM = I.load()

    for lat, lon in points:
        x, y = ll_to_pixel(lat, lon)
        for x1, y1 in [(x,y),
                       (x+1,y+1),
                       (x-1,y-1),
                       (x-1,y+1),
                       (x+1, y-1),
                       (x+2,y+2),
                       (x-2,y-2),
                       (x-2,y+2),
                       (x+2, y-2)]:
            if 0 <= x1 < MAX_X and 0 <= y1 < MAX_Y:
                IM[x1,y1] = (0,0,0)

    I.save(fname + "." + n_bedrooms + "br." + str(MAX_X) + ".png", "PNG")

if __name__ == "__main__":
    start(*sys.argv[1:])
