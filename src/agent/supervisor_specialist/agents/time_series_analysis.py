"""Time-Series Analysis Specialist — trend analysis, forecasting, anomaly detection."""

from __future__ import annotations

import json

from agent.supervisor_specialist._utils import extract_file_paths
from agent.supervisor_specialist.agents.base import SpecialistAgent


class TimeSeriesAnalysisSpecialist(SpecialistAgent):
    role = "time_series_analysis_specialist"
    role_prefix = "ts"
    allowed_artifact_types = ("analysis_result",)
    _extra_artifact_rules = (
        "- For anomaly detection or TSAD tasks, every analysis_result payload must include "
        "top-level fields: operation=\"anomaly_detection\", task_completed=true, "
        "anomaly_count, results_file, target_columns, evidence, and remaining_uncertainty; "
        "do not put these completion fields only under an asset-named nested object\n"
        "- If tsfm.run_integrated_tsad or tsfm.run_tsad succeeded, task_completed must be true "
        "and results_file must be copied from the tool result\n"
        "- The summary must state that anomaly detection completed and include the anomaly count"
    )
    _extra_react_rules = (
        "- If the task asks to fine-tune or finetune a forecasting model, you MUST call "
        "tsfm.run_tsfm_finetuning before done=true; utilities.csv_stats is only for "
        "discovering exact column names and is not a substitute for fine-tuning\n"
        "- For fine-tuning, use the concrete csv_path as dataset_path, timestamp as "
        "timestamp_column when present, and choose target_columns from the requested "
        "focus metrics, prior sensor-mapping artifacts, or the most relevant numeric "
        "sensor column\n"
        "- For real-time incident or trip analysis, run anomaly detection on available "
        "recent sensor columns that are relevant to the incident; utilities.csv_stats "
        "may be used to discover exact column names but is not a substitute for TSAD\n"
        "- Do not analyze work-order failure rates, MTBI, corrective/preventive counts, "
        "or work-order distribution artifacts; those are maintenance_planning_specialist "
        "tasks, not sensor time-series tasks"
    )
    allowed_tools = {
        "tsfm.get_ai_tasks",
        "tsfm.get_tsfm_models",
        "tsfm.run_tsfm_forecasting",
        "tsfm.run_tsfm_finetuning",
        "tsfm.run_tsad",
        "tsfm.run_integrated_tsad",
        "utilities.csv_stats",
        "utilities.json_reader",
    }

    def _done_blocking_message(self, task, input_artifacts, results) -> str | None:
        text = f"{task.task_type} {task.goal}".lower()
        if "fine-tune" not in text and "finetune" not in text and "fine tune" not in text:
            return None
        if any(
            r.tool_name == "tsfm.run_tsfm_finetuning" and r.status == "ok"
            for r in results
        ):
            return None

        has_csv = False
        for artifact in input_artifacts:
            if any(path.lower().endswith(".csv") for path in extract_file_paths(artifact.payload)):
                has_csv = True
                break
        if not has_csv:
            return None

        return (
            "Fine-tuning task is not complete. A CSV input artifact is available, "
            "but tsfm.run_tsfm_finetuning has not succeeded. Call "
            "tsfm.run_tsfm_finetuning with the concrete csv_path before done=true; "
            "utilities.csv_stats alone is not fine-tuning."
        )

    def _postprocess_artifacts(self, task, artifacts, results) -> None:
        del task
        finetune_result = None
        for result in results:
            if result.tool_name != "tsfm.run_tsfm_finetuning" or result.status != "ok":
                continue
            finetune_result = self._parse_tool_result(result.result)
            break

        if not isinstance(finetune_result, dict):
            return

        checkpoint_path = finetune_result.get("model_checkpoint")
        metrics_file = finetune_result.get("results_file")
        for artifact in artifacts:
            if artifact.artifact_type != "analysis_result":
                continue
            artifact.payload.setdefault("task_completed", True)
            artifact.payload.setdefault("operation", "fine_tuning")
            if checkpoint_path:
                artifact.payload.setdefault("checkpoint_path", checkpoint_path)
                artifact.payload.setdefault("model_checkpoint", checkpoint_path)
            if metrics_file:
                artifact.payload.setdefault("metrics_file", metrics_file)
                artifact.payload.setdefault("results_file", metrics_file)

    @staticmethod
    def _parse_tool_result(value):
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return None
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
