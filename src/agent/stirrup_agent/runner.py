"""AgentRunner backed by Artificial Analysis' Stirrup framework.

Stirrup is an in-process Python library (not a separate binary), so this
runner builds a client, attaches the Multi-Turn AssetOps MCP servers as a tool
provider, runs the agent loop, and maps the returned message history onto the
runner-local trajectory model.

Model routing:
  * OpenAI-compatible router prefixes -> Stirrup ``ChatCompletionsClient``.
  * ``<provider>/<model>``     -> Stirrup ``LiteLLMClient``, which reaches
    Anthropic, watsonx, Bedrock, etc. natively through LiteLLM.  This means
    ``watsonx/...`` models work directly here, without the proxy detour Goose
    needed.

Tracks (the code switch):
  * ``code_enabled=False`` -> run the agent with MCP tools only.
  * ``code_enabled=True``  -> a sandboxed code-execution tool (Docker by
    default) is added, so the agent may solve a scenario by writing code.
    This is useful for local data processing and validation.

Stirrup's web/default tools are deliberately NOT attached: the environment
under test is the MCP servers (plus, on the code track, code execution), so
adding web search would contaminate the benchmark.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import shlex
import shutil
from pathlib import Path

from llm.routers import resolve_model, resolve_router_creds
from .finish_tool import ASSETOPS_FINISH_TOOL
from .handoff_tools import build_handoff_tools
from .models import AgentResult
from .prompt import build_agent_system_prompt
from .trajectory import build_trajectory, final_answer

_log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_DEFAULT_MODEL = "watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8"
# The code-track image carries the scientific stack used for local analysis.
_DEFAULT_CODE_IMAGE = os.environ.get("STIRRUP_CODE_IMAGE", "assetops-code")
_WORKING_CONTEXT_BUDGET = 100_000
_CONTEXT_SUMMARIZATION_CUTOFF = 0.75
DEFAULT_SERVER_PATHS: dict[str, str] = {
    "iot": "iot-mcp-server",
    "utilities": "utilities-mcp-server",
    "fmsr": "fmsr-mcp-server",
    "tsfm": "tsfm-mcp-server",
    "wo": "wo-mcp-server",
}
_CODE_EXEC_SYSTEM_PROMPT = """\
Code execution:
- MCP tools and their definitions are authoritative for domain data and semantics.
  Never use code to query backing services or bypass an available MCP tool.
- Do not overuse code_exec. Answer directly from MCP results, domain knowledge,
  and basic reasoning or arithmetic when sufficient. Use code_exec only for
  necessary computation, data processing, workspace inspection, or validation.
  Never use it for planning, comments, placeholders, or empty scripts.
- Prefer one complete script that inspects, analyzes, and verifies. Do not repeat
  equivalent experiments; correct failures directly.
- Stay inside the execution workspace and use relative paths. Workspace state
  persists across code_exec calls.
- For artifacts, inspect only the schema, counts, a small sample, or the specific
  rows or fields needed, then process in place. If an artifact exceeds 200 KiB,
  never print it in full; extract and process the relevant subset in bounded
  batches. Avoid large record lists and verbose diagnostics. Reuse snapshots
  unless domain state has changed.
"""
_DOCKER_CODE_EXEC_SYSTEM_PROMPT = """\
The Docker execution workspace is /workspace. Host filesystem paths are not
available inside the container. NumPy, pandas, and SciPy are installed; check
availability before using other packages.
"""
_LOCAL_CODE_EXEC_SYSTEM_PROMPT = """\
The local execution workspace is a temporary directory, but commands run on the
host with the current user's permissions. Keep all reads and writes inside the
workspace and use relative paths.
"""


def _build_full_summary_logger():
    """Return a Stirrup logger that displays generated summaries without truncation."""
    from rich.text import Text
    from stirrup.utils.logging import AgentLogger, console

    class _FullSummaryLogger(AgentLogger):
        def context_summarization_complete(
            self, summary: str, bridge: str
        ) -> None:
            console.print(Text("✓ Summary Generated", style="bold green"))
            console.print(summary, markup=False, soft_wrap=True)

    return _FullSummaryLogger()


def _copy_workspace_contents(source: Path, destination: Path) -> None:
    """Copy code-exec workspace contents out of Stirrup's temp child dir."""
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _preserving_provider_class(provider_cls):
    class _PreservingCodeExecToolProvider(provider_cls):
        def __init__(self, *args, preserve_dir: Path, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._assetops_preserve_dir = preserve_dir

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            temp_dir = self.temp_dir
            if temp_dir is not None and temp_dir.exists():
                try:
                    fix_ownership = getattr(self, "_fix_file_ownership", None)
                    if fix_ownership is not None:
                        await fix_ownership()
                    _copy_workspace_contents(temp_dir, self._assetops_preserve_dir)
                    _log.info(
                        "Preserved Stirrup code workspace %s -> %s",
                        temp_dir,
                        self._assetops_preserve_dir,
                    )
                except Exception:
                    _log.warning(
                        "Failed to preserve Stirrup code workspace %s",
                        temp_dir,
                        exc_info=True,
                    )
            return await super().__aexit__(exc_type, exc_val, exc_tb)

    return _PreservingCodeExecToolProvider


class StirrupAgentRunner:
    """Run a question through a Stirrup agent against the MCP servers.

    Args:
        llm: Unused compatibility argument.
        server_paths: MCP server specs. Defaults to the five Multi-Turn servers.
        model: ``litellm_proxy/<provider>/<model>`` or native ``<provider>/<model>``.
        code_enabled: Add a sandboxed code-execution tool (the code track).
        code_backend: ``"docker"`` (sandboxed, default) or ``"local"``.
        workspace_dir: Optional host base directory for Docker/local code execution.
        preserve_workspace: Copy final code-execution files back into ``workspace_dir``.
        max_turns: Stirrup agent loop bound.
        temperature: Optional sampling temperature passed to the Stirrup client.
        reasoning_effort: Optional reasoning effort passed to the Stirrup client.
        reference_date: UTC date used to resolve relative time expressions. Uses
            today's UTC date when omitted.
    """

    def __init__(
        self,
        llm=None,
        server_paths=None,
        model: str = _DEFAULT_MODEL,
        code_enabled: bool = True,
        code_backend: str = "docker",
        workspace_dir: Path | str | None = None,
        preserve_workspace: bool = False,
        max_turns: int = 30,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        reference_date: str | None = None,
    ) -> None:
        del llm
        self._server_paths = dict(
            DEFAULT_SERVER_PATHS if server_paths is None else server_paths
        )
        if code_backend not in {"docker", "local"}:
            raise ValueError("code_backend must be 'docker' or 'local'")
        self._model_id = model
        self._code_enabled = code_enabled
        self._code_backend = code_backend
        self._workspace_dir = (
            Path(workspace_dir).expanduser().resolve()
            if workspace_dir is not None
            else None
        )
        if preserve_workspace and self._workspace_dir is None:
            raise ValueError("workspace_dir is required when preserve_workspace is enabled")
        if preserve_workspace and code_backend not in {"docker", "local"}:
            raise ValueError(
                "preserve_workspace is only supported with docker or local code backends"
            )
        self._preserve_workspace = preserve_workspace
        self._max_turns = max_turns
        self._temperature = temperature
        self._reasoning_effort = reasoning_effort
        self._reference_date = self._resolve_reference_date(reference_date)

    @staticmethod
    def _resolve_reference_date(reference_date: str | None) -> str:
        """Return a strict ISO date, defaulting to today's UTC date."""
        if reference_date is None:
            return _dt.datetime.now(_dt.UTC).date().isoformat()
        try:
            parsed = _dt.date.fromisoformat(reference_date)
        except ValueError as exc:
            raise ValueError(
                "reference_date must use YYYY-MM-DD format, "
                f"received {reference_date!r}"
            ) from exc
        if parsed.isoformat() != reference_date:
            raise ValueError(
                "reference_date must use YYYY-MM-DD format, "
                f"received {reference_date!r}"
            )
        return parsed.isoformat()

    # -- client / tools ----------------------------------------------------

    def _build_client(self):
        """Build a Stirrup LLM client for the configured model id."""
        client_kwargs = (
            {"temperature": self._temperature}
            if self._temperature is not None
            else None
        )

        creds = resolve_router_creds(self._model_id)
        if creds is not None:
            from stirrup.clients.chat_completions_client import ChatCompletionsClient

            common_kwargs = {
                "model": resolve_model(self._model_id),
                "context_window_tokens": _WORKING_CONTEXT_BUDGET,
                "base_url": creds.base_url.rstrip("/"),
                "api_key": creds.api_key,
                "reasoning_effort": self._reasoning_effort,
                "kwargs": client_kwargs,
            }
            client = ChatCompletionsClient(**common_kwargs)
        else:
            from stirrup.clients.litellm_client import LiteLLMClient

            client = LiteLLMClient(
                model=self._model_id,
                context_window_tokens=_WORKING_CONTEXT_BUDGET,
                reasoning_effort=self._reasoning_effort,
                kwargs=client_kwargs,
            )
        return client

    def _build_mcp_config(self):
        """Build the Stirrup MCP configuration for Multi-Turn AssetOps servers.

        Each server is a stdio process launched exactly as the other runners
        launch it: ``uv run --directory <repo> <entry-point>``.
        """
        from stirrup.tools.mcp import MCPConfig

        servers: dict[str, dict] = {}
        for name, spec in self._server_paths.items():
            command_args = shlex.split(str(spec))
            if not command_args:
                raise ValueError(f"MCP server command for {name!r} is empty")
            servers[name] = {
                "command": "uv",
                "args": ["run", "--directory", str(_REPO_ROOT), *command_args],
                "cwd": str(_REPO_ROOT),
                "env": dict(os.environ),
            }
        return MCPConfig.model_validate({"mcpServers": servers})

    def _build_mcp_provider(self, *, exec_env=None):
        """Build the MCP provider, bridging large results when code is enabled."""
        config = self._build_mcp_config()
        if exec_env is None:
            from stirrup.tools.mcp import MCPToolProvider

            return MCPToolProvider(config=config)

        from .workspace_bridge import WorkspaceBridgedMCPToolProvider

        return WorkspaceBridgedMCPToolProvider(
            config=config,
            exec_env=exec_env,
        )

    def _build_code_provider(self):
        """Build the sandboxed code-execution provider for the code track."""
        if self._code_backend == "local":
            from stirrup.tools.code_backends.local import LocalCodeExecToolProvider

            provider_cls = LocalCodeExecToolProvider
            kwargs = {"temp_base_dir": self._workspace_dir}
            if self._preserve_workspace:
                provider_cls = _preserving_provider_class(provider_cls)
                kwargs["preserve_dir"] = self._workspace_dir
            return provider_cls(**kwargs)
        from stirrup.tools.code_backends.docker import DockerCodeExecToolProvider

        if self._preserve_workspace:
            provider_cls = _preserving_provider_class(DockerCodeExecToolProvider)
            return provider_cls(
                _DEFAULT_CODE_IMAGE,
                is_dockerfile=False,
                temp_base_dir=self._workspace_dir,
                preserve_dir=self._workspace_dir,
            )
        return DockerCodeExecToolProvider.from_image(
            _DEFAULT_CODE_IMAGE,
            temp_base_dir=self._workspace_dir,
        )

    def _build_tools(self) -> list:
        if not self._code_enabled:
            return [self._build_mcp_provider()]

        code_provider = self._build_code_provider()
        return [
            code_provider,
            *build_handoff_tools(code_provider),
            self._build_mcp_provider(exec_env=code_provider),
        ]

    def _build_system_prompt(self) -> str:
        """Append code-execution guidance when the code track is enabled."""
        base_prompt = build_agent_system_prompt(self._reference_date)
        if not self._code_enabled:
            return base_prompt

        backend_prompt = (
            _DOCKER_CODE_EXEC_SYSTEM_PROMPT
            if self._code_backend == "docker"
            else _LOCAL_CODE_EXEC_SYSTEM_PROMPT
        )
        return f"{base_prompt}\n{_CODE_EXEC_SYSTEM_PROMPT}\n{backend_prompt}"

    # -- run ---------------------------------------------------------------

    async def run(self, question: str) -> AgentResult:
        from stirrup import Agent

        started_at = _dt.datetime.now(_dt.UTC).isoformat()

        client = self._build_client()
        agent = Agent(
            client=client,
            name="assetops",
            system_prompt=self._build_system_prompt(),
            tools=self._build_tools(),
            finish_tool=ASSETOPS_FINISH_TOOL,
            max_turns=self._max_turns,
            context_summarization_cutoff=_CONTEXT_SUMMARIZATION_CUTOFF,
            logger=_build_full_summary_logger(),
        )

        _log.info(
            "StirrupAgentRunner: starting (model=%s, code=%s, backend=%s, workspace=%s, preserve=%s)",
            self._model_id,
            self._code_enabled,
            self._code_backend,
            self._workspace_dir,
            self._preserve_workspace,
        )

        async with agent.session() as session:
            finish_params, history, _metadata = await session.run(question)

        trajectory = build_trajectory(history)
        trajectory.started_at = started_at
        answer = final_answer(history, finish_params)
        _log.info(
            "StirrupAgentRunner: done (turns=%d, tool_calls=%d)",
            len(trajectory.turns),
            len(trajectory.all_tool_calls),
        )
        return AgentResult(question=question, answer=answer, trajectory=trajectory)
