"""Read-only final metrics for the completed, sealed holdout bundle."""

from __future__ import annotations

import numpy as np
import pandas as pd

from brindco_momentum.paths import ROOT


BUNDLE = ROOT / "results/accounts_holdout/frozen_bundle"
OUT = ROOT / "results"
ANCHOR = pd.Timestamp("2023-03-31")
END = pd.Timestamp("2026-03-30")
ACCOUNTS = ("MOM", "VM", "FIX", "FIXVOL")


def main() -> None:
    summary = pd.read_csv(BUNDLE / "holdout_metrics.csv").set_index("account")
    if set(summary.index) != set(ACCOUNTS) or not summary.sessions.eq(742).all():
        raise ValueError("Completed four-account bundle is incomplete")
    tri = pd.read_parquet(
        ROOT / "data/processed/nifty500_tri_2013_2026.parquet",
        columns=["date", "tri"],
        filters=[("date", ">=", ANCHOR), ("date", "<=", END)],
    ).sort_values("date")
    dates = pd.read_parquet(
        ROOT / "data/processed/nse_trading_calendar_2013_2026.parquet",
        columns=["date"],
        filters=[("date", ">", ANCHOR), ("date", "<=", END)],
    ).sort_values("date")["date"].reset_index(drop=True)
    if (len(tri) != len(dates) + 1 or tri.date.iloc[0] != ANCHOR
            or tri.date.iloc[-1] != END or not tri.date.iloc[1:].reset_index(drop=True).equals(dates)
            or not np.isfinite(tri.tri).all() or tri.tri.le(0).any()):
        raise ValueError("Holdout NIFTY 500 TRI does not cover all canonical sessions")
    years = (END - ANCHOR).days / 365.2425
    benchmark_cagr = float((tri.tri.iloc[-1] / tri.tri.iloc[0]) ** (1 / years) - 1)
    rows = []
    for name in ACCOUNTS:
        nav = pd.read_parquet(BUNDLE / f"{name}_nav_daily.parquet")
        fills = pd.read_parquet(BUNDLE / f"{name}_fills.parquet")
        cash = pd.read_parquet(BUNDLE / f"{name}_cash_events.parquet")
        if (len(nav) != len(dates)
                or not pd.DatetimeIndex(nav.date).equals(pd.DatetimeIndex(dates))
                or nav.reconciliation_error.abs().max() > 1e-6
                or not fills.side.isin(["BUY", "SELL"]).all()
                or not np.isfinite(fills[["consideration", "fees", "impact_rupees"]]).all().all()):
            raise ValueError(f"Incomplete account ledger: {name}")
        initial = float(summary.loc[name, "start_nav"])
        values = nav.nav.astype(float).reset_index(drop=True)
        if not np.allclose(values / values.shift(1, fill_value=initial) - 1,
                           nav.daily_return, rtol=0, atol=1e-12):
            raise ValueError(f"Daily NAV return reconciliation failed: {name}")
        paid = (-cash.loc[cash.category.eq("ANNUAL_TAX_PAYMENT")]
                .groupby("date").amount.sum().reindex(nav.date, fill_value=0.0))
        paid = paid.reset_index(drop=True)
        paid_before_close = paid.cumsum().shift(1, fill_value=0.0)
        cost = fills.fees + fills.impact_rupees
        costs_by_day = (fills.assign(implementation_cost=cost)
                        .groupby("date").implementation_cost.sum()
                        .reindex(nav.date, fill_value=0.0).reset_index(drop=True))
        before_tax = values + nav.tax_liability.reset_index(drop=True) + paid_before_close
        cost_tax_reversed = before_tax + costs_by_day.cumsum()
        before_tax_cagr = float((before_tax.iloc[-1] / initial) ** (1 / years) - 1)
        matched_gross_cagr = float((cost_tax_reversed.iloc[-1] / initial) ** (1 / years) - 1)
        prior_nav = values.shift(1, fill_value=initial)
        date_to_prior_nav = dict(zip(nav.date, prior_nav))
        annual_turnover = float(
            (fills.consideration / fills.date.map(date_to_prior_nav)).sum() * 252 / len(nav)
        )
        after_tax_cagr = float(summary.loc[name, "cagr"])
        if (abs(values.iloc[-1] - summary.loc[name, "end_nav"]) > 1e-6
                or not np.isfinite([before_tax_cagr, matched_gross_cagr, annual_turnover]).all()):
            raise ValueError(f"Final metric reconciliation failed: {name}")
        rows.append({
            "account": name, "sessions": len(nav),
            "start_nav": initial, "final_nav": float(values.iloc[-1]),
            "cagr": after_tax_cagr,
            "annualised_volatility": float(summary.loc[name, "annualised_volatility"]),
            "sharpe_0pct_cash": float(summary.loc[name, "sharpe_0pct_cash"]),
            "max_drawdown": float(summary.loc[name, "max_drawdown"]),
            "nifty500_tri_cagr": benchmark_cagr,
            "cagr_minus_tri_percentage_points": (after_tax_cagr - benchmark_cagr) * 100,
            "annualised_gross_turnover": annual_turnover,
            "annualised_round_trip_equivalent_turnover": annual_turnover / 2,
            "total_fees_and_impact": float(cost.sum()),
            "annualised_implementation_cost_drag": matched_gross_cagr - before_tax_cagr,
            "capital_gains_tax_paid": float(paid.sum()),
            "ending_accrued_tax_liability": float(nav.tax_liability.iloc[-1]),
            "annualised_tax_drag": before_tax_cagr - after_tax_cagr,
            "matched_executable_before_tax_cagr": before_tax_cagr,
            "matched_executable_cost_tax_reversed_cagr": matched_gross_cagr,
            "maximum_nav_reconciliation_error": float(nav.reconciliation_error.abs().max()),
        })
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT / "holdout_summary.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
