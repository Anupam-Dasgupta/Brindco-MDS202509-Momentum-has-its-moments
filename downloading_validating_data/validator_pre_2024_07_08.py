import pandas as pd

df = pd.read_parquet("data/processed/nse_cm_legacy_2013_2024.parquet")

print(df.shape)
print(df["date"].min(), df["date"].max())
print(df["date"].nunique())
print(df["isin"].nunique())
print(df["series"].value_counts().head(20))

print(df.isna().sum())

dupes = df.duplicated(
    subset=["date", "isin", "series"],
    keep=False
)
print("Duplicate key rows:", dupes.sum())