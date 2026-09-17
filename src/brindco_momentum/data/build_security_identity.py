from __future__ import annotations

from pathlib import Path
from brindco_momentum.paths import ROOT
import hashlib
import re

import pandas as pd
import pyarrow.dataset as ds


# ============================================================
# PATHS
# ============================================================

PRICE_PARQUET = ROOT / Path("data/processed/nse_cm_2013_2026.parquet"
)

MEMBERSHIP_PARQUET = ROOT / Path("data/processed/membership_audit/"
    "nifty500_membership_intervals.parquet"
)

MISMATCH_FILE = ROOT / Path("data/processed/membership_audit/"
    "membership_price_symbol_mismatches.csv"
)

RAW_IDENTITY_DIR = ROOT / Path("data/raw/security_identity"
)

SYMBOL_CHANGE_FILE = (
    RAW_IDENTITY_DIR / "symbolchange.csv"
)

NAME_CHANGE_FILE = (
    RAW_IDENTITY_DIR / "namechange.csv"
)

CURRENT_EQUITY_FILE = (
    RAW_IDENTITY_DIR / "EQUITY_L.csv"
)

OUTPUT_DIR = ROOT / Path("data/processed/security_identity"
)


# ============================================================
# HELPERS
# ============================================================

def normalize_column_name(name: str) -> str:
    """
    Convert headers like:

        "OLD SYMBOL"
        "Old Symbol "
        "OLD-SYMBOL"

    into:

        OLD_SYMBOL
    """

    name = str(name).strip().upper()
    name = re.sub(r"[^A-Z0-9]+", "_", name)
    return name.strip("_")


def normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [
        normalize_column_name(c)
        for c in df.columns
    ]
    return df


def clean_symbol(series: pd.Series) -> pd.Series:
    return (
        series
        .astype("string")
        .str.strip()
        .str.upper()
    )


def clean_isin(series: pd.Series) -> pd.Series:
    return (
        series
        .astype("string")
        .str.strip()
        .str.upper()
    )


def pick_column(
    columns,
    candidates,
    required=True,
):
    """
    Find first matching normalized column name.
    """

    columns = set(columns)

    for candidate in candidates:
        if candidate in columns:
            return candidate

    if required:
        raise ValueError(
            "Could not identify required column.\n"
            f"Tried: {candidates}\n"
            f"Available: {sorted(columns)}"
        )

    return None


# ============================================================
# UNION-FIND
# ============================================================

class UnionFind:
    """
    Build connected components of ticker aliases.
    """

    def __init__(self):
        self.parent = {}

    def add(self, x):
        if x not in self.parent:
            self.parent[x] = x

    def find(self, x):
        self.add(x)

        if self.parent[x] != x:
            self.parent[x] = self.find(
                self.parent[x]
            )

        return self.parent[x]

    def union(self, a, b):
        ra = self.find(a)
        rb = self.find(b)

        if ra != rb:
            self.parent[rb] = ra

    def components(self):
        result = {}

        for x in self.parent:
            root = self.find(x)
            result.setdefault(root, set()).add(x)

        return result


# ============================================================
# LOAD PRICE IDENTITY OBSERVATIONS
# ============================================================

def load_price_identity_data():
    """
    Load only the columns needed for security identity.

    EQ series only.
    """

    print("\nLoading EQ identity observations from price parquet...")

    dataset = ds.dataset(
        PRICE_PARQUET,
        format="parquet",
    )

    table = dataset.to_table(
        columns=[
            "date",
            "symbol",
            "series",
            "isin",
        ],
        filter=(
            ds.field("series") == "EQ"
        ),
    )

    df = table.to_pandas()

    df["date"] = pd.to_datetime(
        df["date"]
    )

    df["symbol"] = clean_symbol(
        df["symbol"]
    )

    df["isin"] = clean_isin(
        df["isin"]
    )

    df = df[
        df["symbol"].notna()
        &
        df["isin"].notna()
        &
        df["symbol"].ne("")
        &
        df["isin"].ne("")
    ].copy()

    print(
        f"EQ observations : {len(df):,}"
    )
    print(
        f"Unique symbols  : {df['symbol'].nunique():,}"
    )
    print(
        f"Unique ISINs    : {df['isin'].nunique():,}"
    )

    return df


# ============================================================
# OBSERVED SYMBOL / ISIN HISTORY
# ============================================================

def build_observed_history(
    prices: pd.DataFrame,
):
    print(
        "\nBuilding observed symbol/ISIN history..."
    )

    history = (
        prices
        .groupby(
            ["isin", "symbol"],
            as_index=False,
        )
        .agg(
            first_seen=("date", "min"),
            last_seen=("date", "max"),
            observations=("date", "size"),
        )
    )

    history = history.sort_values(
        [
            "isin",
            "first_seen",
            "symbol",
        ]
    ).reset_index(drop=True)

    history.to_parquet(
        OUTPUT_DIR /
        "observed_symbol_isin_history.parquet",
        index=False,
    )

    history.to_csv(
        OUTPUT_DIR /
        "observed_symbol_isin_history.csv",
        index=False,
    )

    print(
        f"Observed ISIN-symbol pairs: "
        f"{len(history):,}"
    )

    return history


# ============================================================
# LOAD SYMBOL CHANGES
# ============================================================

def load_symbol_changes():

    print("\nReading symbolchange.csv...")

    # NSE's symbolchange.csv is HEADERLESS.
    raw = pd.read_csv(
        SYMBOL_CHANGE_FILE,
        header=None,
        dtype="string",
        low_memory=False,
    )

    # Drop completely empty columns, if any.
    raw = raw.dropna(
        axis=1,
        how="all",
    )

    if raw.shape[1] != 4:
        raise ValueError(
            f"Expected 4 columns in symbolchange.csv, "
            f"found {raw.shape[1]}.\n"
            f"First rows:\n{raw.head().to_string(index=False)}"
        )

    raw.columns = [
        "company_name",
        "old_symbol",
        "new_symbol",
        "effective_date",
    ]

    print(
        "symbolchange.csv interpreted columns:",
        list(raw.columns),
    )

    # Clean fields.
    raw["company_name"] = (
        raw["company_name"]
        .astype("string")
        .str.strip()
    )

    raw["old_symbol"] = clean_symbol(
        raw["old_symbol"]
    )

    raw["new_symbol"] = clean_symbol(
        raw["new_symbol"]
    )

    raw["effective_date"] = pd.to_datetime(
        raw["effective_date"],
        dayfirst=True,
        errors="coerce",
    )

    # Remove malformed / unusable rows.
    changes = raw[
        raw["old_symbol"].notna()
        &
        raw["new_symbol"].notna()
        &
        raw["old_symbol"].ne("")
        &
        raw["new_symbol"].ne("")
        &
        (
            raw["old_symbol"]
            != raw["new_symbol"]
        )
    ].copy()

    # Keep only relevant fields for identity graph.
    changes = changes[
        [
            "company_name",
            "old_symbol",
            "new_symbol",
            "effective_date",
        ]
    ]

    changes = changes.drop_duplicates()

    changes.to_csv(
        OUTPUT_DIR /
        "normalized_symbol_changes.csv",
        index=False,
    )

    print(
        f"Usable symbol-change records: "
        f"{len(changes):,}"
    )

    print(
        f"Unparseable effective dates: "
        f"{changes['effective_date'].isna().sum():,}"
    )

    return changes

# ============================================================
# CURRENT EQUITY MASTER
# ============================================================

def load_current_equities():

    print("\nReading EQUITY_L.csv...")

    raw = pd.read_csv(
        CURRENT_EQUITY_FILE,
        dtype="string",
        low_memory=False,
    )

    raw = normalize_headers(raw)

    print(
        "EQUITY_L.csv columns:",
        list(raw.columns),
    )

    symbol_col = pick_column(
        raw.columns,
        [
            "SYMBOL",
        ],
    )

    isin_col = pick_column(
        raw.columns,
        [
            "ISIN_NUMBER",
            "ISIN",
        ],
    )

    name_col = pick_column(
        raw.columns,
        [
            "NAME_OF_COMPANY",
            "COMPANY_NAME",
            "NAME",
        ],
        required=False,
    )

    result = pd.DataFrame({
        "symbol": clean_symbol(
            raw[symbol_col]
        ),
        "isin": clean_isin(
            raw[isin_col]
        ),
    })

    if name_col:
        result["company_name"] = (
            raw[name_col]
            .astype("string")
            .str.strip()
        )

    result = (
        result
        .dropna(
            subset=["symbol"]
        )
        .drop_duplicates()
    )

    result.to_csv(
        OUTPUT_DIR /
        "normalized_current_equities.csv",
        index=False,
    )

    print(
        f"Current equity symbols: "
        f"{result['symbol'].nunique():,}"
    )

    return result


# ============================================================
# NAME CHANGE AUDIT
# ============================================================

def inspect_name_changes():
    """
    Name changes do NOT drive ticker identity joins.

    We preserve them as supporting evidence only.
    """

    print("\nReading namechange.csv...")

    raw = pd.read_csv(
        NAME_CHANGE_FILE,
        dtype="string",
        low_memory=False,
    )

    raw = normalize_headers(raw)

    print(
        "namechange.csv columns:",
        list(raw.columns),
    )

    raw.to_csv(
        OUTPUT_DIR /
        "normalized_name_changes.csv",
        index=False,
    )

    print(
        f"Company-name change rows: "
        f"{len(raw):,}"
    )


# ============================================================
# BUILD SAME-ISIN EDGES
# ============================================================

def build_isin_edges(
    history: pd.DataFrame,
):
    """
    If the same ISIN appears under multiple sequential tickers,
    this is strong direct evidence of security identity.

    We deliberately flag cases where two different symbols with
    the same ISIN overlap for >5 calendar days rather than
    automatically merging them.
    """

    edges = []
    suspicious = []

    for isin, group in history.groupby(
        "isin",
        sort=False,
    ):

        if len(group) < 2:
            continue

        g = group.sort_values(
            [
                "first_seen",
                "last_seen",
            ]
        ).reset_index(drop=True)

        for i in range(
            len(g) - 1
        ):

            left = g.iloc[i]
            right = g.iloc[i + 1]

            overlap_days = (
                left["last_seen"]
                - right["first_seen"]
            ).days

            # If intervals overlap for more than five days,
            # don't automatically claim alias identity.
            if overlap_days > 5:

                suspicious.append({
                    "isin": isin,
                    "symbol_1": left["symbol"],
                    "symbol_2": right["symbol"],
                    "symbol_1_first":
                        left["first_seen"],
                    "symbol_1_last":
                        left["last_seen"],
                    "symbol_2_first":
                        right["first_seen"],
                    "symbol_2_last":
                        right["last_seen"],
                    "overlap_days":
                        overlap_days,
                })

                continue

            edges.append({
                "symbol_a": left["symbol"],
                "symbol_b": right["symbol"],
                "source":
                    "same_isin_observed",
                "evidence":
                    isin,
                "effective_date":
                    right["first_seen"],
            })

    suspicious_df = pd.DataFrame(
        suspicious
    )

    if not suspicious_df.empty:

        suspicious_df.to_csv(
            OUTPUT_DIR /
            "same_isin_overlap_flags.csv",
            index=False,
        )

    print(
        "Same-ISIN sequential ticker edges:",
        len(edges),
    )

    print(
        "Suspicious same-ISIN overlaps:",
        len(suspicious),
    )

    return pd.DataFrame(edges)


# ============================================================
# BUILD ALIAS GRAPH
# ============================================================

def build_alias_graph(
    history,
    symbol_changes,
    membership,
    current_equities,
):

    explicit_edges = pd.DataFrame({
        "symbol_a":
            symbol_changes["old_symbol"],
        "symbol_b":
            symbol_changes["new_symbol"],
        "source":
            "nse_symbolchange",
        "evidence":
            "symbolchange.csv",
        "effective_date":
            symbol_changes["effective_date"],
    })

    isin_edges = build_isin_edges(
        history
    )

    edges = pd.concat(
        [
            explicit_edges,
            isin_edges,
        ],
        ignore_index=True,
    )

    edges = edges[
        edges["symbol_a"].notna()
        &
        edges["symbol_b"].notna()
        &
        (
            edges["symbol_a"]
            != edges["symbol_b"]
        )
    ].drop_duplicates()

    edges.to_csv(
        OUTPUT_DIR /
        "symbol_alias_edges.csv",
        index=False,
    )

    uf = UnionFind()

    # Make sure standalone symbols also get components.
    symbol_sets = [
        history["symbol"],
        membership["symbol"],
        current_equities["symbol"],
        edges["symbol_a"],
        edges["symbol_b"],
    ]

    for series in symbol_sets:

        for symbol in (
            series
            .dropna()
            .astype(str)
            .str.upper()
            .unique()
        ):
            uf.add(symbol)

    for row in edges.itertuples(
        index=False
    ):

        uf.union(
            row.symbol_a,
            row.symbol_b,
        )

    components = uf.components()

    print(
        f"\nTicker identity components: "
        f"{len(components):,}"
    )

    return uf, components, edges


# ============================================================
# COMPONENT TABLE
# ============================================================

def build_component_table(
    components,
    history,
    membership,
    current_equities,
):

    membership_symbols = set(
        membership["symbol"]
        .dropna()
        .astype(str)
        .str.upper()
    )

    current_symbols = set(
        current_equities["symbol"]
        .dropna()
        .astype(str)
        .str.upper()
    )

    observation_lookup = {}

    for row in history.itertuples(
        index=False
    ):

        observation_lookup.setdefault(
            row.symbol,
            [],
        ).append(row)

    rows = []

    component_alias_lookup = {}

    for symbols in components.values():

        aliases = sorted(symbols)

        identity_id = (
            "ID_"
            +
            hashlib.sha1(
                "|".join(
                    aliases
                ).encode()
            ).hexdigest()[:12]
        )

        current_candidates = sorted(
            set(aliases)
            &
            current_symbols
        )

        # Find symbol with latest observed market date.
        observed_candidates = []

        for symbol in aliases:

            for obs in observation_lookup.get(
                symbol,
                [],
            ):

                observed_candidates.append(
                    (
                        obs.last_seen,
                        symbol,
                    )
                )

        latest_observed_symbol = None

        if observed_candidates:

            latest_observed_symbol = max(
                observed_candidates
            )[1]

        # Canonical identity label.
        if len(current_candidates) == 1:

            canonical_symbol = (
                current_candidates[0]
            )

            canonical_rule = (
                "unique_current_nse_symbol"
            )

        elif latest_observed_symbol is not None:

            canonical_symbol = (
                latest_observed_symbol
            )

            canonical_rule = (
                "latest_observed_symbol"
            )

        else:

            canonical_symbol = aliases[-1]

            canonical_rule = (
                "lexicographic_fallback"
            )

        component_alias_lookup.update({
            symbol: set(aliases)
            for symbol in aliases
        })

        for alias in aliases:

            obs_rows = (
                observation_lookup.get(
                    alias,
                    [],
                )
            )

            if obs_rows:

                first_seen = min(
                    x.first_seen
                    for x in obs_rows
                )

                last_seen = max(
                    x.last_seen
                    for x in obs_rows
                )

                isins = sorted({
                    x.isin
                    for x in obs_rows
                })

            else:

                first_seen = pd.NaT
                last_seen = pd.NaT
                isins = []

            rows.append({
                "identity_id":
                    identity_id,
                "canonical_symbol":
                    canonical_symbol,
                "canonical_rule":
                    canonical_rule,
                "alias_symbol":
                    alias,
                "is_membership_symbol":
                    alias
                    in membership_symbols,
                "is_current_nse_symbol":
                    alias
                    in current_symbols,
                "first_seen":
                    first_seen,
                "last_seen":
                    last_seen,
                "observed_isins":
                    ";".join(isins),
                "all_aliases":
                    ";".join(aliases),
            })

    result = pd.DataFrame(rows)

    result = result.sort_values(
        [
            "identity_id",
            "alias_symbol",
        ]
    ).reset_index(drop=True)

    result.to_parquet(
        OUTPUT_DIR /
        "symbol_alias_components.parquet",
        index=False,
    )

    result.to_csv(
        OUTPUT_DIR /
        "symbol_alias_components.csv",
        index=False,
    )

    return result, component_alias_lookup


# ============================================================
# NIFTY 500 CROSSWALK
# ============================================================

def build_membership_crosswalk(
    membership,
    component_table,
):

    component_lookup = (
        component_table
        .set_index("alias_symbol")
    )

    rows = []

    for symbol in sorted(
        membership["symbol"]
        .dropna()
        .unique()
    ):

        if symbol not in component_lookup.index:

            rows.append({
                "membership_symbol":
                    symbol,
                "identity_id":
                    None,
                "canonical_symbol":
                    None,
                "aliases":
                    "",
                "observed_in_prices":
                    False,
            })

            continue

        record = component_lookup.loc[
            symbol
        ]

        # alias_symbol is unique by construction.
        observed = (
            pd.notna(
                record["first_seen"]
            )
            or
            any(
                component_table.loc[
                    component_table[
                        "identity_id"
                    ].eq(
                        record[
                            "identity_id"
                        ]
                    ),
                    "first_seen",
                ].notna()
            )
        )

        rows.append({
            "membership_symbol":
                symbol,
            "identity_id":
                record["identity_id"],
            "canonical_symbol":
                record["canonical_symbol"],
            "aliases":
                record["all_aliases"],
            "observed_in_prices":
                bool(observed),
        })

    crosswalk = pd.DataFrame(rows)

    crosswalk.to_parquet(
        OUTPUT_DIR /
        "nifty500_symbol_crosswalk.parquet",
        index=False,
    )

    crosswalk.to_csv(
        OUTPUT_DIR /
        "nifty500_symbol_crosswalk.csv",
        index=False,
    )

    print(
        "\nNIFTY 500 membership symbols:",
        len(crosswalk),
    )

    print(
        "Identity components with price evidence:",
        int(
            crosswalk[
                "observed_in_prices"
            ].sum()
        ),
    )

    return crosswalk


# ============================================================
# RESOLVE THE PREVIOUS 318 MISMATCHES
# ============================================================

def resolve_mismatches(
    prices,
    alias_lookup,
):

    if not MISMATCH_FILE.exists():

        print(
            "\nNo mismatch file found; "
            "skipping mismatch resolution."
        )

        return

    mismatches = pd.read_csv(
        MISMATCH_FILE
    )

    mismatches[
        "membership_date"
    ] = pd.to_datetime(
        mismatches[
            "membership_date"
        ]
    )

    mismatches[
        "price_date_used"
    ] = pd.to_datetime(
        mismatches[
            "price_date_used"
        ]
    )

    mismatches["symbol"] = (
        clean_symbol(
            mismatches["symbol"]
        )
    )

    needed_dates = set(
        mismatches[
            "price_date_used"
        ].dropna()
    )

    px_subset = prices[
        prices["date"].isin(
            needed_dates
        )
    ]

    symbols_by_date = {
        d: set(
            g["symbol"]
            .dropna()
            .unique()
        )
        for d, g in px_subset.groupby(
            "date"
        )
    }

    rows = []

    for row in mismatches.itertuples(
        index=False
    ):

        symbol = row.symbol
        px_date = row.price_date_used

        aliases = alias_lookup.get(
            symbol,
            {symbol},
        )

        symbols_present = (
            symbols_by_date.get(
                px_date,
                set(),
            )
        )

        candidates = sorted(
            aliases
            &
            symbols_present
        )

        if len(candidates) == 1:

            status = "RESOLVED"
            resolved_symbol = candidates[0]

        elif len(candidates) > 1:

            status = "AMBIGUOUS"
            resolved_symbol = ";".join(
                candidates
            )

        else:

            status = "UNRESOLVED"
            resolved_symbol = None

        rows.append({
            "membership_date":
                row.membership_date,
            "price_date_used":
                px_date,
            "membership_symbol":
                symbol,
            "status":
                status,
            "resolved_price_symbol":
                resolved_symbol,
            "alias_component":
                ";".join(
                    sorted(aliases)
                ),
        })

    result = pd.DataFrame(rows)

    result.to_csv(
        OUTPUT_DIR /
        "membership_mismatch_resolution.csv",
        index=False,
    )

    unresolved = result[
        result["status"].eq(
            "UNRESOLVED"
        )
    ]

    unresolved.to_csv(
        OUTPUT_DIR /
        "unresolved_membership_mismatches.csv",
        index=False,
    )

    ambiguous = result[
        result["status"].eq(
            "AMBIGUOUS"
        )
    ]

    ambiguous.to_csv(
        OUTPUT_DIR /
        "ambiguous_membership_mismatches.csv",
        index=False,
    )

    print(
        "\n=== PREVIOUS MISMATCH RESOLUTION ==="
    )

    print(
        result[
            "status"
        ].value_counts().to_string()
    )

    total = len(result)

    resolved = int(
        result[
            "status"
        ].eq("RESOLVED").sum()
    )

    if total:

        print(
            f"\nResolved automatically: "
            f"{resolved}/{total} "
            f"({100 * resolved / total:.1f}%)"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Required inputs
    # --------------------------------------------------------

    required_files = [
        PRICE_PARQUET,
        MEMBERSHIP_PARQUET,
        SYMBOL_CHANGE_FILE,
        NAME_CHANGE_FILE,
        CURRENT_EQUITY_FILE,
    ]

    for path in required_files:

        if not path.exists():

            raise FileNotFoundError(
                f"Missing required file:\n"
                f"{path.resolve()}"
            )

    # --------------------------------------------------------
    # Load core datasets
    # --------------------------------------------------------

    prices = load_price_identity_data()

    membership = pd.read_parquet(
        MEMBERSHIP_PARQUET
    )

    membership["symbol"] = (
        clean_symbol(
            membership["symbol"]
        )
    )

    # --------------------------------------------------------
    # Build market-observed history
    # --------------------------------------------------------

    history = build_observed_history(
        prices
    )

    # --------------------------------------------------------
    # NSE identity evidence
    # --------------------------------------------------------

    symbol_changes = (
        load_symbol_changes()
    )

    current_equities = (
        load_current_equities()
    )

    inspect_name_changes()

    # --------------------------------------------------------
    # Build ticker identity graph
    # --------------------------------------------------------

    uf, components, edges = (
        build_alias_graph(
            history,
            symbol_changes,
            membership,
            current_equities,
        )
    )

    component_table, alias_lookup = (
        build_component_table(
            components,
            history,
            membership,
            current_equities,
        )
    )

    # --------------------------------------------------------
    # Membership crosswalk
    # --------------------------------------------------------

    crosswalk = (
        build_membership_crosswalk(
            membership,
            component_table,
        )
    )

    # --------------------------------------------------------
    # Attack our 318 mismatches
    # --------------------------------------------------------

    resolve_mismatches(
        prices,
        alias_lookup,
    )

    print(
        "\n"
        + "=" * 65
    )

    print(
        "SECURITY IDENTITY BUILD COMPLETE"
    )

    print(
        "=" * 65
    )

    print(
        f"\nOutputs:\n"
        f"{OUTPUT_DIR.resolve()}"
    )

    print(
        "\nImportant outputs:"
    )

    print(
        "  observed_symbol_isin_history.parquet"
    )

    print(
        "  normalized_symbol_changes.csv"
    )

    print(
        "  symbol_alias_edges.csv"
    )

    print(
        "  symbol_alias_components.parquet"
    )

    print(
        "  nifty500_symbol_crosswalk.parquet"
    )

    print(
        "  membership_mismatch_resolution.csv"
    )

    print(
        "  unresolved_membership_mismatches.csv"
    )

    print(
        "\nDo NOT manually alter unresolved names yet."
    )


if __name__ == "__main__":
    main()