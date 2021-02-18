import sys

def start(index):
  seen = set()
  br2 = {} # date -> 2br prices
  is_first = True
  with open(index) as index_inf:
    for index_line in index_inf:
      apts_fname, date = index_line.strip().split()
      if not is_first:
        br2[date] = []
      with open(apts_fname) as apts_inf:
        for apts_line in apts_inf:
          price, nbr, listing_id, *_ = apts_line.split()
          if listing_id not in seen:
            seen.add(listing_id)
            if nbr == "2" and not is_first:
              br2[date].append(int(price))
      is_first = False
  with open("2br-prices.tsv", "w") as outf:
    outf.write("percentile\t%s\n" % ("\t".join(sorted(br2))))
    for date_index, (date, br2_prices) in enumerate(sorted(br2.items())):
      br2_prices.sort()
      for price_index, price in enumerate(br2_prices):
        outf.write("%.4f\t%s%s\n" % (price_index/len(br2_prices), "\t"*date_index, price))
      
if __name__ == "__main__":
  start(*sys.argv[1:])
