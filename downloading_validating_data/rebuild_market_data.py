from gatherer import build_legacy_parquet
from gatherer_udiff import (
    build_udiff_parquet,
    build_final_parquet,
    validate_final_parquet,
)

print("\n=== REBUILDING LEGACY ===")
build_legacy_parquet()

print("\n=== REBUILDING UDIFF ===")
build_udiff_parquet()

print("\n=== REBUILDING FINAL MARKET DATA ===")
build_final_parquet()

print("\n=== VALIDATING FINAL MARKET DATA ===")
validate_final_parquet()

print("\nDONE.")