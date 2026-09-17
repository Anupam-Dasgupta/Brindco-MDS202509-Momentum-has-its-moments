"""Acquire and normalize NSE corporate-action records."""

from brindco_momentum.data.download_corporate_actions import audit, build_parquet, download_all


if __name__ == "__main__":
    download_all()
    build_parquet()
    audit()
