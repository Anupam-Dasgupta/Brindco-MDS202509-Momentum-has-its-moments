"""Build the frozen development shadow portfolio."""

from brindco_momentum.portfolio.shadow_portfolio import build_primary_shadow


if __name__ == "__main__":
    for name, value in build_primary_shadow().items():
        print(f"{name}: {value}")
