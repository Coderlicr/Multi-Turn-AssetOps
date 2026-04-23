import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, List, Optional
from uuid import uuid4

import numpy as np
import pandas as pd
import pendulum
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

import os

# Setup logging — default WARNING so stderr stays quiet when used as MCP server;
# set LOG_LEVEL=INFO (or DEBUG) in the environment to see verbose output.
_log_level = getattr(logging, os.environ.get("LOG_LEVEL", "WARNING").upper(), logging.WARNING)
logging.basicConfig(level=_log_level)
logger = logging.getLogger("utilities-mcp-server")

mcp = FastMCP("utilities")


class DateTimeResult(BaseModel):
    currentDateTime: str
    currentDateTimeDescription: str


class TimeEnglishResult(BaseModel):
    english: str
    iso: str


# --- Helper Functions ---


def get_temp_filename() -> str:
    tmpdir = tempfile.gettempdir()
    tmppath = Path(tmpdir)
    basepath = Path("cbmdir")
    filename = str(uuid4())

    tmpdir_path = tmppath / basepath
    tmpdir_path.mkdir(parents=True, exist_ok=True)

    filepath = tmpdir_path / (filename + ".json")
    return str(filepath)


# --- JSON Tools ---


@mcp.tool()
def json_reader(
    file_name: Annotated[str, Field(description="Absolute path to a .json file. This tool only reads JSON files — do NOT pass a .csv path here. For CSV files (e.g. from history_csv or run_tsad), use csv_stats instead.")],
) -> str:
    """Reads a JSON file and returns its parsed content. For CSV files use csv_stats."""
    try:
        with open(file_name, "r") as fp:
            contents = json.load(fp)
        return json.dumps(contents)
    except Exception as e:
        logger.error(f"Error reading JSON file {file_name}: {e}")
        return json.dumps({"error": str(e)})


# --- Time Tools ---


@mcp.tool()
def current_date_time() -> DateTimeResult:
    """Provides the current date time as a JSON object."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat().replace("+00:00", "Z")

    date_part = now_iso.split("T")[0]
    time_part = now_iso.split("T")[1].split(".")[0]

    description = f"Today's date is {date_part} and time is {time_part}."

    return DateTimeResult(currentDateTime=now_iso, currentDateTimeDescription=description)


@mcp.tool()
def current_time_english() -> TimeEnglishResult:
    """Returns the current time in English text."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat().replace("+00:00", "Z")

    dt = pendulum.parse(now_iso)
    eng = dt.to_datetime_string()

    return TimeEnglishResult(english=eng, iso=now_iso)


@mcp.tool()
def csv_stats(
    csv_path: Annotated[str, Field(description="Absolute path to a .csv file, e.g. the csv_path returned by history_csv or run_tsad/run_integrated_tsad. Use this tool — not json_reader — whenever the prior step returned a CSV file path.")],
    columns: Annotated[Optional[List[str]], Field(description="List of column names to analyse. If omitted, all numeric columns are included.")] = None,
) -> str:
    """Compute descriptive statistics (mean, std, min, max, trend slope) for columns in a CSV file.

    Use this tool to read results from history_csv, run_tsad, or run_integrated_tsad — not json_reader.
    """
    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:
        return json.dumps({"error": f"Cannot read CSV '{csv_path}': {exc}"})

    numeric_df = df.select_dtypes(include=[np.number])
    if columns:
        missing = [c for c in columns if c not in numeric_df.columns]
        if missing:
            return json.dumps({"error": f"Columns not found or not numeric: {missing}"})
        numeric_df = numeric_df[columns]

    if numeric_df.empty:
        return json.dumps({"error": "No numeric columns available"})

    stats: dict = {}
    for col in numeric_df.columns:
        series = numeric_df[col].dropna()
        if series.empty:
            stats[col] = {"count": 0}
            continue
        x = np.arange(len(series), dtype=float)
        slope = float(np.polyfit(x, series.values, 1)[0]) if len(series) > 1 else 0.0
        stats[col] = {
            "count": int(series.count()),
            "mean": round(float(series.mean()), 4),
            "std": round(float(series.std()), 4),
            "min": round(float(series.min()), 4),
            "max": round(float(series.max()), 4),
            "trend_slope": round(slope, 6),
        }

    return json.dumps({"csv_path": csv_path, "stats": stats})


def main():
    # Initialize and run the server
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
