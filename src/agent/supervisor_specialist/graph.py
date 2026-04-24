"""LangGraph graph definition for the Supervisor-Specialist system.

LangGraph is responsible only for:
  - Storing shared state (GraphState)
  - Running nodes
  - Routing via the next_node field written by Supervisor

Business logic, planning, and specialist selection all live in the agent classes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph

from agent.supervisor_specialist._utils import call_llm, format_artifacts_summary
from agent.supervisor_specialist.agents.data_collection import DataCollectionSpecialist
from agent.supervisor_specialist.agents.failure_reasoning import FailureReasoningSpecialist
from agent.supervisor_specialist.agents.maintenance_planning import MaintenancePlanningSpecialist
from agent.supervisor_specialist.agents.supervisor import SupervisorAgent
from agent.supervisor_specialist.agents.time_series_analysis import TimeSeriesAnalysisSpecialist
from agent.supervisor_specialist.runtime.artifact_store import ArtifactStore
from agent.supervisor_specialist.runtime.behavior_log import BehaviorLog
from agent.supervisor_specialist.runtime.event_stream import EventStream
from agent.supervisor_specialist.schemas import GraphState, ToolCallLog

_log = logging.getLogger(__name__)

_FINAL_RESPONSE_PROMPT = """\
You are a senior industrial asset operations expert.
Based on the analysis below, write a clear and structured response to the user's question.

User question: {user_goal}

Case findings:
{artifacts_summary}

Root cause identified: {root_cause}
Recommended actions: {recommended_actions}

Error note (if any): {error_message}

Write a comprehensive response that:
1. Directly answers the user's question
2. Summarizes key findings and evidence
3. States the most likely root cause with confidence level (if applicable)
4. Lists concrete recommended actions in priority order
5. Notes any remaining uncertainties or next steps

Response:"""


@dataclass
class Dependencies:
    supervisor: SupervisorAgent
    data_collection: DataCollectionSpecialist
    time_series_analysis: TimeSeriesAnalysisSpecialist
    failure_reasoning: FailureReasoningSpecialist
    maintenance_planning: MaintenancePlanningSpecialist
    artifact_store: ArtifactStore
    event_stream: EventStream
    behavior_log: BehaviorLog
    llm: object  # LiteLLMBackend


def build_graph(deps: Dependencies):
    """Build and compile the Supervisor-Specialist LangGraph."""

    def route_from_supervisor(state: GraphState) -> str:
        return state.get("next_node", "respond_to_user")

    def _make_specialist_node(specialist):
        async def node(state: GraphState) -> GraphState:
            task = state.get("current_task")
            if task is None:
                _log.error("%s: received None current_task", specialist.role)
                deps.behavior_log.write(
                    case_id=state["case_state"].case_id,
                    agent_role=specialist.role,
                    task_type="error",
                    input_artifact_ids=[],
                    tool_calls=[],
                    output_artifact_ids=[],
                    status="failed",
                )
                return {
                    **state,
                    "next_node": "supervisor",
                    "error_message": f"{specialist.role}: current_task was None.",
                }

            try:
                artifacts = await specialist.run(task)
                deps.artifact_store.save_many(artifacts)

                case_state = state["case_state"]
                case_state.artifact_ids.extend(a.artifact_id for a in artifacts)

                return {
                    **state,
                    "case_state": case_state,
                    "last_artifacts": artifacts,
                    "current_task": None,
                    "next_node": "supervisor",
                    "error_message": None,
                }
            except Exception as exc:  # noqa: BLE001
                _log.exception("%s: unexpected error: %s", specialist.role, exc)
                deps.behavior_log.write(
                    case_id=state["case_state"].case_id,
                    agent_role=specialist.role,
                    task_type=task.task_type if task else "error",
                    input_artifact_ids=task.input_artifacts if task else [],
                    tool_calls=[],
                    output_artifact_ids=[],
                    status="failed",
                )
                deps.event_stream.emit(
                    case_id=state["case_state"].case_id,
                    agent_role=specialist.role,
                    task_type=task.task_type if task else "error",
                    status="failed",
                    message=f"Unexpected error: {exc}",
                )
                return {
                    **state,
                    "next_node": "supervisor",
                    "error_message": f"{specialist.role} error: {exc}",
                }

        node.__name__ = f"{specialist.role}_node"
        return node

    async def respond_to_user_node(state: GraphState) -> GraphState:
        case_state = state["case_state"]
        artifacts = deps.artifact_store.get_many(case_state.artifact_ids)

        deps.event_stream.emit(
            case_id=case_state.case_id,
            agent_role="respond_to_user",
            task_type="final_response",
            status="running",
            message="Building final response.",
        )

        prompt = _FINAL_RESPONSE_PROMPT.format(
            user_goal=case_state.user_goal,
            artifacts_summary=format_artifacts_summary(artifacts),
            root_cause=case_state.root_cause or "(not identified)",
            recommended_actions=", ".join(case_state.recommended_actions) or "(none)",
            error_message=state.get("error_message") or "none",
        )

        try:
            final_response = await call_llm(deps.llm, prompt)
        except Exception as exc:  # noqa: BLE001
            _log.exception("respond_to_user_node: LLM call failed: %s", exc)
            final_response = (
                f"Analysis complete. Goal: {case_state.user_goal}\n"
                f"Collected {len(artifacts)} artifact(s). "
                f"(Final response generation failed: {exc})"
            )

        if case_state.status != "waiting_for_user":
            case_state.status = "completed"

        deps.behavior_log.write(
            case_id=case_state.case_id,
            agent_role="respond_to_user",
            task_type="final_response",
            input_artifact_ids=case_state.artifact_ids,
            tool_calls=[],
            output_artifact_ids=[],
            status="ok",
            final_response=final_response,
        )

        deps.event_stream.emit(
            case_id=case_state.case_id,
            agent_role="respond_to_user",
            task_type="final_response",
            status="completed",
            message="Final response ready.",
        )

        return {
            **state,
            "case_state": case_state,
            "final_response": final_response,
            "current_task": None,
        }

    # ── Build the graph ────────────────────────────────────────────────────────
    graph = StateGraph(GraphState)

    graph.add_node("supervisor", deps.supervisor.decide)
    graph.add_node(
        "data_collection_specialist",
        _make_specialist_node(deps.data_collection),
    )
    graph.add_node(
        "time_series_analysis_specialist",
        _make_specialist_node(deps.time_series_analysis),
    )
    graph.add_node(
        "failure_reasoning_specialist",
        _make_specialist_node(deps.failure_reasoning),
    )
    graph.add_node(
        "maintenance_planning_specialist",
        _make_specialist_node(deps.maintenance_planning),
    )
    graph.add_node("respond_to_user", respond_to_user_node)

    graph.add_edge(START, "supervisor")

    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "data_collection_specialist": "data_collection_specialist",
            "time_series_analysis_specialist": "time_series_analysis_specialist",
            "failure_reasoning_specialist": "failure_reasoning_specialist",
            "maintenance_planning_specialist": "maintenance_planning_specialist",
            "respond_to_user": "respond_to_user",
        },
    )

    graph.add_edge("data_collection_specialist", "supervisor")
    graph.add_edge("time_series_analysis_specialist", "supervisor")
    graph.add_edge("failure_reasoning_specialist", "supervisor")
    graph.add_edge("maintenance_planning_specialist", "supervisor")
    graph.add_edge("respond_to_user", END)

    return graph.compile()
