import sys

def start(index):
  seen = set()
  brN = {} # (date, n) -> price
  is_first = True
  with open(index) as index_inf:
    for index_line in index_inf:
      apts_fname, date = index_line.strip().split()
      with open(apts_fname) as apts_inf:
        for apts_line in apts_inf:
          price, nbr, listing_id, *_ = apts_line.split()
          if int(nbr) > 6:
            continue
          
          if listing_id not in seen:
            seen.add(listing_id)
            if not is_first:
              key = date, nbr
              if key not in brN:
                brN[key] = []
              brN[key].append(int(price))
      is_first = False
  for (date, nbr), prices in brN.items():
    with open('prices-%s-%s.tsv' % (date, nbr), 'w') as outf:
      outf.write("percentile\t%s %s\n" % (date, nbr))
      prices.sort()
      for price_index, price in enumerate(prices):
        outf.write("%.4f\t%s\n" % (price_index/len(prices), price))
      
if __name__ == "__main__":
  start(*sys.argv[1:])
