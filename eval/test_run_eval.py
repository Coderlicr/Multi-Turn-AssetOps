from pathlib import Path

import pytest

from eval import run_eval


@pytest.mark.parametrize(
    ("architecture", "entrypoint", "extra_flag"),
    [
        ("plan-execute", "plan-execute", "--show-plan"),
        ("supervisor-specialist", "supervisor-specialist", "--no-stream"),
        (
            "supervisor-specialist-parallel",
            "supervisor-specialist",
            "--parallel",
        ),
    ],
)
def test_build_agent_command_selects_real_architecture(
    monkeypatch, architecture, entrypoint, extra_flag
):
    monkeypatch.setattr(run_eval, "_resolve_entrypoint", lambda name: f"/bin/{name}")

    command = run_eval._build_agent_command(
        architecture=architecture,
        first_turn="hello",
        reference_date="2020-06-20",
        model_id="deepseek/deepseek-chat",
        agent_log_path=Path("agent.jsonl"),
    )

    assert command[0] == f"/bin/{entrypoint}"
    assert extra_flag in command
    assert command[-1] == "hello"
    assert command[command.index("--reference-date") + 1] == "2020-06-20"
    assert command[command.index("--model-id") + 1] == "deepseek/deepseek-chat"


def test_parallel_flag_only_used_for_parallel_architecture(monkeypatch):
    monkeypatch.setattr(run_eval, "_resolve_entrypoint", lambda name: f"/bin/{name}")
    common = {
        "first_turn": "hello",
        "reference_date": "2020-06-20",
        "model_id": None,
        "agent_log_path": Path("agent.jsonl"),
    }

    sequential = run_eval._build_agent_command("supervisor-specialist", **common)
    parallel = run_eval._build_agent_command(
        "supervisor-specialist-parallel", **common
    )

    assert "--parallel" not in sequential
    assert "--parallel" in parallel


def test_unknown_architecture_is_rejected():
    with pytest.raises(ValueError, match="Unknown architecture"):
        run_eval._build_agent_command(
            architecture="label-only",
            first_turn="hello",
            reference_date="2020-06-20",
            model_id=None,
            agent_log_path=Path("agent.jsonl"),
        )


def test_wtb_server_override_is_forwarded(monkeypatch):
    monkeypatch.setattr(run_eval, "_resolve_entrypoint", lambda name: f"/bin/{name}")
    command = run_eval._build_agent_command(
        architecture="supervisor-specialist",
        first_turn="hello",
        reference_date="2020-06-20",
        model_id="deepseek/deepseek-v4-flash",
        agent_log_path=Path("agent.jsonl"),
        server_specs=["maintie=maintie-mcp-server"],
    )
    assert command[command.index("--server") + 1] == "maintie=maintie-mcp-server"


def test_repo_root_can_make_relative_output_paths_absolute():
    output = run_eval.REPO_ROOT / Path("eval/results/smoke")
    assert output.is_absolute()
    assert output.relative_to(run_eval.REPO_ROOT) == Path("eval/results/smoke")
