import json
import sys
import urllib.request, urllib.parse, urllib.error
import urllib.request, urllib.error, urllib.parse
import os.path
import subprocess
import shlex
import time

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

class AreaTooLarge(Exception):
  pass

def direct_fetch(cmd_prefix, minLat, minLng, maxLat, maxLng, it):
  args = shlex.split(cmd_prefix)
  args.append("--data-binary")
  # You would think we could just use offset, but that's not actually respected
  # by the backend.
  args.append('{"bedrooms":[0,1,2,3,4,5],"limit":100,'
              '"maxLat":%s,"minLat":%s,"maxLng":%s,"minLng":%s,'
              '"offset":0,"propertyCategories":["apartment"]}' % (
                  maxLat, minLat, maxLng, minLng))
  args.append('--compressed')
  args.append('-sS')
  time.sleep(1)
  result = json.loads(subprocess.check_output(args))
  if len(result) > 99:
    if it > 50:
      # we've already tried to zoom in too far here, and now we're stuck.
      import pprint
      pprint.pprint(result)
    else:
      raise AreaTooLarge()

  if type(result) != type([]):
    import pprint
    pprint.pprint(result)
  return result

def intermediate(minVal, maxVal):
  return (maxVal-minVal)/2 + minVal

def fetch(cmd_prefix, minLat, minLng, maxLat, maxLng, it=0):
  print(('%s %.10f %.10f %.10f %.10f' % ('  '* it, minLat, minLng, maxLat, maxLng)))

  def fetchHelper(minLat, minLng, maxLat, maxLng):
    return fetch(cmd_prefix, minLat, minLng, maxLat, maxLng, it+1)

  try:
    return direct_fetch(cmd_prefix, minLat, minLng, maxLat, maxLng, it)
  except AreaTooLarge:
    if it % 2:
      return (fetchHelper(minLat, minLng, intermediate(minLat, maxLat), maxLng) +
              fetchHelper(intermediate(minLat, maxLat), minLng, maxLat, maxLng))
    else:
      return (fetchHelper(minLat, minLng, maxLat, intermediate(minLng, maxLng)) +
              fetchHelper(minLat, intermediate(minLng, maxLng), maxLat, maxLng))

def download(fname):
  print("Visit:")
  print('https://www.padmapper.com/apartments/belmont-ma/belmont-hill?box=-71.1993028524,42.396054506,-71.1761285665,42.4262507215&property-categories=apartment')
  print("Inspect the networking, find a pins request, copy request as curl and paste here.")
  inp = input("> ")
  while inp.endswith("\\"):
    inp = inp[:-2] + " "
    inp += input("> ")

  print ("%r" % inp)

  if "--data-raw" not in inp:
    raise Exception("Something looks wrong.  Was that the curl version of a pins request?")

  cmd_prefix = inp.split("--data-raw")[0]
  result = fetch(cmd_prefix, MIN_LAT, MIN_LON, MAX_LAT, MAX_LON)
  if not result:
    raise Exception("no response")
  with open(fname, 'w') as outf:
    outf.write(json.dumps(result))

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

  with open(fname_out, "w") as outf:
    print("writing to %s" % fname_out)
    for rent, bedrooms, apt_id, lon, lat in processed:
      outf.write("%s %s %s %s %s\n" % (rent, bedrooms, apt_id, lon, lat))

def start(fname_download, fname_processed):
  if not os.path.exists(fname_download):
    download(fname_download)
  if not os.path.exists(fname_download):
    raise Exception("%s still missing" % fname_download)

  if not os.path.exists(fname_processed):
    process(fname_download, fname_processed)
  else:
    print("%s already exists" % fname_processed)

  print("Now you want to use draw_heatmap.py on %s" % fname_processed)

if __name__ == "__main__":
  start(*sys.argv[1:])
