"""Abstract base class for all Specialist agents.

Execution protocol (ReAct loop):
  Each specialist runs a Reasoning+Acting loop:
    1. LLM sees task + input artifacts + tool schemas + ALL prior tool results
    2. LLM decides the NEXT tool to call, or outputs {"done": true}
    3. Execute the tool, append result to context
    4. Repeat until done or max_tool_calls reached
  Then a separate LLM call generates the ArtifactEnvelope payload from all results.

This allows dynamic argument passing between tools: when iot.history_csv returns
a real csv_path, the next LLM step can see that path and pass it correctly to
utilities.csv_stats or tsfm.run_integrated_tsad.
"""

from __future__ import annotations

import json
import logging
from abc import ABC
from pathlib import Path

from agent.supervisor_specialist._utils import (
    call_llm,
    extract_file_paths,
    format_artifacts_summary,
    format_tool_results_for_prompt,
    format_tool_schemas_for_prompt,
    parse_json_from_llm,
)
from agent.supervisor_specialist.runtime.artifact_store import ArtifactStore
from agent.supervisor_specialist.runtime.behavior_log import BehaviorLog
from agent.supervisor_specialist.runtime.event_stream import EventStream
from agent.supervisor_specialist.runtime.mcp_tools import MCPToolClient
from agent.supervisor_specialist.schemas import (
    ArtifactDraft,
    ArtifactEnvelope,
    SpecialistResult,
    SpecialistFinal,
    TaskEnvelope,
    TimeWindow,
    ToolCallLog,
    ToolCallResult,
    ToolCallSummary,
)

_log = logging.getLogger(__name__)

_MAX_TOOL_CALLS_PER_SPECIALIST = 20


# ── ReAct step prompt ─────────────────────────────────────────────────────────

_REACT_STEP_PROMPT = """\
You are the {role_label} for an industrial asset operations AI system.

YOUR TASK:
{goal}

Case ID: {case_id}
Site: {site}
Assets: {asset_ids}
Time window: {time_window}
Focus metrics: {focus_metrics}

Input artifacts from previous specialists:
{input_artifacts_summary}

Your available tools (ONLY these are allowed):
{tool_schemas}

Tool calls executed so far in this task:
{prior_results}

Decide the NEXT action.

YOUR RESPONSE MUST BE A SINGLE RAW JSON OBJECT AND NOTHING ELSE.
Do not write any explanation. Output only valid JSON.

Option A — call one tool:
{{"tool_name": "<exact tool name from the list above>", "args": {{...}}}}

Option B — you have enough data, stop:
{{"done": true}}

Option C — this task cannot be done with the tools listed above:
{{"cannot_fulfill": true, "reason": "<one sentence: what was asked, and which capability you lack>"}}

Critical rules:
- If a prior tool returned a file path (e.g. csv_path in iot.history_csv result), use THAT EXACT PATH string in subsequent calls — never invent a path
- Artifact IDs such as "artifact_dc_001" or "artifact_ts_001" are references only; NEVER pass an artifact ID as a file path argument to a tool
- For file-based tools, use only concrete paths from prior tool results or input artifact payloads, e.g. values named csv_path, results_file, json_path, or entries listed under file_paths
- tool_name must exactly match one of the listed tool names
- Date/time args MUST be ISO 8601 strings, e.g. "2020-06-01T00:00:00" — never use expressions or function calls
- Stop (done=true) once you have enough data to produce a meaningful artifact
- Use cannot_fulfill when the task asks for something none of your tools produce (for
  example a causal validation, a ranking, or a narrative plan when you only have
  retrieval tools). Say so instead of returning the closest thing you can compute:
  a wrong-but-successful-looking answer makes the supervisor ask you again
- Never copy an input artifact's payload through as if it were your own result
- Do NOT repeat a tool that already succeeded with the same arguments
- If a tool has FAILED and you are about to call it again with essentially the same arguments, do NOT retry — output {{"done": true}} or try a completely different tool instead
- When you receive a CSV file path (from any prior tool result or input artifact) and you are unsure of the column names, call utilities.csv_stats with ONLY the csv_path (omit the columns parameter) first — this returns all_columns so you know the exact column names before making further calls
{extra_rules}
JSON:"""


# ── Artifact generation prompt (unchanged from original) ─────────────────────

_ARTIFACT_PROMPT = """\
You are the {role_label} for an industrial asset operations AI system.

YOUR TASK:
{goal}

Case ID: {case_id}
Site: {site}
Assets: {asset_ids}

Input artifacts:
{input_artifacts_summary}

Tool call results:
{tool_results}

Based on the tool results, produce structured analysis artifacts.

YOUR RESPONSE MUST BE A SINGLE RAW JSON OBJECT AND NOTHING ELSE.
Do not write any explanation. Output only valid JSON.
Use EXACTLY this schema:
{{
  "artifacts": [
    {{
      "artifact_type": "<one of: {allowed_artifact_types}>",
      "asset_ids": [...],
      "time_window": {{"start": "...", "end": "..."}},
      "source_artifacts": [...],
      "payload": {{...}},
      "open_questions": [...],
      "summary": "<2-4 sentences: what you were asked to do, what tools you called, and what result/conclusion you obtained; include requested recommendations for planning_result/draft_action artifacts, but do not add unrelated recommendations>"
    }}
  ]
}}

Rules:
- artifact_type must be one of: {allowed_artifact_types}
- payload MUST include concrete quantitative findings from tool results — do NOT write only prose descriptions:
  * For anomaly detection results: include top-level operation="anomaly_detection", task_completed=true, total anomaly_count, results_file, and target_columns; also organize per-asset/per-column details by asset — e.g. {{"Chiller 3": {{"Supply Temperature": {{"anomaly_count": 345}}, ...}}, "Chiller 9": {{...}}}}; never aggregate across assets — each asset must have its own anomaly counts; always include the results_file path per asset
  * For sensor/CSV data: include key stats (mean, std, min, max) for the most relevant columns
  * For work orders: include counts, types, and date ranges
  * For reasoning_result artifacts, top-level task_completed, operation, primary_hypothesis or root_cause, competing_hypotheses when alternatives are being compared, evidence, confidence, and remaining_uncertainty fields are REQUIRED; do not hide the diagnosis only inside an asset-named nested object or only in summary text
  * Always include csv_path or file paths from tool results so downstream specialists can use them
- open_questions should list uncertainties or recommended follow-up investigations
- source_artifacts should list input artifact IDs you used (from the input artifacts section)
- The summary must accurately name the tools that actually succeeded; do not say that fine-tuning, forecasting, or anomaly detection was performed unless the corresponding tsfm tool succeeded
- For reasoning_result artifacts, the summary must state the current conclusion in one sentence, including the primary hypothesis/root cause and whether confidence is high, moderate, low, or unresolved
{extra_artifact_rules}

JSON:"""


# ── Helper ────────────────────────────────────────────────────────────────────

def format_specialist_catalog(specialists: list[type["SpecialistAgent"]]) -> str:
    """Render the supervisor-facing capability catalog.

    The tool list is printed verbatim from allowed_tools so the supervisor sees
    what a specialist can actually reach, rather than a hand-written blurb that
    may promise more than the tools deliver.
    """
    blocks = []
    for cls in specialists:
        tools = ", ".join(sorted(cls.allowed_tools)) or "(none)"
        block = [f"- {cls.role}", f"    CAN: {cls.capability_summary}", f"    TOOLS: {tools}"]
        if cls.cannot_do:
            block.append(f"    CANNOT: {'; '.join(cls.cannot_do)}")
        blocks.append("\n".join(block))
    return "\n".join(blocks)


def _format_react_results(results: list[ToolCallResult]) -> str:
    """Format prior tool results for the ReAct step prompt.

    Shows full result values (up to 2000 chars each) so LLM can extract
    file paths, IDs, or other values to use in subsequent tool calls.
    """
    if not results:
        return "(none — this is the first tool call)"
    lines = []
    for r in results:
        args_preview = json.dumps(r.args, ensure_ascii=False)[:300]
        if r.status == "ok":
            result_str = str(r.result)[:2000]
            if len(str(r.result or "")) > 2000:
                result_str += "... [truncated]"
            lines.append(
                f"[{r.order}] {r.tool_name}({args_preview}) → OK\n"
                f"    Result: {result_str}"
            )
        else:
            lines.append(
                f"[{r.order}] {r.tool_name}({args_preview}) → FAILED\n"
                f"    Error: {r.error}"
            )
    return "\n\n".join(lines)


def _summarize_tool_calls(results: list[ToolCallResult]) -> list[ToolCallSummary]:
    """Compact tool results for cross-turn memory."""
    summaries: list[ToolCallSummary] = []
    for r in results:
        result_text = str(r.result or "")
        preview = result_text[:700] if result_text else None
        if preview and len(result_text) > 700:
            preview += "... [truncated]"
        summaries.append(
            ToolCallSummary(
                order=r.order,
                tool_name=r.tool_name,
                args=r.args,
                status=r.status,
                result_preview=preview,
                error=r.error,
                file_paths=extract_file_paths(r.result),
            )
        )
    return summaries


# ── Base class ────────────────────────────────────────────────────────────────

class SpecialistAgent(ABC):
    role: str
    role_prefix: str
    allowed_tools: set[str]
    allowed_artifact_types: tuple[str, ...]
    #: One line on what this specialist can deliver, phrased in terms its tools support.
    capability_summary: str = ""
    #: Things this specialist must NOT be asked for, because no tool it owns can do them.
    #: Kept next to allowed_tools so the two cannot drift apart unnoticed.
    cannot_do: tuple[str, ...] = ()
    _extra_react_rules: str = ""  # Subclasses can override to inject role-specific rules
    _extra_artifact_rules: str = ""  # Subclasses can override to inject role-specific artifact rules

    def __init__(
        self,
        llm,
        mcp_tools: MCPToolClient,
        artifact_store: ArtifactStore,
        behavior_log: BehaviorLog,
        event_stream: EventStream,
    ) -> None:
        self.llm = llm
        self.mcp_tools = mcp_tools
        self.artifact_store = artifact_store
        self.logger = behavior_log
        self.event_stream = event_stream

    @property
    def _role_label(self) -> str:
        return self.role.replace("_", " ").title()

    async def run(self, task: TaskEnvelope) -> SpecialistResult:
        self.event_stream.emit(
            case_id=task.case_id,
            agent_role=self.role,
            task_type=task.task_type,
            status="running",
            message=f"Starting: {task.goal[:80]}",
        )

        input_artifacts = self.artifact_store.get_many(task.input_artifacts)
        tool_schemas = await self.mcp_tools.get_allowed_tool_schemas(self.allowed_tools)

        # ReAct loop: interleave LLM decisions with tool execution
        results, unmet_reason = await self._run_react_loop(task, input_artifacts, tool_schemas)

        if unmet_reason:
            # Deliberately skip artifact generation. Asking for an artifact here is
            # what produced the fake successes: the model copies an input payload,
            # stamps task_completed=true, and the supervisor re-dispatches forever.
            return self._unfulfilled_result(task, results, unmet_reason)

        # Artifact generation: LLM synthesizes all tool results into artifacts
        final = await self._call_llm_for_artifacts(task, input_artifacts, results)

        # Wrap ArtifactDraft -> ArtifactEnvelope (runtime assigns artifact_id)
        successful_tools = [r.tool_name for r in results if r.status == "ok"]
        artifacts: list[ArtifactEnvelope] = [
            ArtifactEnvelope(
                artifact_id=self.artifact_store.next_id(self.role_prefix),
                case_id=task.case_id,
                producer=self.role,
                artifact_type=draft.artifact_type,
                asset_ids=draft.asset_ids,
                time_window=self._artifact_time_window(task, draft),
                source_tools=successful_tools,
                source_artifacts=self._valid_source_artifacts(task, draft.source_artifacts),
                payload=draft.payload,
                open_questions=draft.open_questions,
                summary=draft.summary,
            )
            for draft in final.artifacts
        ]
        self._postprocess_artifacts(task, artifacts, results)

        self.logger.write(
            case_id=task.case_id,
            agent_role=self.role,
            task_type=task.task_type,
            input_artifact_ids=task.input_artifacts,
            tool_calls=[
                ToolCallLog(
                    order=r.order,
                    tool_name=r.tool_name,
                    args=r.args,
                    status=r.status,
                    result=r.result,
                    error=r.error,
                )
                for r in results
            ],
            output_artifact_ids=[a.artifact_id for a in artifacts],
            output_artifacts=artifacts,
            status="ok",
            turn_id=task.constraints.get("turn_id"),
            task=task,
        )

        self.event_stream.emit(
            case_id=task.case_id,
            agent_role=self.role,
            task_type=task.task_type,
            status="completed",
            message=f"Produced {len(artifacts)} artifact(s): {[a.artifact_id for a in artifacts]}",
        )
        for artifact in artifacts:
            if artifact.summary:
                self.event_stream.emit(
                    case_id=task.case_id,
                    agent_role=self.role,
                    task_type=task.task_type,
                    status="completed",
                    message=f"[{artifact.artifact_id}] {artifact.summary}",
                )
        return SpecialistResult(
            artifacts=artifacts,
            tool_calls=_summarize_tool_calls(results),
        )

    def _unfulfilled_result(
        self,
        task: TaskEnvelope,
        results: list[ToolCallResult],
        reason: str,
    ) -> SpecialistResult:
        """Report back that the task is outside this specialist's tools."""
        self.logger.write(
            case_id=task.case_id,
            agent_role=self.role,
            task_type=task.task_type,
            input_artifact_ids=task.input_artifacts,
            tool_calls=[
                ToolCallLog(
                    order=r.order, tool_name=r.tool_name, args=r.args,
                    status=r.status, result=r.result, error=r.error,
                )
                for r in results
            ],
            output_artifact_ids=[],
            status="cannot_fulfill",
            turn_id=task.constraints.get("turn_id"),
            task=task,
            unmet_reason=reason,
        )
        self.event_stream.emit(
            case_id=task.case_id,
            agent_role=self.role,
            task_type=task.task_type,
            status="cannot_fulfill",
            message=f"Cannot fulfill: {reason}",
        )
        return SpecialistResult(
            artifacts=[],
            tool_calls=_summarize_tool_calls(results),
            outcome="cannot_fulfill",
            unmet_reason=reason,
        )

    async def _run_react_loop(
        self,
        task: TaskEnvelope,
        input_artifacts: list[ArtifactEnvelope],
        tool_schemas: list[dict],
    ) -> tuple[list[ToolCallResult], str | None]:
        """ReAct loop: LLM decides one tool at a time, sees each result before deciding next.

        Returns the tool results and, when the specialist declared the task
        outside its tools, the reason it gave.
        """
        results: list[ToolCallResult] = []

        for call_num in range(1, _MAX_TOOL_CALLS_PER_SPECIALIST + 1):
            prompt = _REACT_STEP_PROMPT.format(
                role_label=self._role_label,
                goal=task.goal,
                case_id=task.case_id,
                site=task.site,
                asset_ids=", ".join(task.asset_ids) or "(to be discovered)",
                time_window=task.time_window.model_dump_json(),
                focus_metrics=", ".join(task.focus_metrics) or "(all relevant)",
                input_artifacts_summary=format_artifacts_summary(input_artifacts),
                tool_schemas=format_tool_schemas_for_prompt(tool_schemas),
                prior_results=_format_react_results(results),
                extra_rules=self._extra_react_rules,
            )

            raw = await call_llm(self.llm, prompt)
            parsed = parse_json_from_llm(raw)

            if parsed is None:
                _log.warning(
                    "%s: ReAct step %d: could not parse LLM response — stopping loop.",
                    self.role, call_num,
                )
                break

            # LLM declares the task outside its tool set
            if parsed.get("cannot_fulfill"):
                reason = str(parsed.get("reason") or "").strip() or (
                    "Specialist reported the task cannot be fulfilled with its tools."
                )
                _log.info("%s: cannot fulfill task: %s", self.role, reason)
                return results, reason

            # LLM signals it is done
            if parsed.get("done"):
                done_blocker = self._done_blocking_message(task, input_artifacts, results)
                if done_blocker:
                    results.append(ToolCallResult(
                        order=call_num,
                        tool_name="internal.done_guard",
                        args={},
                        status="failed",
                        error=done_blocker,
                    ))
                    continue
                _log.debug("%s: ReAct loop done after %d call(s).", self.role, call_num - 1)
                break

            tool_name = parsed.get("tool_name")
            if not tool_name:
                _log.warning(
                    "%s: ReAct step %d: response has no tool_name and no done=true — stopping.",
                    self.role, call_num,
                )
                break

            args = parsed.get("args") or {}

            # Unauthorised tool guard
            if tool_name not in self.allowed_tools:
                _log.warning("%s: unauthorised tool '%s' blocked.", self.role, tool_name)
                self.event_stream.emit(
                    case_id=task.case_id,
                    agent_role=self.role,
                    task_type=task.task_type,
                    status="failed",
                    message=f"Unauthorised tool blocked: {tool_name}",
                )
                results.append(ToolCallResult(
                    order=call_num, tool_name=tool_name, args=args,
                    status="failed", error="Tool is not allowed for this specialist.",
                ))
                continue

            file_arg_error = self._validate_file_args(
                tool_name, args, input_artifacts, results
            )
            if file_arg_error:
                _log.warning("%s: invalid file argument blocked: %s", self.role, file_arg_error)
                self.event_stream.emit(
                    case_id=task.case_id,
                    agent_role=self.role,
                    task_type=task.task_type,
                    status="failed",
                    message=file_arg_error,
                )
                results.append(ToolCallResult(
                    order=call_num,
                    tool_name=tool_name,
                    args=args,
                    status="failed",
                    error=file_arg_error,
                ))
                continue

            self.event_stream.emit(
                case_id=task.case_id,
                agent_role=self.role,
                task_type=task.task_type,
                status="running",
                message=f"Calling {tool_name}",
            )

            mcp_result = await self.mcp_tools.call(tool_name, args)
            results.append(ToolCallResult(
                order=call_num, tool_name=tool_name, args=args,
                status=mcp_result.status, result=mcp_result.result, error=mcp_result.error,
            ))

            if mcp_result.status == "ok":
                self.event_stream.emit(
                    case_id=task.case_id,
                    agent_role=self.role,
                    task_type=task.task_type,
                    status="completed",
                    message=f"{tool_name} succeeded",
                )
            else:
                self.event_stream.emit(
                    case_id=task.case_id,
                    agent_role=self.role,
                    task_type=task.task_type,
                    status="failed",
                    message=f"{tool_name} failed: {mcp_result.error}",
                )

            # Consecutive-failure guard: if the same tool failed 3 times in a row,
            # stop the loop — retrying further won't help.
            if len(results) >= 3:
                last3 = results[-3:]
                if (
                    all(r.status == "failed" for r in last3)
                    and len({r.tool_name for r in last3}) == 1
                ):
                    _log.warning(
                        "%s: tool '%s' failed 3 consecutive times — stopping ReAct loop.",
                        self.role, last3[-1].tool_name,
                    )
                    break

        return results, None

    def _done_blocking_message(
        self,
        task: TaskEnvelope,
        input_artifacts: list[ArtifactEnvelope],
        results: list[ToolCallResult],
    ) -> str | None:
        return None

    def _postprocess_artifacts(
        self,
        task: TaskEnvelope,
        artifacts: list[ArtifactEnvelope],
        results: list[ToolCallResult],
    ) -> None:
        return None

    @staticmethod
    def _artifact_time_window(task: TaskEnvelope, draft: ArtifactDraft) -> TimeWindow:
        if task.time_window.start or task.time_window.end:
            return task.time_window
        return draft.time_window

    @staticmethod
    def _valid_source_artifacts(task: TaskEnvelope, source_artifacts: list[str]) -> list[str]:
        allowed = set(task.input_artifacts)
        return [artifact_id for artifact_id in source_artifacts if artifact_id in allowed]

    def _validate_file_args(
        self,
        tool_name: str,
        args: dict,
        input_artifacts: list[ArtifactEnvelope],
        results: list[ToolCallResult],
    ) -> str | None:
        del input_artifacts, results
        if not (
            tool_name.startswith("tsfm.")
            or tool_name in {"utilities.csv_stats", "utilities.json_reader"}
        ):
            return None

        file_arg_names = {
            "csv_path",
            "dataset_path",
            "results_file",
            "json_path",
            "path",
            "file_path",
        }
        for name, value in args.items():
            if name not in file_arg_names or not isinstance(value, str):
                continue
            if value.startswith("artifact_"):
                return (
                    f"{tool_name} received artifact ID '{value}' as a file path. "
                    "Use a concrete file path from an input artifact payload instead."
                )
            if value.startswith("path/to/") or value.startswith("<") or value.endswith(">"):
                return (
                    f"{tool_name} received placeholder file path '{value}'. "
                    "Use an existing concrete file path from an input artifact payload."
                )
            if not Path(value).is_file():
                return (
                    f"{tool_name} received non-existent file path '{value}'. "
                    "Collect the data first or use a concrete file path returned by a prior tool."
                )
        return None

    async def _call_llm_for_artifacts(
        self,
        task: TaskEnvelope,
        input_artifacts: list[ArtifactEnvelope],
        tool_results: list[ToolCallResult],
    ) -> SpecialistFinal:
        prompt = _ARTIFACT_PROMPT.format(
            role_label=self._role_label,
            goal=task.goal,
            case_id=task.case_id,
            site=task.site,
            asset_ids=", ".join(task.asset_ids) or "(discovered from tools)",
            input_artifacts_summary=format_artifacts_summary(input_artifacts),
            tool_results=format_tool_results_for_prompt(tool_results),
            allowed_artifact_types=", ".join(self.allowed_artifact_types),
            extra_artifact_rules=self._extra_artifact_rules,
        )
        for attempt in range(2):
            raw = await call_llm(self.llm, prompt)
            parsed = parse_json_from_llm(raw)
            if parsed is not None:
                try:
                    return SpecialistFinal.model_validate(parsed)
                except Exception:  # noqa: BLE001
                    pass
            if attempt == 0:
                prompt += "\n\nYour previous response could not be parsed. Output ONLY a valid JSON object."

        _log.warning("%s: SpecialistFinal generation failed; creating fallback artifact.", self.role)
        fallback_type = self.allowed_artifact_types[0]
        # Include tool results summary in fallback so Supervisor can detect failure
        return SpecialistFinal(
            artifacts=[
                ArtifactDraft(
                    artifact_type=fallback_type,
                    asset_ids=task.asset_ids,
                    time_window=TimeWindow(),
                    source_artifacts=task.input_artifacts,
                    payload={
                        "_status": "fallback_error",
                        "note": "LLM artifact generation failed.",
                        "successful_tools": [r.tool_name for r in tool_results if r.status == "ok"],
                        "failed_tools": [r.tool_name for r in tool_results if r.status == "failed"],
                    },
                    open_questions=["Artifact generation failed — manual review required."],
                )
            ]
        )
