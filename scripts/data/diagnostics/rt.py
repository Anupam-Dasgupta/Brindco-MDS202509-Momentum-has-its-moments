import pandas as pd
from brindco_momentum.paths import ROOT

audit = pd.read_csv(
    ROOT / "data/processed/trading_calendar_audit.csv"
)

print(audit.to_string(index=False))
