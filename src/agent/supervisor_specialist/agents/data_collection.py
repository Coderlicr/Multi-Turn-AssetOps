"""Data Collection Specialist — gathers IoT data, work orders, and events."""

from __future__ import annotations

from agent.supervisor_specialist.agents.base import (
    SpecialistAgent,
    _parse_tool_json,
    _unique,
)
from agent.supervisor_specialist.schemas import (
    ArtifactEnvelope,
    TaskEnvelope,
    ToolCallRequest,
    ToolCallResult,
)


class DataCollectionSpecialist(SpecialistAgent):
    role = "data_collection_specialist"
    role_prefix = "dc"
    allowed_artifact_types = ("dataset_ref", "inventory")
    _extra_react_rules = (
        "- If iot.assets returns multiple assets and the goal does not name a specific asset, "
        "collect data for ALL returned assets before marking done — do not stop after the first one\n"
        "- After calling iot.history_csv for an asset, always call utilities.csv_stats on the "
        "returned csv_path to obtain column statistics before moving to the next asset\n"
        "- For MaintIE corpus questions, use only maintie.* tools. Reuse wo_ids with "
        "within_ids on follow-up turns; patient_of_activity='Replace' gives exact "
        "replaced-component relation counts"
    )
    allowed_tools = {
        "iot.sites",
        "iot.assets",
        "iot.sensors",
        "iot.history",
        "iot.history_csv",
        "wo.get_work_orders",
        "wo.get_preventive_work_orders",
        "wo.get_corrective_work_orders",
        "wo.get_events",
        "wo.get_failure_codes",
        "wo.get_alert_rules",
        "utilities.csv_stats",
        "utilities.json_reader",
        "utilities.current_date_time",
        "utilities.current_time_english",
        "maintie.search",
        "maintie.extract",
        "maintie.count",
        "maintie.group_count",
        "maintie.rank",
        "maintie.get_text",
        "maintie.compare",
    }

    async def _postprocess_tool_results(
        self,
        task: TaskEnvelope,
        input_artifacts: list[ArtifactEnvelope],
        results: list[ToolCallResult],
        *,
        max_tool_calls: int,
    ) -> list[ToolCallResult]:
        del input_artifacts
        required_assets = self._required_assets(task, results)
        if len(required_assets) <= 1 or not task.time_window.start or not task.time_window.end:
            return results

        existing_assets = {
            result.args.get("asset_id")
            for result in results
            if result.status == "ok" and result.tool_name == "iot.history_csv"
        }
        missing_assets = [
            asset for asset in required_assets if asset and asset not in existing_assets
        ]
        if not missing_assets:
            return results

        requests = [
            ToolCallRequest(
                tool_name="iot.history_csv",
                args={
                    "site_name": task.site,
                    "asset_id": asset,
                    "start": task.time_window.start,
                    "final": task.time_window.end,
                },
            )
            for asset in missing_assets
        ]
        new_results = await self._execute_coverage_calls(
            task,
            results,
            requests,
            message=f"Completing dataset coverage for {len(missing_assets)} asset(s).",
            max_tool_calls=max_tool_calls,
        )
        return results + new_results

    def _postprocess_artifacts(
        self,
        task: TaskEnvelope,
        input_artifacts: list[ArtifactEnvelope],
        results: list[ToolCallResult],
        artifacts: list[ArtifactEnvelope],
    ) -> list[ArtifactEnvelope]:
        del input_artifacts
        datasets_by_asset = self._datasets_by_asset(results)
        if not datasets_by_asset:
            return artifacts

        covered_assets = _unique(list(datasets_by_asset))
        coverage_payload = {
            "datasets_by_asset": datasets_by_asset,
            "csv_paths": [
                item["csv_path"]
                for item in datasets_by_asset.values()
                if item.get("csv_path")
            ],
            "asset_count": len(datasets_by_asset),
        }

        updated: list[ArtifactEnvelope] = []
        applied = False
        for artifact in artifacts:
            if artifact.artifact_type == "dataset_ref" and not applied:
                updated.append(
                    artifact.model_copy(
                        update={
                            "asset_ids": _unique(artifact.asset_ids + covered_assets),
                            "payload": {**artifact.payload, **coverage_payload},
                            "time_window": artifact.time_window
                            if artifact.time_window.start
                            else task.time_window,
                        }
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
                artifact_type="dataset_ref",
                asset_ids=covered_assets,
                time_window=task.time_window,
                source_tools=["iot.history_csv"],
                source_artifacts=task.input_artifacts,
                payload=coverage_payload,
                open_questions=[],
            )
        )
        return updated

    def _required_assets(
        self,
        task: TaskEnvelope,
        results: list[ToolCallResult],
    ) -> list[str]:
        assets: list[str] = []
        for result in results:
            if result.status != "ok" or result.tool_name != "iot.assets":
                continue
            parsed = _parse_tool_json(result.result)
            if isinstance(parsed.get("assets"), list):
                assets.extend(str(asset) for asset in parsed["assets"])
        discovered_assets = _unique(assets)
        if discovered_assets:
            return discovered_assets
        return _unique(task.asset_ids)

    def _datasets_by_asset(self, results: list[ToolCallResult]) -> dict[str, dict]:
        datasets: dict[str, dict] = {}
        for result in results:
            if result.status != "ok" or result.tool_name != "iot.history_csv":
                continue
            parsed = _parse_tool_json(result.result)
            asset = str(result.args.get("asset_id") or parsed.get("asset_id") or "")
            csv_path = parsed.get("csv_path")
            if not asset or not isinstance(csv_path, str):
                continue
            datasets[asset] = {
                "csv_path": csv_path,
                "start": parsed.get("start") or result.args.get("start"),
                "end": parsed.get("final") or result.args.get("final"),
                "columns": parsed.get("columns", []),
                "total_observations": parsed.get("total_observations"),
            }
        return datasets
