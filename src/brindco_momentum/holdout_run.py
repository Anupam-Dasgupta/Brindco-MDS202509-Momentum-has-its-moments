"""Run the frozen strategy through holdout, publishing only a complete bundle."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from brindco_momentum.data.stock_total_returns import build_returns, prepare_prices
from brindco_momentum.execution.holdout_accounts import OPENING_STATES, run_sealed_bundle
from brindco_momentum.paths import ROOT
from brindco_momentum.portfolio.shadow_portfolio import simulate_shadow
from brindco_momentum.portfolio.volatility_overlay import build_return_overrides, formation_risk
from brindco_momentum.signals.momentum_signal import build_monthly, build_roster, build_formations


START = pd.Timestamp("2023-04-03")
END = pd.Timestamp("2026-03-30")
LAST_FORMATION = pd.Period("2026-02", freq="M")
PROCESSED = ROOT / "data/processed"
OUTPUT = ROOT / "results/accounts_holdout/frozen_bundle"
RUNTIME_INPUTS = PROCESSED / "runtime_inputs"
SUPPLEMENTAL_MARKET = RUNTIME_INPUTS / "supplemental_market_observations.parquet"

PANEL_COLUMNS = [
    "date", "security_id", "symbol", "isin", "series", "open", "close", "volume",
    "market_observed", "market_data_status", "identity_status", "adv20_lagged",
    "adv20_complete", "adv20_observation_count", "positive_volume_sessions_20",
    "in_nifty500", "momentum_signal_safe", "momentum_signal_exclusion_reason",
    "corporate_action_timing_event_ids", "is_formation_date",
]
RETURN_COLUMNS = [
    "date", "security_id", "previous_close", "price_return", "daily_total_return",
    "total_return_available", "exclusion_reason", "all_event_ids", "quality_status",
    "cash_effect", "share_effect", "entitlement_effect",
]


def calculate_lagged_adv(panel: pd.DataFrame) -> pd.DataFrame:
    """Use the preceding 20 observed sessions and exclude today's trade."""
    panel["adv20_lagged"] = np.nan
    panel["adv20_observation_count"] = np.int16(0)
    panel["positive_volume_sessions_20"] = np.int16(0)
    for positions in panel.groupby("security_id", sort=False).indices.values():
        positions = np.asarray(positions)
        sessions = panel.loc[positions, "trading_day_number"].to_numpy(dtype=np.int64)
        traded = panel.loc[positions, "traded_value"].to_numpy(dtype=float)
        observed = (panel.loc[positions, "market_observed"].to_numpy(dtype=bool)
                    & np.isfinite(traded) & (traded >= 0))
        observed_sessions = sessions[observed]
        traded_values = traded[observed]
        positive_volume = (
            panel.loc[positions[observed], "volume"].to_numpy(dtype=float) > 0
        ).astype(np.int16)
        left = np.searchsorted(observed_sessions, sessions - 20, side="left")
        right = np.searchsorted(observed_sessions, sessions, side="left")
        counts = right - left
        value_prefix = np.concatenate([[0.0], np.cumsum(traded_values)])
        positive_prefix = np.concatenate([[0], np.cumsum(positive_volume)])
        complete = counts == 20
        panel.loc[positions, "adv20_lagged"] = np.where(
            complete, (value_prefix[right] - value_prefix[left]) / 20.0, np.nan
        )
        panel.loc[positions, "adv20_observation_count"] = counts.astype(np.int16)
        panel.loc[positions, "positive_volume_sessions_20"] = (
            positive_prefix[right] - positive_prefix[left]
        ).astype(np.int16)
    panel["adv20_complete"] = panel["adv20_observation_count"].eq(20)
    return panel


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _return_events(identity: pd.DataFrame) -> pd.DataFrame:
    accepted = pd.read_parquet(
        PROCESSED / "corporate_action_treatment_holdout/accepted_event_treatments.parquet"
    )
    accepted_events = pd.DataFrame({
        "event_id": accepted["event_id"],
        "security_id": accepted["security_id"],
        "ex_date": pd.to_datetime(accepted["effective_date"]),
        "primary_class": accepted["parent_event_class"],
        "signal_relevant": True,
        "application_status": np.where(
            accepted["blocks_total_return"].eq(True), "RETURN_UNAVAILABLE_EXPLICIT",
            np.where(accepted["treatment_status"].eq("RESOLVED_NO_DIRECT_HOLDER_ADJUSTMENT"),
                     "NO_DIRECT_ADJUSTMENT_REQUIRED", "APPLIED_TO_RETURN"),
        ),
        "application_reason": np.where(
            accepted["blocks_total_return"].eq(True),
            "MANDATORY_UNLISTED_RECEIVED_SECURITY_UNPRICED",
            np.where(accepted["treatment_status"].eq("RESOLVED_NO_DIRECT_HOLDER_ADJUSTMENT"),
                     "ACCEPTED_NO_DIRECT_ADJUSTMENT", "ACCEPTED_DIRECT_TERMS"),
        ),
        "cash_effect": accepted["cash_per_pre_event_share"].astype(float),
        "share_effect": accepted["share_multiplier"].astype(float),
        "entitlement_effect": accepted["entitlement_value_per_pre_event_share"].astype(float),
    })
    applying = accepted_events["application_status"].eq("APPLIED_TO_RETURN")
    if accepted_events.loc[applying, ["cash_effect", "share_effect", "entitlement_effect"]].isna().any().any():
        raise ValueError("Accepted holdout action has incomplete return terms")

    hard = pd.read_csv(
        RUNTIME_INPUTS / "holdout_corporate_action_runtime_hard_stops.csv",
        parse_dates=["ex_date"],
    )
    off_session = pd.read_csv(
        RUNTIME_INPUTS / "off_session_accepted_action_runtime_guards.csv",
        parse_dates=["ex_date"],
    )
    hard = pd.concat([hard, off_session], ignore_index=True, sort=False)
    known = hard[hard["security_id"].notna()][["event_id", "security_id", "ex_date"]]
    unknown = hard[hard["security_id"].isna()]
    aliases = identity[["security_id", "symbol", "isin", "first_seen"]].copy()
    aliases["first_seen"] = pd.to_datetime(aliases["first_seen"])
    symbol_links = unknown[["event_id", "symbol", "ex_date"]].merge(
        aliases[["security_id", "symbol", "first_seen"]], on="symbol", how="inner"
    )
    symbol_links = symbol_links.loc[symbol_links["first_seen"].le(symbol_links["ex_date"])]
    isin_links = unknown[["event_id", "nse_isin", "ex_date"]].merge(
        aliases[["security_id", "isin", "first_seen"]], left_on="nse_isin", right_on="isin", how="inner"
    )
    isin_links = isin_links.loc[isin_links["first_seen"].le(isin_links["ex_date"])]
    blocked = pd.concat([
        known, symbol_links[["event_id", "security_id", "ex_date"]],
        isin_links[["event_id", "security_id", "ex_date"]],
    ]).drop_duplicates(["event_id", "security_id", "ex_date"])
    blocked_events = blocked.assign(
        primary_class="UNRESOLVED", signal_relevant=True,
        application_status="RETURN_UNAVAILABLE_EXPLICIT",
        application_reason="HARD_STOP_IF_HELD", cash_effect=0.0,
        share_effect=1.0, entitlement_effect=0.0,
    )
    events = pd.concat([accepted_events, blocked_events], ignore_index=True)
    if accepted_events["event_id"].duplicated().any() or len(hard) != 376:
        raise ValueError("Frozen holdout action coverage changed")
    return events


def _received_security_account_quotes(account_panel: pd.DataFrame) -> pd.DataFrame:
    """Add actual VLEGOV quotes for account valuation without changing the research universe."""
    evidence = pd.read_csv(RUNTIME_INPUTS / "vakrangee_demerger_verified_evidence.csv").iloc[0]
    first = pd.Timestamp(evidence["first_observable_price_date"])
    security_id = evidence["received_security_id"]
    market = pd.read_parquet(
        SUPPLEMENTAL_MARKET,
        filters=[("isin", "=", evidence["received_isin"]),
                 ("date", ">=", first), ("date", "<=", END)],
    )
    market["date"] = pd.to_datetime(market["date"])
    if (market.empty or market.duplicated("date").any()
            or not market["symbol"].eq(evidence["received_symbol"]).all()
            or not market["series"].isin(["EQ", "BE", "BZ"]).all()
            or market["open"].le(0).any() or market["close"].le(0).any()
            or market["volume"].lt(0).any()
            or market.loc[market["date"].eq(first), "close"].tolist() != [29.5]):
        raise ValueError("VLEGOV account quote evidence differs from official observed market")
    calendar = pd.read_parquet(
        PROCESSED / "nse_trading_calendar_2013_2026.parquet",
        columns=["date", "trading_day_number"],
        filters=[("date", ">=", first), ("date", "<=", END)],
    )
    quotes = calendar.merge(market, on="date", how="left", validate="one_to_one")
    quotes["security_id"] = security_id
    quotes["market_observed"] = quotes["close"].notna()
    quotes["market_data_status"] = np.where(quotes["market_observed"], "OK", "PRICE_MISSING")
    quotes = calculate_lagged_adv(quotes.reset_index(drop=True))
    if account_panel["security_id"].eq(security_id).any():
        raise ValueError("Received security already exists in the account panel")
    return pd.concat([account_panel, quotes.reindex(columns=account_panel.columns)], ignore_index=True)


def _tradable_rights_account_quotes(account_panel: pd.DataFrame) -> pd.DataFrame:
    """Include verified RE trades for account valuation and execution only."""
    for filename in ("upl_rights_verified_evidence.csv", "inoxwind_rights_verified_evidence.csv"):
        evidence = pd.read_csv(RUNTIME_INPUTS / filename).iloc[0]
        start = pd.Timestamp(evidence["record_date"])
        end = pd.Timestamp(evidence["issue_close_date"])
        calendar = pd.read_parquet(
            PROCESSED / "nse_trading_calendar_2013_2026.parquet",
            columns=["date", "trading_day_number"],
            filters=[("date", ">=", start), ("date", "<=", end)],
        )
        market = pd.read_parquet(
            SUPPLEMENTAL_MARKET,
            filters=[("isin", "=", evidence["re_isin"]),
                     ("date", ">=", start), ("date", "<=", end)],
        )
        market["date"] = pd.to_datetime(market["date"])
        expected = set(calendar.loc[
            calendar.date.between(evidence["re_trade_start"], evidence["re_trade_end"]), "date"
        ])
        if (market.duplicated("date").any() or set(market.date) != expected
                or not market.symbol.eq(evidence["re_symbol"]).all()
                or not market.series.eq("BE").all()
                or market.open.le(0).any() or market.close.le(0).any()
                or market.volume.le(0).any()):
            raise ValueError(f"{evidence['re_symbol']} observed trades differ from official window")
        quotes = calendar.merge(market, on="date", how="left", validate="one_to_one")
        quotes["security_id"] = evidence["re_security_id"]
        quotes["market_observed"] = quotes["close"].notna()
        quotes["market_data_status"] = np.where(quotes["market_observed"], "OK", "PRICE_MISSING")
        quotes = calculate_lagged_adv(quotes.reset_index(drop=True))
        if account_panel["security_id"].eq(evidence["re_security_id"]).any():
            raise ValueError("Verified RE already exists in account panel")
        account_panel = pd.concat(
            [account_panel, quotes.reindex(columns=account_panel.columns)], ignore_index=True
        )
    return account_panel


def _new_member_prehistory(dev_ids: set[str], identity: pd.DataFrame,
                           membership: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load accepted pre-membership history absent from the development panel."""
    new_ids = set(membership["security_id"]) - dev_ids
    selected = pd.read_parquet(RUNTIME_INPUTS / "new_member_prehistory.parquet")
    blocked_events = pd.read_parquet(
        RUNTIME_INPUTS / "new_member_prehistory_blocked_events.parquet"
    )
    if (not set(selected["security_id"]).issubset(new_ids)
            or selected.duplicated(["date", "security_id"]).any()
            or not set(blocked_events["security_id"]).issubset(new_ids)):
        raise ValueError("Accepted new-member prehistory is inconsistent")
    return selected, blocked_events


def produce_inputs() -> dict:
    calendar = pd.read_parquet(
        PROCESSED / "nse_trading_calendar_2013_2026.parquet",
        columns=["date", "previous_trading_day", "next_trading_day",
                 "is_last_trading_day_of_month"],
        filters=[("date", "<=", END)],
    ).sort_values("date")
    calendar["date"] = pd.to_datetime(calendar["date"])
    dev_panel = pd.read_parquet(PROCESSED / "research_panel_v2.parquet", columns=PANEL_COLUMNS)
    holdout = pd.read_parquet(PROCESSED / "holdout_execution_panel.parquet",
                              columns=[column for column in PANEL_COLUMNS if column not in {
                                  "momentum_signal_safe", "momentum_signal_exclusion_reason",
                                  "corporate_action_timing_event_ids", "is_formation_date",
                              }])
    if (dev_panel["date"].max() != pd.Timestamp("2023-03-31")
            or holdout["date"].min() != START or holdout["date"].max() != END):
        raise ValueError("Development or holdout panel date contract failed")
    holdout["identity_status"] = holdout["identity_status"].fillna("RESOLVED")
    month_ends = set(calendar.loc[calendar["is_last_trading_day_of_month"], "date"])
    holdout["is_formation_date"] = holdout["date"].isin(month_ends)
    holdout["momentum_signal_safe"] = pd.Series(pd.NA, index=holdout.index, dtype="boolean")
    holdout.loc[holdout["is_formation_date"], "momentum_signal_safe"] = True
    holdout["momentum_signal_exclusion_reason"] = ""
    holdout["corporate_action_timing_event_ids"] = ""

    identity = pd.read_parquet(PROCESSED / "security_identity_holdout/dated_security_identity.parquet")
    membership = pd.read_parquet(
        PROCESSED / "membership_holdout/nifty500_membership_intervals_through_2026_03_30.parquet",
        columns=["security_id", "published_symbol", "valid_from", "valid_to"],
    )
    prehistory, historical_blockers = _new_member_prehistory(
        set(dev_panel["security_id"]), identity, membership
    )
    events = pd.concat([_return_events(identity), historical_blockers], ignore_index=True)
    anchor = dev_panel.loc[dev_panel["date"].eq(pd.Timestamp("2023-03-31"))]
    price_input = pd.concat([anchor, prehistory, holdout], ignore_index=True, sort=False)
    prices = prepare_prices(price_input, calendar)
    returns = build_returns(prices, events)
    holdout_returns = returns.loc[returns["date"].ge(START), RETURN_COLUMNS].copy()
    prehistory_returns = returns.loc[returns["security_id"].isin(prehistory["security_id"])
                                     & returns["date"].lt(START), RETURN_COLUMNS].copy()
    if (len(holdout_returns) != len(holdout)
            or len(prehistory_returns) != len(prehistory)
            or holdout_returns.duplicated(["date", "security_id"]).any()):
        raise ValueError("Holdout return layer lost or duplicated panel rows")
    del prices, price_input, returns

    dev_returns = pd.read_parquet(PROCESSED / "stock_total_returns.parquet", columns=RETURN_COLUMNS)
    all_returns = pd.concat([dev_returns, prehistory_returns, holdout_returns], ignore_index=True)
    panel = pd.concat([dev_panel, prehistory, holdout], ignore_index=True, sort=False)
    panel = panel.merge(all_returns, on=["date", "security_id"], how="left", validate="one_to_one")
    if (panel.duplicated(["date", "security_id"]).any()
            or panel["quality_status"].isna().any()
            or len(panel) != len(dev_panel) + len(prehistory) + len(holdout)):
        raise ValueError("Combined return/panel linkage is incomplete")
    delayed = pd.read_csv(
        PROCESSED / "corporate_action_treatment/bonus_debenture_delayed_recognition.csv",
        parse_dates=["event_ex_date", "price_trade_date"],
    )
    timing = pd.read_csv(
        RUNTIME_INPUTS / "bonus_debenture_signal_timing_audit.csv",
        parse_dates=["formation_date"],
    )
    monthly = build_monthly(panel, calendar, delayed, timing)
    roster = build_roster(membership, calendar, last_formation=LAST_FORMATION)
    formations = build_formations(roster, panel, monthly, timing)
    winners = formations.loc[formations["winner"], [
        "formation_date", "holding_month", "scored", "security_id", "symbol",
        "momentum_score", "rank", "eligible_count", "target_winner_count",
    ]].sort_values(["formation_date", "rank"])
    frozen_winners = pd.read_parquet(PROCESSED / "momentum_winners.parquet")
    prefix_winners = winners.loc[winners["formation_date"].le("2023-02-28")]
    if not prefix_winners.reset_index(drop=True).equals(frozen_winners.reset_index(drop=True)):
        raise ValueError("Generalized winner producer changed frozen development selections")

    market = panel.loc[panel["security_id"].isin(winners["security_id"]), [
        "date", "security_id", "symbol", "series", "open", "close", "market_observed",
        "market_data_status", "identity_status", "previous_close", "price_return",
        "daily_total_return", "total_return_available", "exclusion_reason", "all_event_ids",
        "cash_effect", "share_effect", "entitlement_effect",
    ]].copy()
    overrides = build_return_overrides(market)
    _, shadow, _, materiality = simulate_shadow(calendar, winners, market, overrides)
    frozen_shadow = pd.read_parquet(PROCESSED / "primary_modelling_shadow_daily_returns.parquet")
    old_shadow = shadow.loc[shadow["date"].le("2023-03-31")]
    if (len(old_shadow) != len(frozen_shadow)
            or not old_shadow["date"].reset_index(drop=True).equals(frozen_shadow["date"])
            or not np.allclose(old_shadow["shadow_daily_return"],
                               frozen_shadow["shadow_daily_return"], equal_nan=True, atol=1e-12, rtol=0)):
        raise ValueError("Generalized shadow changed frozen development returns")
    if shadow.empty or shadow["date"].max() != END or not shadow["valid_return"].all():
        blocked = shadow.loc[~shadow["valid_return"]]
        if not blocked.empty:
            day = blocked.iloc[0]["date"]
            causes = materiality.loc[materiality["date"].eq(day), ["security_id", "event_ids", "reason"]]
            raise ValueError("Shadow blocker on " + str(day.date()) + ": "
                             + causes.to_json(orient="records"))
        raise ValueError("Shadow did not reach the final holdout session")

    risk = formation_risk(calendar, winners, shadow, cutoff=END)
    frozen_risk = pd.read_parquet(PROCESSED / "volatility_overlay_development.parquet")
    old_risk = risk.loc[risk["formation_date"].le("2023-02-28")]
    if (len(old_risk) != len(frozen_risk)
            or not old_risk["formation_date"].reset_index(drop=True).equals(frozen_risk["formation_date"])
            or not np.allclose(old_risk["exposure"], frozen_risk["exposure"], equal_nan=True, atol=1e-12, rtol=0)):
        raise ValueError("Generalized volatility overlay changed frozen development targets")

    holdout_winners = winners.loc[winners["formation_date"].ge("2023-03-31")].copy()
    holdout_risk = risk.loc[risk["formation_date"].ge("2023-03-31")].copy()
    months = pd.period_range("2023-04", "2026-03", freq="M").astype(str)
    selections = {str(month): group["security_id"].tolist()
                  for month, group in holdout_winners.groupby(holdout_winners["holding_month"].astype(str))}
    vm_exposure = dict(zip(holdout_risk["holding_month"].astype(str), holdout_risk["exposure"]))
    if set(selections) != set(months) or set(vm_exposure) != set(months):
        raise ValueError("Holdout winner or VM exposure schedule is incomplete")
    constants = {name: float(json.loads((ROOT / f"results/controls_development/{name}/control_definition.json")
                                        .read_text())["allocation"]) for name in ("FIX", "FIXVOL")}
    exposures = {
        "MOM": {month: 1.0 for month in months},
        "VM": vm_exposure,
        "FIX": {month: constants["FIX"] for month in months},
        "FIXVOL": {month: constants["FIXVOL"] for month in months},
    }
    sessions = calendar.loc[calendar["date"].between(START, END), "date"].dt.date.tolist()
    return {"holdout_returns": holdout_returns, "monthly": monthly, "formations": formations,
            "winners": holdout_winners, "shadow": shadow, "risk": holdout_risk,
            "selections": selections, "sessions": sessions, "exposures": exposures,
            "account_panel": _tradable_rights_account_quotes(
                _received_security_account_quotes(holdout))}


def main() -> None:
    source_paths = sorted(path for path in RUNTIME_INPUTS.rglob("*") if path.is_file())
    source_paths += [
        PROCESSED / "research_panel_v2.parquet",
        PROCESSED / "stock_total_returns.parquet",
        PROCESSED / "holdout_execution_panel.parquet",
    ]
    digest = hashlib.sha256()
    for path in source_paths:
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(_sha256(path).encode("ascii"))
    input_hash = digest.hexdigest()
    inputs = produce_inputs()
    result = run_sealed_bundle(
        inputs["selections"], inputs["sessions"], inputs["exposures"],
        inputs["account_panel"], input_hash, OUTPUT,
    )
    if result["status"] != "COMPLETE":
        print(json.dumps(result, sort_keys=True))
        return
    input_dir = OUTPUT / "producer_inputs"
    input_dir.mkdir()
    for name in ("holdout_returns", "monthly", "formations", "winners", "shadow", "risk"):
        inputs[name].to_parquet(input_dir / f"{name}.parquet", index=False)
    metrics = []
    for name, path in OPENING_STATES.items():
        state = json.loads(path.read_text(encoding="utf-8"))
        initial = (float(state["cash"])
                   + sum(float(row["amount"]) for row in state["sale_receivables"])
                   + sum(float(row["amount"]) for row in state["dividend_receivables"])
                   + sum(float(row["quantity"]) * float(state["last_marks"][row["security_id"]])
                         for row in state["lots"])
                   + sum(float(row["quantity"]) * float(state["last_marks"][row["security_id"]])
                         for row in state["bonus_entitlements"])
                   - float(state["tax_liability"]))
        nav = pd.read_parquet(OUTPUT / f"{name}_nav_daily.parquet")
        if (len(nav) != len(inputs["sessions"])
                or not pd.DatetimeIndex(nav["date"]).equals(pd.DatetimeIndex(inputs["sessions"]))
                or nav["reconciliation_error"].abs().max() > 1e-6):
            raise ValueError(f"Completed {name} account failed final NAV reconciliation")
        values = nav["nav"].astype(float)
        daily = values / values.shift(1, fill_value=initial) - 1
        if not np.allclose(daily, nav["daily_return"], rtol=0, atol=1e-12):
            raise ValueError(f"Completed {name} daily returns differ from NAV")
        years = (END.date() - pd.Timestamp("2023-03-31").date()).days / 365.2425
        sd = float(daily.std(ddof=1))
        peaks = np.maximum.accumulate(np.r_[initial, values.to_numpy()])
        drawdown = np.r_[initial, values.to_numpy()] / peaks - 1
        metrics.append({
            "account": name, "sessions": len(nav), "start_nav": initial,
            "end_nav": float(values.iloc[-1]), "total_return": float(values.iloc[-1] / initial - 1),
            "cagr": float((values.iloc[-1] / initial) ** (1 / years) - 1),
            "annualised_volatility": sd * np.sqrt(252),
            "sharpe_0pct_cash": float(daily.mean() / sd * np.sqrt(252)) if sd > 0 else np.nan,
            "max_drawdown": float(drawdown.min()),
        })
    summary = pd.DataFrame(metrics)
    summary.to_csv(OUTPUT / "holdout_metrics.csv", index=False)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
