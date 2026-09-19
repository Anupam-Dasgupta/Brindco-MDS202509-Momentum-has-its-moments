"""Build the gross unscaled primary shadow from historical winner holdings."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from brindco_momentum.signals.momentum_signal import CUTOFF, CALENDAR, PANEL, RETURNS, WINNERS_OUTPUT


from brindco_momentum.paths import ROOT
OUTPUT = ROOT / "data/processed"
AUDIT = ROOT / "results/shadow_audit"
FIRST_MEMBERSHIP = pd.Timestamp("2014-08-28")
FIRST_SCORED_FORMATION = pd.Timestamp("2015-03-31")


def usable_quote(row: pd.Series, opening: bool = False) -> bool:
    price = row["open"] if opening else row["close"]
    return bool(
        row["market_observed"]
        and row["market_data_status"] == "OK"
        and row["identity_status"] == "RESOLVED"
        and row["series"] in {"EQ", "BE", "BZ"}
        and np.isfinite(price) and price > 0
    )


def simulate_shadow(
    calendar: pd.DataFrame, winners: pd.DataFrame, market: pd.DataFrame,
    return_overrides: dict[tuple[pd.Timestamp, str], dict[str, object]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    calendar = calendar.sort_values("date").reset_index(drop=True)
    next_session = calendar.set_index("date")["next_trading_day"]
    winners = winners.copy()
    winners["rebalance_date"] = winners["formation_date"].map(next_session)
    if winners["rebalance_date"].isna().any() or winners["formation_date"].min() < FIRST_MEMBERSHIP:
        raise ValueError("Winner formation has no evidenced next-session rebalance")
    targets = {date: group for date, group in winners.groupby("rebalance_date", sort=True)}
    first_date = min(targets)
    dates = calendar.loc[calendar["date"].ge(first_date), "date"]
    market = market.set_index(["date", "security_id"]).sort_index()
    if not market.index.is_unique:
        raise ValueError("Duplicate shadow market observation")

    holdings: dict[str, float] = {}
    last_values: dict[str, float] = {}
    nav = 1.0
    holdings_rows = []
    daily_rows = []
    rebalance_rows = []
    materiality_rows = []

    for date in dates:
        try:
            day = market.loc[date]
        except KeyError:
            day = pd.DataFrame(columns=market.columns)
        old_ids = list(holdings)
        pre_weights = {security_id: value / nav for security_id, value in last_values.items()}
        is_rebalance = date in targets
        selected = targets[date] if is_rebalance else None
        blocker_reason = ""
        blocked_ids = []
        modelled_today = {
            security_id: value
            for (override_date, security_id), value in (return_overrides or {}).items()
            if override_date == date and security_id in holdings
        }

        # Record every sourced unavailable return before the first blocker.
        unavailable = day.loc[day["total_return_available"].eq(False)
                              & day["all_event_ids"].fillna("").ne("")]
        for security_id, row in unavailable.iterrows():
            held = security_id in holdings
            treatment = modelled_today.get(security_id)
            record = {
                "security_id": security_id, "date": date, "symbol": row["symbol"],
                "event_ids": row["all_event_ids"], "held_before_event": held,
                "pre_event_weight": pre_weights.get(security_id, 0.0),
                "materiality_status": (
                    treatment["status"] if treatment is not None
                    else "SHADOW_DAILY_RETURN_BLOCKER" if held else "NOT_HELD"
                ),
                "reason": row["exclusion_reason"],
            }
            if return_overrides is not None:
                record.update({
                    "raw_price_return": row.get("price_return", np.nan),
                    "modelled_stock_return": treatment["daily_return"] if treatment else np.nan,
                    "share_multiplier": treatment["share_multiplier"] if treatment else np.nan,
                    "cash_per_pre_event_share": treatment["cash_per_pre_event_share"] if treatment else np.nan,
                    "modelling_assumption_id": treatment["assumption_id"] if treatment else "",
                    "evidence_source": treatment["evidence_source"] if treatment else "",
                })
            materiality_rows.append(record)

        if modelled_today:
            day = day.copy()
            for security_id, treatment in modelled_today.items():
                replacement_return = treatment["daily_return"]
                if (security_id not in holdings or security_id not in day.index
                        or bool(day.loc[security_id, "total_return_available"])
                        or not np.isfinite(replacement_return)
                        or replacement_return < -1
                        or not treatment["assumption_id"]
                        or not treatment["status"]
                        or not np.isfinite(treatment["share_multiplier"])
                        or treatment["share_multiplier"] <= 0
                        or not np.isfinite(treatment["cash_per_pre_event_share"])):
                    raise ValueError("Modelled return is not an explicit held unavailable event")
                day.loc[security_id, "daily_total_return"] = replacement_return
                day.loc[security_id, "total_return_available"] = True
                day.loc[security_id, "share_effect"] = treatment["share_multiplier"]
                day.loc[security_id, "cash_effect"] = treatment["cash_per_pre_event_share"]

        old_rows = day.reindex(old_ids)
        for security_id, row in old_rows.iterrows():
            if (
                pd.isna(row["close"]) or not usable_quote(row)
                or not bool(row["total_return_available"])
                or not np.isfinite(row["daily_total_return"])
                or row["daily_total_return"] < -1
            ):
                blocked_ids.append(security_id)
        if blocked_ids:
            blocker_reason = "SHADOW_DAILY_RETURN_BLOCKER"

        if not blocker_reason and is_rebalance:
            # The old book owns the overnight leg. The new book starts at the
            # ex-date open and therefore does not inherit the old entitlement.
            for security_id, row in old_rows.iterrows():
                if not usable_quote(row, opening=True):
                    blocked_ids.append(security_id)
                    blocker_reason = "OLD_HOLDING_OPEN_MISSING"
                elif row["entitlement_effect"] != 0:
                    blocked_ids.append(security_id)
                    blocker_reason = "ENTITLEMENT_OPEN_VALUE_UNEVIDENCED"
            new_rows = day.reindex(selected["security_id"].tolist())
            for security_id, row in new_rows.iterrows():
                if not usable_quote(row, opening=True) or not usable_quote(row):
                    blocked_ids.append(security_id)
                    blocker_reason = "SELECTED_OPEN_OR_CLOSE_MISSING"

        if blocker_reason:
            for security_id in set(blocked_ids):
                if not any(item["security_id"] == security_id and item["date"] == date
                           for item in materiality_rows):
                    materiality_rows.append({
                        "security_id": security_id, "date": date,
                        "symbol": day.loc[security_id, "symbol"] if security_id in day.index else "",
                        "event_ids": day.loc[security_id, "all_event_ids"] if security_id in day.index else "",
                        "held_before_event": security_id in holdings,
                        "pre_event_weight": pre_weights.get(security_id, 0.0),
                        "materiality_status": blocker_reason,
                        "reason": (day.loc[security_id, "exclusion_reason"]
                                   if security_id in day.index else "MARKET_ROW_MISSING"),
                    })
            blocked_day = {
                "date": date, "shadow_nav_index": np.nan, "shadow_daily_return": np.nan,
                "valid_return": False, "blocker_reason": blocker_reason,
                "holdings_count": len(holdings), "rebalance_flag": is_rebalance,
            }
            if return_overrides is not None:
                blocked_day.update({
                    "return_status": "BLOCKED", "modelling_assumption_used": False,
                    "modelling_assumption_id": "",
                })
            daily_rows.append(blocked_day)
            break

        previous_nav = nav
        if is_rebalance:
            open_wealth = sum(
                holdings[security_id] * (
                    row["share_effect"] * row["open"] + row["cash_effect"]
                )
                for security_id, row in old_rows.iterrows()
            ) if holdings else nav
            if not np.isfinite(open_wealth) or open_wealth <= 0:
                raise ValueError("Shadow has no positive opening wealth")
            target_count = len(selected)
            holdings = {
                security_id: open_wealth / target_count / day.loc[security_id, "open"]
                for security_id in selected["security_id"]
            }
            last_values = {
                security_id: units * day.loc[security_id, "close"]
                for security_id, units in holdings.items()
            }
            nav = sum(last_values.values())
            rebalance_rows.append({
                "formation_date": selected["formation_date"].iloc[0],
                "rebalance_date": date, "old_holdings_count": len(old_ids),
                "winner_count": target_count, "prior_close_nav": previous_nav,
                "opening_nav": open_wealth, "closing_nav": nav,
            })
        else:
            next_values = {
                security_id: last_values[security_id] * (1 + row["daily_total_return"])
                for security_id, row in old_rows.iterrows()
            }
            holdings = {
                security_id: next_values[security_id] / day.loc[security_id, "close"]
                for security_id in old_ids
            }
            last_values = next_values
            nav = sum(last_values.values())
        if not np.isfinite(nav) or nav < 0:
            raise ValueError("Shadow wealth became invalid")
        completed_day = {
            "date": date, "shadow_nav_index": nav,
            "shadow_daily_return": nav / previous_nav - 1,
            "valid_return": True, "blocker_reason": "",
            "holdings_count": len(holdings), "rebalance_flag": is_rebalance,
        }
        if return_overrides is not None:
            assumption_id = ";".join(value["assumption_id"] for value in modelled_today.values())
            completed_day.update({
                "return_status": ";".join(value["status"] for value in modelled_today.values())
                if modelled_today else "AUDITED",
                "modelling_assumption_used": bool(modelled_today),
                "modelling_assumption_id": assumption_id,
            })
        daily_rows.append(completed_day)
        selected_month = date.to_period("M")
        for security_id, units in holdings.items():
            value = last_values[security_id]
            holdings_rows.append({
                "date": date, "security_id": security_id, "symbol": day.loc[security_id, "symbol"],
                "units": units, "close": day.loc[security_id, "close"],
                "market_value": value, "portfolio_weight": value / nav,
                "selected_month": selected_month, "rebalance_flag": is_rebalance,
            })

    return (pd.DataFrame(holdings_rows), pd.DataFrame(daily_rows),
            pd.DataFrame(rebalance_rows), pd.DataFrame(materiality_rows))


def load_shadow_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    winners = pd.read_parquet(WINNERS_OUTPUT)
    if winners["formation_date"].max() > CUTOFF or winners["formation_date"].min() < FIRST_MEMBERSHIP:
        raise ValueError("Primary winners cross membership or holdout boundary")
    calendar = ds.dataset(CALENDAR, format="parquet").to_table(
        columns=["date", "next_trading_day"],
        filter=ds.field("date") <= CUTOFF.to_datetime64(),
    ).to_pandas()
    calendar = calendar.sort_values("date")
    if calendar["date"].max() > CUTOFF:
        raise ValueError("Post-cutoff calendar date read")
    security_ids = winners["security_id"].unique().tolist()
    first_date = calendar.set_index("date").loc[winners["formation_date"].min(), "next_trading_day"]
    if pd.isna(first_date) or first_date > CUTOFF:
        raise ValueError("First official formation has no development rebalance session")
    date_filter = ((ds.field("date") >= first_date.to_datetime64())
                   & (ds.field("date") <= CUTOFF.to_datetime64())
                   & ds.field("security_id").isin(security_ids))
    panel = ds.dataset(PANEL, format="parquet").to_table(
        columns=["date", "security_id", "symbol", "series", "open", "close",
                 "market_observed", "market_data_status", "identity_status"],
        filter=date_filter,
    ).to_pandas()
    returns = ds.dataset(RETURNS, format="parquet").to_table(
        columns=["date", "security_id", "close", "previous_close", "price_return", "daily_total_return", "total_return_available",
                 "exclusion_reason", "all_event_ids", "cash_effect", "share_effect",
                 "entitlement_effect"],
        filter=date_filter,
    ).to_pandas()
    market = panel.merge(returns, on=["date", "security_id"], how="outer", validate="one_to_one",
                         suffixes=("", "_return"), indicator=True)
    if (len(market) != len(panel) or len(market) != len(returns)
            or not market["_merge"].eq("both").all()
            or not np.allclose(market["close"], market["close_return"], equal_nan=True)
            or market["date"].max() > CUTOFF):
        raise ValueError("Shadow market join or holdout boundary failed")
    market = market.drop(columns=["close_return", "_merge"])
    return calendar, winners, market


def build_primary_shadow() -> dict[str, object]:
    calendar, winners, market = load_shadow_inputs()
    first_date = calendar.set_index("date").loc[winners["formation_date"].min(), "next_trading_day"]
    holdings, daily, rebalances, materiality = simulate_shadow(calendar, winners, market)
    if daily.empty or daily["date"].min() != first_date:
        raise ValueError("Shadow did not start at first evidenced opening session")
    first_blocker = daily.loc[~daily["valid_return"], "date"].min()
    strict = pd.read_csv(ROOT / "data/processed/runtime_inputs/event_application_detail.csv")
    strict_ids = {
        "CA_faa277a19bfa2ac115cc", "CA_df82d8fc43ad7e21c2a8",
        "CA_52dafdfb28d9f35d7326", "CA_9d29c825ee80b650567a",
    }
    strict = strict.loc[strict["event_id"].isin(strict_ids), ["event_id", "security_id", "symbol", "ex_date"]]
    if len(strict) != 4:
        raise ValueError("Four accepted strict daily exceptions were not found")
    strict["ex_date"] = pd.to_datetime(strict["ex_date"])
    extra = []
    for event in strict.itertuples(index=False):
        if not materiality.empty and (
            materiality["security_id"].eq(event.security_id)
            & materiality["date"].eq(event.ex_date)
        ).any():
            continue
        if pd.notna(first_blocker) and event.ex_date > first_blocker:
            status = "NOT_ASSESSABLE_AFTER_FIRST_BLOCKER"
            held_before = pd.NA
            pre_weight = np.nan
        else:
            prior_dates = calendar.loc[calendar["date"].lt(event.ex_date), "date"]
            previous_date = prior_dates.max() if not prior_dates.empty else pd.NaT
            held = holdings.loc[holdings["date"].eq(previous_date)
                                & holdings["security_id"].eq(event.security_id)]
            if not held.empty:
                raise ValueError("Held strict exception was omitted from daily materiality")
            status = "NOT_HELD"
            held_before = False
            pre_weight = 0.0
        extra.append({
            "security_id": event.security_id, "date": event.ex_date, "symbol": event.symbol,
            "event_ids": event.event_id, "held_before_event": held_before,
            "pre_event_weight": pre_weight, "materiality_status": status,
            "reason": "ACCEPTED_STRICT_RETURN_EXCEPTION",
        })
    if extra:
        materiality = pd.concat([materiality, pd.DataFrame(extra)], ignore_index=True)
    materiality["first_affected_risk_window_end"] = pd.NaT
    materiality["last_affected_risk_window_end"] = pd.NaT
    materiality["affected_monthly_formations"] = ""
    calendar_dates = calendar["date"].tolist()
    for row in materiality.index[materiality["materiality_status"].eq("SHADOW_DAILY_RETURN_BLOCKER")]:
        event_date = materiality.at[row, "date"]
        position = calendar_dates.index(event_date)
        last_window_end = calendar_dates[min(position + 125, len(calendar_dates) - 1)]
        affected = winners.loc[winners["formation_date"].between(event_date, last_window_end), "formation_date"].drop_duplicates()
        materiality.at[row, "first_affected_risk_window_end"] = event_date
        materiality.at[row, "last_affected_risk_window_end"] = last_window_end
        materiality.at[row, "affected_monthly_formations"] = ";".join(affected.dt.strftime("%Y-%m-%d"))
    AUDIT.mkdir(parents=True, exist_ok=True)
    holdings.to_parquet(OUTPUT / "primary_shadow_holdings.parquet", index=False)
    daily.to_parquet(OUTPUT / "primary_shadow_daily_returns.parquet", index=False)
    rebalances.to_csv(AUDIT / "rebalance_summary.csv", index=False)
    daily.to_csv(AUDIT / "shadow_daily_return_completeness.csv", index=False)
    materiality.to_csv(AUDIT / "unavailable_daily_return_materiality.csv", index=False)

    valid = daily.loc[daily["valid_return"]]
    warmup = valid.loc[valid["date"].le(FIRST_SCORED_FORMATION)]
    first_formation = winners["formation_date"].min()
    summary = {
        "primary_signal_convention": "STRICT_AUDITABLE_SIGNAL_PRIMARY",
        "first_shadow_formation": first_formation.date().isoformat(),
        "first_shadow_holding_month": str(winners.loc[winners["formation_date"].eq(first_formation), "holding_month"].iloc[0]),
        "first_daily_shadow_return": daily["date"].min().date().isoformat(),
        "rebalance_dates_completed": len(rebalances),
        "daily_observations": len(daily),
        "valid_daily_returns": len(valid),
        "valid_daily_returns_by_march_2015_formation": len(warmup),
        "warmup_gate": "PASS" if len(warmup) >= 126 else "FAIL",
        "first_blocker_date": first_blocker.date().isoformat() if pd.notna(first_blocker) else "",
        "max_value_date_read": market["date"].max().date().isoformat(),
    }
    pd.DataFrame([{"measure": key, "value": value} for key, value in summary.items()]).to_csv(
        AUDIT / "warmup_summary.csv", index=False
    )
    return summary


if __name__ == "__main__":
    for name, value in build_primary_shadow().items():
        print(f"{name}: {value}")
