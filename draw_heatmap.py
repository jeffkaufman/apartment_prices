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

def load_prices(*fs):
    prices = []
    seen = set()
    for f in fs:
        with open(f) as inf:
            for line in inf:
                if not line[0].isdigit():
                    continue

                rent, bedrooms, apt_id, lon, lat = line.strip().split()
                rent, bedrooms = int(rent), int(bedrooms)
            
                if bedrooms < 1:
                    bedrooms = 1

                price = rent / bedrooms

                if apt_id in seen:
                    continue
                else:
                    seen.add(apt_id)
            
                if price < 300:
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

def color(val):
    if val is None:
        return (255,255,255,0)

    if val > 1800:
        return (255, 0, 0) # red
    elif val > 1700:
        return (255, 43, 0) # redorange
    elif val > 1600:
        return (255, 86, 0) # orangered
    elif val > 1500:
        return (255, 127, 0) # orange
    elif val > 1400:
        return (255, 171, 0) # orangeyellow
    elif val > 1300:
        return (255, 213, 0) # yelloworange
    elif val > 1200:
        return (255, 255, 0) # yellow
    elif val > 1100:
        return (127, 255, 0) # lime green
    elif val > 1000:
        return (0, 255, 0) # green
    elif val > 900:
        return (0, 255, 127) # teal
    elif val > 800:
        return (0, 255, 255) # light blue
    elif val > 700:
        return (0, 213, 255) # medium light blue
    elif val > 600:
        return (0, 171, 255) # light medium blue
    elif val > 500:
        return (0, 127, 255) # medium blue
    elif val > 400:
        return (0, 86, 255) # medium dark blue
    elif val > 300:
        return (0, 43, 255) # dark medium blue
    else:
        return (0, 0, 255) # dark blue

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
    

def start():
    priced_points = load_prices("apts.txt")

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

            IM[x,y] = color(price)
                

        print "%s/%s" % (x, MAX_X)

    for _, lat, lon in priced_points:
        x, y = ll_to_pixel(lat, lon)
        if 0 <= x < MAX_X and 0 <= y < MAX_Y:
            IM[x,y] = (0,0,0)

    I.save("apts.png", "PNG")

if __name__ == "__main__":
    start()
