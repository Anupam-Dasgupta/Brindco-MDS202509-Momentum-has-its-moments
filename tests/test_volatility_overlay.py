import hashlib

import numpy as np
import pandas as pd
import pytest

from momentum_signal import CUTOFF, RETURNS
from shadow_portfolio import simulate_shadow
from volatility_overlay import (
    ADANIENT_DATE, ADANIENT_EVENT, ADANIENT_SECURITY, ASSUMPTION_ID, AUDIT,
    COMBINED_STATUS, HGS_BONUS, HGS_DATE, HGS_DIVIDEND, HGS_SECURITY,
    EASE_BONUS, EASE_DATE, EASE_SECURITY, EASE_SPLIT,
    OUTPUT, ROOT, STRICT_DAILY, STRICT_HOLDINGS, ZERO_STATUS,
    build_return_overrides, exposure_for_sigma, formation_risk,
)


def test_exposure_rule_uses_plan_cash_fallback():
    assert exposure_for_sigma(0.06) == (1.0, "VALID")
    assert exposure_for_sigma(0.12) == (1.0, "VALID")
    assert exposure_for_sigma(0.24) == (0.5, "VALID")
    assert exposure_for_sigma(0.0) == (0.0, "NONPOSITIVE_VOLATILITY")
    assert exposure_for_sigma(-0.01) == (0.0, "NONPOSITIVE_VOLATILITY")
    for invalid in (np.nan, np.inf, -np.inf):
        assert exposure_for_sigma(invalid) == (0.0, "NONFINITE_VOLATILITY")


def synthetic_risk_inputs(return_value=0.01):
    # These are the synthetic canonical sessions for this unit test.
    dates = pd.bdate_range("2014-09-01", periods=127)
    calendar = pd.DataFrame({"date": dates})
    winners = pd.DataFrame({
        "formation_date": [dates[124], dates[125]],
        "holding_month": ["2015-02", "2015-03"],
        "scored": [False, True],
    })
    daily = pd.DataFrame({
        "date": dates,
        "shadow_daily_return": [return_value] * len(dates),
        "valid_return": [True] * len(dates),
        "modelling_assumption_used": [False] * len(dates),
    })
    return calendar, winners, daily


def test_exact_canonical_window_rms_and_no_future_return():
    calendar, winners, daily = synthetic_risk_inputs()
    daily.loc[daily.index[-1], "shadow_daily_return"] = 0.9
    risk = formation_risk(calendar, winners, daily)
    early, scored = risk.iloc[0], risk.iloc[1]
    assert early.shadow_returns_used == 125
    assert early.risk_status == "INSUFFICIENT_SHADOW_HISTORY"
    assert pd.isna(early.sigma_hat) and early.exposure == 0 and early.cash_fraction == 1

    assert scored.shadow_returns_used == 126
    assert scored.risk_window_start == daily.iloc[0].date
    assert scored.risk_window_end == winners.iloc[1].formation_date
    assert scored.source_data_max_date == scored.formation_date
    assert np.isclose(scored.sum_squared_daily_returns, 126 * 0.01**2)
    assert np.isclose(scored.sigma_hat_sq, 252 / 126 * 126 * 0.01**2)
    assert np.isclose(scored.sigma_hat, np.sqrt(252) * 0.01)
    assert np.isclose(scored.exposure, 0.12 / scored.sigma_hat)
    # Constant returns have zero demeaned standard deviation, but positive RMS risk.
    assert scored.sigma_hat > 0.15


def test_zero_and_unavailable_window_returns_target_cash():
    calendar, winners, daily = synthetic_risk_inputs(return_value=0.0)
    risk = formation_risk(calendar, winners, daily)
    scored = risk.iloc[1]
    assert scored.sigma_hat == 0
    assert scored.risk_status == "NONPOSITIVE_VOLATILITY"
    assert not scored.risk_estimate_available
    assert scored.exposure == 0 and scored.cash_fraction == 1

    daily.loc[10, "shadow_daily_return"] = np.nan
    daily.loc[10, "valid_return"] = False
    risk = formation_risk(calendar, winners, daily)
    scored = risk.iloc[1]
    assert scored.risk_status == "SHADOW_DAILY_RETURN_UNAVAILABLE"
    assert pd.isna(scored.sigma_hat)
    assert scored.exposure == 0 and scored.cash_fraction == 1

    daily.loc[10, "shadow_daily_return"] = np.inf
    daily.loc[10, "valid_return"] = True
    risk = formation_risk(calendar, winners, daily)
    assert risk.iloc[1].risk_status == "SHADOW_DAILY_RETURN_UNAVAILABLE"
    assert risk.iloc[1].exposure == 0


def test_noncanonical_or_unordered_shadow_dates_fail():
    calendar, winners, daily = synthetic_risk_inputs()
    with pytest.raises(ValueError, match="unordered"):
        formation_risk(calendar, winners, daily.iloc[::-1].reset_index(drop=True))
    daily.loc[0, "date"] = pd.Timestamp("2014-08-30")
    with pytest.raises(ValueError, match="noncanonical"):
        formation_risk(calendar, winners, daily)


def test_only_explicit_modelled_return_continues_shadow():
    dates = pd.to_datetime(["2014-08-28", "2014-09-01", "2014-09-02", "2014-09-03"])
    calendar = pd.DataFrame({"date": dates, "next_trading_day": [*dates[1:], pd.NaT]})
    winners = pd.DataFrame({"formation_date": [dates[0]], "security_id": ["A"]})
    market = pd.DataFrame({
        "date": dates[1:], "security_id": ["A"] * 3, "symbol": ["A"] * 3,
        "series": ["EQ"] * 3, "open": [100.0, 90.0, 80.0],
        "close": [100.0, 90.0, 80.0], "market_observed": [True] * 3,
        "market_data_status": ["OK"] * 3, "identity_status": ["RESOLVED"] * 3,
        "daily_total_return": [0.0, np.nan, np.nan],
        "total_return_available": [True, False, False],
        "exclusion_reason": ["", "TREATMENT_NOT_ACCEPTED", "DIFFERENT_ACTION_UNRESOLVED"],
        "all_event_ids": ["", "E1", "E2"], "cash_effect": [0.0] * 3,
        "share_effect": [1.0] * 3, "entitlement_effect": [0.0] * 3,
    })
    _, strict_daily, _, _ = simulate_shadow(calendar, winners, market)
    assert len(strict_daily) == 2 and not strict_daily.iloc[-1].valid_return
    override = {
        "daily_return": -0.1, "status": ZERO_STATUS,
        "assumption_id": "EXPLICIT_E1", "share_multiplier": 1.0,
        "cash_per_pre_event_share": 0.0, "evidence_source": "synthetic",
    }
    _, modelled_daily, _, materiality = simulate_shadow(calendar, winners, market, {(dates[2], "A"): override})
    assert len(modelled_daily) == 3
    assert modelled_daily.iloc[1].valid_return
    assert modelled_daily.iloc[1].modelling_assumption_used
    assert modelled_daily.iloc[1].modelling_assumption_id == "EXPLICIT_E1"
    assert not modelled_daily.iloc[2].valid_return
    assert modelled_daily.iloc[2].blocker_reason == "SHADOW_DAILY_RETURN_BLOCKER"
    blocked = materiality.loc[materiality.materiality_status.eq("SHADOW_DAILY_RETURN_BLOCKER")]
    assert blocked.iloc[-1].event_ids == "E2" and blocked.iloc[-1].pre_event_weight > 0


def test_combined_bonus_and_dividend_preserve_reinvested_wealth():
    dates = pd.to_datetime(["2014-08-28", "2014-09-01", "2014-09-02", "2014-09-03"])
    calendar = pd.DataFrame({"date": dates, "next_trading_day": [*dates[1:], pd.NaT]})
    winners = pd.DataFrame({"formation_date": [dates[0]], "security_id": ["A"]})
    market = pd.DataFrame({
        "date": dates[1:], "security_id": ["A"] * 3, "symbol": ["A"] * 3,
        "series": ["EQ"] * 3, "open": [100.0, 50.0, 55.0],
        "close": [100.0, 50.0, 55.0], "market_observed": [True] * 3,
        "market_data_status": ["OK"] * 3, "identity_status": ["RESOLVED"] * 3,
        "price_return": [0.0, -0.5, 0.1],
        "daily_total_return": [0.0, np.nan, 0.1],
        "total_return_available": [True, False, True],
        "exclusion_reason": ["", "MULTIPLE_ACTION_UNITS_UNVERIFIED", ""],
        "all_event_ids": ["", "BONUS;DIVIDEND", ""],
        "cash_effect": [0.0] * 3, "share_effect": [1.0] * 3,
        "entitlement_effect": [0.0] * 3,
    })
    override = {
        "daily_return": 0.05, "status": COMBINED_STATUS,
        "assumption_id": "VERIFIED_COMBINED", "share_multiplier": 2.0,
        "cash_per_pre_event_share": 5.0, "evidence_source": "synthetic",
    }
    holdings, daily, _, materiality = simulate_shadow(calendar, winners, market, {(dates[2], "A"): override})
    before = holdings.loc[holdings.date.eq(dates[1]), "units"].iloc[0]
    after = holdings.loc[holdings.date.eq(dates[2]), "units"].iloc[0]
    assert np.isclose(after / before, 2 + 5 / 50)
    assert np.isclose(daily.loc[daily.date.eq(dates[2]), "shadow_nav_index"].iloc[0], 1.05)
    assert np.isclose(daily.loc[daily.date.eq(dates[3]), "shadow_nav_index"].iloc[0], 1.155)
    assert daily.loc[daily.date.eq(dates[2]), "return_status"].iloc[0] == COMBINED_STATUS
    assert materiality.loc[materiality.date.eq(dates[2]), "cash_per_pre_event_share"].iloc[0] == 5


def test_real_fallback_gate_rejects_bad_quotes_and_ordinary_combo():
    market = pd.DataFrame([
        {
            "date": ADANIENT_DATE, "security_id": ADANIENT_SECURITY, "series": "EQ",
            "previous_close": 151.45, "close": 147.85,
            "all_event_ids": ADANIENT_EVENT, "exclusion_reason": "TREATMENT_NOT_ACCEPTED",
        },
        {
            "date": HGS_DATE, "security_id": HGS_SECURITY, "series": "EQ",
            "previous_close": 2733.8, "close": 1310.1,
            "all_event_ids": f"{HGS_DIVIDEND};{HGS_BONUS}",
            "exclusion_reason": "MULTIPLE_ACTION_UNITS_UNVERIFIED",
        },
        {
            "date": EASE_DATE, "security_id": EASE_SECURITY, "series": "EQ",
            "previous_close": 381.95, "close": 57.3,
            "all_event_ids": f"{EASE_BONUS};{EASE_SPLIT}",
            "exclusion_reason": "MULTIPLE_ACTION_UNITS_UNVERIFIED",
        },
    ])
    market["price_return"] = market["close"] / market["previous_close"] - 1
    market["market_observed"] = True
    market["market_data_status"] = "OK"
    market["identity_status"] = "RESOLVED"
    market["total_return_available"] = False
    market["cash_effect"] = 0.0
    market["share_effect"] = 1.0
    market["entitlement_effect"] = 0.0

    overrides = build_return_overrides(market)
    assert set(overrides) == {
        (ADANIENT_DATE, ADANIENT_SECURITY), (HGS_DATE, HGS_SECURITY),
        (EASE_DATE, EASE_SECURITY),
    }
    assert overrides[(ADANIENT_DATE, ADANIENT_SECURITY)]["daily_return"] == market.iloc[0].price_return
    assert np.isclose(overrides[(HGS_DATE, HGS_SECURITY)]["daily_return"],
                      (2 * 1310.1 + 28) / 2733.8 - 1)
    assert overrides[(HGS_DATE, HGS_SECURITY)]["status"] == COMBINED_STATUS
    ease = overrides[(EASE_DATE, EASE_SECURITY)]
    assert ease["share_multiplier"] == 8
    assert ease["cash_per_pre_event_share"] == 0
    assert np.isclose(ease["daily_return"], 8 * 57.3 / 381.95 - 1)
    assert not np.isclose(ease["daily_return"], market.iloc[2].price_return)
    assert ease["status"] == COMBINED_STATUS

    missing_price = market.copy()
    missing_price.loc[0, "price_return"] = np.nan
    with pytest.raises(ValueError, match="ADANIENT"):
        build_return_overrides(missing_price)
    bad_identity = market.copy()
    bad_identity.loc[0, "identity_status"] = "UNRESOLVED"
    with pytest.raises(ValueError, match="ADANIENT"):
        build_return_overrides(bad_identity)


def test_real_modelling_artifacts_keep_strict_shadow_and_cutoff():
    hashes = pd.read_csv(AUDIT / "strict_shadow_hashes.csv")
    for path in (RETURNS, STRICT_HOLDINGS, STRICT_DAILY):
        row = hashes.loc[hashes.artifact.eq(path.relative_to(ROOT).as_posix())]
        assert len(row) == 1
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == row.iloc[0].before_sha256 == row.iloc[0].after_sha256

    daily = pd.read_parquet(OUTPUT / "primary_modelling_shadow_daily_returns.parquet")
    strict = pd.read_parquet(STRICT_DAILY)
    prefix = daily.loc[daily.date.lt(ADANIENT_DATE),
                       ["date", "shadow_daily_return", "shadow_nav_index"]]
    pd.testing.assert_frame_equal(
        prefix.reset_index(drop=True),
        strict.loc[strict.date.lt(ADANIENT_DATE), prefix.columns].reset_index(drop=True),
    )
    modelled = daily.loc[daily.modelling_assumption_used]
    assert len(modelled) == 3
    assert modelled.iloc[0].date == ADANIENT_DATE
    assert modelled.iloc[0].modelling_assumption_id == ASSUMPTION_ID
    assert modelled.iloc[1].date == HGS_DATE
    assert modelled.iloc[1].return_status == COMBINED_STATUS
    assert modelled.iloc[2].date == EASE_DATE
    assert modelled.iloc[2].return_status == COMBINED_STATUS
    assert daily.date.max() <= CUTOFF
    assert daily.iloc[-1].valid_return
    assert daily.iloc[-1].date == CUTOFF

    ease_source = pd.read_parquet(
        RETURNS, columns=["date", "security_id", "previous_session_date", "previous_close", "close", "price_return"],
        filters=[[('date', '=', EASE_DATE), ('security_id', '=', EASE_SECURITY)]],
    ).iloc[0]
    assert ease_source.previous_session_date == pd.Timestamp("2022-11-18")
    assert np.isclose(ease_source.previous_close, 381.95)
    assert np.isclose(ease_source.close, 57.3)
    ease_return = 8 * ease_source.close / ease_source.previous_close - 1
    assert not np.isclose(ease_return, ease_source.price_return)
    ease_holdings = pd.read_parquet(
        OUTPUT / "primary_modelling_shadow_holdings.parquet",
        columns=["date", "security_id", "units"],
        filters=[[('date', '>=', pd.Timestamp("2022-11-18")), ('date', '<=', EASE_DATE),
                  ('security_id', '=', EASE_SECURITY)]],
    ).sort_values("date")
    assert len(ease_holdings) == 2
    assert np.isclose(ease_holdings.units.iloc[1], 8 * ease_holdings.units.iloc[0])

    risk = pd.read_parquet(OUTPUT / "volatility_overlay_development.parquet")
    assert risk.formation_date.max() <= CUTOFF
    has_source = risk.source_data_max_date.notna()
    assert risk.loc[has_source, "source_data_max_date"].le(
        risk.loc[has_source, "formation_date"]
    ).all()
    flagged = risk.loc[risk.modelling_assumption_in_window]
    assert flagged.formation_date.dt.strftime("%Y-%m-%d").tolist() == [
        "2018-04-30", "2018-05-31", "2018-06-29",
        "2018-07-31", "2018-08-31", "2018-09-28",
        "2022-02-28", "2022-03-31", "2022-04-29",
        "2022-05-31", "2022-06-30", "2022-07-29",
        "2022-11-30", "2022-12-30", "2023-01-31", "2023-02-28",
    ]
    assert risk.loc[flagged.index, "modelling_days_in_window"].eq(1).all()
    assert risk.loc[~risk.modelling_assumption_in_window, "modelling_days_in_window"].eq(0).all()
    assert risk.loc[risk.risk_status.eq("MODELLING_SHADOW_STOPPED"), "exposure"].eq(0).all()
    materiality = pd.read_csv(AUDIT / "modelled_corporate_action_days.csv")
    assert set(materiality.symbol) == {"ADANIENT", "HGS", "EASEMYTRIP"}
    assert len(materiality) == 3
    assert np.isclose(materiality.loc[materiality.symbol.eq("HGS"), "modelled_stock_return"].iloc[0],
                      (2 * 1310.1 + 28) / 2733.8 - 1)
    ease_materiality = materiality.loc[materiality.symbol.eq("EASEMYTRIP")].iloc[0]
    assert ease_materiality.share_multiplier == 8
    assert ease_materiality.cash_per_pre_event_share == 0
    assert np.isclose(ease_materiality.modelled_stock_return, ease_return)
    assert not np.isclose(ease_materiality.modelled_stock_return, ease_materiality.raw_price_return)
    all_materiality = pd.read_csv(AUDIT / "modelling_shadow_return_materiality.csv")
    blocker = all_materiality.loc[all_materiality.materiality_status.eq("SHADOW_DAILY_RETURN_BLOCKER")]
    assert blocker.empty
    checks = pd.read_csv(AUDIT / "exposure_sanity_checks.csv").set_index("measure")["value"]
    assert checks["max_value_date_read"] == "2023-03-31"
