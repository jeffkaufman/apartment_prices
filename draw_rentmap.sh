#!/bin/bash
# Monthly rent map build (v3).  Installed on ps as /home/jefftk/draw_heatmaps.sh.
#
#  - Builds every month with build_rentmap.py into the main apartment_prices
#    directory.  Months already built with the current parameters are
#    skipped, and each month's files are written atomically, so a crash just
#    means the next run redoes that month: no .started/.finished markers that
#    can get stuck.
#  - The front end (site/index.html, site/trends.html) is copied from the repo
#    on each run instead of being edited in place.
#  - Still regenerates data-listing.html like the v2 script did.
#
# Requirements on ps (already present): python3, numpy, scipy, pillow.

set -euo pipefail

CODE_DIR=/home/jefftk/code/apartment_prices
WORKING_DIR=/home/jefftk/jtk/apartment_prices
OUT_DIR=$WORKING_DIR

DATA_LISTING=$WORKING_DIR/data-listing.html
: > "$DATA_LISTING.tmp"
for x in "$WORKING_DIR"/apts-1*.txt ; do
  ts=$(basename "$x" .txt | sed s/apts-//)
  YYYYMMDD=$(date --utc --date=@"$ts" +%F)
  echo "<a href='$(echo "$x" | sed s~/home/jefftk/jtk~~)'>$YYYYMMDD</a><br>" >> "$DATA_LISTING.tmp"
done
mv "$DATA_LISTING.tmp" "$DATA_LISTING"

cd "$CODE_DIR"
python3 build_rentmap.py "$WORKING_DIR" "$OUT_DIR"
