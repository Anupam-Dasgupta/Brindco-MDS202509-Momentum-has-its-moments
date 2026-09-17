from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# PATHS
# ============================================================

INPUT = Path(
    "data/processed/nse_corporate_actions_2013_2026.parquet"
)

OUTPUT_DIR = Path(
    "data/processed/corporate_actions"
)

OUTPUT = (
    OUTPUT_DIR /
    "nse_corporate_actions_classified.parquet"
)


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_purpose(x) -> str:

    if pd.isna(x):
        return ""

    x = str(x).upper().strip()

    # Normalize whitespace.
    x = re.sub(
        r"\s+",
        " ",
        x,
    )

    return x


# ============================================================
# EVENT FLAGS
# ============================================================

def contains_any(
    text: str,
    patterns,
) -> bool:

    return any(
        re.search(
            pattern,
            text,
            flags=re.I,
        )
        for pattern in patterns
    )


def classify_flags(
    text: str,
):

    # --------------------------------------------------------
    # DIVIDEND
    # --------------------------------------------------------

    is_dividend = contains_any(
        text,
        [
            r"\bDIVIDEND\b",
            r"\bINTERIM DIVIDEND\b",
            r"\bFINAL DIVIDEND\b",
            r"\bSPECIAL DIVIDEND\b",
        ],
    )

    # --------------------------------------------------------
    # BONUS
    # --------------------------------------------------------

    is_bonus = contains_any(
        text,
        [
            r"\bBONUS\b",
            r"\bBONUS ISSUE\b",
            r"\bBONUS SHARES?\b",
        ],
    )

    # --------------------------------------------------------
    # SPLIT / SUB-DIVISION
    # --------------------------------------------------------

    is_split = contains_any(
        text,
        [
            r"\bSPLIT\b",
            r"\bSUB[- ]?DIVISION\b",
            r"\bSUBDIVISION\b",
            r"\bFACE VALUE SPLIT\b",
        ],
    )

    # --------------------------------------------------------
    # CONSOLIDATION / REVERSE SPLIT
    # --------------------------------------------------------

    is_consolidation = contains_any(
        text,
        [
            r"\bCONSOLIDATION\b",
            r"\bREVERSE SPLIT\b",
        ],
    )

    # --------------------------------------------------------
    # RIGHTS
    # --------------------------------------------------------

    is_rights = contains_any(
        text,
        [
            r"\bRIGHTS?\b",
            r"\bRIGHT ISSUE\b",
            r"\bRIGHTS ISSUE\b",
        ],
    )

    # --------------------------------------------------------
    # STRUCTURAL CORPORATE EVENTS
    # --------------------------------------------------------

    is_structural = contains_any(
        text,
        [
            r"\bMERGER\b",
            r"\bAMALGAMATION\b",
            r"\bDEMERGER\b",
            r"\bDE-MERGER\b",
            r"\bSCHEME OF ARRANGEMENT\b",
            r"\bSCHEME OF AMALGAMATION\b",
            r"\bRESTRUCTURING\b",
            r"\bSLUMP SALE\b",
        ],
    )

    # --------------------------------------------------------
    # BUYBACK
    # --------------------------------------------------------

    is_buyback = contains_any(
        text,
        [
            r"\bBUYBACK\b",
            r"\bBUY-BACK\b",
        ],
    )

    # --------------------------------------------------------
    # CAPITAL REDUCTION
    # --------------------------------------------------------

    is_capital_reduction = contains_any(
        text,
        [
            r"\bCAPITAL REDUCTION\b",
            r"\bREDUCTION OF CAPITAL\b",
        ],
    )

    # --------------------------------------------------------
    # ADMINISTRATIVE / NON-RETURN EVENTS
    # --------------------------------------------------------

    is_meeting = contains_any(
        text,
        [
            r"\bAGM\b",
            r"\bANNUAL GENERAL MEETING\b",
            r"\bEGM\b",
            r"\bEXTRAORDINARY GENERAL MEETING\b",
            r"\bCOURT CONVENED MEETING\b",
        ],
    )

    is_interest = contains_any(
        text,
        [
            r"\bINTEREST\b",
        ],
    )

    is_redemption = contains_any(
        text,
        [
            r"\bREDEMPTION\b",
        ],
    )

    return {
        "is_dividend":
            is_dividend,

        "is_bonus":
            is_bonus,

        "is_split":
            is_split,

        "is_consolidation":
            is_consolidation,

        "is_rights":
            is_rights,

        "is_structural":
            is_structural,

        "is_buyback":
            is_buyback,

        "is_capital_reduction":
            is_capital_reduction,

        "is_meeting":
            is_meeting,

        "is_interest":
            is_interest,

        "is_redemption":
            is_redemption,
    }


# ============================================================
# PRIMARY EVENT CLASS
# ============================================================

def primary_class(row):

    # Structural cases are deliberately given precedence.
    if row["is_structural"]:
        return "STRUCTURAL"

    if row["is_capital_reduction"]:
        return "CAPITAL_REDUCTION"

    if row["is_split"]:
        return "SPLIT"

    if row["is_consolidation"]:
        return "CONSOLIDATION"

    if row["is_bonus"]:
        return "BONUS"

    if row["is_rights"]:
        return "RIGHTS"

    if row["is_dividend"]:
        return "DIVIDEND"

    if row["is_buyback"]:
        return "BUYBACK"

    if row["is_redemption"]:
        return "REDEMPTION"

    if row["is_interest"]:
        return "INTEREST"

    if row["is_meeting"]:
        return "MEETING_ONLY"

    return "OTHER"


# ============================================================
# DIVIDEND AMOUNT PARSER
# ============================================================

def parse_dividend_amount(
    purpose: str,
):

    if not purpose:
        return np.nan

    text = purpose.upper()

    patterns = [

        # Rs 5 per share
        r"(?:RS\.?|INR|₹)\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*(?:/-)?\s*"
        r"(?:PER\s+SHARE)?",

        # Dividend 5/-
        r"DIVIDEND[^0-9]{0,30}"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*/-",

        # Dividend - 5.00
        r"DIVIDEND[^0-9]{0,30}"
        r"([0-9]+(?:\.[0-9]+)?)",
    ]

    candidates = []

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            text,
            flags=re.I,
        ):

            try:

                value = float(
                    match.group(1)
                )

                if 0 < value < 10000:
                    candidates.append(
                        value
                    )

            except Exception:
                pass

    if not candidates:
        return np.nan

    # Conservative:
    # return first plausible rupee amount.
    return candidates[0]


# ============================================================
# RATIO PARSER
# ============================================================

def parse_ratio(
    purpose: str,
):

    if not purpose:
        return (
            np.nan,
            np.nan,
        )

    # Matches forms such as:
    # 1:1
    # 2 : 5
    # 3 FOR 2

    patterns = [
        r"\b(\d+(?:\.\d+)?)\s*:\s*"
        r"(\d+(?:\.\d+)?)\b",

        r"\b(\d+(?:\.\d+)?)\s+FOR\s+"
        r"(\d+(?:\.\d+)?)\b",
    ]

    for pattern in patterns:

        m = re.search(
            pattern,
            purpose,
            flags=re.I,
        )

        if m:

            return (
                float(m.group(1)),
                float(m.group(2)),
            )

    return (
        np.nan,
        np.nan,
    )


# ============================================================
# FACE VALUE PARSER FOR SPLITS
# ============================================================

def parse_face_value_change(
    purpose: str,
):

    if not purpose:
        return (
            np.nan,
            np.nan,
        )

    text = purpose.upper()

    # Examples:
    #
    # FV FROM RS.10 TO RS.2
    # FACE VALUE RS 10/- TO RS 5/-
    # SUB-DIVISION FROM RS 10 TO RS 1

    pattern = (
        r"(?:FROM|FV\s+FROM|FACE\s+VALUE\s+FROM)"
        r"[^0-9]{0,20}"
        r"(?:RS\.?|INR|₹)?\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"[^0-9]{1,40}"
        r"(?:TO)"
        r"[^0-9]{0,20}"
        r"(?:RS\.?|INR|₹)?\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
    )

    m = re.search(
        pattern,
        text,
        flags=re.I,
    )

    if not m:
        return (
            np.nan,
            np.nan,
        )

    return (
        float(m.group(1)),
        float(m.group(2)),
    )


# ============================================================
# MAIN
# ============================================================

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    df = pd.read_parquet(
        INPUT
    )

    print(
        f"Loaded corporate actions: "
        f"{len(df):,}"
    )

    df["purpose_normalized"] = (
        df["purpose"]
        .map(
            normalize_purpose
        )
    )

    # --------------------------------------------------------
    # Classification flags
    # --------------------------------------------------------

    flags = (
        df["purpose_normalized"]
        .apply(classify_flags)
        .apply(pd.Series)
    )

    df = pd.concat(
        [
            df,
            flags,
        ],
        axis=1,
    )

    df["primary_class"] = (
        df.apply(
            primary_class,
            axis=1,
        )
    )

    # --------------------------------------------------------
    # Dividend amounts
    # --------------------------------------------------------

    df["dividend_amount"] = np.where(
        df["is_dividend"],
        df[
            "purpose_normalized"
        ].map(
            parse_dividend_amount
        ),
        np.nan,
    )

    # --------------------------------------------------------
    # Ratios
    # --------------------------------------------------------

    ratios = (
        df["purpose_normalized"]
        .map(parse_ratio)
    )

    df["ratio_a"] = [
        x[0]
        for x in ratios
    ]

    df["ratio_b"] = [
        x[1]
        for x in ratios
    ]

    # --------------------------------------------------------
    # Face value changes
    # --------------------------------------------------------

    fv = (
        df["purpose_normalized"]
        .map(
            parse_face_value_change
        )
    )

    df["old_face_value_parsed"] = [
        x[0]
        for x in fv
    ]

    df["new_face_value_parsed"] = [
        x[1]
        for x in fv
    ]

    # --------------------------------------------------------
    # Multiple economically-relevant events on same row
    # --------------------------------------------------------

    relevant_flag_cols = [
        "is_dividend",
        "is_bonus",
        "is_split",
        "is_consolidation",
        "is_rights",
        "is_structural",
        "is_buyback",
        "is_capital_reduction",
    ]

    df[
        "economic_event_count"
    ] = (
        df[
            relevant_flag_cols
        ]
        .astype(int)
        .sum(axis=1)
    )

    df[
        "multiple_event_types"
    ] = (
        df[
            "economic_event_count"
        ] > 1
    )

    # --------------------------------------------------------
    # Conservative review flags
    # --------------------------------------------------------

    df[
        "needs_manual_review"
    ] = False

    # Structural actions always deserve review.
    df.loc[
        df["is_structural"],
        "needs_manual_review",
    ] = True

    # Capital reductions too.
    df.loc[
        df["is_capital_reduction"],
        "needs_manual_review",
    ] = True

    # Multiple return-relevant events in one purpose string.
    df.loc[
        df["multiple_event_types"],
        "needs_manual_review",
    ] = True

    # Dividend mentioned but amount not parsable.
    df.loc[
        (
            df["is_dividend"]
            &
            df[
                "dividend_amount"
            ].isna()
        ),
        "needs_manual_review",
    ] = True

    # Bonus / rights where ratio was not parsed.
    df.loc[
        (
            (
                df["is_bonus"]
                |
                df["is_rights"]
            )
            &
            (
                df["ratio_a"].isna()
                |
                df["ratio_b"].isna()
            )
        ),
        "needs_manual_review",
    ] = True

    # Splits/consolidations without either explicit FV change
    # or ratio.
    df.loc[
        (
            (
                df["is_split"]
                |
                df[
                    "is_consolidation"
                ]
            )
            &
            (
                df[
                    "old_face_value_parsed"
                ].isna()
            )
            &
            (
                df[
                    "ratio_a"
                ].isna()
            )
        ),
        "needs_manual_review",
    ] = True

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    df = df.sort_values(
        [
            "ex_date",
            "symbol",
            "purpose_normalized",
        ]
    ).reset_index(
        drop=True
    )

    df.to_parquet(
        OUTPUT,
        compression="zstd",
        index=False,
    )

    df.to_csv(
        OUTPUT_DIR /
        "nse_corporate_actions_classified.csv",
        index=False,
    )

    # --------------------------------------------------------
    # Review tables
    # --------------------------------------------------------

    review = df[
        df[
            "needs_manual_review"
        ]
    ].copy()

    review.to_csv(
        OUTPUT_DIR /
        "corporate_actions_manual_review.csv",
        index=False,
    )

    other = df[
        df[
            "primary_class"
        ].eq(
            "OTHER"
        )
    ].copy()

    other.to_csv(
        OUTPUT_DIR /
        "corporate_actions_other.csv",
        index=False,
    )

    # Unique OTHER purposes make manual inspection much easier.
    other_purposes = (
        other[
            "purpose_normalized"
        ]
        .value_counts()
        .rename_axis(
            "purpose"
        )
        .reset_index(
            name="count"
        )
    )

    other_purposes.to_csv(
        OUTPUT_DIR /
        "other_purpose_counts.csv",
        index=False,
    )

    # --------------------------------------------------------
    # REPORT
    # --------------------------------------------------------

    print(
        "\n=== PRIMARY EVENT CLASSES ==="
    )

    print(
        df[
            "primary_class"
        ]
        .value_counts()
        .to_string()
    )

    print(
        "\n=== RETURN-RELEVANT FLAGS ==="
    )

    for col in relevant_flag_cols:

        print(
            f"{col:25s}: "
            f"{int(df[col].sum()):,}"
        )

    print(
        "\n=== PARSER COVERAGE ==="
    )

    dividend_rows = df[
        df["is_dividend"]
    ]

    print(
        "Dividend rows:",
        len(dividend_rows)
    )

    print(
        "Dividend amount parsed:",
        int(
            dividend_rows[
                "dividend_amount"
            ].notna().sum()
        ),
    )

    bonus_rows = df[
        df["is_bonus"]
    ]

    print(
        "\nBonus rows:",
        len(bonus_rows)
    )

    print(
        "Bonus ratio parsed:",
        int(
            (
                bonus_rows["ratio_a"].notna()
                &
                bonus_rows["ratio_b"].notna()
            ).sum()
        ),
    )

    split_rows = df[
        (
            df["is_split"]
            |
            df[
                "is_consolidation"
            ]
        )
    ]

    print(
        "\nSplit/consolidation rows:",
        len(split_rows)
    )

    print(
        "FV transition parsed:",
        int(
            (
                split_rows[
                    "old_face_value_parsed"
                ].notna()
                &
                split_rows[
                    "new_face_value_parsed"
                ].notna()
            ).sum()
        ),
    )

    print(
        "\nManual-review rows:",
        int(
            df[
                "needs_manual_review"
            ].sum()
        ),
    )

    print(
        "OTHER rows:",
        int(
            df[
                "primary_class"
            ].eq(
                "OTHER"
            ).sum()
        ),
    )

    print(
        "\nWritten:"
    )

    print(
        OUTPUT.resolve()
    )


if __name__ == "__main__":
    main()