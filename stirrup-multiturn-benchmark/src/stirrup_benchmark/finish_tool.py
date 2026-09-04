"""Explicit Stirrup finish tool that captures the final user-facing answer."""

from pydantic import BaseModel, Field, field_validator
from stirrup.constants import DEFAULT_FINISH_TOOL_NAME
from stirrup.core.models import Tool, ToolResult, ToolUseCountMetadata


class BenchmarkFinishParams(BaseModel):
    answer: str = Field(
        min_length=1,
        description="Complete response to return directly to the user.",
    )
    reason: str = Field(default="", description="Optional internal completion note.")

    @field_validator("answer")
    @classmethod
    def answer_must_contain_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("answer must include non-whitespace content")
        return value


async def _finish_executor(
    params: BenchmarkFinishParams,
) -> ToolResult[ToolUseCountMetadata]:
    return ToolResult(
        content=params.answer,
        metadata=ToolUseCountMetadata(),
        success=True,
    )


BENCHMARK_FINISH_TOOL: Tool[BenchmarkFinishParams, ToolUseCountMetadata] = Tool(
    name=DEFAULT_FINISH_TOOL_NAME,
    description=(
        "End the task when the current user request is fully answered. Put the "
        "complete user-facing response in answer. Call this tool alone."
    ),
    parameters=BenchmarkFinishParams,
    executor=_finish_executor,
)
