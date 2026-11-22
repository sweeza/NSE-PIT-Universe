"""6.7: for every curated alias (company -> symbol), compare the company name with every bhavcopy name ever
used by the security(ies) behind that symbol. Low similarity = needs a human look (rename without name overlap)."""
import glob, re, collections, pandas as pd
B = "data/build/"
a = pd.read_csv("data/curated/name_aliases.csv", dtype=str).fillna("")
seg = pd.read_parquet(B + "identity/segments.parquet")
names = collections.defaultdict(set)   # sec_id -> names
for f in glob.glob(B + "bhavcopy/*.parquet"):
    d = pd.read_parquet(f, columns=["sec_id", "name"]).drop_duplicates().dropna()
    for s, n in zip(d.sec_id, d.name): names[s].add(n)
STOP = {"ltd","limited","india","indian","co","company","corporation","corp","the","of","and","&","pvt","private","industries","services","inc"}
def toks(s): return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in STOP}
rows = []
for r in a.itertuples():
    sids = set(seg.sec_id[seg.symbol == r.symbol])
    if not sids: rows.append((r.company, r.symbol, "NO_SECURITY", 0, r.source[:40])); continue
    allnames = set().union(*[names[s] for s in sids]) or set()
    ct = toks(r.company)
    best = max((len(ct & toks(n)) / max(1, len(ct)) for n in allnames), default=0)
    rows.append((r.company, r.symbol, "|".join(sorted(allnames))[:70], round(best, 2), r.source[:40]))
df = pd.DataFrame(rows, columns=["company", "symbol", "bhavcopy_names", "overlap", "source"])
print("aliases", len(df), "| no security", (df.bhavcopy_names == "NO_SECURITY").sum(), "| overlap==0:", (df.overlap == 0).sum(), "| <0.5:", (df.overlap < 0.5).sum())
print(df[df.overlap < 0.5].groupby("source").size().to_dict())
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 60)
print(df[df.overlap == 0].to_string(index=False)[:6000])
df.to_csv("audit/stage67_alias_review.csv", index=False)
