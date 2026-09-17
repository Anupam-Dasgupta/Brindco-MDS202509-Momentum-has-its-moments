import pandas as pd

x = pd.read_csv(
    "data/processed/membership_audit/overlapping_intervals.csv"
)

print(x.to_string(index=False))