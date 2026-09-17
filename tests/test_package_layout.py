import subprocess
import sys

from brindco_momentum.paths import ROOT


def test_repository_paths_are_independent_of_working_directory(tmp_path):
    assert (ROOT / "plan.md").is_file()
    code = (
        "from brindco_momentum.paths import ROOT; "
        "from brindco_momentum.execution.development_accounts import INPUTS; "
        "assert (ROOT / 'plan.md').is_file(); "
        "assert all(path.is_absolute() and path.is_relative_to(ROOT) "
        "for path in INPUTS.values())"
    )
    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, check=True)


def test_stage_modules_are_importable():
    from brindco_momentum.data import panel_build
    from brindco_momentum.signals import momentum_signal
    from brindco_momentum.portfolio import shadow_portfolio, volatility_overlay
    from brindco_momentum.execution import development_accounts

    assert callable(panel_build.build_panel)
    assert callable(momentum_signal.main)
    assert callable(shadow_portfolio.build_primary_shadow)
    assert callable(volatility_overlay.build_overlay)
    assert callable(development_accounts.main)
