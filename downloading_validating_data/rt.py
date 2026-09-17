import pandas as pd

audit = pd.read_csv(
    "data/processed/trading_calendar_audit.csv"
)

print(audit.to_string(index=False))