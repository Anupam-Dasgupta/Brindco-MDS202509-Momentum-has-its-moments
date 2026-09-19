"""Runtime guard for unresolved corporate actions affecting held securities."""

from __future__ import annotations

import pandas as pd


def held_hard_stops_with_lineage(
    hard_stops: pd.DataFrame,
    dated_identity: pd.DataFrame,
    held_security_ids: set[str],
    day: object,
) -> pd.DataFrame:
    event_date = pd.Timestamp(day)
    aliases = dated_identity[
        dated_identity["security_id"].isin(held_security_ids)
        & pd.to_datetime(dated_identity["first_seen"]).le(event_date)
    ]
    symbols = set(aliases["symbol"].dropna().astype(str).str.upper().str.strip())
    isins = set(aliases["isin"].dropna().astype(str).str.upper().str.strip())
    on_date = hard_stops[pd.to_datetime(hard_stops["ex_date"]).eq(event_date)]
    known = on_date["security_id"].notna()
    hit = known & on_date["security_id"].astype(str).isin(held_security_ids)
    hit |= ~known & on_date["symbol"].astype(str).str.upper().str.strip().isin(symbols)
    if "nse_isin" in on_date.columns:
        hit |= (~known
                & on_date["nse_isin"].astype(str).str.upper().str.strip().isin(isins))
    return on_date.loc[hit].drop_duplicates("event_id").copy()
