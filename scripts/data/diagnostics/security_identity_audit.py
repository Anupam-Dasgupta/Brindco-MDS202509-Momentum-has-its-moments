import pandas as pd
from brindco_momentum.paths import ROOT

base = ROOT / "data/processed/security_identity"

res = pd.read_csv(base / "membership_mismatch_resolution.csv")

print("\n=== MISMATCH RESOLUTION ===")
print(res["status"].value_counts(dropna=False))

print("\nResolution rate:")
print(
    round(
        100 * (res["status"] == "RESOLVED").mean(),
        2
    ),
    "%"
)

unresolved_path = base / "unresolved_membership_mismatches.csv"

if unresolved_path.exists():
    u = pd.read_csv(unresolved_path)

    print("\n=== UNRESOLVED ===")
    print("Rows:", len(u))
    print("Unique membership symbols:", u["membership_symbol"].nunique())

    print("\nMost common unresolved symbols:")
    print(
        u["membership_symbol"]
        .value_counts()
        .head(30)
        .to_string()
    )

ambiguous_path = base / "ambiguous_membership_mismatches.csv"

if ambiguous_path.exists():
    a = pd.read_csv(ambiguous_path)

    print("\n=== AMBIGUOUS ===")
    print("Rows:", len(a))
    print("Unique symbols:", a["membership_symbol"].nunique())

overlap_path = base / "same_isin_overlap_flags.csv"

if overlap_path.exists():
    o = pd.read_csv(overlap_path)

    print("\n=== SAME-ISIN OVERLAP FLAGS ===")
    print("Rows:", len(o))
    print(o.head(20).to_string(index=False))
else:
    print("\nNo suspicious same-ISIN overlap file generated.")
