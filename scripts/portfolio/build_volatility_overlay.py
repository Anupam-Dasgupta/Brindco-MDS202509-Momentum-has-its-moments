"""Build the development volatility overlay."""

from brindco_momentum.portfolio.volatility_overlay import build_overlay


if __name__ == "__main__":
    for name, value in build_overlay().items():
        print(f"{name}: {value}")
