"""Continue the declared modelling shadow and estimate formation-close RMS risk."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from brindco_momentum.signals.momentum_signal import CUTOFF, RETURNS
from brindco_momentum.portfolio.shadow_portfolio import ROOT, OUTPUT, load_shadow_inputs, simulate_shadow


AUDIT = ROOT / "results/volatility_overlay_audit"
ADANIENT_DATE = pd.Timestamp("2018-04-05")
ADANIENT_SECURITY = "NSE_42CD50DCCBD6"
ADANIENT_EVENT = "CA_09d4133ad6ad9024fa83"
ASSUMPTION_ID = "ADANIENT_2018_04_05_ZERO_INCREMENTAL_ENTITLEMENT"
HGS_DATE = pd.Timestamp("2022-02-22")
HGS_SECURITY = "NSE_03B0BD5CB55C"
HGS_BONUS = "CA_a28c7ef7be5fba82424e"
HGS_DIVIDEND = "CA_4bd3ac9cadba72dfd0ee"
HGS_FILING = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/f5386769-50d2-43c5-aa62-a7bee9caed11.pdf"
EASE_DATE = pd.Timestamp("2022-11-21")
EASE_SECURITY = "NSE_4F096D93F0F3"
EASE_BONUS = "CA_bd1a9c0fb614d418b033"
EASE_SPLIT = "CA_d980fda0218090aafc5e"
EASE_FILING = "https://www.easemytrip.com/investor-pdf/2022/Intimation-of-Record-Date-22-11-2022.pdf"
EVENT_DETAIL = ROOT / "results/stock_total_return_audit/event_application_detail.csv"
ZERO_STATUS = "MODELLED_ZERO_INCREMENTAL_ENTITLEMENT"
COMBINED_STATUS = "VERIFIED_ORDINARY_COMBINED_ACTION"
STRICT_HOLDINGS = OUTPUT / "primary_shadow_holdings.parquet"
STRICT_DAILY = OUTPUT / "primary_shadow_daily_returns.parquet"
WINDOW = 126
ANNUAL_SESSIONS = 252
TARGET = 0.12


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def exposure_for_sigma(sigma: float) -> tuple[float, str]:
    if not np.isfinite(sigma):
        return 0.0, "NONFINITE_VOLATILITY"
    if sigma <= 0:
        return 0.0, "NONPOSITIVE_VOLATILITY"
    return min(1.0, TARGET / sigma), "VALID"


def valid_raw_quote(row: pd.Series) -> bool:
    return bool(
        row["market_observed"]
        and row["market_data_status"] == "OK"
        and row["identity_status"] == "RESOLVED"
        and row["series"] in {"EQ", "BE", "BZ"}
        and np.isfinite(row["previous_close"]) and row["previous_close"] > 0
        and np.isfinite(row["close"]) and row["close"] > 0
        and np.isfinite(row["price_return"])
        and np.isclose(row["price_return"], row["close"] / row["previous_close"] - 1)
    )


def build_return_overrides(market: pd.DataFrame) -> dict[tuple[pd.Timestamp, str], dict[str, object]]:
    columns = [
        "event_id", "security_id", "series", "ex_date", "primary_class", "purpose_normalized",
        "source_file", "application_status", "application_reason", "cash_effect",
        "share_effect", "entitlement_effect",
    ]
    events = pd.read_csv(EVENT_DETAIL, usecols=columns, parse_dates=["ex_date"])
    if events["event_id"].duplicated().any() or events["ex_date"].max() > CUTOFF:
        raise ValueError("Corporate-action evidence is duplicated or crosses the development cutoff")
    events = events.set_index("event_id")

    hgs = market.loc[market["date"].eq(HGS_DATE) & market["security_id"].eq(HGS_SECURITY)]
    if len(hgs) != 1 or not valid_raw_quote(hgs.iloc[0]):
        raise ValueError("HGS combined-action quote or identity is unavailable")
    hgs = hgs.iloc[0]
    hgs_ids = {HGS_BONUS, HGS_DIVIDEND}
    hgs_events = events.loc[[HGS_BONUS, HGS_DIVIDEND]]
    if (
        bool(hgs["total_return_available"])
        or hgs["exclusion_reason"] != "MULTIPLE_ACTION_UNITS_UNVERIFIED"
        or len(hgs["all_event_ids"].split(";")) != 2
        or set(hgs["all_event_ids"].split(";")) != hgs_ids
        or not hgs_events["security_id"].eq(HGS_SECURITY).all()
        or not hgs_events["ex_date"].eq(HGS_DATE).all()
        or not hgs_events["series"].eq("EQ").all()
        or not hgs_events["application_status"].eq("RETURN_UNAVAILABLE_EXPLICIT").all()
        or not hgs_events["application_reason"].eq("MULTIPLE_ACTION_UNITS_UNVERIFIED").all()
        or hgs_events.loc[HGS_BONUS, "primary_class"] != "BONUS"
        or hgs_events.loc[HGS_DIVIDEND, "primary_class"] != "DIVIDEND"
        or not np.isclose(hgs_events.loc[HGS_BONUS, "share_effect"], 2)
        or not np.isclose(hgs_events.loc[HGS_BONUS, "cash_effect"], 0)
        or not np.isclose(hgs_events.loc[HGS_DIVIDEND, "share_effect"], 1)
        or not np.isclose(hgs_events.loc[HGS_DIVIDEND, "cash_effect"], 28)
        or not hgs_events["entitlement_effect"].eq(0).all()
    ):
        raise ValueError("HGS no longer matches the verified bonus and pre-bonus dividend")
    hgs_return = (2 * hgs["close"] + 28) / hgs["previous_close"] - 1
    overrides = {
        (HGS_DATE, HGS_SECURITY): {
            "daily_return": float(hgs_return), "status": COMBINED_STATUS,
            "assumption_id": "HGS_2022_02_22_VERIFIED_BONUS_DIVIDEND",
            "share_multiplier": 2.0, "cash_per_pre_event_share": 28.0,
            "evidence_source": HGS_FILING,
        }
    }

    ease = market.loc[market["date"].eq(EASE_DATE) & market["security_id"].eq(EASE_SECURITY)]
    if len(ease) != 1 or not valid_raw_quote(ease.iloc[0]):
        raise ValueError("EASEMYTRIP combined-action quote or identity is unavailable")
    ease = ease.iloc[0]
    ease_ids = {EASE_BONUS, EASE_SPLIT}
    ease_events = events.loc[[EASE_BONUS, EASE_SPLIT]]
    if (
        bool(ease["total_return_available"])
        or ease["exclusion_reason"] != "MULTIPLE_ACTION_UNITS_UNVERIFIED"
        or len(ease["all_event_ids"].split(";")) != 2
        or set(ease["all_event_ids"].split(";")) != ease_ids
        or not ease_events["security_id"].eq(EASE_SECURITY).all()
        or not ease_events["ex_date"].eq(EASE_DATE).all()
        or not ease_events["series"].eq("EQ").all()
        or not ease_events["application_status"].eq("RETURN_UNAVAILABLE_EXPLICIT").all()
        or not ease_events["application_reason"].eq("MULTIPLE_ACTION_UNITS_UNVERIFIED").all()
        or ease_events.loc[EASE_BONUS, "primary_class"] != "BONUS"
        or ease_events.loc[EASE_SPLIT, "primary_class"] != "SPLIT"
        or not np.isclose(ease_events.loc[EASE_BONUS, "share_effect"], 4)
        or not np.isclose(ease_events.loc[EASE_SPLIT, "share_effect"], 2)
        or not ease_events["cash_effect"].eq(0).all()
        or not ease_events["entitlement_effect"].eq(0).all()
    ):
        raise ValueError("EASEMYTRIP no longer matches the verified split and bonus")
    ease_return = 8 * ease["close"] / ease["previous_close"] - 1
    overrides[(EASE_DATE, EASE_SECURITY)] = {
        "daily_return": float(ease_return), "status": COMBINED_STATUS,
        "assumption_id": "EASEMYTRIP_2022_11_21_VERIFIED_SPLIT_BONUS",
        "share_multiplier": 8.0, "cash_per_pre_event_share": 0.0,
        "evidence_source": EASE_FILING,
    }

    complex_classes = {"STRUCTURAL", "RIGHTS", "PREFERENCE_SHARE_BONUS", "DEBENTURE_ENTITLEMENT"}
    blocked = market.loc[market["total_return_available"].eq(False)
                         & market["all_event_ids"].fillna("").ne("")]
    for row in blocked.itertuples(index=False):
        key = (row.date, row.security_id)
        if key in overrides:
            continue
        source = pd.Series(row._asdict())
        if (row.exclusion_reason not in {"TREATMENT_NOT_ACCEPTED", "ACCEPTED_STRICT_RETURN_EXCEPTION"}
                or not valid_raw_quote(source)):
            continue
        ids = row.all_event_ids.split(";")
        if len(ids) != len(set(ids)) or not set(ids).issubset(events.index):
            continue
        same_day = events.loc[events["security_id"].eq(row.security_id)
                              & events["ex_date"].eq(row.date)
                              & events["application_status"].ne("NOT_SIGNAL_RELEVANT")]
        if set(same_day.index) != set(ids):
            continue
        group = events.loc[ids]
        if (not group["security_id"].eq(row.security_id).all()
                or not group["ex_date"].eq(row.date).all()
                or not group["series"].eq(row.series).all()
                or not group["primary_class"].isin(complex_classes).all()
                or not group["application_status"].eq("RETURN_UNAVAILABLE_EXPLICIT").all()
                or not group["application_reason"].isin({"TREATMENT_NOT_ACCEPTED", "ACCEPTED_STRICT_RETURN_EXCEPTION"}).all()
                or not group["share_effect"].eq(1).all()
                or not group["cash_effect"].eq(0).all()
                or not group["entitlement_effect"].eq(0).all()
                or not np.isclose(row.share_effect, 1)
                or not np.isclose(row.cash_effect, 0)
                or not np.isclose(row.entitlement_effect, 0)):
            continue
        # A broad structural label cannot waive a named ordinary or terminal leg.
        ordinary_or_terminal = r"DIVIDEND|SPLIT|BUYBACK|TENDER|MERGER|AMALGAMATION|DELIST|CANCELLATION|LIQUIDATION|CAPITAL REDUCTION"
        if group["purpose_normalized"].fillna("").str.contains(ordinary_or_terminal, case=False).any():
            continue
        if group.loc[group["primary_class"].isin({"STRUCTURAL", "RIGHTS"}), "purpose_normalized"].fillna("").str.contains(
            r"BONUS|CASH", case=False
        ).any():
            continue
        assumption_id = ASSUMPTION_ID if ids == [ADANIENT_EVENT] else "ZERO_INCREMENTAL_ENTITLEMENT_" + "_".join(ids)
        overrides[key] = {
            "daily_return": float(row.price_return), "status": ZERO_STATUS,
            "assumption_id": assumption_id,
            "share_multiplier": 1.0, "cash_per_pre_event_share": 0.0,
            "evidence_source": ";".join(group["source_file"].dropna().unique()),
        }
    if (ADANIENT_DATE, ADANIENT_SECURITY) not in overrides:
        raise ValueError("Accepted ADANIENT complex-entitlement modelling day was not identified")
    return overrides


def formation_risk(calendar: pd.DataFrame, winners: pd.DataFrame,
                   daily: pd.DataFrame) -> pd.DataFrame:
    dates = pd.DatetimeIndex(calendar["date"].sort_values().drop_duplicates())
    if dates.max() > CUTOFF or daily["date"].max() > CUTOFF:
        raise ValueError("Risk calculation crossed the development cutoff")
    if daily.duplicated("date").any() or not daily["date"].is_monotonic_increasing:
        raise ValueError("Modelling shadow has duplicate or unordered sessions")
    if not pd.DatetimeIndex(daily["date"]).isin(dates).all():
        raise ValueError("Modelling shadow contains a noncanonical date")
    observed = daily.set_index("date")
    formations = winners[["formation_date", "holding_month", "scored"]].drop_duplicates()
    if formations.duplicated("formation_date").any():
        raise ValueError("Formation metadata is ambiguous")
    rows = []
    for formation in formations.sort_values("formation_date").itertuples(index=False):
        date = formation.formation_date
        position = dates.get_indexer([date])[0]
        if position < 0:
            raise ValueError("Formation is absent from canonical NSE calendar")
        window_dates = dates[max(0, position - WINDOW + 1):position + 1]
        window = observed.reindex(window_dates)
        valid = window["valid_return"].fillna(False).astype(bool) & np.isfinite(window["shadow_daily_return"])
        complete = len(window_dates) == WINDOW and valid.all()
        if complete:
            returns = window["shadow_daily_return"].to_numpy(dtype=float)
            square_sum = float(np.sum(returns * returns))
            sigma_sq = ANNUAL_SESSIONS / WINDOW * square_sum
            sigma = float(np.sqrt(sigma_sq))
            exposure, risk_status = exposure_for_sigma(sigma)
            reason = "" if risk_status == "VALID" else risk_status
        else:
            square_sum = sigma_sq = sigma = np.nan
            if len(window_dates) < WINDOW or window_dates[0] < observed.index.min():
                reason = "INSUFFICIENT_SHADOW_HISTORY"
            elif window_dates[-1] > observed.index.max():
                reason = "MODELLING_SHADOW_STOPPED"
            else:
                reason = "SHADOW_DAILY_RETURN_UNAVAILABLE"
            exposure = 0.0
            risk_status = reason
        available_dates = window.index[valid]
        modelled_days = int(window.loc[valid, "modelling_assumption_used"].fillna(False).sum()) if complete else 0
        rows.append({
            "formation_date": date, "holding_month": formation.holding_month,
            "is_scored": bool(formation.scored),
            "risk_window_start": window_dates[0] if len(window_dates) == WINDOW else pd.NaT,
            "risk_window_end": date,
            "shadow_returns_used": int(valid.sum()),
            "sum_squared_daily_returns": square_sum,
            "sigma_hat_sq": sigma_sq, "sigma_hat": sigma,
            "volatility_target": TARGET, "exposure": exposure,
            "cash_fraction": 1 - exposure,
            "exposure_capped": bool(risk_status == "VALID" and exposure == 1),
            "risk_estimate_available": risk_status == "VALID",
            "risk_status": risk_status,
            "modelling_shadow_used": bool(complete),
            "modelling_assumption_in_window": modelled_days > 0,
            "modelling_days_in_window": modelled_days,
            "contains_modelled_ADANIENT_day": ADANIENT_DATE in window_dates,
            "source_data_max_date": available_dates.max() if len(available_dates) else pd.NaT,
            "risk_exclusion_reason": reason,
        })
    risk = pd.DataFrame(rows)
    if risk.duplicated("formation_date").any():
        raise ValueError("Duplicate formation risk row")
    valid_risk = risk.loc[risk["risk_estimate_available"]]
    if (valid_risk["shadow_returns_used"].ne(WINDOW).any()
            or valid_risk["risk_window_end"].ne(valid_risk["formation_date"]).any()
            or valid_risk["source_data_max_date"].gt(valid_risk["formation_date"]).any()
            or valid_risk["sigma_hat"].isna().any()
            or valid_risk["sigma_hat"].lt(0).any()
            or valid_risk["exposure"].lt(0).any()
            or valid_risk["exposure"].gt(1).any()
            or valid_risk.loc[valid_risk["sigma_hat"].le(TARGET), "exposure"].ne(1).any()
            or valid_risk.loc[valid_risk["sigma_hat"].gt(TARGET), "exposure"].ge(1).any()
            or not np.allclose(valid_risk["cash_fraction"], 1 - valid_risk["exposure"])
            or risk.loc[~risk["risk_estimate_available"], "exposure"].ne(0).any()
            or risk.loc[~risk["risk_estimate_available"], "cash_fraction"].ne(1).any()):
        raise ValueError("Formation RMS risk or exposure invariant failed")
    return risk


def build_overlay() -> dict[str, object]:
    frozen_paths = (
        RETURNS, STRICT_HOLDINGS, STRICT_DAILY, EVENT_DETAIL,
        OUTPUT / "corporate_action_treatment/in_universe_event_treatments.parquet",
        OUTPUT / "corporate_action_treatment/nse_corporate_actions_treated_through_2023_03_31.parquet",
    )
    strict_hashes = {path: sha256(path) for path in frozen_paths}
    calendar, winners, market = load_shadow_inputs()
    overrides = build_return_overrides(market)
    holdings, daily, rebalances, materiality = simulate_shadow(calendar, winners, market, overrides)
    modelled = daily.loc[daily["modelling_assumption_used"]]
    modelled_events = materiality.loc[materiality["materiality_status"].isin({ZERO_STATUS, COMBINED_STATUS})].copy()
    for date, security_id, status in (
        (ADANIENT_DATE, ADANIENT_SECURITY, ZERO_STATUS),
        (HGS_DATE, HGS_SECURITY, COMBINED_STATUS),
        (EASE_DATE, EASE_SECURITY, COMBINED_STATUS),
    ):
        used = modelled_events.loc[modelled_events["date"].eq(date)
                                   & modelled_events["security_id"].eq(security_id)]
        if len(used) != 1 or used.iloc[0]["materiality_status"] != status:
            raise ValueError("A frozen corporate-action modelling day was not applied exactly once")
    if modelled_events.duplicated(["date", "security_id"]).any() or modelled_events["date"].nunique() != len(modelled):
        raise ValueError("Modelled security-days and shadow flags do not reconcile")
    strict = pd.read_parquet(STRICT_DAILY)
    prefix = daily.loc[daily["date"].lt(ADANIENT_DATE), ["date", "shadow_daily_return", "shadow_nav_index"]]
    accepted_prefix = strict.loc[strict["date"].lt(ADANIENT_DATE), prefix.columns]
    if not prefix.reset_index(drop=True).equals(accepted_prefix.reset_index(drop=True)):
        raise ValueError("Modelling shadow changed pre-assumption strict history")
    if daily["date"].max() > CUTOFF or holdings["date"].max() > CUTOFF:
        raise ValueError("Modelling shadow crossed the development cutoff")
    risk = formation_risk(calendar, winners, daily)

    AUDIT.mkdir(parents=True, exist_ok=True)
    holdings.to_parquet(OUTPUT / "primary_modelling_shadow_holdings.parquet", index=False)
    daily.to_parquet(OUTPUT / "primary_modelling_shadow_daily_returns.parquet", index=False)
    risk.to_parquet(OUTPUT / "volatility_overlay_development.parquet", index=False)
    risk.to_csv(AUDIT / "formation_risk_summary.csv", index=False)
    materiality.to_csv(AUDIT / "modelling_shadow_return_materiality.csv", index=False)
    modelled_events.to_csv(AUDIT / "modelled_corporate_action_days.csv", index=False)

    event_day = modelled.loc[modelled["date"].eq(ADANIENT_DATE)].iloc[0]
    event_weight = materiality.loc[
        materiality["date"].eq(ADANIENT_DATE)
        & materiality["security_id"].eq(ADANIENT_SECURITY)
        & materiality["materiality_status"].eq(ZERO_STATUS),
        "pre_event_weight",
    ]
    if len(event_weight) != 1 or not 0 < event_weight.iloc[0] < 1:
        raise ValueError("ADANIENT modelled-day pre-event weight was not established")
    sensitivity_rows = []
    for formation in risk.loc[risk["risk_estimate_available"]
                              & risk["modelling_assumption_in_window"]].itertuples(index=False):
        for stock_increment in (-0.05, 0.0, 0.05):
            changed_day = event_day.shadow_daily_return + event_weight.iloc[0] * stock_increment
            square_sum = formation.sum_squared_daily_returns - event_day.shadow_daily_return ** 2 + changed_day ** 2
            sigma = float(np.sqrt(ANNUAL_SESSIONS / WINDOW * square_sum))
            scenario_exposure, scenario_status = exposure_for_sigma(sigma)
            sensitivity_rows.append({
                "formation_date": formation.formation_date, "holding_month": formation.holding_month,
                "stock_return_increment_pp": stock_increment * 100,
                "modelled_event_weight": event_weight.iloc[0],
                "shadow_event_return_scenario": changed_day,
                "sigma_hat": sigma, "exposure": scenario_exposure,
                "risk_status": scenario_status,
            })
    pd.DataFrame(sensitivity_rows).to_csv(AUDIT / "adanient_modelled_window_impact.csv", index=False)

    valid_risk = risk.loc[risk["risk_estimate_available"]]
    first_scored_date = winners.loc[winners["scored"], "formation_date"].min()
    first_scored_risk = risk.loc[risk["formation_date"].eq(first_scored_date)]
    warmup_returns = daily.loc[daily["date"].le(first_scored_date) & daily["valid_return"]]
    if (len(first_scored_risk) != 1 or len(warmup_returns) < WINDOW
            or not first_scored_risk.iloc[0]["risk_estimate_available"]):
        raise ValueError("First scored formation failed the 126-session warm-up gate")
    first_scored_risk = first_scored_risk.iloc[0]
    checks = {
        "formation_rows": len(risk),
        "valid_risk_formations": len(valid_risk),
        "valid_scored_formations": int(valid_risk["is_scored"].sum()),
        "scored_exposure_below_one": int(valid_risk.loc[valid_risk["is_scored"], "exposure"].lt(1).sum()),
        "first_scored_formation": first_scored_date.date().isoformat(),
        "valid_shadow_returns_by_first_scored_formation": len(warmup_returns),
        "first_scored_window_start": first_scored_risk["risk_window_start"].date().isoformat(),
        "first_scored_sigma_hat": first_scored_risk["sigma_hat"],
        "first_scored_exposure": first_scored_risk["exposure"],
        "exposure_below_one": int(valid_risk["exposure"].lt(1).sum()),
        "min_exposure": valid_risk["exposure"].min() if not valid_risk.empty else np.nan,
        "median_exposure": valid_risk["exposure"].median() if not valid_risk.empty else np.nan,
        "mean_exposure": valid_risk["exposure"].mean() if not valid_risk.empty else np.nan,
        "max_sigma_hat": valid_risk["sigma_hat"].max() if not valid_risk.empty else np.nan,
        "modelled_day_risk_windows": int(valid_risk["modelling_assumption_in_window"].sum()),
        "modelled_security_days": len(modelled_events),
        "modelled_corporate_action_dates": modelled_events["date"].nunique(),
        "modelling_shadow_daily_rows": len(daily),
        "modelling_shadow_valid_returns": int(daily["valid_return"].sum()),
        "first_modelled_shadow_date": daily["date"].min().date().isoformat(),
        "last_valid_shadow_date": daily.loc[daily["valid_return"], "date"].max().date().isoformat(),
        "first_blocker_after_assumption": (daily.loc[~daily["valid_return"], "date"].min().date().isoformat()
                                           if (~daily["valid_return"]).any() else ""),
        "modelling_shadow_reaches_cutoff": bool(daily.iloc[-1]["valid_return"]
                                               and daily.iloc[-1]["date"] == CUTOFF),
        "max_value_date_read": market["date"].max().date().isoformat(),
    }
    pd.DataFrame([{"measure": key, "value": value} for key, value in checks.items()]).to_csv(
        AUDIT / "exposure_sanity_checks.csv", index=False
    )
    hash_rows = []
    for path, before in strict_hashes.items():
        after = sha256(path)
        if before != after:
            raise ValueError("Frozen audited artifact changed")
        hash_rows.append({"artifact": path.relative_to(ROOT).as_posix(), "before_sha256": before,
                          "after_sha256": after})
    pd.DataFrame(hash_rows).to_csv(AUDIT / "strict_shadow_hashes.csv", index=False)
    return checks


if __name__ == "__main__":
    for name, value in build_overlay().items():
        print(f"{name}: {value}")
