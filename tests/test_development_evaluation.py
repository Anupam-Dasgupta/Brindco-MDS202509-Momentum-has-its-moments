import hashlib

import numpy as np
import pandas as pd
import pytest

from brindco_momentum.evaluation import development


def test_cagr_volatility_and_sharpe_use_declared_conventions():
    days = pd.Series(pd.to_datetime(["2015-04-01", "2015-04-06", "2015-04-07"]))
    wealth = pd.Series([110.0, 99.0, 108.9])
    result = development.performance(wealth, days, 100.0)
    returns = np.array([.10, -.10, .10])
    years = (development.CUTOFF.date() - development.START.date()).days / 365.2425
    assert result["total_return"] == pytest.approx(.089)
    assert result["cagr"] == pytest.approx(1.089 ** (1 / years) - 1)
    assert result["annualised_volatility"] == pytest.approx(returns.std(ddof=1) * np.sqrt(252))
    assert result["sharpe_0pct_cash"] == pytest.approx(
        returns.mean() / returns.std(ddof=1) * np.sqrt(252))


def test_drawdown_reports_peak_trough_recovery_and_unrecovered():
    days = pd.Series(pd.to_datetime(["2015-04-01", "2015-04-06", "2015-04-07", "2015-04-08"]))
    episodes = development.drawdown_episodes(pd.Series([120, 96, 80, 120]), days, 100)
    assert episodes == [{"peak_date": "2015-04-01", "trough_date": "2015-04-07",
                         "max_drawdown": pytest.approx(-1 / 3), "recovery_date": "2015-04-08"}]
    open_episode = development.drawdown_episodes(pd.Series([120, 96, 80]), days.iloc[:3], 100)
    assert open_episode[0]["recovery_date"] is None


def test_zero_variance_sharpe_is_undefined():
    days = pd.Series(pd.to_datetime(["2015-04-01", "2015-04-06"]))
    result = development.performance(pd.Series([100.0, 100.0]), days, 100.0)
    assert np.isnan(result["sharpe_0pct_cash"])
    assert result["max_drawdown"] == 0


@pytest.mark.parametrize("name", development.ACCOUNTS)
def test_saved_evaluation_aggregates_frozen_fills_tax_and_exposure(name):
    out = development.OUT
    if not (out / "summary_metrics.csv").exists():
        pytest.skip("Development evaluation has not been run")
    row = pd.read_csv(out / "summary_metrics.csv").set_index("strategy").loc[name]
    cost = pd.read_csv(out / "cost_arithmetic.csv").set_index("strategy").loc[name]
    daily = pd.read_csv(out / "daily_accounting_views.csv", parse_dates=["date"])
    daily = daily.loc[daily.strategy.eq(name)].reset_index(drop=True)
    folder = development.MOM_VM if name in {"MOM", "VM"} else development.CONTROLS / name
    fills = pd.read_parquet(folder / f"{name}_fills.parquet",
                            columns=["date", "consideration", "stt", "stamp", "exchange",
                                     "sebi_gst", "fees", "impact_rupees"],
                            filters=[("date", "<=", development.CUTOFF)])
    cash = pd.read_parquet(folder / f"{name}_cash_events.parquet",
                           columns=["date", "category", "amount"],
                           filters=[("date", "<=", development.CUTOFF)])
    assert len(daily) == 1982 and daily.date.min() == development.START
    assert daily.date.max() == development.CUTOFF
    assert row.end_nav == pytest.approx(daily.after_tax_nav.iloc[-1])
    assert row.total_transaction_costs == pytest.approx((fills.fees + fills.impact_rupees).sum())
    assert cost.total_fees == pytest.approx(fills.fees.sum())
    assert cost.total_stt == pytest.approx(fills.stt.sum())
    assert cost.total_stamp == pytest.approx(fills.stamp.sum())
    assert cost.total_exchange == pytest.approx(fills.exchange.sum())
    assert cost.total_sebi_gst == pytest.approx(fills.sebi_gst.sum())
    assert cost.total_impact == pytest.approx(fills.impact_rupees.sum())
    payments = -cash.loc[cash.category.eq("ANNUAL_TAX_PAYMENT"), "amount"].sum()
    assert row.total_capital_gains_tax_paid == pytest.approx(payments)
    assert row.average_realised_equity_exposure == pytest.approx(daily.realised_equity_exposure.mean())
    assert row.minimum_realised_equity_exposure == pytest.approx(daily.realised_equity_exposure.min())
    assert row.maximum_realised_equity_exposure == pytest.approx(daily.realised_equity_exposure.max())
    assert cost.gross_annual_edge_required_to_clear_costs_and_tax == pytest.approx(
        row.annualised_implementation_cost_drag + row.annualised_tax_drag)
    assert row.scheduled_monthly_rebalances == 96
    assert row.number_of_fills == len(fills)
    first_five = set(daily.date.iloc[:5].dt.date)
    fill_dates = pd.to_datetime(fills.date)
    prior = daily.after_tax_nav.shift(1, fill_value=row.start_nav)
    prior_by_day = dict(zip(daily.date.dt.date, prior))
    recurring = ~fill_dates.dt.date.isin(first_five)
    turnover = sum(fills.loc[recurring, "consideration"].to_numpy()
                   / fill_dates.loc[recurring].dt.date.map(prior_by_day).to_numpy())
    assert row.annualised_recurring_gross_turnover == pytest.approx(turnover * 252 / 1982)


def test_tax_payment_enters_matched_pre_tax_path_after_close():
    daily = pd.read_csv(development.OUT / "daily_accounting_views.csv", parse_dates=["date"])
    mom = daily.loc[daily.strategy.eq("MOM")].set_index("date")
    cash = pd.read_parquet(development.MOM_VM / "MOM_cash_events.parquet",
                           columns=["date", "category", "amount"],
                           filters=[("date", "<=", development.CUTOFF)])
    payments = cash.loc[cash.category.eq("ANNUAL_TAX_PAYMENT")]
    assert not payments.empty
    day = pd.Timestamp(payments.iloc[0].date)
    next_day = mom.index[mom.index.get_loc(day) + 1]
    assert mom.loc[day, "tax_paid_before_close"] == 0
    assert mom.loc[next_day, "tax_paid_before_close"] == pytest.approx(-payments.iloc[0].amount)
    assert np.allclose(mom.matched_before_tax_nav,
                       mom.after_tax_nav + mom.tax_liability + mom.tax_paid_before_close)
    assert np.allclose(mom.matched_cost_tax_reversed_nav,
                       mom.matched_before_tax_nav + mom.daily_fees_and_impact.cumsum())


def test_evaluation_has_no_post_cutoff_values_and_replays_identically(tmp_path, monkeypatch):
    real_read = pd.read_parquet
    read_count = 0
    frozen = [development.MOM_VM / "MOM_nav_daily.parquet",
              development.MOM_VM / "VM_nav_daily.parquet",
              development.CONTROLS / "FIX/FIX_nav_daily.parquet",
              development.CONTROLS / "FIXVOL/FIXVOL_nav_daily.parquet",
              development.CONTROLS / "FIX/control_definition.json",
              development.CONTROLS / "FIXVOL/control_definition.json"]
    frozen_hashes = {path: hashlib.sha256(path.read_bytes()).digest() for path in frozen}

    def guarded_read(path, *args, **kwargs):
        nonlocal read_count
        read_count += 1
        filters = kwargs.get("filters", [])
        assert any(col in {"date", "formation_date"} and op == "<=" and value == development.CUTOFF
                   for col, op, value in filters), path
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(development.pd, "read_parquet", guarded_read)
    first, second = tmp_path / "first", tmp_path / "second"
    development.evaluate(first)
    development.evaluate(second)
    assert read_count > 0
    files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    assert files == sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    for relative in files:
        assert hashlib.sha256((first / relative).read_bytes()).digest() == hashlib.sha256(
            (second / relative).read_bytes()).digest()
    assert frozen_hashes == {path: hashlib.sha256(path.read_bytes()).digest() for path in frozen}
    manifest = pd.read_csv(first / "input_manifest.csv")
    assert pd.to_datetime(manifest.maximum_value_date).max() <= development.CUTOFF
    assert len(list((first / "figures").glob("*.png"))) == 5
