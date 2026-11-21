from PIL import Image
import sys
import math
import numpy
import json

MAX_X=1000
MAX_Y=1000

def bucket(x):
    if x == (255,255,255,0) or x == (0,0,0,255):
        return None
    r,g,b,a=x
    x=r,g,b
    return [(255, 0, 0),
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
              ].index(x)

def load_metadata(x):
    with open(x.replace(".png", ".metadata.json")) as inf:
        return json.loads(inf.read())

def lookup(val, metadata):
    b = bucket(val)
    if b is None:
        return None

    if b >= len(metadata["buckets"]):
        b = len(metadata["buckets"]) - 1 

    return metadata["buckets"][b] * (2 + metadata["num_phantom_bedrooms"]) * metadata["adjustments"]["2"]

def start(map_a, map_b, out):
    metadata_a = load_metadata(map_a)
    metadata_b = load_metadata(map_b)

    img_a = Image.open(map_a)
    img_b = Image.open(map_b)

    i_a = img_a.load()
    i_b = img_b.load()


    # color regions by price
    I = Image.new('RGBA', (MAX_X, MAX_Y))
    IM = I.load()
    for x in range(MAX_X):
        for y in range(MAX_Y):
            price_a = lookup(i_a[x,y], metadata_a)
            price_b = lookup(i_b[x,y], metadata_b)
            
            if price_a is not None and price_b is not None:
                print price_b

if __name__ == "__main__":
    start(*sys.argv[1:])
