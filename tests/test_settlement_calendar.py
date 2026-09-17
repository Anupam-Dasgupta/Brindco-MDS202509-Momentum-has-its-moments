from datetime import date

import pandas as pd

from brindco_momentum.execution.account_engine import settlement_after
from brindco_momentum.data.settlement_calendar import AMENDMENTS, CUTOFF, EVIDENCE, NOTICE_IDS, build_calendar, sha256


def test_official_calendar_coverage_and_provenance():
    calendar = build_calendar()
    assert len(calendar) == 2922
    assert calendar.date.min() == pd.Timestamp("2015-04-01")
    assert calendar.date.max() == CUTOFF
    assert calendar.date.is_unique
    assert calendar.source_notice.notna().all()
    assert all((EVIDENCE / f"{notice}.pdf").exists() and
               len(sha256(EVIDENCE / f"{notice}.pdf")) == 64
               for notice in [*NOTICE_IDS.values(), *(row[0] for row in AMENDMENTS.values())])


def test_settlement_specific_holidays_and_amendments_extend_t_plus_two():
    calendar = build_calendar()
    dates = list(calendar.loc[calendar.settlement_business_day, "date"].dt.date)
    # Bank/RBI closures can occur on ordinary equity trading sessions.
    assert settlement_after(date(2015, 6, 29), dates) == date(2015, 7, 2)
    assert settlement_after(date(2017, 2, 17), dates) == date(2017, 2, 22)
    assert settlement_after(date(2018, 3, 28), dates) == date(2018, 4, 4)
    assert calendar.set_index("date").loc[pd.Timestamp("2017-02-21"), "source_notice"] == "CMPT34182"
    assert calendar.set_index("date").loc[pd.Timestamp("2018-04-02"), "source_notice"] == "CMPT37310"
