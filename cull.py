import sys
seen = set()
for fname in sys.argv[1:]:
  with open(fname) as inf:
    with open(fname + '.culled', 'w') as outf:
      for line in inf:
        try:
          apt_id = line.split()[2]
        except:
          print('%s: %s' % (fname, line))
          raise
                   
        if apt_id in seen:
          continue
        seen.add(apt_id)
        outf.write(line)
  
