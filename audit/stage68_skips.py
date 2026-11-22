"""6.8a: run check_membership with the date-based exemptions removed, to see what they hide."""
import pandas as pd
from nseuniverse import verify
base = verify.check_membership(); print("as shipped:", base.status, base.summary)
verify._RESTRUCTURE_DATE = pd.Timestamp("1900-01-01")
r = verify.check_membership(); print("no 2016 skip:", r.status, r.summary)
import collections
print(collections.Counter((p[0], p[1], p[2]) for p in r.details if p[0]=="subset_violation").most_common(8)); print(r.details[:6])
verify._RESTRUCTURE_DATE = pd.Timestamp("2016-04-01"); verify._MIDCAP100_RESTRUCTURE_DATE = pd.Timestamp("1900-01-01")
r = verify.check_membership(); print("no 2018 midcap100 skip:", r.status, r.summary); print(r.details[:6])
