import pandas as pd
from brindco_momentum.paths import ROOT

x = pd.read_csv(
    ROOT / "data/processed/membership_audit/overlapping_intervals.csv"
)

print(x.to_string(index=False))
