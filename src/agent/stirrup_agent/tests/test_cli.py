"""Tests for the Stirrup agent CLI arguments."""

import pytest

from agent.stirrup_agent.cli import _build_parser, _parse_servers


def test_cli_accepts_max_reasoning_effort() -> None:
    args = _build_parser().parse_args(
        ["Return OK.", "--reasoning-effort", "max"]
    )

    assert args.reasoning_effort == "max"


def test_cli_accepts_reference_date() -> None:
    args = _build_parser().parse_args(
        ["Analyze the past month.", "--reference-date", "2020-06-20"]
    )

    assert args.reference_date == "2020-06-20"


def test_cli_accepts_trajectory_log_options(tmp_path) -> None:
    args = _build_parser().parse_args(
        ["Analyze the asset.", "--no-log", "--log-dir", str(tmp_path)]
    )

    assert args.no_log is True
    assert args.log_dir == tmp_path


def test_cli_server_overrides_are_parsed() -> None:
    assert _parse_servers(
        ["iot=iot-mcp-server", "custom=python -m servers.custom.main"]
    ) == {
        "iot": "iot-mcp-server",
        "custom": "python -m servers.custom.main",
    }


def test_cli_uses_default_servers_when_no_override_is_supplied() -> None:
    assert _parse_servers([]) is None


@pytest.mark.parametrize("entry", ["iot", "=iot-mcp-server", "iot="])
def test_cli_rejects_invalid_server_override(entry: str) -> None:
    with pytest.raises(ValueError, match="NAME=COMMAND"):
        _parse_servers([entry])
