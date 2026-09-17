from datetime import date

import pandas as pd

from brindco_momentum.execution.development_accounts import run_account


def _run(tmp_path, exit_adv):
    days = [date(2020, 1, d) for d in (2, 3, 6, 7, 8)]
    rows = []
    for day in days:
        rows.append({"date": pd.Timestamp(day), "security_id": "TEST_SECURITY",
                     "symbol": "TEST", "series": "EQ", "open": 100.0,
                     "high": 101.0, "low": 99.0, "close": 100.0,
                     "volume": 1_000_000, "adv20_lagged":
                     exit_adv if day >= date(2020, 1, 6) else 1_000_000_000.0,
                     "market_observed": True, "market_data_status": "OK"})
    panel = pd.DataFrame(rows)
    event = {"event_id": "UNSUPPORTED_EVENT", "security_id": "TEST_SECURITY",
             "primary_class": "STRUCTURAL", "application_status": "RETURN_UNAVAILABLE_EXPLICIT"}
    notice = {"event_id": "UNSUPPORTED_EVENT", "security_id": "TEST_SECURITY",
              "announcement_date": date(2020, 1, 3),
              "effective_date": date(2020, 1, 8),
              "evidence_source": "https://example.org/official-notice"}
    common = {"events": {date(2020, 1, 8): [event]},
              "settling": [date(2020, 1, d) for d in (3, 6, 7, 8, 9, 10, 13)],
              "rights": {}, "operational_notices": [notice],
              "manifest_hash": "synthetic-test"}
    winners = {"2020-01": ["TEST_SECURITY"]}
    result = run_account("MOM", winners, days, {"2020-01": 1.0}, panel,
                         common, tmp_path, "SYNTHETIC_OPERATIONAL_EXIT")
    return result, pd.read_parquet(tmp_path / "MOM_orders.parquet"), winners


def test_public_notice_blocks_buys_and_exits_without_changing_winners(tmp_path):
    result, orders, winners = _run(tmp_path, 1_000_000_000.0)
    assert result["blocker"] is None
    assert result["last_valid_date"] == date(2020, 1, 8)
    assert winners == {"2020-01": ["TEST_SECURITY"]}
    exit_orders = orders.loc[orders.status.eq("MANDATORY_EXIT_FILLED")]
    assert len(exit_orders) == 1
    assert exit_orders.date.iloc[0] == date(2020, 1, 6)
    assert exit_orders.filled_shares.iloc[0] > 0
    assert orders.status.eq("ANNOUNCED_EVENT_BUY_BLOCKED").any()


def test_insufficient_exit_liquidity_stops_with_residual(tmp_path):
    result, orders, _ = _run(tmp_path, 1_000_000.0)
    assert result["blocker"]["reason"] == "ANNOUNCED_EVENT_RESIDUAL_POSITION"
    assert result["blocker"]["date"] == date(2020, 1, 8)
    assert result["blocker"]["held_quantity"] > 0
    assert result["last_valid_date"] == date(2020, 1, 7)
    assert orders.status.eq("MANDATORY_EXIT_PARTIAL").any()
