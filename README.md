# Brindco: risk-managed NIFTY 500 momentum

This project tests an implementable Indian-equity adaptation of Barroso and Santa-Clara's *Momentum Has Its Moments*. It compares unscaled long-only momentum (MOM), a 12% volatility-managed version (VM), and two fixed-exposure controls (FIX and FIXVOL) using point-in-time NIFTY 500 membership, explicit corporate actions, settlement, costs, whole shares, and FIFO capital-gains tax accounting.

The development period is 1 April 2015–31 March 2023. The untouched holdout is 3 April 2023–30 March 2026.

| Account | Final NAV | CAGR | Annual volatility | 0%-cash Sharpe | Max drawdown |
|---|---:|---:|---:|---:|---:|
| MOM | ₹38.23m | 24.71% | 21.05% | 1.17 | −24.94% |
| VM | ₹23.17m | 16.05% | 15.08% | 1.08 | −15.81% |
| FIX | ₹27.68m | 17.80% | 16.09% | 1.12 | −19.22% |
| FIXVOL | ₹28.77m | 18.45% | 16.82% | 1.11 | −20.05% |

NIFTY 500 TRI CAGR was 13.23%. Different final NAVs reflect different frozen 2023-03-31 account states; growth rates and normalized paths are the appropriate comparisons.

## Reproduce

Use Python 3.12 from the repository root:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe scripts\reproduce.py
.venv\Scripts\python.exe -m pytest -q
```

The reproduction command rebuilds momentum features and winner sets, the shadow portfolio, the volatility overlay, all four development accounts, all four holdout accounts, both summary tables, and the final figures. It removes bulky generated ledgers after validating the submitted metrics. The full chronological account replay is CPU intensive and can take well over an hour on a laptop.

## Submission contents

- [METHODOLOGY.md](METHODOLOGY.md) defines data timing, signals, risk scaling, execution, costs, taxes, corporate actions, and metrics.
- [LIMITATIONS.md](LIMITATIONS.md) states the material modelling and inference limits.
- [Five-page client memo](results/brindco_project_memo.pdf) presents the final study.
- [Development summary](results/development_summary.csv), [holdout summary](results/holdout_summary.csv), and [figure notes](results/final_figures/FIGURE_NOTES.md) are the concise submitted outputs.
- `data/processed/` contains only accepted runtime inputs. `research_panel_v2.parquet` and `holdout_execution_panel.parquet` are the accepted upstream boundary; raw acquisition and historical reconstruction code is intentionally omitted.
- `data/processed/runtime_inputs/` contains compact event evidence and only the supplemental observations needed for later entrants and received/tradable entitlement securities.
- `data/raw/README.md` and `data/raw/OMITTED_SOURCE_MANIFEST.csv` preserve provenance for omitted public archives.
- `tests/` retains only financial invariants and the final-output regression.

No absolute local paths or external files are required.
