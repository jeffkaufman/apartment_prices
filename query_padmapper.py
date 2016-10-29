import json
import sys
import urllib
import urllib2
import os.path

YOUR_NAME = "YOUR NAME (your-email@example.com)"

# boston
MIN_LAT=42.255594
MAX_LAT=42.4351936
MIN_LON=-71.1828231
MAX_LON=-70.975800

# baltimore
#MAX_LAT=39.388979
#MIN_LON=-76.752548
#MIN_LAT=39.208315
#MAX_LON=-76.464844

# atlanta
#MIN_LAT=33.453214
#MAX_LON=-84.017944
#MAX_LAT=33.934245
#MIN_LON=-84.508209

# bay area from google maps: ll=37.53151,-122.163849&spn=0.634907,1.0849
#MIN_LAT=37.23
#MAX_LON=-121.62
#MAX_LAT=37.83
#MIN_LON=-122.70

def download(fname):
  base = os.path.basename(fname)
  print "Visit:"
  print 'https://www.padmapper.com/apartments/belmont-ma/belmont-hill?box=-71.1993028524,42.396054506,-71.1761285665,42.4262507215&property-categories=apartment'
  print "Inspect the networking, find a pins request, copy request as curl and paste here."
  inp = raw_input("> ")
  if "--data-binary" not in inp:
    raise Exception("Something looks wrong.  Was that the curl version of a pins request?")

  print "Run:"
  print inp.split("--data-binary")[0] + '--data-binary \'{"bedrooms":[0,1,2,3,4,5],"limit":10000,"maxLat":%s,"minLat":%s,"maxLng":%s,"minLng":%s,"offset":0,"propertyCategories":["apartment"]}\' --compressed -o %s' % (
    MAX_LAT, MIN_LAT, MAX_LON, MIN_LON, base)
  raw_input("waiting...")

def process(fname_in, fname_out):
  with open(fname_in) as inf:
    data = json.loads(inf.read())
  processed = []
  for listing in data:
    lat = listing["lat"]
    lon = listing["lng"]
    bedrooms = listing["min_bedrooms"]
    rent = listing["min_price"]
    apt_id = listing["listing_id"]

    processed.append((rent, bedrooms, apt_id, lon, lat))

  if len(processed) >= 9999:
    print "should probably raise the limit in the pull"

  with open(fname_out, "w") as outf:
    print "writing to %s" % fname_out
    for rent, bedrooms, apt_id, lon, lat in processed:
      outf.write("%s %s %s %s %s\n" % (rent, bedrooms, apt_id, lon, lat))

def start(fname_download, fname_processed):
  if not os.path.exists(fname_download):
    download(fname_download)
  if not os.path.exists(fname_download):
    raise Exeption("%s still missing" % fname_download)

  if not os.path.exists(fname_processed):
    process(fname_download, fname_processed)
  else:
    print "%s already exists" % fname_processed

  print "Now you want to use draw_heatmap.py on %s" % fname_processed

if __name__ == "__main__":
  start(*sys.argv[1:])
