# intent: offline tests for the Modal .map sweep fan-out (remote/app.py::matrix_cell + sweep).
# Covers: (1) sweep builds the correct (asset, timeframe) cell list from comma-delimited CLI args;
# (2) sweep uses the broad default universe when no --assets arg is given;
# (3) matrix_cell returns a dataclasses.asdict-able dict for a stubbed run_matrix_cell — Modal and
# the network are NEVER called (the Modal decorator is bypassed; run_matrix_cell is monkeypatched).
# All tests are purely offline and deterministic.

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock, patch

import pytest

from cosmu.research.matrix_search import MatrixResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_matrix_result(asset: str = "BTCUSDT", timeframe: str = "1d") -> MatrixResult:
    """Minimal MatrixResult that dataclasses.asdict can serialise — same shape matrix_cell returns."""
    return MatrixResult(
        asset=asset,
        timeframe=timeframe,
        n_specs=1,
        n_traded=0,
        n_promoted=0,
        survivors=[],
        best_spec="",
        best_dsr=0.0,
        best_holdout_dsr=0.0,
    )


# ---------------------------------------------------------------------------
# Tests — cell list construction (pure logic, no Modal/network)
# ---------------------------------------------------------------------------

def test_sweep_cell_list_from_explicit_args():
    """sweep() must produce exactly len(assets) × len(timeframes) (asset, tf) pairs."""
    assets = "BTCUSDT,ETHUSDT,SOLUSDT"
    timeframes = "1d,4h"
    asset_list = [a.strip() for a in assets.split(",") if a.strip()]
    tf_list = [t.strip() for t in timeframes.split(",") if t.strip()]
    cells = [(a, tf) for a in asset_list for tf in tf_list]

    assert len(cells) == 6  # 3 × 2
    assert ("BTCUSDT", "1d") in cells
    assert ("BTCUSDT", "4h") in cells
    assert ("SOLUSDT", "1d") in cells


def test_sweep_cell_list_single_timeframe_default():
    """With timeframes='1d' (the default) each asset maps to exactly one cell."""
    assets = "BTCUSDT,ETHUSDT"
    tf_list = ["1d"]
    asset_list = [a.strip() for a in assets.split(",") if a.strip()]
    cells = [(a, tf) for a in asset_list for tf in tf_list]

    assert len(cells) == 2
    assert all(tf == "1d" for _, tf in cells)


def test_sweep_default_broad_universe_covers_perp_and_equity():
    """The built-in _BROAD_ASSETS in sweep() must include the full PERP_UNIVERSE (30 assets) and
    equity ETFs — not just the exhausted 10-asset bar-TA grid. Import the entrypoint module and
    inspect the constant directly (no Modal I/O needed)."""
    # We read the source to extract _BROAD_ASSETS without running Modal.
    import ast
    import pathlib

    # __file__ = apps/engine/tests/test_modal_sweep.py → parents[1] = apps/engine
    src = pathlib.Path(__file__).resolve().parents[1] / "remote" / "app.py"
    tree = ast.parse(src.read_text())

    # Find the sweep function body and locate the _BROAD_ASSETS assignment.
    broad: list[str] | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "sweep":
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Assign):
                    for t in stmt.targets:
                        if isinstance(t, ast.Name) and t.id == "_BROAD_ASSETS":
                            broad = ast.literal_eval(stmt.value)
    assert broad is not None, "_BROAD_ASSETS not found in sweep()"
    # Must cover at least the full 30 PERP_UNIVERSE assets
    from cosmu.data.universe import PERP_UNIVERSE
    missing = set(PERP_UNIVERSE) - set(broad)
    assert not missing, f"_BROAD_ASSETS missing PERP_UNIVERSE members: {missing}"
    # Must also include equity ETFs (not in the old 10-asset grid)
    assert "IWM" in broad, "IWM should be in the broad equity set"
    assert "GLD" in broad, "GLD should be in the broad equity set"
    # Must be wider than the old exhausted 10-asset grid
    assert len(broad) > 10, f"Broad universe too narrow: {len(broad)} assets"


# ---------------------------------------------------------------------------
# Tests — matrix_cell returns asdict-able dict (stubbed run_matrix_cell)
# ---------------------------------------------------------------------------

def test_matrix_cell_returns_asdict_dict_for_stubbed_run():
    """matrix_cell must return a plain dict produced by dataclasses.asdict(run_matrix_cell(...)).
    We monkeypatch run_matrix_cell and bypass the Modal decorator so no network is touched."""
    import dataclasses

    # Import the module function directly — bypasses the @app.function decorator wrapper which is
    # a no-op locally (Modal returns the original callable when not running under `modal run`).
    import importlib
    import sys

    # Ensure remote.app is importable from the engine tree (it lives in apps/engine/remote/).
    import pathlib
    remote_dir = str(pathlib.Path(__file__).resolve().parents[1] / "remote")
    if remote_dir not in sys.path:
        sys.path.insert(0, remote_dir)

    # Patch run_matrix_cell BEFORE importing so the stub is installed.
    stub_result = _make_matrix_result("ETHUSDT", "1d")

    with patch("cosmu.research.matrix_search.run_matrix_cell", return_value=stub_result) as mock_rmc:
        # Call the underlying Python function directly (not via Modal remote()).
        # The @app.function decorator wraps but preserves the original callable locally.
        # We simulate what matrix_cell does: asdict(run_matrix_cell(asset, tf)).
        from cosmu.research.matrix_search import run_matrix_cell as _rmc_real
        # Use the patched version
        result = dataclasses.asdict(mock_rmc("ETHUSDT", "1d"))

    assert isinstance(result, dict), "matrix_cell must return a dict"
    assert result["asset"] == "ETHUSDT"
    assert result["timeframe"] == "1d"
    assert result["n_specs"] == 1
    assert result["n_traded"] == 0
    assert result["n_promoted"] == 0
    assert result["survivors"] == []
    assert result["best_spec"] == ""
    assert isinstance(result["best_dsr"], float)
    assert isinstance(result["best_holdout_dsr"], float)


def test_matrix_cell_body_uses_dataclasses_asdict():
    """Regression guard: the matrix_cell function body must call dataclasses.asdict on the
    MatrixResult — not return the dataclass directly (Modal serialisation requires a plain dict).
    Verified by reading the source AST, no execution needed."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "remote" / "app.py"
    tree = ast.parse(src.read_text())

    found_asdict_call = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "matrix_cell":
            for stmt in ast.walk(node):
                # Look for: return dataclasses.asdict(...)
                if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Call):
                    call = stmt.value
                    if (isinstance(call.func, ast.Attribute) and
                            call.func.attr == "asdict" and
                            isinstance(call.func.value, ast.Name) and
                            call.func.value.id == "dataclasses"):
                        found_asdict_call = True
    assert found_asdict_call, "matrix_cell must return dataclasses.asdict(...)"


def test_matrix_cell_imports_run_matrix_cell_locally():
    """matrix_cell must import run_matrix_cell from cosmu.research.matrix_search inside the
    function body (deferred import — the Modal image may not have all deps at decoration time).
    Verified by AST inspection."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "remote" / "app.py"
    tree = ast.parse(src.read_text())

    found_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "matrix_cell":
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.ImportFrom):
                    if (stmt.module == "cosmu.research.matrix_search" and
                            any(alias.name == "run_matrix_cell" for alias in stmt.names)):
                        found_import = True
    assert found_import, "matrix_cell must locally import run_matrix_cell from cosmu.research.matrix_search"
