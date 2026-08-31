"""Budgeted, multi-turn MaintIE-only path for Supervisor-Specialist."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from agent.supervisor_specialist._utils import (
    call_llm,
    format_tool_schemas_for_prompt,
    parse_json_from_llm,
)
from agent.supervisor_specialist.agents.base import _summarize_tool_calls
from agent.supervisor_specialist.runtime.behavior_log import BehaviorLog
from agent.supervisor_specialist.runtime.event_stream import EventStream
from agent.supervisor_specialist.runtime.mcp_tools import MCPToolClient
from agent.supervisor_specialist.schemas import (
    ConversationMemory,
    DialogTurnRecord,
    ExecutionBudget,
    MaintIEResultDraft,
    MaintIESelection,
    MCPToolResult,
    SpecialistStepDecision,
    SupervisorTurnResult,
    ToolCallLog,
    ToolCallRequest,
    ToolCallResult,
)

MAINTIE_TOOLS = {
    "maintie.search",
    "maintie.extract",
    "maintie.count",
    "maintie.group_count",
    "maintie.rank",
    "maintie.get_text",
    "maintie.compare",
}

_TERMINAL_AGGREGATE_TOOLS = {
    "maintie.count",
    "maintie.group_count",
    "maintie.rank",
    "maintie.compare",
}
_LINES_AND_DRIVES_TERMS = {
    "belt",
    "belts",
    "chain",
    "chains",
    "hose",
    "hoses",
    "cable",
    "cables",
}


def _compact_value(value: Any) -> Any:
    """Remove large ID vectors from prompts while keeping their cardinality."""
    if isinstance(value, str):
        try:
            return _compact_value(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return value[:4000]
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, child in value.items():
            if key == "wo_ids" and isinstance(child, list):
                compact[key] = f"<stored selection: {len(child)} IDs>"
            else:
                compact[key] = _compact_value(child)
        return compact
    if isinstance(value, list):
        if len(value) > 100:
            return [_compact_value(child) for child in value[:100]] + [
                f"<truncated {len(value) - 100} items>"
            ]
        return [_compact_value(child) for child in value]
    return value


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _tool_plan(calls) -> list[list[str]]:
    """Convert ordered calls into sequential/parallel OPR groups."""
    plan: list[list[str]] = []
    group_positions: dict[str, int] = {}
    for call in calls:
        name = call.tool_name.rsplit(".", 1)[-1]
        group_id = call.parallel_group_id
        if group_id:
            if group_id not in group_positions:
                group_positions[group_id] = len(plan)
                plan.append([])
            plan[group_positions[group_id]].append(name)
        else:
            plan.append([name])
    return plan


def _request_key(request: ToolCallRequest) -> str:
    """Stable equality key used only to suppress exact duplicate calls."""
    scope = None if request.tool_name == "maintie.search" else request.selection_scope
    return json.dumps(
        {
            "tool_name": request.tool_name,
            "args": request.args,
            "selection_scope": scope,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def _apply_query_semantics(question: str, request: ToolCallRequest) -> ToolCallRequest:
    """Resolve one MaintIE ontology ambiguity before crossing the MCP boundary."""
    folded_question = question.casefold().replace("&", "and")
    if request.tool_name == "maintie.rank":
        args = dict(request.args)
        if re.search(r"\btop\s+(?:3|three)\b", folded_question):
            args["n"] = 3
        elif (
            "shows up most" in folded_question
            or "most common" in folded_question
            or re.search(r"\btop\s+(?:1|one)\b", folded_question)
        ):
            args["n"] = 1
        return request.model_copy(update={"args": args})
    if request.tool_name != "maintie.search":
        return request
    args = dict(request.args)
    query_filter = args.get("filter")
    if not isinstance(query_filter, dict) or query_filter.get("has_fault") is not True:
        return request
    terms = query_filter.get("object_terms")
    if not isinstance(terms, list):
        return request
    folded_terms = {str(term).casefold() for term in terms}
    if (
        folded_terms
        and folded_terms <= _LINES_AND_DRIVES_TERMS
        and "lines and drives" in folded_question
    ):
        # The user supplied the broader ontology label plus examples. Preserve
        # that explicit class scope instead of intersecting four leaf aliases.
        query_filter = dict(query_filter)
        query_filter["object_terms"] = ["Lines & drives"]
        args["filter"] = query_filter
        return request.model_copy(update={"args": args})
    return request


def _is_acknowledgement(question: str) -> bool:
    """Recognize chat-only turns that should not enter the tool loop."""
    folded = " ".join(question.casefold().split())
    if "?" in folded:
        return False
    return folded.startswith(
        (
            "makes sense",
            "got it",
            "understood",
            "thanks",
            "thank you",
            "fair enough",
        )
    )


def _can_answer_from_recent(question: str, memory: ConversationMemory) -> bool:
    """Recognize a local comparison over the immediately preceding result."""
    if not memory.recent_turns:
        return False
    folded = " ".join(question.casefold().split())
    if not ("which of the two" in folded or "which is more" in folded):
        return False
    recent = memory.recent_turns[-1].structured_result
    return isinstance(recent, dict) and sum(
        isinstance(value, dict) for value in recent.values()
    ) >= 2


def render_maintie_answer(result: dict[str, Any] | None, error: str | None = None) -> str:
    """Deterministic user-facing rendering; never calls an LLM."""
    if result is not None:
        return json.dumps(result, ensure_ascii=False, sort_keys=True)
    if error:
        return f"结构化结果生成失败：{error}"
    return "无需新的结构化结果。"


class MaintIEQueryPath:
    """One specialist dispatch with a hard tool budget and typed set memory."""

    def __init__(
        self,
        *,
        llm,
        mcp_tools: MCPToolClient,
        behavior_log: BehaviorLog,
        event_stream: EventStream,
        enable_parallel: bool = False,
    ) -> None:
        self.llm = llm
        self.mcp_tools = mcp_tools
        self.behavior_log = behavior_log
        self.event_stream = event_stream
        self.enable_parallel = enable_parallel

    async def run_turn(
        self,
        *,
        question: str,
        case_id: str,
        turn_index: int,
        memory: ConversationMemory,
        budget: ExecutionBudget,
    ) -> SupervisorTurnResult:
        budget.record_dispatch()
        schemas = await self.mcp_tools.get_allowed_tool_schemas(MAINTIE_TOOLS)
        acknowledgement = _is_acknowledgement(question)
        results = []
        if not acknowledgement and not _can_answer_from_recent(question, memory):
            results = await self._run_tool_loop(
                question=question,
                case_id=case_id,
                turn_index=turn_index,
                memory=memory,
                schemas=schemas,
                max_tool_calls=budget.remaining_tool_calls,
            )
        budget.record_tool_calls(len(results))
        self._update_selection(memory, results, turn_index)

        if acknowledgement:
            result_value, synthesis_error = None, None
        else:
            result_value, synthesis_error = await self._synthesize_result(
                question=question,
                memory=memory,
                tool_results=results,
            )
        summaries = _summarize_tool_calls(results)
        failed = [result for result in results if result.status == "failed"]
        status = "error" if synthesis_error else ("partial" if failed else "ok")
        error = synthesis_error or (failed[-1].error if failed else None)
        answer = render_maintie_answer(result_value, synthesis_error)

        memory.recent_turns.append(
            DialogTurnRecord(
                turn_index=turn_index,
                user_message=question,
                assistant_answer=answer,
                tool_calls=summaries,
                structured_result=result_value,
            )
        )
        if len(memory.recent_turns) > memory.max_recent_turns:
            memory.recent_turns = memory.recent_turns[-memory.max_recent_turns :]

        self.behavior_log.write(
            case_id=case_id,
            agent_role="maintie_query_specialist",
            task_type="maintie_query",
            input_artifact_ids=[],
            tool_calls=[
                ToolCallLog(
                    order=item.order,
                    tool_name=item.tool_name,
                    args=item.args,
                    status=item.status,
                    result=_compact_value(item.result),
                    error=item.error,
                    parallel_group_id=item.parallel_group_id,
                    parallel_index=item.parallel_index,
                    parallel_size=item.parallel_size,
                    selection_scope=item.selection_scope,
                    within_ids_count=item.within_ids_count,
                )
                for item in results
            ],
            output_artifact_ids=[],
            status=status,
            turn_id=f"turn_{turn_index:03d}",
            final_response=answer,
        )
        return SupervisorTurnResult(
            question=question,
            answer=answer,
            result=result_value,
            tools=_tool_plan(summaries),
            tool_calls=summaries,
            status=status,
            error=error,
        )

    async def _run_tool_loop(
        self,
        *,
        question: str,
        case_id: str,
        turn_index: int,
        memory: ConversationMemory,
        schemas: list[dict],
        max_tool_calls: int,
    ) -> list[ToolCallResult]:
        results: list[ToolCallResult] = []
        while len(results) < max_tool_calls:
            prompt = self._tool_prompt(question, memory, schemas, results, max_tool_calls)
            parsed = parse_json_from_llm(await call_llm(self.llm, prompt))
            if parsed is None:
                break
            try:
                decision = SpecialistStepDecision.model_validate(parsed)
            except Exception:
                break
            if decision.done:
                break
            requests = decision.tool_calls or (
                [
                    ToolCallRequest(
                        tool_name=decision.tool_name,
                        args=decision.args,
                        selection_scope=decision.selection_scope,
                    )
                ]
                if decision.tool_name
                else []
            )
            requests = [_apply_query_semantics(question, request) for request in requests]
            if not requests:
                break
            if not self.enable_parallel:
                requests = requests[:1]
            requests = requests[: max_tool_calls - len(results)]

            prior_keys = {
                _request_key(
                    ToolCallRequest(
                        tool_name=item.tool_name,
                        args=item.args,
                        selection_scope=item.selection_scope,
                    )
                )
                for item in results
            }
            unique_requests: list[ToolCallRequest] = []
            for request in requests:
                key = _request_key(request)
                if key in prior_keys:
                    continue
                prior_keys.add(key)
                unique_requests.append(request)
            requests = unique_requests
            if not requests:
                break

            group_id = (
                f"pg_{uuid.uuid4().hex[:8]}"
                if self.enable_parallel and len(requests) > 1
                else None
            )
            logical: list[tuple[ToolCallRequest, ToolCallRequest, int | None]] = []
            immediate: list[ToolCallResult] = []
            for request in requests:
                if request.tool_name not in MAINTIE_TOOLS:
                    immediate.append(
                        ToolCallResult(
                            order=0,
                            tool_name=request.tool_name,
                            args=request.args,
                            status="failed",
                            error="Tool is not allowed in MaintIE mode.",
                            selection_scope=request.selection_scope,
                        )
                    )
                    continue
                resolved_args = dict(request.args)
                within_count = None
                if request.selection_scope == "active":
                    selection = memory.active_maintie_selection
                    if selection is None:
                        immediate.append(
                            ToolCallResult(
                                order=0,
                                tool_name=request.tool_name,
                                args=request.args,
                                status="failed",
                                error="No active MaintIE selection is available.",
                                selection_scope="active",
                            )
                        )
                        continue
                    resolved_args["within_ids"] = selection.wo_ids
                    within_count = len(selection.wo_ids)
                resolved = ToolCallRequest(tool_name=request.tool_name, args=resolved_args)
                logical.append((request, resolved, within_count))

            mcp_results: list[MCPToolResult] = []
            if logical:
                resolved_requests = [resolved for _, resolved, _ in logical]
                if self.enable_parallel and len(resolved_requests) > 1:
                    mcp_results = await self.mcp_tools.call_many_parallel(
                        resolved_requests,
                        max_concurrency=min(4, len(resolved_requests)),
                    )
                else:
                    for resolved in resolved_requests:
                        mcp_results.append(
                            await self.mcp_tools.call(resolved.tool_name, resolved.args)
                        )

            batch: list[ToolCallResult] = immediate[:]
            for (request, _, within_count), mcp_result in zip(
                logical, mcp_results, strict=True
            ):
                batch.append(
                    ToolCallResult(
                        order=0,
                        tool_name=request.tool_name,
                        args=request.args,
                        status=mcp_result.status,
                        result=mcp_result.result,
                        error=mcp_result.error,
                        selection_scope=request.selection_scope,
                        within_ids_count=within_count,
                    )
                )
            for position, item in enumerate(batch, start=1):
                results.append(
                    item.model_copy(
                        update={
                            "order": len(results) + 1,
                            "parallel_group_id": group_id,
                            "parallel_index": position if group_id else None,
                            "parallel_size": len(batch) if group_id else None,
                        }
                    )
                )
            if any(
                item.status == "ok" and item.tool_name in _TERMINAL_AGGREGATE_TOOLS
                for item in batch
            ):
                break
            if not batch:
                break
        return results

    def _tool_prompt(
        self,
        question: str,
        memory: ConversationMemory,
        schemas: list[dict],
        results: list[ToolCallResult],
        max_tool_calls: int,
    ) -> str:
        selection = memory.active_maintie_selection
        selection_summary = (
            "none"
            if selection is None
            else json.dumps(
                {
                    "count": len(selection.wo_ids),
                    "source_turn": selection.source_turn_index,
                    "source_filter": selection.source_filter,
                    "parent_size": selection.parent_size,
                },
                ensure_ascii=False,
            )
        )
        recent = [
            {
                "turn": turn.turn_index,
                "question": turn.user_message,
                "result": _compact_value(turn.structured_result),
            }
            for turn in memory.recent_turns[-5:]
        ]
        prior = [
            {
                "order": item.order,
                "tool": item.tool_name,
                "args": item.args,
                "selection_scope": item.selection_scope,
                "status": item.status,
                "result": _compact_value(item.result),
                "error": item.error,
            }
            for item in results
        ]
        parallel = (
            'You may return {"tool_calls":[...]} for independent calls.'
            if self.enable_parallel
            else "Return at most one tool call per decision."
        )
        return f"""You are the MaintIE query specialist. Answer only against the 1,076-record MaintIE corpus.

Current question: {question}
Recent structured results: {json.dumps(recent, ensure_ascii=False)}
Active work-order selection metadata: {selection_summary}
Calls already made this turn: {json.dumps(prior, ensure_ascii=False)}
Remaining tool calls: {max_tool_calls - len(results)}

Complete available MCP schemas:
{format_tool_schemas_for_prompt(schemas)}

Output one raw JSON decision:
- Call: {{"tool_name":"maintie.search","args":{{...}},"selection_scope":"corpus"}}
- Parallel calls: {{"tool_calls":[...]}}
- Stop: {{"done":true}}

Rules:
- Use only fields present in the complete JSON schema. The corpus has no site or time fields.
- selection_scope must be corpus or active. Use active for references such as those/of those/now only.
- Never put within_ids in args; the executor injects the typed active selection.
- Use search when a filtered set may be reused by a later turn.
- A newly requested filter, entity, component, grouping, or comparison requires a tool call. A prior count alone cannot answer a narrower subset.
- If the question adds a filter to the active set, call search with selection_scope=active. Never merely relabel the old count.
- Stop without a tool only when the exact requested value is already present in recent structured results, or the user is only chatting/confirming terminology.
- MaintIE annotates “change out” as the Replace activity; a terminology confirmation about that mapping needs no corpus query.
- When the user gives an ontology class label plus examples, filter by the broader class label; examples illustrate the class and are not necessarily an exhaustive leaf list.
- Do not infer has_fault=true from generic words such as jobs, issues, or problems. has_fault specifically means an annotated undesirable State, Process, or Property.
- Never repeat a call that already succeeded or failed with identical arguments and selection_scope.
- Stop as soon as enough evidence exists. {parallel}
JSON:"""

    def _update_selection(
        self,
        memory: ConversationMemory,
        results: list[ToolCallResult],
        turn_index: int,
    ) -> None:
        for item in results:
            if item.status != "ok" or item.tool_name != "maintie.search":
                continue
            parsed = _json_object(item.result)
            ids = parsed.get("wo_ids")
            if not isinstance(ids, list) or not all(isinstance(value, int) for value in ids):
                continue
            parent_size = item.within_ids_count
            source_filter = item.args.get("filter")
            memory.active_maintie_selection = MaintIESelection(
                wo_ids=ids,
                source_turn_index=turn_index,
                source_filter=source_filter if isinstance(source_filter, dict) else {},
                parent_size=parent_size,
            )

    async def _synthesize_result(
        self,
        *,
        question: str,
        memory: ConversationMemory,
        tool_results: list[ToolCallResult],
    ) -> tuple[dict[str, Any] | None, str | None]:
        recent = [
            {
                "turn": turn.turn_index,
                "question": turn.user_message,
                "result": _compact_value(turn.structured_result),
            }
            for turn in memory.recent_turns[-5:]
        ]
        evidence = [
            {
                "tool": item.tool_name,
                "args": item.args,
                "selection_scope": item.selection_scope,
                "status": item.status,
                "result": _compact_value(item.result),
                "error": item.error,
            }
            for item in tool_results
        ]
        base_prompt = f"""Build the structured result for one MaintIE question.

Question: {question}
Recent structured results: {json.dumps(recent, ensure_ascii=False)}
Current tool evidence: {json.dumps(evidence, ensure_ascii=False)}

Output exactly one raw JSON object matching:
{{"result": <object or null>}}

Use concise question-oriented keys and include only what was asked. Answer the exact requested operation rather than returning a larger evidence table: when asked “which”, state the selected item; when asked for top N, return only N rows. Preserve exact labels and counts from evidence; do not add totals, percentages, explanations, or metadata unless requested. If search returned only count and IDs, return only that count unless IDs were requested; never invent a per-term breakdown. Represent ranked rows compactly as [label, count] pairs. For one narrowed-set count, prefer a single short count field. For named component comparisons, keep each component's fault count and activity/remedy counts. Every numeric/string value must come from the supplied evidence or be a direct calculation from it. Do not include raw wo_ids unless explicitly requested. Use null only for pure acknowledgement/chat or terminology confirmation. A follow-up asking which item is worse, an ordinal, a comparison, or a calculation must derive a non-null result from recent structured results even when no new tool was called.
JSON:"""
        prompt = base_prompt
        last_error = "Invalid structured result."
        for attempt in range(2):
            parsed = parse_json_from_llm(await call_llm(self.llm, prompt))
            if parsed is not None:
                try:
                    draft = MaintIEResultDraft.model_validate(parsed)
                    return draft.result, None
                except Exception as exc:
                    last_error = str(exc)
            if attempt == 0:
                prompt = (
                    base_prompt
                    + f"\nPrevious output failed validation: {last_error}\n"
                    + "Return only the corrected JSON object."
                )
        return None, last_error
