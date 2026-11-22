import csv, hashlib, sys, os
from pathlib import Path
root=Path(sys.argv[1]); man=root/'data/raw/manifest.csv'
rows=list(csv.DictReader(open(man,newline='',encoding='utf-8',errors='replace')))
listed=set(); bad=[]; miss=[]; badsize=[]
for r in rows:
    p=root/r['path']; listed.add(os.path.normpath(p))
    if not p.exists(): miss.append(r['path']); continue
    b=p.read_bytes()
    if hashlib.sha256(b).hexdigest()!=r['sha256']: bad.append(r['path'])
    if r.get('bytes') and int(r['bytes'])!=len(b): badsize.append(r['path'])
ondisk=[os.path.normpath(p) for p in (root/'data/raw').rglob('*') if p.is_file()]
skip={'manifest.csv','absent.csv'}
unl=[p for p in ondisk if p not in listed and Path(p).name not in skip]
print('rows',len(rows),'dup_paths',len(rows)-len({r['path'] for r in rows}))
print('missing',len(miss),'hash_bad',len(bad),'size_bad',len(badsize),'unlisted_on_disk',len(unl))
for x in (miss+bad+badsize)[:20]: print(' !',x)
for x in unl[:30]: print(' unlisted',x)
