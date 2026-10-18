import pytest

from . import parallel_support


@pytest.fixture
def anyio_backend():
    """The runner and MCP client use asyncio APIs."""
    return "asyncio"


@pytest.fixture
def existing_csv_inputs(tmp_path, monkeypatch):
    """Give tests that consume CSV paths real, isolated input files."""
    monkeypatch.setattr(parallel_support, "_CSV_ROOT", tmp_path)
    for asset in (3, 4, 6, 9):
        (tmp_path / f"chiller_{asset}.csv").write_text(
            "timestamp,supply_temp\n2020-06-01,50\n"
        )
