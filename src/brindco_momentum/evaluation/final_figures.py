"""Publication figures from the completed development and holdout artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch
from matplotlib.ticker import PercentFormatter
from brindco_momentum.paths import ROOT


BUNDLE = ROOT / "results/accounts_holdout/frozen_bundle"
OUT = ROOT / "results/final_figures"
SUMMARY = ROOT / "results/holdout_summary.csv"
TRI = ROOT / "data/processed/nifty500_tri_2013_2026.parquet"
RISK = BUNDLE / "producer_inputs/risk.parquet"
SHADOW = BUNDLE / "producer_inputs/shadow.parquet"
ANCHOR = pd.Timestamp("2023-03-31")
END = pd.Timestamp("2026-03-30")
ACCOUNTS = ("MOM", "VM", "FIX", "FIXVOL")
COLORS = {
    "MOM": "#DB704A", "VM": "#187C85", "FIX": "#7359B2",
    "FIXVOL": "#D39B34", "NIFTY 500 TRI": "#71849B",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_figure(fig: plt.Figure, stem: str) -> None:
    fig.savefig(OUT / f"{stem}.png", facecolor="white", dpi=300)
    plt.close(fig)


def style_axes(ax: plt.Axes, *, percent: bool = False) -> None:
    ax.set_facecolor("white")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#E5EAF0", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors="#44546A")
    if percent:
        ax.yaxis.set_major_formatter(PercentFormatter(1))


def date_axis(ax: plt.Axes) -> None:
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.set_xlim(ANCHOR, END)
    ax.tick_params(axis="x", rotation=0)


def title_and_caption(fig: plt.Figure, title: str, caption: str) -> None:
    fig.text(0.09, 0.95, title, fontsize=15, fontweight="semibold", color="#17243A")
    fig.text(0.09, 0.91, caption, fontsize=9, color="#66758A")


def load_and_validate() -> tuple[pd.DataFrame, dict[str, pd.DataFrame], pd.DataFrame,
                                 pd.DataFrame, pd.DataFrame, dict[str, float]]:
    summary = pd.read_csv(SUMMARY).set_index("account")
    if set(summary.index) != set(ACCOUNTS) or not summary.sessions.eq(742).all():
        raise ValueError("Completed holdout summary is incomplete")

    navs = {}
    dates = None
    checks = {}
    for name in ACCOUNTS:
        path = BUNDLE / f"{name}_nav_daily.parquet"
        nav = pd.read_parquet(path, columns=["date", "nav", "daily_return"])
        nav["date"] = pd.to_datetime(nav["date"])
        nav = nav.sort_values("date").reset_index(drop=True)
        if (len(nav) != 742 or nav.date.iloc[0] != pd.Timestamp("2023-04-03")
                or nav.date.iloc[-1] != END or nav.date.duplicated().any()
                or not np.isfinite(nav[["nav", "daily_return"]]).all().all()
                or nav.nav.le(0).any()):
            raise ValueError(f"Incomplete holdout NAV: {name}")
        if dates is None:
            dates = pd.DatetimeIndex(nav.date)
        elif not pd.DatetimeIndex(nav.date).equals(dates):
            raise ValueError(f"Holdout account dates differ: {name}")
        initial = float(summary.loc[name, "start_nav"])
        returns = nav.nav / nav.nav.shift(1, fill_value=initial) - 1
        if not np.allclose(returns, nav.daily_return, rtol=0, atol=1e-12):
            raise ValueError(f"NAV and frozen daily return disagree: {name}")
        values = np.r_[initial, nav.nav.to_numpy(dtype=float)]
        drawdown = values / np.maximum.accumulate(values) - 1
        final_error = abs(values[-1] - float(summary.loc[name, "final_nav"]))
        drawdown_error = abs(drawdown.min() - float(summary.loc[name, "max_drawdown"]))
        if final_error > 1e-6 or drawdown_error > 1e-10:
            raise ValueError(f"Plotted path differs from reported metrics: {name}")
        checks[f"{name}_final_nav_abs_error_inr"] = final_error
        checks[f"{name}_max_drawdown_abs_error"] = drawdown_error
        navs[name] = nav

    tri = pd.read_parquet(TRI, columns=["date", "tri"],
                          filters=[("date", ">=", ANCHOR), ("date", "<=", END)])
    tri["date"] = pd.to_datetime(tri.date)
    tri = tri.sort_values("date").reset_index(drop=True)
    if (len(tri) != len(dates) + 1 or tri.date.iloc[0] != ANCHOR
            or not pd.DatetimeIndex(tri.date.iloc[1:]).equals(dates)
            or not np.isfinite(tri.tri).all() or tri.tri.le(0).any()):
        raise ValueError("Benchmark TRI does not align with the holdout sessions")

    risk = pd.read_parquet(RISK).sort_values("formation_date").reset_index(drop=True)
    shadow = pd.read_parquet(SHADOW, columns=["date", "shadow_daily_return", "valid_return"])
    shadow["date"] = pd.to_datetime(shadow.date)
    shadow = shadow.sort_values("date").reset_index(drop=True)
    if (len(risk) != 36 or risk.formation_date.iloc[0] != ANCHOR
            or risk.formation_date.iloc[-1] != pd.Timestamp("2026-02-27")
            or risk.formation_date.duplicated().any()
            or not risk.risk_status.eq("VALID").all()
            or not risk.shadow_returns_used.eq(126).all()
            or not risk.volatility_target.eq(0.12).all()
            or shadow.date.duplicated().any() or not shadow.valid_return.eq(True).all()):
        raise ValueError("Frozen monthly risk or shadow series is incomplete")
    month_keys = risk.holding_month.astype(str).tolist()
    if month_keys != pd.period_range("2023-04", "2026-03", freq="M").astype(str).tolist():
        raise ValueError("Monthly exposure schedule is incomplete")
    max_sigma_error = 0.0
    max_exposure_error = 0.0
    for row in risk.itertuples(index=False):
        window = shadow.loc[shadow.date.le(row.formation_date)].tail(126)
        if (len(window) != 126 or window.date.iloc[0] != row.risk_window_start
                or window.date.iloc[-1] != row.risk_window_end):
            raise ValueError("Risk window differs from stored shadow sessions")
        squared_sum = float(np.sum(np.square(window.shadow_daily_return.to_numpy(dtype=float))))
        sigma = float(np.sqrt(252 / 126 * squared_sum))
        exposure = min(1.0, 0.12 / sigma) if sigma > 0 else 0.0
        max_sigma_error = max(max_sigma_error, abs(sigma - row.sigma_hat))
        max_exposure_error = max(max_exposure_error, abs(exposure - row.exposure))
        if (abs(squared_sum - row.sum_squared_daily_returns) > 1e-12
                or abs(sigma - row.sigma_hat) > 1e-12
                or abs(exposure - row.exposure) > 1e-12):
            raise ValueError(f"Frozen 126-session RMS formula differs at {row.formation_date}")
    checks["vm_sigma_max_abs_error"] = max_sigma_error
    checks["vm_exposure_max_abs_error"] = max_exposure_error
    return summary, navs, tri, risk, shadow, checks


def cumulative_wealth(summary: pd.DataFrame, navs: dict[str, pd.DataFrame],
                      tri: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(10.2, 5.6))
    title_and_caption(
        fig, "Cumulative wealth: long-only momentum and risk controls",
        "Executable post-cost/post-tax accounts; NIFTY 500 TRI benchmark | Holdout: 3 Apr 2023–30 Mar 2026",
    )
    ax.plot(tri.date, tri.tri / tri.tri.iloc[0], label="NIFTY 500 TRI",
            color=COLORS["NIFTY 500 TRI"], linewidth=2, linestyle="--")
    for name in ("FIX", "FIXVOL", "MOM", "VM"):
        dates = pd.DatetimeIndex([ANCHOR]).append(pd.DatetimeIndex(navs[name].date))
        values = np.r_[1.0, navs[name].nav.to_numpy() / summary.loc[name, "start_nav"]]
        ax.plot(dates, values, label=name, color=COLORS[name], linewidth=2.1)
    ax.axhline(1, color="#AAB5C2", linewidth=0.8)
    ax.set_ylabel("Growth of ₹1 at 31 Mar 2023")
    ax.set_ylim(bottom=0)
    date_axis(ax)
    style_axes(ax)
    ax.legend(loc="upper left", ncol=3, frameon=False, fontsize=9)
    fig.subplots_adjust(left=0.09, right=0.98, top=0.84, bottom=0.13)
    save_figure(fig, "01_cumulative_wealth")


def holdout_drawdowns(summary: pd.DataFrame, navs: dict[str, pd.DataFrame]) -> None:
    fig, ax = plt.subplots(figsize=(10.2, 5.4))
    title_and_caption(fig, "Holdout drawdowns",
                      "Executable post-cost/post-tax accounts | 3 Apr 2023–30 Mar 2026")
    for name in ACCOUNTS:
        dates = pd.DatetimeIndex([ANCHOR]).append(pd.DatetimeIndex(navs[name].date))
        values = np.r_[summary.loc[name, "start_nav"], navs[name].nav.to_numpy()]
        drawdown = values / np.maximum.accumulate(values) - 1
        ax.plot(dates, drawdown, label=name, color=COLORS[name], linewidth=1.9)
    ax.set_ylim(min(-0.30, summary.max_drawdown.min() * 1.15), 0.005)
    ax.set_ylabel("Drawdown from running peak")
    date_axis(ax)
    style_axes(ax, percent=True)
    ax.legend(loc="lower left", ncol=4, frameon=False, fontsize=9)
    fig.subplots_adjust(left=0.09, right=0.98, top=0.84, bottom=0.13)
    save_figure(fig, "02_holdout_drawdowns")


def volatility_mechanism(risk: pd.DataFrame) -> None:
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(10.2, 6.9), sharex=True,
                                     gridspec_kw={"height_ratios": [1, 1], "hspace": 0.22})
    title_and_caption(fig, "Volatility signal and resulting equity exposure",
                      "Frozen 126-session RMS estimate; monthly formation decisions | Holdout: Apr 2023–Mar 2026")
    dates = pd.DatetimeIndex(risk.formation_date).append(pd.DatetimeIndex([END]))
    sigma = np.r_[risk.sigma_hat.to_numpy(), risk.sigma_hat.iloc[-1]]
    exposure = np.r_[risk.exposure.to_numpy(), risk.exposure.iloc[-1]]
    top.step(dates, sigma, where="post", color=COLORS["VM"], linewidth=2,
             label="Estimated shadow volatility")
    top.plot(risk.formation_date, risk.sigma_hat, "o", color=COLORS["VM"], markersize=2.8)
    top.axhline(0.12, color=COLORS["MOM"], linewidth=1.5, linestyle="--",
                label="12% target")
    top.set_ylim(0, max(0.30, float(risk.sigma_hat.max()) * 1.15))
    top.set_ylabel("Annualized volatility")
    style_axes(top, percent=True)
    top.legend(loc="upper right", frameon=False, fontsize=9)
    bottom.step(dates, exposure, where="post", color=COLORS["VM"], linewidth=2.2,
                label="VM target equity exposure")
    bottom.plot(risk.formation_date, risk.exposure, "o", color=COLORS["VM"], markersize=2.8)
    bottom.set_ylim(0, 1.05)
    bottom.set_ylabel("Target equity exposure")
    bottom.set_xlabel("Formation date; target applies to the next holding month")
    date_axis(bottom)
    style_axes(bottom, percent=True)
    fig.subplots_adjust(left=0.11, right=0.98, top=0.84, bottom=0.12)
    save_figure(fig, "03_volatility_overlay_mechanism")


def implementation_frictions(summary: pd.DataFrame) -> None:
    x = np.arange(len(ACCOUNTS))
    colors = [COLORS[name] for name in ACCOUNTS]

    fig, ax = plt.subplots(figsize=(8.3, 4.8))
    title_and_caption(fig, "Holdout implementation frictions",
                      "CAGR differences on matched account paths; the two bars are not additive")
    cost = summary.loc[list(ACCOUNTS), "annualised_implementation_cost_drag"].to_numpy() * 100
    tax = summary.loc[list(ACCOUNTS), "annualised_tax_drag"].to_numpy() * 100
    width = 0.33
    cost_bars = ax.bar(x - width / 2, cost, width, color=colors)
    tax_bars = ax.bar(x + width / 2, tax, width, color=colors, hatch="///",
                      edgecolor="white", linewidth=0.8)
    ax.bar_label(cost_bars, labels=[f"{value:.2f}" for value in cost],
                 padding=3, fontsize=8)
    ax.bar_label(tax_bars, labels=[f"{value:.2f}" for value in tax],
                 padding=3, fontsize=8)
    ax.set_xticks(x, ACCOUNTS)
    ax.set_ylabel("Annualized CAGR difference (percentage points)")
    ax.set_ylim(0, max(np.r_[cost, tax]) * 1.22)
    ax.legend(handles=[Patch(facecolor="#71849B", label="Cost drag"),
                       Patch(facecolor="#71849B", hatch="///", edgecolor="white",
                             label="Tax drag")], loc="upper right", frameon=False, fontsize=9)
    style_axes(ax)
    fig.subplots_adjust(left=0.14, right=0.98, top=0.83, bottom=0.13)
    save_figure(fig, "04b_holdout_cost_tax_drag")


def write_notes(checks: dict[str, float], source_hashes: dict[Path, str]) -> None:
    sources = "\n".join(f"- `{path.relative_to(ROOT).as_posix()}` — SHA-256 `{digest}`"
                        for path, digest in source_hashes.items())
    validation = "\n".join(f"- `{name}`: {value:.3g}" for name, value in checks.items())
    notes = f"""# Final figure notes

All plotted account paths are completed executable, post-cost/post-tax holdout results. The benchmark is the published NIFTY 500 total-return index (TRI), which is not an executable after-tax account. No strategy, account, or development artifact was recomputed or changed.

The wealth chart uses **holdout only**. Development and holdout account paths have different opening-state treatment, including the evidence-backed UPL bonus correction, so this report does not splice the two accounting series. The plotted holdout starts at the frozen 2023-03-31 closing state; the first trading return is 2023-04-03.

## Figure 1 — `01_cumulative_wealth`

- Sources: regenerated `results/accounts_holdout/frozen_bundle/{{MOM,VM,FIX,FIXVOL}}_nav_daily.parquet` (`date`, `nav`); `results/holdout_summary.csv` (`start_nav`); `data/processed/nifty500_tri_2013_2026.parquet` (`date`, `tri`).
- Period: 2023-03-31 opening anchor to 2026-03-30; 742 holdout trading sessions from 2023-04-03.
- Normalization: account NAV / its own frozen opening NAV; TRI / its 2023-03-31 value. All start at ₹1. No summary statistics were used to synthesize a path.
- Interpretation: MOM accumulated the most holdout wealth; VM grew less than both fixed-allocation controls.

## Figure 2 — `02_holdout_drawdowns`

- Sources: same account NAV files and `start_nav` values as Figure 1; no benchmark drawdown is plotted.
- Period: 2023-03-31 opening anchor to 2026-03-30, holdout only.
- Calculation: plotted wealth divided by its running maximum minus one, with the frozen opening NAV included in the initial peak.
- Interpretation: VM's worst drawdown was shallower than those of MOM, FIX, and FIXVOL.

## Figure 3 — `03_volatility_overlay_mechanism`

- Sources: `results/accounts_holdout/frozen_bundle/producer_inputs/risk.parquet` (`formation_date`, `holding_month`, `sigma_hat`, `volatility_target`, `exposure`, `risk_window_start`, `risk_window_end`, `sum_squared_daily_returns`, `shadow_returns_used`, `risk_status`); `results/accounts_holdout/frozen_bundle/producer_inputs/shadow.parquet` (`date`, `shadow_daily_return`, `valid_return`) for validation.
- Period: 36 monthly formation decisions from 2023-03-31 (April 2023 holding month) through 2026-02-27 (March 2026 holding month); holdout only. Horizontal steps indicate the monthly decision held until the next formation, not interpolated daily decisions.
- Formula: the frozen estimate is `sqrt(252/126 × sum(last 126 shadow daily returns squared))`; exposure is `min(1, 0.12 / sigma_hat)` for valid positive volatility. The dashed horizontal reference is the frozen 12% target.
- Interpretation: higher estimated shadow volatility lowered VM's equity allocation, with the remainder assigned to cash.

## Figure 4 — `04b_holdout_cost_tax_drag`

- Source: `results/holdout_summary.csv` (`annualised_implementation_cost_drag`, `annualised_tax_drag`); definitions in `METHODOLOGY.md`.
- Period: 2023-04-03 to 2026-03-30; holdout only.
- Definition: cost and tax drags are CAGR differences on matched executable account paths. They are not additive return contributions or a counterfactual re-run with different trades. Solid bars represent cost drag; hatched bars represent tax drag. Numeric bar labels are percentage points.
- Interpretation: all four accounts incurred material tax drag alongside implementation costs.

## Validation

Account final NAVs and max drawdowns from the plotted paths were checked against `summary_metrics.csv`; every difference was within the stated tolerances (₹0.000001 for NAV, 1e-10 for drawdown). Every plotted VM formation was checked against the actual 126 shadow returns and the frozen 12% exposure rule (tolerance 1e-12). The source hashes below were checked again after rendering and were unchanged.

{validation}

## Source file hashes

{sources}

Rendering code: `brindco_momentum.evaluation.final_figures` (Matplotlib {matplotlib.__version__}). Each figure is saved as a 300-dpi PNG.
"""
    (OUT / "FIGURE_NOTES.md").write_text(notes, encoding="utf-8")


def main() -> None:
    sources = [SUMMARY, TRI, RISK, SHADOW]
    sources += [BUNDLE / f"{name}_nav_daily.parquet" for name in ACCOUNTS]
    source_hashes = {path: sha256(path) for path in sources}
    summary, navs, tri, risk, _, checks = load_and_validate()
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10,
        "axes.labelcolor": "#243247", "text.color": "#17243A",
    })
    OUT.mkdir(parents=True, exist_ok=True)
    cumulative_wealth(summary, navs, tri)
    holdout_drawdowns(summary, navs)
    volatility_mechanism(risk)
    implementation_frictions(summary)
    if {path: sha256(path) for path in sources} != source_hashes:
        raise ValueError("Authoritative source changed during rendering")
    write_notes(checks, source_hashes)
    for name, value in checks.items():
        print(f"{name}={value:.12g}")
    print(f"Figures written to {OUT}")


if __name__ == "__main__":
    main()
