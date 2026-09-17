# Brindco momentum research

The project is an editable Python package. Reusable code is under
`src/brindco_momentum/`; runnable stage commands are under `scripts/`.
The existing datasets remain under `data/raw/`, `data/manual/`, and
`data/processed/`; generated audits and account ledgers remain under
`results/`.

Use Python 3.12. For the exact tested dependency set, from the repository
root on Windows:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.venv\Scripts\python.exe -m pytest -q
```

The editable install also works with `python -m pip install -e .`; the lock
file pins transitive dependencies for exact reproduction. No virtual
environment is included in the repository.

Run individual stages only when their accepted inputs are in place. These
commands write project artifacts and are **not** needed to verify the
structural refactor:

```powershell
# Source acquisition (downloads source records)
.venv\Scripts\python.exe scripts/data/acquire_legacy_bhavcopy.py
.venv\Scripts\python.exe scripts/data/acquire_udiff_bhavcopy.py
.venv\Scripts\python.exe scripts/data/acquire_corporate_actions.py

# Data construction
.venv\Scripts\python.exe scripts/data/rebuild_market_data.py
.venv\Scripts\python.exe scripts/data/build_research_panel.py

# Research stages
.venv\Scripts\python.exe scripts/signals/build_momentum.py
.venv\Scripts\python.exe scripts/portfolio/build_shadow.py
.venv\Scripts\python.exe scripts/portfolio/build_volatility_overlay.py
.venv\Scripts\python.exe scripts/execution/run_frozen_corporate_action_accounts.py
```

The final command writes to the frozen account output directory. For a
non-destructive development replay, call the same account runner with a
separate output directory:

```powershell
.venv\Scripts\python.exe -c "from brindco_momentum.execution.development_accounts import ROOT, main; main(ROOT / 'results/project_refactor/reproduced_accounts', 'FROZEN_CORPORATE_ACTION_FRAMEWORK', True, True)"
```

Historical one-off inspection scripts are in `scripts/data/diagnostics/`.
They are retained for provenance, not part of the accepted production
pipeline. Historical reconstruction modules that use the old membership
source are also retained for provenance; the accepted panel builder reads
the official point-in-time membership artifact. The `evaluation/` package
is deliberately empty until the research evaluation stage is authorized.
See [plan.md](plan.md), the [panel specification](docs/specs/PANEL_BUILD_SPEC.md),
the [data description](docs/data_description.md), the
[experiment log](docs/EXPERIMENT_LOG.md), and the [stage audits](docs/audits/)
for economic definitions and input provenance.
