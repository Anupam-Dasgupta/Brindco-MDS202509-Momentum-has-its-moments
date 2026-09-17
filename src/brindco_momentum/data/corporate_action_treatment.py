"""Build the audited treatment layer for the 149 accepted in-universe events.

This stage does not build returns or the research panel.  It records the economic
inputs that a later panel build may consume, together with explicit blockers.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


from brindco_momentum.paths import ROOT
DATA_CUTOFF = pd.Timestamp("2023-03-31")

SOURCE_ACTIONS = (
    ROOT
    / "data"
    / "processed"
    / "corporate_actions_official"
    / "nse_corporate_actions_classified_through_2023_03_31.parquet"
)
SOURCE_UNRESOLVED = (
    ROOT
    / "results"
    / "membership_rebuild_audit"
    / "corporate_action_unresolved_cases.csv"
)
DATED_IDENTITY = (
    ROOT
    / "data"
    / "processed"
    / "security_identity_official"
    / "dated_security_identity.parquet"
)
SERIES_CLASSIFICATION = (
    ROOT
    / "data"
    / "processed"
    / "security_identity_official"
    / "historical_series_classification.parquet"
)
MARKET_DATA = ROOT / "data" / "processed" / "nse_cm_2013_2026.parquet"

EVIDENCE_DIR = ROOT / "data" / "raw" / "corporate_action_evidence"
OUTPUT_DIR = ROOT / "data" / "processed" / "corporate_action_treatment"
AUDIT_DIR = ROOT / "results" / "corporate_action_treatment"

TREATED_ACTIONS = (
    OUTPUT_DIR / "nse_corporate_actions_treated_through_2023_03_31.parquet"
)
PARENT_EVENTS = OUTPUT_DIR / "in_universe_parent_events.parquet"
TREATMENTS = OUTPUT_DIR / "in_universe_event_treatments.parquet"
EVIDENCE_MANIFEST = OUTPUT_DIR / "corporate_action_evidence_manifest.csv"


EVENT_KEY_COLUMNS = [
    "symbol",
    "series",
    "ex_date",
    "purpose_normalized",
    "source_file",
]

REQUIRED_TREATMENT_COLUMNS = [
    "event_id",
    "treatment_status",
    "cash_per_pre_event_share",
    "share_multiplier",
    "entitlement_value_per_pre_event_share",
    "cash_unit_basis",
    "valuation_date",
    "valuation_method",
    "is_mandatory",
    "blocks_total_return",
    "evidence_source",
    "effective_date",
    "security_id",
    "parent_event_class",
    "treatment_notes",
]

ALLOWED_STATUSES = {
    "RESOLVED_DIVIDEND",
    "RESOLVED_COMBINED",
    "RESOLVED_NO_DIRECT_HOLDER_ADJUSTMENT",
    "RESOLVED_RIGHTS_ENTITLEMENT",
    "UNRESOLVED_INSUFFICIENT_TERMS",
    "UNRESOLVED_RIGHTS_TREATMENT",
    "UNRESOLVED_STRUCTURAL_EVENT",
}


DIVIDEND_OVERRIDES = {
    ("JSWENERGY", "2017-06-30"): (
        0.50,
        "MSEI_JSWENERGY_CA",
        "MSEI exchange record corrects the truncated NSE purpose to Re 0.50 per share.",
    ),
    ("SRF", "2017-08-16"): (
        6.00,
        "MSEI_SRF_CA",
        "MSEI exchange record states an interim dividend of Rs 6 per share.",
    ),
    ("COLPAL", "2019-04-05"): (
        7.00,
        "COLPAL_AR_2018_19",
        "The company annual report states that the March 2019 second interim dividend was Rs 7 per share.",
    ),
    ("VIPIND", "2022-03-08"): (
        2.50,
        "VIPIND_AR_2021_22",
        "The company annual report states that the March 2022 interim dividend was Rs 2.50 per share.",
    ),
    ("VEDL", "2022-03-09"): (
        13.00,
        "VEDL_OUTCOME_2022_04_28",
        "The NSE-filed results state that the 2 March 2022 third interim dividend was Rs 13 per share.",
    ),
}

RIGHTS_OVERRIDES = {
    ("SINTEX", "2016-08-08"): {
        "new_shares_per_old_share": 26 / 151,
        "subscription_price": 65.0,
        "evidence_id": "SINTEX_AR_2016_17",
        "notes": "Official report supplies the missing Rs 65 issue price; the same event also pays Rs 0.70 gross cash per old share.",
    },
    ("TATASTEEL", "2018-01-31"): {
        "new_shares_per_old_share": 6 / 25,
        "subscription_price": 545.0,
        "evidence_id": "TATASTEEL_LOF_2018",
        "notes": "The NSE rights-adjustment convention combines 4 fully paid shares at Rs 510 and 2 partly paid shares at Rs 615 into 6 rights at a weighted issue price of Rs 545.",
    },
}

RIGHTS_ENTITLEMENT_SYMBOLS = {
    ("ARVINDFASN", "2020-03-17"): "ARVINDF-RE",
    ("RELIANCE", "2020-05-13"): "RIL-RE",
    ("ABFRL", "2020-06-30"): "ABFRL-RE",
    ("SHRIRAMFIN", "2020-07-09"): "SRTRANS-RE",
    ("M&MFIN", "2020-07-22"): "M&MFIN-RE",
    ("UNOMINDA", "2020-08-14"): "MINDA-RE",
    ("EIHOTEL", "2020-09-22"): "EIH-RE",
    ("SHOPERSTOP", "2020-11-19"): "SHOPER-RE",
    ("BHARTIARTL", "2021-09-27"): "AIRTEL-RE",
    ("INDHOTEL", "2021-11-11"): "IHCL-RE",
    ("WOCKPHARMA", "2022-03-08"): "WOCKH-RE",
    ("SUZLON", "2022-10-03"): "SUZLON-RE",
    ("HATSUN", "2022-12-07"): "HATSUN-RE",
    ("CGCL", "2023-02-17"): "CGCL-RE",
}

EVIDENCE_RECORDS = [
    {
        "evidence_id": "MSEI_JSWENERGY_CA",
        "filename": "msei_jswenergy_corporate_actions.html",
        "source_url": "https://www.msei.in/corporates/corporate-securities-information/corporate-update/default?symbol=JSWENERGY&type=4&vmode=vm",
        "authority": "Metropolitan Stock Exchange of India",
        "document_type": "exchange_corporate_action_page",
        "publication_date": None,
        "document_date": None,
        "publication_date_status": "NOT_STATED_ON_DYNAMIC_EXCHANGE_PAGE",
        "effective_date": "2017-06-30",
        "relevant_terms": "AGM/final dividend Re 0.50 per ordinary share; ex-date 2017-06-30.",
        "review_status": "MANUALLY_REVIEWED",
    },
    {
        "evidence_id": "MSEI_SRF_CA",
        "filename": "msei_srf_corporate_actions.html",
        "source_url": "https://www.msei.in/corporates/corporate-securities-information/corporate-update/default?symbol=SRF&type=4&vmode=vm",
        "authority": "Metropolitan Stock Exchange of India",
        "document_type": "exchange_corporate_action_page",
        "publication_date": None,
        "document_date": None,
        "publication_date_status": "NOT_STATED_ON_DYNAMIC_EXCHANGE_PAGE",
        "effective_date": "2017-08-16",
        "relevant_terms": "Interim dividend Rs 6 per ordinary share; ex-date 2017-08-16.",
        "review_status": "MANUALLY_REVIEWED",
    },
    {
        "evidence_id": "COLPAL_AR_2018_19",
        "filename": "colpal_annual_report_2018_19.pdf",
        "source_url": "https://www.colgateinvestors.co.in/media/2296/colgate-ar-2018-19-full.pdf",
        "authority": "Colgate-Palmolive (India) Limited",
        "document_type": "company_annual_report",
        "publication_date": None,
        "document_date": "2019-05-27",
        "publication_date_status": "NOT_VERIFIED_FROM_PRESERVED_DOCUMENT",
        "effective_date": "2019-04-05",
        "relevant_terms": "Second interim dividend declared in March 2019: Rs 7 per ordinary share.",
        "review_status": "MANUALLY_REVIEWED",
    },
    {
        "evidence_id": "VIPIND_AR_2021_22",
        "filename": "vipind_annual_report_2021_22.pdf",
        "source_url": "https://vipindustries.co.in/storage/investor-presentations/December2022/Annual%20Report%20-%202021-22.pdf",
        "authority": "VIP Industries Limited",
        "document_type": "company_annual_report",
        "publication_date": "2022-07-09",
        "document_date": "2022-07-09",
        "publication_date_status": "STATED_EXCHANGE_SUBMISSION_DATE",
        "effective_date": "2022-03-08",
        "relevant_terms": "Interim dividend paid in March 2022: Rs 2.50 per ordinary share of face value Rs 2.",
        "review_status": "MANUALLY_REVIEWED",
    },
    {
        "evidence_id": "VEDL_OUTCOME_2022_04_28",
        "filename": "vedl_outcome_2022_04_28.pdf",
        "source_url": "https://nsearchives.nseindia.com/corporate/VEDL_28042022154310_OutcomeOfBM28April2022signed.pdf",
        "authority": "Vedanta Limited filing preserved by NSE",
        "document_type": "exchange_filing",
        "publication_date": "2022-04-28",
        "document_date": "2022-04-28",
        "publication_date_status": "STATED_EXCHANGE_FILING_DATE",
        "effective_date": "2022-03-09",
        "relevant_terms": "Third interim dividend approved 2 March 2022: Rs 13 per ordinary share.",
        "review_status": "MANUALLY_REVIEWED",
    },
    {
        "evidence_id": "GRINFRA_DIVIDEND_UPDATE_2022_11_10",
        "filename": "grinfra_dividend_update_2022_11_10.pdf",
        "source_url": "https://www.grinfra.com/wp-content/uploads/2022/11/38.-Update-on-dividend-10.11.2022.pdf",
        "authority": "G R Infraprojects Limited exchange filing",
        "document_type": "company_exchange_filing",
        "publication_date": "2022-11-10",
        "document_date": "2022-11-10",
        "publication_date_status": "STATED_EXCHANGE_FILING_DATE",
        "effective_date": "2022-11-17",
        "relevant_terms": "Board deferred the proposed interim dividend; no declared holder cash amount.",
        "review_status": "MANUALLY_REVIEWED",
    },
    {
        "evidence_id": "SINTEX_AR_2016_17",
        "filename": "sintex_annual_report_2016_17.pdf",
        "source_url": "https://sintex.in/wp-content/uploads/2025/05/Sintex-Annual-Report-2016-17.pdf",
        "authority": "Sintex Industries Limited",
        "document_type": "company_annual_report",
        "publication_date": None,
        "document_date": None,
        "publication_date_status": "NOT_VERIFIED_FROM_PRESERVED_DOCUMENT",
        "effective_date": "2016-08-08",
        "relevant_terms": "26 rights shares per 151 old shares at Rs 65 each, including Rs 64 premium.",
        "review_status": "MANUALLY_REVIEWED",
    },
    {
        "evidence_id": "TATASTEEL_LOF_2018",
        "filename": "tatasteel_letter_of_offer_2018.pdf",
        "source_url": "https://www.sebi.gov.in/sebi_data/attachdocs/jan-2018/1516794446987.pdf",
        "authority": "Tata Steel Limited letter of offer preserved by SEBI",
        "document_type": "rights_letter_of_offer",
        "publication_date": "2018-01-24",
        "document_date": "2018-01-22",
        "publication_date_status": "SEBI_ARCHIVE_TIMESTAMP",
        "effective_date": "2018-01-31",
        "relevant_terms": "4:25 fully paid rights at Rs 510 and 2:25 partly paid rights at Rs 615; simultaneous but unlinked.",
        "review_status": "MANUALLY_REVIEWED",
    },
    {
        "evidence_id": "ABFRL_RIGHTS_ISSUE_AD_2020",
        "filename": "abfrl_rights_issue_ad_2020.pdf",
        "source_url": "https://nsearchives.nseindia.com/corporate/ABFRL_15072020170741_SEIntimationIssueAd.pdf",
        "authority": "Aditya Birla Fashion and Retail Limited filing preserved by NSE",
        "document_type": "rights_issue_advertisement",
        "publication_date": "2020-07-15",
        "document_date": "2020-07-15",
        "publication_date_status": "STATED_EXCHANGE_FILING_DATE",
        "effective_date": "2020-06-30",
        "relevant_terms": "9:77 partly paid rights at a total issue price of Rs 110; transferable NSE rights entitlement.",
        "review_status": "MANUALLY_REVIEWED",
    },
    {
        "evidence_id": "BLUEDART_BONUS_DEBENTURE_TERMS",
        "filename": "bluedart_bonus_debenture_terms.html",
        "source_url": "https://www.bluedart.com/press202",
        "authority": "Blue Dart Express Limited",
        "document_type": "company_release",
        "publication_date": "2013-10-15",
        "document_date": "2013-10-15",
        "publication_date_status": "STATED_COMPANY_RELEASE_DATE",
        "effective_date": "2014-11-17",
        "relevant_terms": "7, 4 and 3 debentures of Rs 10 per equity share, with 36, 48 and 60 month maturities; ex-date fair value is not supplied.",
        "review_status": "TERMS_REVIEWED_VALUE_UNRESOLVED",
    },
    {
        "evidence_id": "NTPC_BONUS_DEBENTURE_TRANSCRIPT",
        "filename": "ntpc_bonus_debenture_transcript.pdf",
        "source_url": "https://ntpc.co.in/sites/default/files/inline-files/transcriptq42014-15.pdf",
        "authority": "NTPC Limited",
        "document_type": "company_results_transcript",
        "publication_date": None,
        "document_date": "2015-05-29",
        "publication_date_status": "NOT_VERIFIED_FROM_PRESERVED_DOCUMENT",
        "effective_date": "2015-03-20",
        "relevant_terms": "One Rs 12.50 debenture per equity share, 8.49% coupon, principal redeemed 20:40:40 after 8, 9 and 10 years; ex-date fair value is not supplied.",
        "review_status": "TERMS_REVIEWED_VALUE_UNRESOLVED",
    },
    {
        "evidence_id": "BRITANNIA_AR_2021_22_2019_EVENT",
        "filename": "britannia_annual_report_2021_22.pdf",
        "source_url": "https://nsearchives.nseindia.com/corporate/BRITANNIA_03062022000002_IntimationAnnualReport2022.pdf",
        "authority": "Britannia Industries Limited filing preserved by NSE",
        "document_type": "company_annual_report",
        "publication_date": "2022-06-03",
        "document_date": "2022-06-03",
        "publication_date_status": "STATED_EXCHANGE_FILING_DATE",
        "effective_date": "2019-08-22",
        "relevant_terms": "2019 debenture: 1:1, Rs 30 face, 8%, three years. Ex-date fair value is not supplied.",
        "review_status": "TERMS_REVIEWED_VALUE_UNRESOLVED",
    },
    {
        "evidence_id": "BRITANNIA_AR_2021_22_2021_EVENT",
        "filename": "britannia_annual_report_2021_22.pdf",
        "source_url": "https://nsearchives.nseindia.com/corporate/BRITANNIA_03062022000002_IntimationAnnualReport2022.pdf",
        "authority": "Britannia Industries Limited filing preserved by NSE",
        "document_type": "company_annual_report",
        "publication_date": "2022-06-03",
        "document_date": "2022-06-03",
        "publication_date_status": "STATED_EXCHANGE_FILING_DATE",
        "effective_date": "2021-05-25",
        "relevant_terms": "2021 debenture: 1:1, Rs 29 face, 5.5%. Ex-date fair value is not supplied.",
        "review_status": "TERMS_REVIEWED_VALUE_UNRESOLVED",
    },
    {
        "evidence_id": "BLUEDART_AR_2014_15",
        "filename": "bluedart_annual_report_2014_15.pdf",
        "source_url": "https://bluedart.com/documents/20182/380977/annualreport2014-15/4a52cf7b-5013-91fc-2e77-d500703d7449",
        "authority": "Blue Dart Express Limited",
        "document_type": "company_annual_report",
        "publication_date": None,
        "document_date": None,
        "publication_date_status": "NOT_VERIFIED_FROM_PRESERVED_DOCUMENT",
        "effective_date": "2014-11-17",
        "relevant_terms": "Post-ex-date report states 9.3%, 9.4% and 9.5% coupons, 2014-11-21 allotment and 2017/2018/2019 redemption dates; it does not establish when the coupons were fixed.",
        "review_status": "POST_EX_TERMS_ONLY_NOT_ADMISSIBLE_FOR_EX_DATE_VALUE",
    },
    {
        "evidence_id": "NSE_BLUEDART_LISTING_2014_11_26",
        "filename": "nse_bluedart_listing_2014_11_26.html",
        "source_url": "https://nsearchives.nseindia.com/content/press/26112014.htm",
        "authority": "National Stock Exchange of India",
        "document_type": "exchange_listing_press_release",
        "publication_date": "2014-11-26",
        "document_date": "2014-11-26",
        "publication_date_status": "STATED_EXCHANGE_RELEASE_DATE",
        "effective_date": "2014-11-17",
        "relevant_terms": "Post-ex-date listing notice identifies N1/N2/N3 ISINs and the 9.3%, 9.4% and 9.5% coupons.",
        "review_status": "POST_EX_TERMS_ONLY_NOT_ADMISSIBLE_FOR_EX_DATE_VALUE",
    },
    {
        "evidence_id": "BSE_NTPC_COUPON_ANNOUNCEMENT_2015_03_20",
        "filename": "bse_ntpc_coupon_announcement_2015_03_20.json",
        "source_url": "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=-1&subcategory=&strPrevDate=20150319&strscrip=532555&strSearch=P&strToDate=20150321&strType=C",
        "authority": "BSE Limited",
        "document_type": "official_exchange_announcement_api_response",
        "publication_date": "2015-03-20",
        "document_date": "2015-03-20",
        "publication_date_status": "STATED_EXCHANGE_ARCHIVE_TIMESTAMP",
        "publication_timestamp_ist": "2015-03-20T19:47:23+05:30",
        "effective_date": "2015-03-20",
        "relevant_terms": "BSE archive states that NTPC fixed the coupon at 8.49% payable annually and timestamps the announcement 19:47:23 on the equity ex-date, after market close.",
        "review_status": "POINT_IN_TIME_TERMS_FAIL_DISCLOSED_AFTER_EX_DATE_CLOSE",
    },
    {
        "evidence_id": "NTPC_PIB_RELEASE_2015_03_26",
        "filename": "ntpc_pib_release_2015_03_26.pdf",
        "source_url": "https://dea.gov.in/files/press_release_documents/NTPC_issue_Bonus_Debentures26032015.pdf",
        "authority": "Government of India Press Information Bureau",
        "document_type": "government_press_release",
        "publication_date": "2015-03-26",
        "document_date": "2015-03-26",
        "publication_date_status": "STATED_GOVERNMENT_RELEASE_DATE",
        "effective_date": "2015-03-20",
        "relevant_terms": "Post-ex-date release confirms one Rs 12.50 debenture, 8.49% annual fixed coupon, AAA ratings and staged redemption in years 8, 9 and 10.",
        "review_status": "POST_EX_TERMS_ONLY_NOT_ADMISSIBLE_FOR_EX_DATE_VALUE",
    },
    {
        "evidence_id": "NSE_NTPC_LISTING_2015_03_27",
        "filename": "nse_ntpc_listing_2015_03_27.html",
        "source_url": "https://nsearchives.nseindia.com/content/press/27032015.htm",
        "authority": "National Stock Exchange of India",
        "document_type": "exchange_listing_press_release",
        "publication_date": "2015-03-27",
        "document_date": "2015-03-27",
        "publication_date_status": "STATED_EXCHANGE_RELEASE_DATE",
        "effective_date": "2015-03-20",
        "relevant_terms": "Post-ex-date listing notice identifies the 8.49% NTPC bonus debenture and ISIN INE733E07JP6.",
        "review_status": "POST_EX_TERMS_ONLY_NOT_ADMISSIBLE_FOR_EX_DATE_VALUE",
    },
    {
        "evidence_id": "BRITANNIA_IM_2019",
        "filename": "britannia_information_memorandum_2019.pdf",
        "source_url": "https://nsearchives.nseindia.com/corporates/offerdocument/scheme/IM_BRITANNIA.pdf",
        "authority": "Britannia Industries Limited filing preserved by NSE",
        "document_type": "scheme_and_information_memorandum",
        "publication_date": None,
        "document_date": None,
        "publication_date_status": "NOT_VERIFIED_FROM_PRESERVED_DOCUMENT",
        "effective_date": "2019-08-22",
        "relevant_terms": "The scheme says the Board determines the coupon on the 2019-08-23 record date; the later term sheet states 8%, 2019-08-28 allotment and 2022-08-28 redemption.",
        "review_status": "POINT_IN_TIME_TERMS_FAIL_COUPON_SET_AFTER_EX_DATE",
    },
    {
        "evidence_id": "BRITANNIA_ALLOTMENT_2019_08_28",
        "filename": "britannia_allotment_2019_08_28.pdf",
        "source_url": "https://nsearchives.nseindia.com/corporate/BRITANNIA_28082019165059_OUTCOMEBONUSDEBENTURECOMMITTEEALLOTMENT_260.pdf",
        "authority": "Britannia Industries Limited filing preserved by NSE",
        "document_type": "exchange_allotment_filing",
        "publication_date": "2019-08-28",
        "document_date": "2019-08-28",
        "publication_date_status": "STATED_EXCHANGE_FILING_DATE",
        "effective_date": "2019-08-22",
        "relevant_terms": "Post-ex-date allotment filing confirms one Rs 30 debenture per share and an 8% coupon.",
        "review_status": "POST_EX_TERMS_ONLY_NOT_ADMISSIBLE_FOR_EX_DATE_VALUE",
    },
    {
        "evidence_id": "BRITANNIA_TERMS_2021_05_21",
        "filename": "britannia_terms_2021_05_21.pdf",
        "source_url": "https://archives.nseindia.com/corporate/BRITANNIA_21052021165600_Intimtion21052021.pdf",
        "authority": "Britannia Industries Limited filing preserved by NSE",
        "document_type": "exchange_terms_filing",
        "publication_date": "2021-05-21",
        "document_date": "2021-05-21",
        "publication_date_status": "STATED_EXCHANGE_FILING_DATE",
        "effective_date": "2021-05-25",
        "relevant_terms": "Pre-ex-date terms fix one Rs 29 debenture per share, annual payments and three-year tenor, but explicitly defer coupon setting until after scheme approval and before allotment.",
        "review_status": "POINT_IN_TIME_TERMS_FAIL_COUPON_SET_AFTER_EX_DATE",
    },
    {
        "evidence_id": "BRITANNIA_ALLOTMENT_2021_06_03",
        "filename": "britannia_allotment_2021_06_03.pdf",
        "source_url": "https://archives.nseindia.com/corporate/BRITANNIA_03062021131616_OUTCOMEOFBDC03062021.pdf",
        "authority": "Britannia Industries Limited filing preserved by NSE",
        "document_type": "exchange_allotment_filing",
        "publication_date": "2021-06-03",
        "document_date": "2021-06-03",
        "publication_date_status": "STATED_EXCHANGE_FILING_DATE",
        "effective_date": "2021-05-25",
        "relevant_terms": "Post-ex-date filing fixes the 5.5% coupon, 2021-06-03 allotment and 2024-06-03 redemption.",
        "review_status": "POST_EX_TERMS_ONLY_NOT_ADMISSIBLE_FOR_EX_DATE_VALUE",
    },
    {
        "evidence_id": "FIMMDA_VALUATION_CIRCULAR_2012",
        "filename": "fimmda_valuation_circular_march_2012.pdf",
        "source_url": "https://fimmda.org/uploads/general/Valuation-Circ-March2012.pdf",
        "authority": "Fixed Income Money Market and Derivatives Association of India",
        "document_type": "official_bond_valuation_methodology",
        "publication_date": "2012-03-01",
        "document_date": "2012-03-01",
        "publication_date_status": "STATED_CIRCULAR_DATE",
        "effective_date": "2012-03-01",
        "relevant_terms": "Corporate bonds use coupon-frequency base curves plus rating spreads; intermediate tenors may be interpolated; qualifying issuer traded spreads have a 15-day maximum lookback; staggered principal uses weighted-average maturity.",
        "review_status": "METHODOLOGY_REVIEWED",
    },
]


def read_dated_parquet(
    path: Path,
    date_column: str,
    columns: list[str],
    extra_filters: list[tuple[str, str, object]] | None = None,
) -> pd.DataFrame:
    """Read a dated Parquet source with the research cutoff at the scanner."""

    filters: list[tuple[str, str, object]] = [(date_column, "<=", DATA_CUTOFF)]
    if extra_filters:
        filters.extend(extra_filters)
    return pd.read_parquet(path, columns=columns, filters=filters)


def parse_compact_cash_amount(purpose: str) -> float | None:
    """Parse compact NSE amounts such as ``Rs.0125`` as 0.125, not 125."""

    match = re.search(r"(?i)\b(?:RS|RE)\.(0\d{2,})(?!\.)\b", str(purpose))
    if not match:
        return None
    return float("0." + match.group(1)[1:])


def event_is_ordinary_equity_bonus(purpose: str, series: str = "EQ") -> bool:
    text = str(purpose).upper()
    if series != "EQ" or "BONUS" not in text:
        return False
    excluded = ("PREFERENCE", "DEBENTURE", "WARRANT")
    return not any(token in text for token in excluded)


def research_total_return(
    previous_close: float,
    ex_date_close: float,
    cash_per_pre_event_share: float = 0.0,
    share_multiplier: float = 1.0,
    entitlement_value_per_pre_event_share: float = 0.0,
    blocks_total_return: bool = False,
) -> float:
    """Apply a reviewed passive-holder transformation to one pre-event share."""

    if blocks_total_return:
        return np.nan
    numerator = (
        share_multiplier * ex_date_close
        + cash_per_pre_event_share
        + entitlement_value_per_pre_event_share
    )
    return numerator / previous_close - 1.0


def classify_buyback(mechanism: str) -> dict[str, object]:
    """Return passive-holder treatment; optional participation never creates cash."""

    mechanism = mechanism.upper()
    if mechanism == "TENDER_OFFER":
        return {
            "treatment_status": "RESOLVED_NO_DIRECT_HOLDER_ADJUSTMENT",
            "cash_per_pre_event_share": 0.0,
            "share_multiplier": 1.0,
            "entitlement_value_per_pre_event_share": 0.0,
            "blocks_total_return": False,
            "assumption_code": "PASSIVE_HOLDER_DOES_NOT_TENDER",
        }
    if mechanism == "OPEN_MARKET":
        return {
            "treatment_status": "RESOLVED_NO_DIRECT_HOLDER_ADJUSTMENT",
            "cash_per_pre_event_share": 0.0,
            "share_multiplier": 1.0,
            "entitlement_value_per_pre_event_share": 0.0,
            "blocks_total_return": False,
            "assumption_code": "PASSIVE_HOLDER_TAKES_NO_ACTION",
        }
    return {
        "treatment_status": "UNRESOLVED_STRUCTURAL_EVENT",
        "cash_per_pre_event_share": np.nan,
        "share_multiplier": np.nan,
        "entitlement_value_per_pre_event_share": np.nan,
        "blocks_total_return": True,
        "assumption_code": "",
    }


def rights_entitlement_value(
    previous_close: float,
    new_shares_per_old_share: float,
    subscription_price: float,
    cash_per_pre_event_share: float = 0.0,
) -> float:
    """Value an entitlement with the documented NSE theoretical ex-rights model.

    Cash paid on the same ex-date is first removed from the cum-rights close.  The
    result is the entitlement value per old share; it is not a subscription, cash
    receipt, or use of a later RE-market price.
    """

    values = [
        previous_close,
        new_shares_per_old_share,
        subscription_price,
        cash_per_pre_event_share,
    ]
    if not all(np.isfinite(value) for value in values):
        return np.nan
    if previous_close <= 0 or new_shares_per_old_share <= 0:
        return np.nan
    theoretical = (
        new_shares_per_old_share
        / (1.0 + new_shares_per_old_share)
        * (previous_close - cash_per_pre_event_share - subscription_price)
    )
    return max(theoretical, 0.0)


def parse_rights_terms(row: pd.Series) -> dict[str, object]:
    key = (str(row["symbol"]), pd.Timestamp(row["ex_date"]).strftime("%Y-%m-%d"))
    if key in RIGHTS_OVERRIDES:
        return dict(RIGHTS_OVERRIDES[key])

    ratio_a = pd.to_numeric(row.get("ratio_a"), errors="coerce")
    ratio_b = pd.to_numeric(row.get("ratio_b"), errors="coerce")
    face_value = pd.to_numeric(row.get("face_value"), errors="coerce")
    premium = re.search(
        r"(?i)\bPREM(?:IUM)?(?:\s+OF)?\s+RS\.?\s*(\d+(?:\.\d+)?)",
        str(row.get("purpose", "")),
    )
    if not premium or not np.isfinite(ratio_a) or not np.isfinite(ratio_b):
        return {
            "new_shares_per_old_share": np.nan,
            "subscription_price": np.nan,
            "evidence_id": "",
            "notes": "Official rights ratio or subscription price is missing.",
        }
    if ratio_a <= 0 or ratio_b <= 0 or not np.isfinite(face_value):
        return {
            "new_shares_per_old_share": np.nan,
            "subscription_price": np.nan,
            "evidence_id": "",
            "notes": "Official rights terms are invalid.",
        }
    return {
        "new_shares_per_old_share": ratio_a / ratio_b,
        "subscription_price": face_value + float(premium.group(1)),
        "evidence_id": "",
        "notes": "Issue price is event face value plus the premium stated in the official NSE corporate-action record.",
    }


def add_event_ids(actions: pd.DataFrame) -> pd.DataFrame:
    actions = actions.copy()
    keys = actions[EVENT_KEY_COLUMNS].copy()
    for column in ["symbol", "series", "purpose_normalized", "source_file"]:
        keys[column] = keys[column].fillna("").astype(str).str.strip()
    keys["ex_date"] = pd.to_datetime(keys["ex_date"]).dt.strftime("%Y-%m-%d")
    occurrence = keys.groupby(EVENT_KEY_COLUMNS, dropna=False).cumcount()
    payload = keys.astype(str).agg("|".join, axis=1) + "|" + occurrence.astype(str)
    actions["event_id"] = payload.map(
        lambda value: "CA_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    )
    if actions["event_id"].isna().any() or actions["event_id"].duplicated().any():
        raise ValueError("Event IDs must be present and unique")
    return actions


def load_parent_events(actions: pd.DataFrame) -> pd.DataFrame:
    unresolved = pd.read_csv(SOURCE_UNRESOLVED)
    unresolved = unresolved[unresolved["is_nifty500_member_on_ex_date"]].copy()
    unresolved["ex_date"] = pd.to_datetime(unresolved["ex_date"])

    event_keys = actions[EVENT_KEY_COLUMNS + ["event_id"]]
    parents = unresolved.merge(
        event_keys,
        on=EVENT_KEY_COLUMNS,
        how="left",
        validate="one_to_one",
    )
    if len(parents) != 149:
        raise ValueError(f"Expected 149 accepted parent events, found {len(parents)}")
    if parents["event_id"].isna().any() or parents["event_id"].duplicated().any():
        raise ValueError("Accepted parent events did not map one-to-one to event IDs")
    parents["effective_date"] = parents["ex_date"]
    parents["parent_event_class"] = parents["primary_class"]
    return parents.sort_values(["ex_date", "symbol", "series"]).reset_index(drop=True)


def event_market_rows(parents: pd.DataFrame) -> pd.DataFrame:
    target = parents[parents["primary_class"].eq("RIGHTS")][
        ["event_id", "security_id", "ex_date"]
    ]
    identity = pd.read_parquet(DATED_IDENTITY)
    identity["first_seen"] = pd.to_datetime(identity["first_seen"])
    identity["last_seen"] = pd.to_datetime(identity["last_seen"])

    candidates = target.merge(identity, on="security_id", how="left")
    candidates = candidates[
        candidates["ex_date"].between(candidates["first_seen"], candidates["last_seen"])
    ]
    isins = candidates["isin"].dropna().unique().tolist()
    market = read_dated_parquet(
        MARKET_DATA,
        "date",
        ["date", "isin", "symbol", "series", "prev_close", "close"],
        [("isin", "in", isins)],
    )
    market["date"] = pd.to_datetime(market["date"])
    market = market[market["series"].isin(["EQ", "BE", "BZ"])]

    matched = candidates.merge(
        market,
        left_on=["ex_date", "isin"],
        right_on=["date", "isin"],
        how="left",
        suffixes=("_identity", "_market"),
    )
    matched["series_rank"] = matched["series"].map({"EQ": 0, "BE": 1, "BZ": 2}).fillna(9)
    matched = matched.sort_values(["event_id", "series_rank"]).drop_duplicates("event_id")
    matched = matched.rename(
        columns={
            "symbol_market": "market_symbol",
            "isin": "market_isin",
            "series": "market_series",
            "close": "ex_date_close",
        }
    )
    output = matched[
        [
            "event_id",
            "market_symbol",
            "market_isin",
            "market_series",
            "prev_close",
            "ex_date_close",
        ]
    ]
    if len(output) != len(target) or output["prev_close"].isna().any():
        missing = target[~target["event_id"].isin(output.loc[output["prev_close"].notna(), "event_id"])]
        raise ValueError(f"Missing ex-date market inputs for rights events: {missing.to_dict('records')}")
    return output


def rights_listing_rows(parents: pd.DataFrame) -> pd.DataFrame:
    history = pd.read_parquet(SERIES_CLASSIFICATION)
    history = history[history["classification"].eq("RIGHTS_ENTITLEMENT")]
    history = history.set_index("symbol")
    rows = []
    for row in parents[parents["primary_class"].eq("RIGHTS")].itertuples():
        key = (row.symbol, pd.Timestamp(row.ex_date).strftime("%Y-%m-%d"))
        re_symbol = RIGHTS_ENTITLEMENT_SYMBOLS.get(key, "")
        if re_symbol and re_symbol in history.index:
            observed = history.loc[re_symbol]
            if isinstance(observed, pd.DataFrame):
                observed = observed.iloc[0]
            rows.append(
                {
                    "event_id": row.event_id,
                    "rights_entitlement_symbol": re_symbol,
                    "rights_entitlement_observed": True,
                    "rights_entitlement_first_seen": observed["first_seen"],
                    "rights_entitlement_last_seen": observed["last_seen"],
                }
            )
        else:
            rows.append(
                {
                    "event_id": row.event_id,
                    "rights_entitlement_symbol": "",
                    "rights_entitlement_observed": False,
                    "rights_entitlement_first_seen": pd.NaT,
                    "rights_entitlement_last_seen": pd.NaT,
                }
            )
    return pd.DataFrame(rows)


def base_treatment(row: pd.Series) -> dict[str, object]:
    return {
        "event_id": row["event_id"],
        "treatment_status": "UNRESOLVED_INSUFFICIENT_TERMS",
        "cash_per_pre_event_share": np.nan,
        "share_multiplier": np.nan,
        "entitlement_value_per_pre_event_share": np.nan,
        "cash_unit_basis": "UNRESOLVED",
        "valuation_date": pd.NaT,
        "valuation_method": "UNRESOLVED",
        "is_mandatory": True,
        "blocks_total_return": True,
        "evidence_source": f"LOCAL_NSE_CA_API:{row['source_file']}",
        "effective_date": row["ex_date"],
        "security_id": row["security_id"],
        "parent_event_class": row["primary_class"],
        "treatment_notes": "Official evidence is insufficient for a numeric passive-holder treatment.",
        "event_mechanism": "UNRESOLVED",
        "assumption_code": "",
        "assumption_requires_approval": False,
        "no_direct_adjustment_component": False,
        "rights_new_shares_per_old_share": np.nan,
        "rights_subscription_price": np.nan,
        "previous_close": np.nan,
        "ex_date_close": np.nan,
        "market_symbol": "",
        "market_isin": "",
        "market_series": "",
    }


def direct_terms_treatment(row: pd.Series) -> dict[str, object]:
    treatment = base_treatment(row)
    split_factor = 1.0
    if bool(row["is_split"]):
        old_face = pd.to_numeric(row["old_face_value_parsed"], errors="coerce")
        new_face = pd.to_numeric(row["new_face_value_parsed"], errors="coerce")
        if not np.isfinite(old_face) or not np.isfinite(new_face) or new_face <= 0:
            return treatment
        split_factor = old_face / new_face

    bonus_factor = 1.0
    if bool(row["is_bonus"]):
        if not event_is_ordinary_equity_bonus(row["purpose"], row["series"]):
            treatment["treatment_status"] = "UNRESOLVED_STRUCTURAL_EVENT"
            return treatment
        ratio_a = pd.to_numeric(row["ratio_a"], errors="coerce")
        ratio_b = pd.to_numeric(row["ratio_b"], errors="coerce")
        if not np.isfinite(ratio_a) or not np.isfinite(ratio_b) or ratio_b <= 0:
            return treatment
        bonus_factor = 1.0 + ratio_a / ratio_b

    cash = 0.0
    if bool(row["is_dividend"]):
        cash = pd.to_numeric(row["dividend_amount"], errors="coerce")
        if not np.isfinite(cash):
            return treatment

    treatment.update(
        {
            "treatment_status": "RESOLVED_COMBINED",
            "cash_per_pre_event_share": float(cash),
            "share_multiplier": float(split_factor * bonus_factor),
            "entitlement_value_per_pre_event_share": 0.0,
            "cash_unit_basis": (
                "GROSS_DECLARED_CASH_PER_PRE_EVENT_SHARE"
                if cash
                else "NOT_APPLICABLE"
            ),
            "valuation_date": row["ex_date"],
            "valuation_method": "DIRECT_OFFICIAL_EVENT_TERMS",
            "blocks_total_return": False,
            "event_mechanism": "COMBINED_ORDINARY_EQUITY_EVENT",
            "treatment_notes": "All ordinary cash and resulting-share components are composed on the same ex-date.",
        }
    )
    return treatment


def dividend_treatment(row: pd.Series) -> dict[str, object]:
    treatment = base_treatment(row)
    key = (str(row["symbol"]), pd.Timestamp(row["ex_date"]).strftime("%Y-%m-%d"))

    if key == ("GRINFRA", "2022-11-17"):
        treatment.update(
            {
                "treatment_status": "RESOLVED_NO_DIRECT_HOLDER_ADJUSTMENT",
                "cash_per_pre_event_share": 0.0,
                "share_multiplier": 1.0,
                "entitlement_value_per_pre_event_share": 0.0,
                "cash_unit_basis": "NOT_APPLICABLE",
                "valuation_date": row["ex_date"],
                "valuation_method": "OFFICIAL_FILING_CONFIRMS_NO_DECLARATION",
                "blocks_total_return": False,
                "evidence_source": "GRINFRA_DIVIDEND_UPDATE_2022_11_10",
                "event_mechanism": "DIVIDEND_PROPOSAL_DEFERRED",
                "no_direct_adjustment_component": True,
                "treatment_notes": "The board deferred the proposal; no dividend was declared for this record-date entry.",
            }
        )
        return treatment

    cash = pd.to_numeric(row["dividend_amount"], errors="coerce")
    evidence = f"LOCAL_NSE_CA_API:{row['source_file']}"
    note = "Gross declared cash per ordinary share from the official NSE event record."
    if key in DIVIDEND_OVERRIDES:
        cash, evidence, note = DIVIDEND_OVERRIDES[key]
    if not np.isfinite(cash):
        return treatment

    status = "RESOLVED_DIVIDEND"
    mechanism = "ORDINARY_CASH_DIVIDEND"
    no_direct_component = False
    assumption_code = ""
    if bool(row["is_buyback"]):
        status = "RESOLVED_COMBINED"
        mechanism = "ORDINARY_DIVIDEND_PLUS_OPTIONAL_TENDER_BUYBACK"
        no_direct_component = True
        assumption_code = "PASSIVE_HOLDER_DOES_NOT_TENDER"
        note += " The optional tender buyback creates no direct holder adjustment under the recorded passive-holder non-participation assumption."

    treatment.update(
        {
            "treatment_status": status,
            "cash_per_pre_event_share": float(cash),
            "share_multiplier": 1.0,
            "entitlement_value_per_pre_event_share": 0.0,
            "cash_unit_basis": "GROSS_DECLARED_CASH_PER_PRE_EVENT_SHARE",
            "valuation_date": row["ex_date"],
            "valuation_method": "DIRECT_OFFICIAL_EVENT_TERMS",
            "blocks_total_return": False,
            "evidence_source": evidence,
            "event_mechanism": mechanism,
            "assumption_code": assumption_code,
            "no_direct_adjustment_component": no_direct_component,
            "treatment_notes": note,
        }
    )
    return treatment


def rights_treatment(row: pd.Series, market: pd.Series) -> dict[str, object]:
    treatment = base_treatment(row)
    terms = parse_rights_terms(row)
    cash = pd.to_numeric(row["dividend_amount"], errors="coerce")
    cash = float(cash) if np.isfinite(cash) else 0.0
    q = float(terms["new_shares_per_old_share"])
    subscription_price = float(terms["subscription_price"])
    value = rights_entitlement_value(
        float(market["prev_close"]), q, subscription_price, cash
    )
    if not np.isfinite(value):
        treatment["treatment_status"] = "UNRESOLVED_RIGHTS_TREATMENT"
        treatment["treatment_notes"] = str(terms["notes"])
        return treatment

    evidence_parts = [f"LOCAL_NSE_CA_API:{row['source_file']}"]
    if terms["evidence_id"]:
        evidence_parts.append(str(terms["evidence_id"]))
    if row["symbol"] == "ABFRL":
        evidence_parts.append("ABFRL_RIGHTS_ISSUE_AD_2020")

    combined = cash > 0
    treatment.update(
        {
            "treatment_status": (
                "RESOLVED_COMBINED" if combined else "RESOLVED_RIGHTS_ENTITLEMENT"
            ),
            "cash_per_pre_event_share": cash,
            "share_multiplier": 1.0,
            "entitlement_value_per_pre_event_share": value,
            "cash_unit_basis": (
                "GROSS_DECLARED_CASH_PER_PRE_EVENT_SHARE"
                if combined
                else "NOT_APPLICABLE"
            ),
            "valuation_date": row["ex_date"],
            "valuation_method": "THEORETICAL_EX_RIGHTS_VALUE_FROM_CUM_RIGHTS_PREVIOUS_CLOSE",
            "blocks_total_return": False,
            "evidence_source": ";".join(evidence_parts),
            "event_mechanism": (
                "ORDINARY_DIVIDEND_PLUS_RIGHTS_ENTITLEMENT"
                if combined
                else "RIGHTS_ENTITLEMENT"
            ),
            "assumption_code": "PASSIVE_HOLDER_DOES_NOT_SUBSCRIBE;ENTITLEMENT_VALUED_BY_NSE_TERP_METHOD",
            "assumption_requires_approval": False,
            "rights_new_shares_per_old_share": q,
            "rights_subscription_price": subscription_price,
            "previous_close": float(market["prev_close"]),
            "ex_date_close": float(market["ex_date_close"]),
            "market_symbol": market["market_symbol"],
            "market_isin": market["market_isin"],
            "market_series": market["market_series"],
            "treatment_notes": str(terms["notes"])
            + " The passive holder injects no subscription cash. The entitlement is credited at its ex-date theoretical value from terms known by then; no later RE price or immediate-sale proceeds are used.",
        }
    )
    return treatment


def buyback_treatment(row: pd.Series) -> dict[str, object]:
    treatment = base_treatment(row)
    if row["series"] != "EQ":
        treatment.update(
            {
                "treatment_status": "RESOLVED_NO_DIRECT_HOLDER_ADJUSTMENT",
                "cash_per_pre_event_share": 0.0,
                "share_multiplier": 1.0,
                "entitlement_value_per_pre_event_share": 0.0,
                "cash_unit_basis": "NOT_APPLICABLE",
                "valuation_date": row["ex_date"],
                "valuation_method": "SECURITY_SERIES_CLASSIFICATION",
                "is_mandatory": False,
                "blocks_total_return": False,
                "event_mechanism": "NON_EQUITY_SERIES_SAME_ISSUER_SYMBOL",
                "no_direct_adjustment_component": True,
                "treatment_notes": f"Series {row['series']} with face value Rs {row['face_value']:g} is not the issuer's ordinary EQ security; it creates no ordinary-equity holder adjustment.",
            }
        )
        return treatment

    # An NSE buyback corporate-action record with an eligibility record date is a
    # tender offer, rather than purchases in the open market.
    classified = classify_buyback("TENDER_OFFER")
    treatment.update(classified)
    treatment.update(
        {
            "cash_unit_basis": "NOT_APPLICABLE",
            "valuation_date": row["ex_date"],
            "valuation_method": "PASSIVE_HOLDER_NON_PARTICIPATION_POLICY",
            "is_mandatory": False,
            "event_mechanism": "OPTIONAL_TENDER_BUYBACK",
            "no_direct_adjustment_component": True,
            "treatment_notes": "Optional tender buyback: RESOLVED_NO_DIRECT_HOLDER_ADJUSTMENT only under the explicit passive-holder assumption that the holder does not tender.",
        }
    )
    return treatment


def structural_treatment(row: pd.Series) -> dict[str, object]:
    treatment = base_treatment(row)
    evidence = f"LOCAL_NSE_CA_API:{row['source_file']}"
    if row["symbol"] == "BLUEDART":
        evidence += (
            ";BLUEDART_BONUS_DEBENTURE_TERMS;BLUEDART_AR_2014_15;"
            "NSE_BLUEDART_LISTING_2014_11_26;FIMMDA_VALUATION_CIRCULAR_2012"
        )
        notes = (
            "The pre-ex-date issuer release fixes quantities, face value, annual "
            "frequency and tenor, but says the Board will determine the coupons. "
            "The preserved official sources that state 9.3%, 9.4% and 9.5% are "
            "post-ex-date and do not establish when those rates or the allotment "
            "date became legally fixed. Contractual cash flows therefore cannot be "
            "constructed point in time; no yield or value is selected."
        )
    elif row["symbol"] == "NTPC":
        evidence += (
            ";BSE_NTPC_COUPON_ANNOUNCEMENT_2015_03_20;"
            "NTPC_BONUS_DEBENTURE_TRANSCRIPT;NTPC_PIB_RELEASE_2015_03_26;"
            "NSE_NTPC_LISTING_2015_03_27;FIMMDA_VALUATION_CIRCULAR_2012"
        )
        notes = (
            "The official BSE archive timestamps public disclosure of the 8.49% "
            "coupon at 19:47:23 on 2015-03-20, after the equity market close used "
            "for the ex-date return. The coupon was therefore not a knowable input "
            "to that closing valuation. Contractual cash flows cannot be constructed "
            "point in time; no yield or value is selected."
        )
    elif row["symbol"] == "BRITANNIA":
        event_year = pd.Timestamp(row["ex_date"]).year
        if event_year == 2019:
            evidence += (
                ";BRITANNIA_IM_2019;BRITANNIA_ALLOTMENT_2019_08_28;"
                "BRITANNIA_AR_2021_22_2019_EVENT;FIMMDA_VALUATION_CIRCULAR_2012"
            )
            notes = (
                "The official scheme says the Board determines the coupon on the "
                "2019-08-23 record date, after the 2019-08-22 equity ex-date. The "
                "later 8% coupon and 2019-08-28 allotment date are hindsight inputs "
                "for this valuation date. Contractual cash flows therefore cannot be "
                "constructed point in time; no yield or value is selected."
            )
        else:
            evidence += (
                ";BRITANNIA_TERMS_2021_05_21;BRITANNIA_ALLOTMENT_2021_06_03;"
                "BRITANNIA_AR_2021_22_2021_EVENT;FIMMDA_VALUATION_CIRCULAR_2012"
            )
            notes = (
                "The 2021-05-21 official terms state that the Board will determine "
                "the coupon after scheme approval and before allotment. The 5.5% "
                "coupon and 2021-06-03 allotment date were fixed after the "
                "2021-05-25 equity ex-date. Contractual cash flows therefore cannot "
                "be constructed point in time; no yield or value is selected."
            )
    else:
        notes = (
            "The mandatory non-cash entitlement lacks point-in-time contractual "
            "terms or a convention-specified contemporaneous market yield."
        )
    treatment.update(
        {
            "treatment_status": "UNRESOLVED_STRUCTURAL_EVENT",
            "share_multiplier": 1.0,
            "cash_unit_basis": "NOT_APPLICABLE",
            "valuation_method": (
                "BLOCKED_POINT_IN_TIME_CONTRACTUAL_TERMS_INCOMPLETE"
            ),
            "event_mechanism": "MANDATORY_BONUS_DEBENTURE_ENTITLEMENT",
            "evidence_source": evidence,
            "treatment_notes": notes,
        }
    )
    return treatment


def build_treatments(parents: pd.DataFrame) -> pd.DataFrame:
    market = event_market_rows(parents).set_index("event_id")
    rows = []
    for _, row in parents.iterrows():
        event_class = row["primary_class"]
        if event_class in {"BONUS", "SPLIT"}:
            treatment = direct_terms_treatment(row)
        elif event_class == "DIVIDEND":
            treatment = dividend_treatment(row)
        elif event_class == "RIGHTS":
            treatment = rights_treatment(row, market.loc[row["event_id"]])
        elif event_class == "BUYBACK":
            treatment = buyback_treatment(row)
        elif event_class == "DEBENTURE_ENTITLEMENT":
            treatment = structural_treatment(row)
        else:
            treatment = base_treatment(row)
        rows.append(treatment)

    treatments = pd.DataFrame(rows)
    listings = rights_listing_rows(parents)
    treatments = treatments.merge(listings, on="event_id", how="left", validate="one_to_one")
    treatments["rights_entitlement_observed"] = (
        treatments["rights_entitlement_observed"].fillna(False).astype(bool)
    )
    treatments["treatment_row_id"] = treatments["event_id"] + "_T1"
    return treatments


def validate_treatments(parents: pd.DataFrame, treatments: pd.DataFrame) -> dict[str, object]:
    missing_columns = sorted(set(REQUIRED_TREATMENT_COLUMNS) - set(treatments.columns))
    if missing_columns:
        raise ValueError(f"Missing required treatment columns: {missing_columns}")
    if parents["event_id"].isna().any() or treatments["event_id"].isna().any():
        raise ValueError("No parent or treatment may have a missing event_id")
    if parents["event_id"].duplicated().any():
        raise ValueError("Parent event_id is duplicated")
    if treatments["event_id"].duplicated().any():
        raise ValueError("Treatment event_id is duplicated")

    parent_ids = set(parents["event_id"])
    treatment_ids = set(treatments["event_id"])
    orphan_ids = treatment_ids - parent_ids
    missing_ids = parent_ids - treatment_ids
    if orphan_ids:
        raise ValueError(f"Treatment rows without a valid parent: {sorted(orphan_ids)}")
    if missing_ids:
        raise ValueError(f"Parent events without treatment: {sorted(missing_ids)}")
    if not set(treatments["treatment_status"]).issubset(ALLOWED_STATUSES):
        invalid = sorted(set(treatments["treatment_status"]) - ALLOWED_STATUSES)
        raise ValueError(f"Invalid treatment statuses: {invalid}")

    counts = treatments.groupby("event_id").size()
    exactly_one = int(counts.eq(1).sum())
    blockers = int(treatments["blocks_total_return"].sum())
    gate_passes = exactly_one == 149 and blockers == 0
    return {
        "distinct_parent_event_ids_with_exactly_one_treatment": exactly_one,
        "blocking_event_count": blockers,
        "duplicated_parent_event_id_count": int(parents["event_id"].duplicated().sum()),
        "duplicated_treatment_event_id_count": int(treatments["event_id"].duplicated().sum()),
        "missing_event_id_count": int(
            parents["event_id"].isna().sum() + treatments["event_id"].isna().sum()
        ),
        "orphan_treatment_count": len(orphan_ids),
        "corporate_action_gate_passes": gate_passes,
    }


def evidence_manifest() -> pd.DataFrame:
    rows = []
    for record in EVIDENCE_RECORDS:
        path = EVIDENCE_DIR / record["filename"]
        if not path.is_file():
            raise FileNotFoundError(f"Missing preserved evidence: {path}")
        content = path.read_bytes()
        rows.append(
            {
                **record,
                "local_file": path.relative_to(ROOT).as_posix(),
                "retrieved_at_utc": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
                "parsing_status": "MANUAL_REVIEW_COMPLETE",
            }
        )
    manifest = pd.DataFrame(rows)
    manifest["publication_date"] = pd.to_datetime(manifest["publication_date"])
    manifest["document_date"] = pd.to_datetime(manifest["document_date"])
    manifest["effective_date"] = pd.to_datetime(manifest["effective_date"])
    return manifest


def repaired_actions(actions: pd.DataFrame, treatments: pd.DataFrame) -> pd.DataFrame:
    repaired = actions.copy()
    treatment_columns = [
        column
        for column in treatments.columns
        if column not in {"security_id", "effective_date", "parent_event_class"}
    ]
    repaired = repaired.merge(
        treatments[treatment_columns], on="event_id", how="left", validate="one_to_one"
    )
    repaired["treatment_reviewed_for_in_universe_event"] = repaired[
        "treatment_row_id"
    ].notna()

    for (symbol, date_text), (amount, evidence, reason) in DIVIDEND_OVERRIDES.items():
        treatment_ids = treatments.loc[
            treatments["evidence_source"].eq(evidence), "event_id"
        ]
        if len(treatment_ids) != 1:
            raise ValueError(
                f"Dividend evidence did not identify exactly one treatment: "
                f"{symbol} {date_text}"
            )
        mask = repaired["event_id"].eq(treatment_ids.iloc[0])
        if mask.sum() != 1:
            raise ValueError(
                f"Dividend event_id did not identify exactly one action: "
                f"{symbol} {date_text}"
            )
        repaired.loc[mask, "dividend_amount"] = amount
        repaired.loc[mask, "repair_status"] = "CA_TREATMENT_OVERRIDE"
        repaired.loc[mask, "repair_reason"] = reason + f" Evidence: {evidence}."

    grinfra = repaired["event_id"].eq(
        treatments.loc[
            treatments["event_mechanism"].eq("DIVIDEND_PROPOSAL_DEFERRED"), "event_id"
        ].iloc[0]
    )
    repaired.loc[grinfra, "repair_status"] = "CA_TREATMENT_OVERRIDE"
    repaired.loc[
        grinfra, "repair_reason"
    ] = "Official company filing confirms that the proposed interim dividend was deferred and no cash was declared."

    resolved = repaired["treatment_reviewed_for_in_universe_event"] & ~repaired[
        "blocks_total_return"
    ].fillna(False)
    repaired.loc[resolved, "needs_manual_review"] = False
    unresolved = repaired["treatment_reviewed_for_in_universe_event"] & repaired[
        "blocks_total_return"
    ].fillna(False)
    repaired.loc[unresolved, "needs_manual_review"] = True
    return repaired


def write_audits(
    parents: pd.DataFrame,
    treatments: pd.DataFrame,
    manifest: pd.DataFrame,
    gate: dict[str, object],
) -> None:
    detail = parents.merge(treatments, on="event_id", how="left", validate="one_to_one")
    numeric = treatments["treatment_status"].isin(
        {
            "RESOLVED_DIVIDEND",
            "RESOLVED_COMBINED",
            "RESOLVED_RIGHTS_ENTITLEMENT",
        }
    )
    no_direct = treatments["treatment_status"].eq(
        "RESOLVED_NO_DIRECT_HOLDER_ADJUSTMENT"
    )
    unresolved = treatments["treatment_status"].str.startswith("UNRESOLVED")

    summary_rows = [
        ("starting_in_universe_treatment_dependent_events", len(parents)),
        ("resolved_numeric_events", int(numeric.sum())),
        ("resolved_no_direct_holder_adjustment_events", int(no_direct.sum())),
        ("remaining_genuinely_unresolved_events", int(unresolved.sum())),
        ("events_blocking_total_return", int(treatments["blocks_total_return"].sum())),
    ]
    summary_rows.extend(gate.items())
    for event_class, count in parents["primary_class"].value_counts().sort_index().items():
        summary_rows.append((f"parent_class_{event_class}", int(count)))
    for status, count in treatments["treatment_status"].value_counts().sort_index().items():
        summary_rows.append((f"treatment_status_{status}", int(count)))
    pd.DataFrame(summary_rows, columns=["metric", "value"]).to_csv(
        AUDIT_DIR / "corporate_action_treatment_summary.csv", index=False
    )

    detail.to_csv(AUDIT_DIR / "corporate_action_treatment_detail.csv", index=False)
    detail[detail["treatment_status"].str.startswith("UNRESOLVED")].to_csv(
        AUDIT_DIR / "unresolved_corporate_actions_in_universe.csv", index=False
    )
    detail[detail["no_direct_adjustment_component"]].to_csv(
        AUDIT_DIR / "no_direct_adjustment_events.csv", index=False
    )
    detail[detail["is_rights"]].to_csv(
        AUDIT_DIR / "rights_treatment_audit.csv", index=False
    )
    detail[detail["is_buyback"]].to_csv(
        AUDIT_DIR / "buyback_treatment_audit.csv", index=False
    )
    detail[
        detail["multiple_event_types"]
        | detail["treatment_status"].eq("RESOLVED_COMBINED")
    ].to_csv(AUDIT_DIR / "combined_event_audit.csv", index=False)

    unresolved_detail = detail[detail["blocks_total_return"]]
    unresolved_lines = "\n".join(
        f"- `{row.event_id}` — {row.symbol}, {pd.Timestamp(row.ex_date).date()}: {row.treatment_notes}"
        for row in unresolved_detail.itertuples()
    )
    evidence_lines = "\n".join(
        f"- `{row.evidence_id}` — {row.authority}; `{row.local_file}`; SHA-256 `{row.sha256}`."
        for row in manifest.itertuples()
    )
    status_lines = "\n".join(
        f"- `{status}`: {count}"
        for status, count in treatments["treatment_status"].value_counts().sort_index().items()
    )

    audit = f"""# Corporate-action treatment audit

## Scope and result

This stage starts from the 149 treatment-dependent events that occurred while the accepted security was an official NIFTY 500 member. It does not alter membership or identity, rebuild the research panel, calculate momentum, construct portfolios, or inspect performance.

- Starting parent events: **{len(parents)}**
- Numerically resolved events: **{int(numeric.sum())}**
- Events resolved with no direct passive-holder adjustment: **{int(no_direct.sum())}**
- Genuinely unresolved events: **{int(unresolved.sum())}**
- Events that block a complete daily total-return series: **{int(treatments['blocks_total_return'].sum())}**
- Corporate-action gate: **{'PASS' if gate['corporate_action_gate_passes'] else 'FAIL'}**

## Literal gate

```sql
corporate_action_gate_passes =
    count(distinct event_id with exactly one parent treatment) == 149
    AND count(event_id where blocks_total_return == true) == 0
```

- Distinct parent event IDs with exactly one treatment: **{gate['distinct_parent_event_ids_with_exactly_one_treatment']}**
- Blocking event IDs: **{gate['blocking_event_count']}**
- Duplicated parent event IDs: **{gate['duplicated_parent_event_id_count']}**
- Duplicated treatment event IDs: **{gate['duplicated_treatment_event_id_count']}**
- Missing event IDs: **{gate['missing_event_id_count']}**
- Treatment rows without a valid parent event ID: **{gate['orphan_treatment_count']}**

The one-treatment integrity condition passes. The overall gate fails because four mandatory bonus-debenture entitlements lack a defensible contemporaneous ex-date fair value.

## Treatment counts

{status_lines}

Parent classes are: buyback 86, rights 39, bonus/multi-event bonus 8, dividend/combined 7, split/multi-event split 5, and debenture entitlement 4.

## Economic conventions

- Ordinary dividend cash is the gross declared cash per pre-event ordinary share. Investor-level dividend tax, STCG and LTCG are deferred to the later account ledger.
- A split multiplier is old face value divided by new face value. An ordinary bonus multiplier is `1 + new/old`. Same-date ordinary components are multiplied and cash remains on its documented pre-event-share basis.
- Optional tender buyback: `RESOLVED_NO_DIRECT_HOLDER_ADJUSTMENT` only under the explicit passive-holder assumption that the holder does not tender. Every ordinary-equity buyback parent has an NSE eligibility record date, so it is classified as a tender offer. Three IDFCFIRSTB records are HA/H9/HB debt series under the same issuer symbol and do not affect an ordinary EQ holder.
- Rights use `q / (1 + q) * max(P_previous - D - K, 0)`, where `q` is new shares per old share, `K` is the subscription price, and `D` is simultaneous gross cash per old share. The passive holder does not subscribe. The entitlement is credited as property received at a theoretical ex-rights value from terms and the cum-rights previous close known by the ex-date. No later RE price or immediate-sale proceeds are used.
- The 14 observed NSE rights-entitlement securities are recorded only as corroboration. Their later prices are not used to value an earlier ex-date.
- Bonus debentures are mandatory property distributions. Nominal value is not assumed to be fair value, and a later first-listed price is not backfilled onto the ex-date.

## Manual evidence-backed corrections

- JSWENERGY 2017-06-30: Re 0.50 final dividend.
- SRF 2017-08-16: Rs 6 interim dividend.
- COLPAL 2019-04-05: Rs 7 interim dividend.
- VIPIND 2022-03-08: Rs 2.50 interim dividend.
- VEDL 2022-03-09: Rs 13 interim dividend.
- GRINFRA 2022-11-17: proposed dividend was deferred; no holder cash.
- SINTEX 2016-08-08: rights issue price Rs 65; simultaneous dividend remains Rs 0.70.
- TATASTEEL 2018-01-31: combined 6:25 entitlement at an NSE weighted issue price of Rs 545.

The accepted upstream fixes for GENESYS, JKTYRE, SBI, ZEEL and the bonus-debenture classifications are retained.

## Remaining blockers

{unresolved_lines}

These four cases prevent creation of a complete audited daily total-return series. Resolving them requires an approved contemporaneous valuation convention or additional same-date fair-value evidence. Treating par as fair value or using a later listing price would be an unsupported assumption.

## New official evidence

{evidence_lines}

The manifest distinguishes a publication/filing date from a date printed inside a document. A publication date is left null when it cannot be verified from the preserved official source; this applies to the dynamic MSEI pages and three annual-report/transcript files. Every downloaded file records its URL, retrieval timestamp, original bytes, byte count, SHA-256, relevant terms, effective date and review status.

## Output contract

`data/processed/corporate_action_treatment/in_universe_event_treatments.parquet` contains exactly one treatment per accepted parent and includes the fixed required schema. `nse_corporate_actions_treated_through_2023_03_31.parquet` is a new versioned artifact; the accepted upstream corporate-action file is unchanged. No post-2023-03-31 price or return observation is read.
"""
    (ROOT / "docs/audits/CORPORATE_ACTION_TREATMENT_AUDIT.md").write_text(
        audit, encoding="utf-8"
    )


def validate_accepted_repairs(actions: pd.DataFrame) -> None:
    genesys = actions[
        actions["symbol"].eq("GENESYS")
        & actions["purpose"].str.contains(r"Rs\.0125", case=False, na=False)
    ]
    if len(genesys) != 1 or genesys.iloc[0]["dividend_amount"] != 0.125:
        raise ValueError("Accepted GENESYS compact-decimal repair is missing")
    if parse_compact_cash_amount(genesys.iloc[0]["purpose"]) != 0.125:
        raise ValueError("Compact-decimal parser no longer reproduces GENESYS 0.125")
    if actions["ex_date"].max() > DATA_CUTOFF:
        raise ValueError("Corporate-action input contains post-cutoff rows")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    print("Reading accepted cutoff-safe corporate actions...")
    actions = pd.read_parquet(
        SOURCE_ACTIONS,
        filters=[("ex_date", "<=", DATA_CUTOFF)],
    )
    actions["ex_date"] = pd.to_datetime(actions["ex_date"])
    validate_accepted_repairs(actions)
    actions = add_event_ids(actions)

    print("Building the 149 parent events and treatments...")
    parents = load_parent_events(actions)
    treatments = build_treatments(parents)
    gate = validate_treatments(parents, treatments)
    manifest = evidence_manifest()
    treated = repaired_actions(actions, treatments)

    parents.to_parquet(PARENT_EVENTS, index=False)
    treatments.to_parquet(TREATMENTS, index=False)
    manifest.to_csv(EVIDENCE_MANIFEST, index=False)
    treated.to_parquet(TREATED_ACTIONS, index=False)
    write_audits(parents, treatments, manifest, gate)

    print(f"Parent events: {len(parents)}")
    print(f"Treatments: {len(treatments)}")
    print(f"Blocking events: {gate['blocking_event_count']}")
    print(
        "Corporate-action gate: "
        + ("PASS" if gate["corporate_action_gate_passes"] else "FAIL")
    )


if __name__ == "__main__":
    main()
