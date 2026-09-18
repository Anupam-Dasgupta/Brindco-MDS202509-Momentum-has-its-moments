"""Read-only development evaluation of the four frozen executable accounts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from brindco_momentum.data.settlement_calendar import CUTOFF, ROOT, START
from brindco_momentum.evaluation.figures import make_figures


OUT = ROOT / "results/evaluation_development"
MOM_VM = ROOT / "results/accounts_development/frozen_corporate_action_scenario"
CONTROLS = ROOT / "results/controls_development"
TRI = ROOT / "data/processed/nifty500_tri_2013_2026.parquet"
SHADOW = ROOT / "data/processed/primary_modelling_shadow_daily_returns.parquet"
OVERLAY = ROOT / "data/processed/volatility_overlay_development.parquet"
ACCOUNTS = ("MOM", "VM", "FIX", "FIXVOL")


def read_account(name: str, dates: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    folder = MOM_VM if name in {"MOM", "VM"} else CONTROLS / name
    paths = {kind: folder / f"{name}_{kind}.parquet"
             for kind in ("nav_daily", "positions", "fills", "cash_events")}
    nav = pd.read_parquet(paths["nav_daily"],
                          columns=["date", "nav", "daily_return", "nav_status", "stocks",
                                   "tax_liability", "reconciliation_error"],
                          filters=[("date", ">=", START), ("date", "<=", CUTOFF)])
    nav["date"] = pd.to_datetime(nav.date)
    nav = nav.sort_values("date").reset_index(drop=True)
    if (not pd.DatetimeIndex(nav.date).equals(dates) or nav.date.duplicated().any()
            or not np.isfinite(nav[["nav", "daily_return", "stocks", "tax_liability"]]).all().all()
            or nav.nav.le(0).any() or nav.reconciliation_error.abs().max() > 1e-6):
        raise ValueError(f"Incomplete or unreconciled development NAV: {name}")

    fills = pd.read_parquet(paths["fills"],
                            columns=["date", "side", "quantity", "raw_open", "consideration",
                                     "stt", "stamp", "exchange", "sebi_gst", "fees", "impact_rupees"],
                            filters=[("date", ">=", START), ("date", "<=", CUTOFF)])
    fills["date"] = pd.to_datetime(fills.date)
    if (fills.empty or not fills.date.isin(dates).all() or
            not np.isfinite(fills[["quantity", "raw_open", "consideration", "stt", "stamp",
                                    "exchange", "sebi_gst", "fees", "impact_rupees"]]).all().all() or
            fills[["quantity", "raw_open", "consideration"]].le(0).any().any() or
            fills[["stt", "stamp", "exchange", "sebi_gst", "fees",
                   "impact_rupees"]].lt(0).any().any() or
            not fills.side.isin(["BUY", "SELL"]).all()):
        raise ValueError(f"Invalid development fills: {name}")
    if not np.allclose(fills.fees, fills.stt + fills.stamp + fills.exchange + fills.sebi_gst,
                       rtol=0, atol=1e-8):
        raise ValueError(f"Fill fee components do not reconcile: {name}")
    loaded_fill_digest = hashlib.sha256(
        pd.util.hash_pandas_object(fills, index=False).values.tobytes()).hexdigest()
    fills["implementation_cost"] = fills.fees + fills.impact_rupees

    positions = pd.read_parquet(paths["positions"], columns=["date", "market_value"],
                                filters=[("date", ">=", START), ("date", "<=", CUTOFF)])
    positions["date"] = pd.to_datetime(positions.date)
    stocks = positions.groupby("date").market_value.sum().reindex(dates, fill_value=0.0)
    if not np.allclose(stocks.to_numpy(), nav.stocks.to_numpy(), rtol=0, atol=1e-5):
        raise ValueError(f"Positions do not reconcile to NAV stock value: {name}")

    cash = pd.read_parquet(paths["cash_events"], columns=["date", "category", "amount"],
                           filters=[("date", ">=", START), ("date", "<=", CUTOFF)])
    cash["date"] = pd.to_datetime(cash.date)
    funding = cash.loc[cash.category.eq("INITIAL_FUNDING"), "amount"]
    if len(funding) != 1 or funding.iloc[0] <= 0:
        raise ValueError(f"Missing initial funding: {name}")
    initial = float(funding.iloc[0])
    tax_paid_by_day = (-cash.loc[cash.category.eq("ANNUAL_TAX_PAYMENT")]
                       .groupby("date").amount.sum().reindex(dates, fill_value=0.0))
    if tax_paid_by_day.lt(0).any():
        raise ValueError(f"Invalid tax payment: {name}")

    # FY-end payments are booked after that date's closing NAV. They first
    # affect the next session's opening state, so exclude today's payment here.
    paid_before_close = tax_paid_by_day.cumsum().shift(1, fill_value=0.0)
    costs_by_day = fills.groupby("date").implementation_cost.sum().reindex(dates, fill_value=0.0)
    prior_nav = nav.nav.shift(1, fill_value=initial)
    fills["prior_close_nav"] = fills.date.map(dict(zip(dates, prior_nav)))
    fills["turnover_contribution"] = fills.consideration / fills.prior_close_nav

    daily = pd.DataFrame({
        "date": dates, "strategy": name, "after_tax_nav": nav.nav.to_numpy(),
        "after_tax_daily_return": nav.daily_return.to_numpy(),
        "tax_liability": nav.tax_liability.to_numpy(),
        "tax_paid_before_close": paid_before_close.to_numpy(),
        "daily_fees_and_impact": costs_by_day.to_numpy(),
        "realised_equity_exposure": stocks.to_numpy() / nav.nav.to_numpy(),
        "nav_status": nav.nav_status.to_numpy(),
    })
    daily["matched_before_tax_nav"] = (daily.after_tax_nav + daily.tax_liability
                                        + daily.tax_paid_before_close)
    daily["matched_cost_tax_reversed_nav"] = (daily.matched_before_tax_nav
                                               + daily.daily_fees_and_impact.cumsum())
    for column in ("after_tax_nav", "matched_before_tax_nav", "matched_cost_tax_reversed_nav"):
        daily[column.replace("_nav", "_return")] = (
            daily[column] / daily[column].shift(1, fill_value=initial) - 1
        )
    if not np.allclose(daily.after_tax_return, daily.after_tax_daily_return, rtol=0, atol=1e-12):
        raise ValueError(f"Frozen daily return differs from NAV change: {name}")
    if (daily.matched_before_tax_nav.lt(daily.after_tax_nav - 1e-6).any() or
            daily.matched_cost_tax_reversed_nav.lt(daily.matched_before_tax_nav - 1e-6).any()):
        raise ValueError(f"Invalid matched cash-flow reversal: {name}")
    source_frames = {"nav_daily": nav, "fills": fills, "positions": positions, "cash_events": cash}
    source_manifest = []
    for kind, frame in source_frames.items():
        digest = (loaded_fill_digest if kind == "fills" else hashlib.sha256(
            pd.util.hash_pandas_object(frame, index=False).values.tobytes()).hexdigest())
        source_manifest.append({"source": f"{name}_{kind}",
                                "path": paths[kind].relative_to(ROOT).as_posix(),
                                "development_rows": len(frame), "development_rows_sha256": digest,
                                "maximum_value_date": str(frame.date.max().date())})
    return daily, fills, {"initial": initial, "tax_paid": float(tax_paid_by_day.sum()),
                          "source_manifest": source_manifest}


def drawdown_episodes(wealth: pd.Series, dates: pd.Series, initial: float) -> list[dict]:
    """A peak starts an episode; recovery requires regaining that same wealth."""
    peak_value = initial
    peak_date = START.date()
    current = None
    episodes = []
    for day, value in zip(pd.to_datetime(dates).dt.date, wealth):
        if value >= peak_value:
            if current is not None:
                episodes.append({**current, "recovery_date": day.isoformat()})
                current = None
            peak_value, peak_date = value, day
        else:
            depth = value / peak_value - 1
            if current is None:
                current = {"peak_date": peak_date.isoformat(), "trough_date": day.isoformat(),
                           "max_drawdown": depth}
            elif depth < current["max_drawdown"]:
                current["trough_date"] = day.isoformat()
                current["max_drawdown"] = depth
    if current is not None:
        episodes.append({**current, "recovery_date": None})
    return episodes


def performance(wealth: pd.Series, dates: pd.Series, initial: float) -> dict:
    values = pd.Series(wealth, dtype=float).reset_index(drop=True)
    returns = values / values.shift(1, fill_value=initial) - 1
    years = (CUTOFF.date() - START.date()).days / 365.2425
    sd = float(returns.std(ddof=1))
    episodes = drawdown_episodes(values, dates, initial)
    worst = min(episodes, key=lambda row: row["max_drawdown"]) if episodes else None
    return {
        "start_nav": initial, "end_nav": float(values.iloc[-1]),
        "total_return": float(values.iloc[-1] / initial - 1),
        "cagr": float((values.iloc[-1] / initial) ** (1 / years) - 1),
        "annualised_volatility": sd * np.sqrt(252) if np.isfinite(sd) else np.nan,
        "sharpe_0pct_cash": float(returns.mean() / sd * np.sqrt(252)) if sd > 0 else np.nan,
        "max_drawdown": worst["max_drawdown"] if worst else 0.0,
        "drawdown_start_date": worst["peak_date"] if worst else None,
        "drawdown_trough_date": worst["trough_date"] if worst else None,
        "drawdown_recovery_date": worst["recovery_date"] if worst else None,
    }


def evaluate(output_dir: Path = OUT) -> None:
    calendar = pd.read_parquet(ROOT / "data/processed/nse_trading_calendar_2013_2026.parquet",
                               columns=["date"], filters=[("date", ">=", START),
                                                          ("date", "<=", CUTOFF)])
    dates = pd.DatetimeIndex(pd.to_datetime(calendar.date).sort_values())
    if dates.has_duplicates or dates[0] != START or dates[-1] != CUTOFF or len(dates) != 1982:
        raise ValueError("Unexpected development trading calendar")

    shadow = pd.read_parquet(SHADOW, columns=["date", "shadow_daily_return", "valid_return"],
                             filters=[("date", ">=", START), ("date", "<=", CUTOFF)])
    shadow["date"] = pd.to_datetime(shadow.date)
    shadow = shadow.sort_values("date")
    if not pd.DatetimeIndex(shadow.date).equals(dates) or not shadow.valid_return.eq(True).all():
        raise ValueError("Incomplete development MOM shadow reference")
    vm_ref = pd.read_parquet(CONTROLS / "vm_gross_reference_daily_returns.parquet",
                             columns=["date", "mom_shadow_daily_return", "vm_target_exposure",
                                      "vm_gross_reference_daily_return"],
                             filters=[("date", ">=", START), ("date", "<=", CUTOFF)])
    vm_ref["date"] = pd.to_datetime(vm_ref.date)
    vm_ref = vm_ref.sort_values("date")
    if (not pd.DatetimeIndex(vm_ref.date).equals(dates) or
            not np.allclose(vm_ref.mom_shadow_daily_return, shadow.shadow_daily_return) or
            not np.allclose(vm_ref.vm_gross_reference_daily_return,
                            vm_ref.vm_target_exposure * vm_ref.mom_shadow_daily_return)):
        raise ValueError("VM gross reference differs from frozen control convention")
    overlay = pd.read_parquet(OVERLAY, columns=["formation_date", "holding_month", "is_scored",
                                                 "risk_estimate_available", "risk_status", "exposure"],
                              filters=[("formation_date", "<=", CUTOFF), ("is_scored", "=", True)])
    overlay["holding_month"] = overlay.holding_month.astype(str)
    overlay = overlay.loc[overlay.holding_month.between("2015-04", "2023-03")].sort_values("holding_month")
    if (len(overlay) != 96 or overlay.holding_month.duplicated().any() or
            not overlay.risk_estimate_available.eq(True).all() or
            not overlay.risk_status.eq("VALID").all()):
        raise ValueError("Invalid frozen scored VM target series")
    month_exposure = dict(zip(overlay.holding_month, overlay.exposure))
    expected_exposure = pd.Series(dates.strftime("%Y-%m")).map(month_exposure).to_numpy()
    if not np.allclose(expected_exposure, vm_ref.vm_target_exposure):
        raise ValueError("VM target exposure reference does not match frozen overlay")

    tri = pd.read_parquet(TRI, columns=["date", "tri"],
                          filters=[("date", ">=", pd.Timestamp("2015-03-31")),
                                   ("date", "<=", CUTOFF)])
    tri["date"] = pd.to_datetime(tri.date)
    tri = tri.sort_values("date")
    if (len(tri) != len(dates) + 1 or tri.date.iloc[0] != pd.Timestamp("2015-03-31")
            or not pd.DatetimeIndex(tri.date.iloc[1:]).equals(dates)
            or not np.isfinite(tri.tri).all() or tri.tri.le(0).any()):
        raise ValueError("Incomplete development NIFTY 500 TRI")

    fixed = json.loads((CONTROLS / "FIX/control_definition.json").read_text())["allocation"]
    fixed_vol = json.loads((CONTROLS / "FIXVOL/control_definition.json").read_text())["allocation"]
    reference_returns = {
        "MOM": shadow.shadow_daily_return.to_numpy(),
        "VM": vm_ref.vm_gross_reference_daily_return.to_numpy(),
        "FIX": fixed * shadow.shadow_daily_return.to_numpy(),
        "FIXVOL": fixed_vol * shadow.shadow_daily_return.to_numpy(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    all_daily, summary, accounting, costs, episodes, account_manifest = [], [], [], [], [], []
    for name in ACCOUNTS:
        daily, fills, evidence = read_account(name, dates)
        account_manifest.extend(evidence["source_manifest"])
        initial = evidence["initial"]
        daily["zero_friction_reference_nav"] = initial * np.cumprod(1 + reference_returns[name])
        daily["zero_friction_reference_return"] = reference_returns[name]
        all_daily.append(daily)
        after = performance(daily.after_tax_nav, daily.date, initial)
        pre_tax = performance(daily.matched_before_tax_nav, daily.date, initial)
        matched_gross = performance(daily.matched_cost_tax_reversed_nav, daily.date, initial)
        reference = performance(daily.zero_friction_reference_nav, daily.date, initial)
        for view, metrics in (("zero_friction_reference", reference),
                              ("matched_executable_before_tax", pre_tax),
                              ("executable_after_tax", after)):
            accounting.append({"strategy": name, "accounting_view": view, **metrics})

        # The most recent closing NAV is the only recorded pre-trade NAV. It
        # is explicitly not an open-marked, contemporaneous intraday NAV.
        first_five = set(dates[:5])
        initial_fills = fills.date.isin(first_five)
        recurring = fills.loc[~initial_fills]
        annual_turnover = float(recurring.turnover_contribution.sum() * 252 / len(dates))
        total_cost = float(fills.implementation_cost.sum())
        cost_drag = matched_gross["cagr"] - pre_tax["cagr"]
        tax_drag = pre_tax["cagr"] - after["cagr"]
        exposure = daily.realised_equity_exposure
        summary.append({"strategy": name, "accounting_view": "executable_after_tax", **after,
                        "annualised_recurring_gross_turnover": annual_turnover,
                        "annualised_recurring_round_trip_turnover": annual_turnover / 2,
                        "total_transaction_costs": total_cost,
                        "annualised_implementation_cost_drag": cost_drag,
                        "total_capital_gains_tax_paid": evidence["tax_paid"],
                        "annualised_tax_drag": tax_drag,
                        "scheduled_monthly_rebalances": len(overlay), "number_of_fills": len(fills),
                        "average_realised_equity_exposure": float(exposure.mean()),
                        "minimum_realised_equity_exposure": float(exposure.min()),
                        "maximum_realised_equity_exposure": float(exposure.max()),
                        "unpriced_rights_or_claim_nav_days": int(daily.nav_status.str.contains("UNPRICED").sum())})
        buys = fills.side.eq("BUY")
        sells = ~buys
        buy_bps = float(fills.loc[buys, "implementation_cost"].sum()
                        / fills.loc[buys, "consideration"].sum() * 10_000)
        sell_bps = float(fills.loc[sells, "implementation_cost"].sum()
                         / fills.loc[sells, "consideration"].sum() * 10_000)
        rt_bps = float(2 * total_cost / fills.consideration.sum() * 10_000)
        costs.append({
            "strategy": name, "rebalance_cadence": "monthly; first five NSE sessions",
            "turnover_denominator": "previous recorded close NAV; initial funding for first session",
            "annualised_recurring_gross_turnover": annual_turnover,
            "annualised_recurring_round_trip_turnover": annual_turnover / 2,
            "initial_funding_traded_notional": float(fills.loc[initial_fills, "consideration"].sum()),
            "initial_funding_costs": float(fills.loc[initial_fills, "implementation_cost"].sum()),
            "total_traded_notional": float(fills.consideration.sum()),
            "total_stt": float(fills.stt.sum()), "total_stamp": float(fills.stamp.sum()),
            "total_exchange": float(fills.exchange.sum()),
            "total_sebi_gst": float(fills.sebi_gst.sum()),
            "total_fees": float(fills.fees.sum()), "total_impact": float(fills.impact_rupees.sum()),
            "total_implementation_costs": total_cost,
            "effective_buy_cost_bps": buy_bps, "effective_sell_cost_bps": sell_bps,
            "effective_round_trip_cost_bps": rt_bps,
            "annualised_implementation_cost_drag": cost_drag,
            "total_capital_gains_tax_paid": evidence["tax_paid"],
            "ending_accrued_tax_liability": float(daily.tax_liability.iloc[-1]),
            "annualised_tax_drag": tax_drag,
            "gross_edge_comparator": "zero-return cash",
            "gross_annual_edge_required_to_clear_costs_and_tax": cost_drag + tax_drag,
            "observed_matched_gross_annual_return": matched_gross["cagr"],
            "clears_cash_relative_implementation_hurdle":
                bool(matched_gross["cagr"] > cost_drag + tax_drag),
        })
        for episode in sorted(drawdown_episodes(daily.after_tax_nav, daily.date, initial),
                              key=lambda row: row["max_drawdown"])[:5]:
            peak = pd.Timestamp(episode["peak_date"])
            trough = pd.Timestamp(episode["trough_date"])
            during = overlay.loc[overlay.holding_month.between(peak.strftime("%Y-%m"),
                                                                 trough.strftime("%Y-%m")), "exposure"]
            start_exp = month_exposure[peak.strftime("%Y-%m")]
            trough_exp = month_exposure[trough.strftime("%Y-%m")]
            episodes.append({"strategy": name, "accounting_view": "executable_after_tax", **episode,
                             "vm_target_at_peak": start_exp, "vm_target_at_trough": trough_exp,
                             "vm_minimum_target_peak_to_trough": float(during.min()),
                             "vm_below_full_at_peak": bool(start_exp < 1),
                             "vm_target_reduced_by_trough": bool((during < start_exp).any())})

    summary_table = pd.DataFrame(summary)
    comparisons = []
    for other in ("MOM", "FIX", "FIXVOL"):
        vm = summary_table.set_index("strategy").loc["VM"]
        base = summary_table.set_index("strategy").loc[other]
        comparison = {"comparison": f"VM minus {other}", "accounting_view": "executable_after_tax"}
        for column in ("cagr", "annualised_volatility", "sharpe_0pct_cash", "max_drawdown",
                       "annualised_recurring_gross_turnover", "annualised_implementation_cost_drag",
                       "annualised_tax_drag", "average_realised_equity_exposure"):
            comparison[f"difference_{column}"] = float(vm[column] - base[column])
        comparisons.append(comparison)

    shadow_months = pd.DataFrame({"holding_month": dates.strftime("%Y-%m"),
                                  "shadow_return": shadow.shadow_daily_return.to_numpy()})
    monthly = shadow_months.groupby("holding_month").shadow_return.agg(
        subsequent_shadow_return=lambda x: (1 + x).prod() - 1,
        subsequent_shadow_volatility=lambda x: x.std(ddof=1) * np.sqrt(252),
    ).reset_index()
    diagnostics = overlay[["holding_month", "exposure"]].merge(monthly, on="holding_month",
                                                                 validate="one_to_one")
    stats = {"average_vm_target_exposure": float(diagnostics.exposure.mean()),
             "fraction_months_at_full_exposure": float(diagnostics.exposure.eq(1).mean()),
             "correlation_with_subsequent_shadow_return":
                 float(diagnostics.exposure.corr(diagnostics.subsequent_shadow_return)),
             "correlation_with_subsequent_shadow_volatility":
                 float(diagnostics.exposure.corr(diagnostics.subsequent_shadow_volatility))}
    stats.update({f"vm_target_exposure_q{int(q * 100):02d}": float(diagnostics.exposure.quantile(q))
                  for q in (0, .10, .25, .50, .75, .90, 1)})
    tri_wealth = summary_table.start_nav.iloc[0] * tri.tri.iloc[1:].to_numpy() / tri.tri.iloc[0]
    tri_daily = pd.DataFrame({"date": dates, "tri": tri.tri.iloc[1:].to_numpy(),
                              "tri_wealth_from_development_anchor": tri_wealth})
    tri_stats = performance(pd.Series(tri_wealth), pd.Series(dates),
                            float(summary_table.start_nav.iloc[0]))

    daily_table = pd.concat(all_daily, ignore_index=True)
    daily_table.to_csv(output_dir / "daily_accounting_views.csv", index=False)
    daily_table.groupby(["strategy", "nav_status"]).size().rename("days").reset_index().to_csv(
        output_dir / "nav_status_counts.csv", index=False)
    summary_table.to_csv(output_dir / "summary_metrics.csv", index=False)
    pd.DataFrame(accounting).to_csv(output_dir / "accounting_views.csv", index=False)
    pd.DataFrame(comparisons).to_csv(output_dir / "strategy_comparisons.csv", index=False)
    pd.DataFrame(costs).to_csv(output_dir / "cost_arithmetic.csv", index=False)
    pd.DataFrame([stats]).to_csv(output_dir / "vm_exposure_diagnostics.csv", index=False)
    diagnostics.nsmallest(5, "exposure").to_csv(output_dir / "vm_lowest_exposure_months.csv", index=False)
    pd.DataFrame(episodes).to_csv(output_dir / "drawdown_episodes.csv", index=False)
    tri_daily.to_csv(output_dir / "tri_context_daily.csv", index=False)
    pd.DataFrame([{"accounting_view": "published_index_context", **tri_stats}]).to_csv(
        output_dir / "tri_context_metrics.csv", index=False)

    sources = {"calendar": (ROOT / "data/processed/nse_trading_calendar_2013_2026.parquet", calendar),
               "tri": (TRI, tri), "mom_shadow": (SHADOW, shadow),
               "vm_overlay": (OVERLAY, overlay),
               "vm_gross_reference": (CONTROLS / "vm_gross_reference_daily_returns.parquet", vm_ref)}
    manifest = list(account_manifest)
    for name, (path, frame) in sources.items():
        digest = hashlib.sha256(pd.util.hash_pandas_object(frame, index=False).values.tobytes()).hexdigest()
        date_col = "date" if "date" in frame else "formation_date"
        manifest.append({"source": name, "path": path.relative_to(ROOT).as_posix(),
                         "development_rows": len(frame),
                         "development_rows_sha256": digest, "maximum_value_date":
                         str(pd.to_datetime(frame[date_col]).max().date())})
    for name in ("FIX", "FIXVOL"):
        path = CONTROLS / name / "control_definition.json"
        manifest.append({"source": f"{name}_definition", "path": path.relative_to(ROOT).as_posix(),
                         "development_rows": 1,
                         "development_rows_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "maximum_value_date": str(CUTOFF.date())})
    pd.DataFrame(manifest).to_csv(output_dir / "input_manifest.csv", index=False)

    notes = """# Development evaluation notes

All return and performance results use 2015-04-01 through 2023-03-31 only.
Account NAV is the frozen after-cost, after-tax executable path. TRI is a
published index used for context, with no fictional tax or transaction costs.
Its 2015-03-31 close is the anchor for its first development-session return.

Zero-friction reference wealth compounds the frozen MOM modelling-shadow daily
returns at 100%, or the frozen VM monthly target, FIX constant, or FIXVOL
constant times those daily returns. Cash earns zero. This reference does not
model execution or tax. The frozen FIXVOL first-session holding-month exposure
convention is retained.

The matched executable before-tax view adds back accrued capital-gains tax and
tax already paid to the *same executed share path*. FY-end tax payment occurs
after that day's closing NAV, so paid tax is added beginning the next session.
The matched cost/tax-reversed view additionally adds back cumulative recorded
fees and impact as non-invested cash. These are exact cash-flow reversals for
the realised shares and fills, not counterfactual reruns with different trades.
Cost drag is its CAGR minus the matched before-tax CAGR; tax drag is matched
before-tax CAGR minus frozen after-tax CAGR. Both include the initial trades.
Gross edge and hurdle in cost_arithmetic.csv are explicitly relative to 0%
cash using the matched cost/tax-reversed path; this is not an alpha estimate.
The separately saved zero-friction reference also reflects selection and
execution-path differences, so its gap to NAV is not labelled fee drag.
FIX and FIXVOL use constants calibrated on this full development period;
their development comparisons are in-sample controls, not 2015 forecasts.

Executed traded notionals, fees, and participation-dependent impact come from
the fill ledger. Annual recurring gross turnover sums consideration divided by
the latest recorded *previous-close* NAV on each trade day, then multiplies by
252 / 1,982. The first five NSE sessions' funding trades are excluded from
that recurring rate and reported separately. The frozen ledger has no
open-marked contemporaneous pre-trade NAV, so this is a labelled operational
turnover measure, not the exact intraday denominator specified in plan.md.
RT-equivalent turnover is half gross turnover. The weighted effective RT cost
is twice total actual fees-plus-impact divided by total executed consideration;
buy and sell rates are shown separately.

CAGR uses 365.2425-day elapsed calendar years from inception. Annualised
volatility is the sample standard deviation of 1,982 daily returns times
sqrt(252). Sharpe uses daily arithmetic mean / daily sample standard
deviation times sqrt(252) against the declared 0% cash return; zero variance
is undefined. Drawdown starts from initial funded wealth, and recovery is the
first later close at or above the previous peak. Unrecovered episodes have an
empty recovery date. Daily NAV may exclude live unpriced rights or fractional
claims under the frozen account convention; nav_status_counts.csv preserves
the exact counts by strategy. These valuations remain unresolved in the
frozen account scenario and limit interpretation of the results. No parameter
or frozen account artifact is changed here.
"""
    (output_dir / "EVALUATION_NOTES.md").write_text(notes, encoding="utf-8")
    make_figures(output_dir / "figures", daily_table, summary_table, tri_daily, overlay,
                 pd.DataFrame(costs))
    print(f"Development evaluation: {len(summary_table)} accounts, {len(dates)} sessions through "
          f"{CUTOFF.date()}; outputs in {output_dir}")


if __name__ == "__main__":
    evaluate()
