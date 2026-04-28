"""Time-Series Analysis Specialist — trend analysis, forecasting, anomaly detection."""

from __future__ import annotations

from agent.supervisor_specialist.agents.base import SpecialistAgent


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
