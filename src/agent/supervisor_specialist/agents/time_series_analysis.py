"""Time-Series Analysis Specialist — trend analysis, forecasting, anomaly detection."""

from __future__ import annotations

from agent.supervisor_specialist.agents.base import (
    SpecialistAgent,
    _asset_from_path,
    _parse_tool_json,
    _unique,
)
from agent.supervisor_specialist._utils import extract_file_paths
from agent.supervisor_specialist.schemas import (
    ArtifactEnvelope,
    TaskEnvelope,
    ToolCallRequest,
    ToolCallResult,
)


class TimeSeriesAnalysisSpecialist(SpecialistAgent):
    role = "time_series_analysis_specialist"
    role_prefix = "ts"
    allowed_artifact_types = ("analysis_result",)
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

    async def _postprocess_tool_results(
        self,
        task: TaskEnvelope,
        input_artifacts: list[ArtifactEnvelope],
        results: list[ToolCallResult],
    ) -> list[ToolCallResult]:
        datasets = self._datasets_from_artifacts(input_artifacts)
        if not datasets:
            return results

        existing_stats_paths = {
            result.args.get("csv_path")
            for result in results
            if result.status == "ok" and result.tool_name == "utilities.csv_stats"
        }
        missing_stats = [
            path for path in datasets.values() if path and path not in existing_stats_paths
        ]
        if missing_stats:
            stats_requests = [
                ToolCallRequest(tool_name="utilities.csv_stats", args={"csv_path": path})
                for path in missing_stats
            ]
            results = results + await self._execute_coverage_calls(
                task,
                results,
                stats_requests,
                message=f"Completing CSV stats coverage for {len(missing_stats)} dataset(s).",
            )

        existing_tsfm_paths = {
            result.args.get("dataset_path")
            for result in results
            if result.status == "ok"
            and result.tool_name == "tsfm.run_integrated_tsad"
        }
        tsfm_requests: list[ToolCallRequest] = []
        for asset, csv_path in datasets.items():
            if csv_path in existing_tsfm_paths:
                continue
            columns = self._target_columns_for_path(csv_path, results)
            if not columns:
                continue
            tsfm_requests.append(
                ToolCallRequest(
                    tool_name="tsfm.run_integrated_tsad",
                    args={
                        "dataset_path": csv_path,
                        "timestamp_column": "timestamp",
                        "target_columns": columns,
                        "model_checkpoint": "ttm_96_28",
                        "false_alarm": 0.05,
                        "ad_model_type": "timeseries_conformal",
                        "n_calibration": 0.2,
                        "conditional_columns": None,
                        "id_columns": None,
                        "frequency_sampling": "",
                        "autoregressive_modeling": True,
                    },
                )
            )

        if tsfm_requests:
            results = results + await self._execute_coverage_calls(
                task,
                results,
                tsfm_requests,
                message=f"Completing TSFM coverage for {len(tsfm_requests)} dataset(s).",
            )
        return results

    def _postprocess_artifacts(
        self,
        task: TaskEnvelope,
        input_artifacts: list[ArtifactEnvelope],
        results: list[ToolCallResult],
        artifacts: list[ArtifactEnvelope],
    ) -> list[ArtifactEnvelope]:
        del input_artifacts
        analysis_by_asset = self._analysis_by_asset(results)
        if not analysis_by_asset:
            return artifacts

        covered_assets = _unique(list(analysis_by_asset))
        coverage_payload = {
            "analysis_by_asset": analysis_by_asset,
            "coverage_summary": (
                f"Completed time-series analysis for {len(analysis_by_asset)} asset(s)."
            ),
        }
        updated: list[ArtifactEnvelope] = []
        applied = False
        for artifact in artifacts:
            if artifact.artifact_type == "analysis_result" and not applied:
                updated.append(
                    self._with_analysis_coverage(
                        artifact,
                        task,
                        covered_assets,
                        coverage_payload,
                    )
                )
                applied = True
            else:
                updated.append(artifact)

        if applied:
            return updated

        updated.append(
            ArtifactEnvelope(
                artifact_id=self.artifact_store.next_id(self.role_prefix),
                case_id=task.case_id,
                producer=self.role,
                artifact_type="analysis_result",
                asset_ids=covered_assets,
                time_window=task.time_window,
                source_tools=["tsfm.run_integrated_tsad"],
                source_artifacts=task.input_artifacts,
                payload={
                    "aggregate_summary": coverage_payload["coverage_summary"],
                    **coverage_payload,
                },
                open_questions=[],
            )
        )
        return updated

    def _with_analysis_coverage(
        self,
        artifact: ArtifactEnvelope,
        task: TaskEnvelope,
        covered_assets: list[str],
        coverage_payload: dict,
    ) -> ArtifactEnvelope:
        payload = {**artifact.payload, **coverage_payload}
        if not payload.get("aggregate_summary"):
            payload["aggregate_summary"] = coverage_payload["coverage_summary"]
        return artifact.model_copy(
            update={
                "asset_ids": _unique(artifact.asset_ids + covered_assets),
                "payload": payload,
                "time_window": artifact.time_window
                if artifact.time_window.start
                else task.time_window,
            }
        )

    def _datasets_from_artifacts(self, artifacts: list[ArtifactEnvelope]) -> dict[str, str]:
        datasets: dict[str, str] = {}
        for artifact in artifacts:
            payload = artifact.payload or {}
            by_asset = payload.get("datasets_by_asset")
            if isinstance(by_asset, dict):
                for raw_asset, info in by_asset.items():
                    if isinstance(info, dict) and isinstance(info.get("csv_path"), str):
                        datasets[str(raw_asset)] = info["csv_path"]
            csv_path = payload.get("csv_path")
            if isinstance(csv_path, str):
                asset = artifact.asset_ids[0] if len(artifact.asset_ids) == 1 else _asset_from_path(csv_path)
                if asset:
                    datasets[asset] = csv_path
            for path in extract_file_paths(payload):
                if not path.endswith(".csv") or "integrated_tsad" in path:
                    continue
                asset = _asset_from_path(path)
                if asset and asset not in datasets:
                    datasets[asset] = path
        return datasets

    def _target_columns_for_path(
        self,
        csv_path: str,
        results: list[ToolCallResult],
    ) -> list[str]:
        all_columns: list[str] = []
        for result in results:
            if (
                result.status == "ok"
                and result.tool_name == "utilities.csv_stats"
                and result.args.get("csv_path") == csv_path
            ):
                parsed = _parse_tool_json(result.result)
                columns = parsed.get("all_columns")
                if isinstance(columns, list):
                    all_columns = [str(column) for column in columns]
        preferred = [
            column
            for column in all_columns
            if "temperature" in column.lower()
            and "setpoint" not in column.lower()
            and column.lower() not in {"timestamp", "asset_id"}
        ]
        return preferred[:4]

    def _analysis_by_asset(self, results: list[ToolCallResult]) -> dict[str, dict]:
        analyses: dict[str, dict] = {}
        for result in results:
            if result.status != "ok" or result.tool_name != "tsfm.run_integrated_tsad":
                continue
            dataset_path = result.args.get("dataset_path")
            if not isinstance(dataset_path, str):
                continue
            asset = _asset_from_path(dataset_path)
            if not asset:
                continue
            parsed = _parse_tool_json(result.result)
            analyses[asset] = {
                "dataset_path": dataset_path,
                "results_file": parsed.get("results_file"),
                "anomaly_count": parsed.get("anomaly_count"),
                "total_records": parsed.get("total_records"),
                "target_columns": result.args.get("target_columns", []),
                "status": parsed.get("status", "success"),
            }
        return analyses
