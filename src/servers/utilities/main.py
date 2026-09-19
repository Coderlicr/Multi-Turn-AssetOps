import json
import logging
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
    filename = str(uuid4())

    tmpdir_path = Path("/tmp/assetops/cbmdir")
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

    return json.dumps({"csv_path": csv_path, "all_columns": list(df.columns), "stats": stats})


_CSV_QUERY_ROW_CAP = 200
#: The agent prompt shows only the first N characters of a tool result and cuts the
#: rest, which would slice a large JSON payload mid-object. Trim to fit here instead,
#: so what reaches the model is always complete and says how much was left out.
#: Keep this just under agent.supervisor_specialist._utils.TOOL_RESULT_PREVIEW_CHARS
#: (4000); the cap applies to this JSON string itself with nothing prepended, so only
#: a small margin is needed. Raise both together if either changes.
_CSV_QUERY_CHAR_BUDGET = 3800


def _fit_to_budget(payload: dict, key: str, total: int) -> str:
    """Drop trailing items from payload[key] until the serialized JSON fits.

    returned_* and truncated are maintained inside the loop so they are counted
    against the budget too — setting them afterwards would push the payload back
    over it and make "truncated" itself the thing that gets cut off.
    """
    items = payload[key]
    while True:
        payload[key] = items
        payload[f"returned_{key}"] = len(items)
        payload["truncated"] = len(items) < total
        text = json.dumps(payload)
        if len(text) <= _CSV_QUERY_CHAR_BUDGET or not items:
            return text
        items = items[:-1]


def _coerce(series: pd.Series, value):
    """Make *value* comparable with *series* without trusting its literal type."""
    if pd.api.types.is_bool_dtype(series):
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes")
        return bool(value)
    if pd.api.types.is_numeric_dtype(series):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return value


def _apply_filter(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """Apply one {column, op, value} filter.

    Structured filters on purpose: a free-text expression would have to be
    eval'd, and the caller here is an LLM.
    """
    column = spec.get("column")
    op = (spec.get("op") or "==").strip()
    value = spec.get("value")
    if column not in df.columns:
        raise ValueError(f"Unknown column '{column}'. Available: {list(df.columns)}")

    series = df[column]
    if op == "contains":
        return df[series.astype(str).str.contains(str(value), case=False, na=False)]
    if op == "in":
        values = value if isinstance(value, list) else [value]
        return df[series.astype(str).isin([str(v) for v in values])]

    target = _coerce(series, value)
    ops = {
        "==": lambda: series == target,
        "!=": lambda: series != target,
        ">": lambda: series > target,
        ">=": lambda: series >= target,
        "<": lambda: series < target,
        "<=": lambda: series <= target,
    }
    if op not in ops:
        raise ValueError(f"Unsupported op '{op}'. Use one of {sorted(ops) + ['contains', 'in']}.")
    return df[ops[op]()]


@mcp.tool()
def csv_query(
    csv_path: Annotated[str, Field(description="Absolute path to a .csv file, e.g. the results_file returned by run_tsad/run_integrated_tsad or the csv_path from history_csv.")],
    filters: Annotated[Optional[List[dict]], Field(description='Row filters, ANDed together. Each is {"column": str, "op": one of ==,!=,>,>=,<,<=,contains,in, "value": any}. Example: [{"column": "anomaly_label", "op": "==", "value": true}].')] = None,
    columns: Annotated[Optional[List[str]], Field(description="Columns to return. Omit for all columns.")] = None,
    group_by: Annotated[Optional[List[str]], Field(description='Return one summary row per group instead of raw rows, e.g. ["KPI"] to summarise per sensor.')] = None,
    sort_by: Annotated[Optional[str], Field(description="Column to sort by, e.g. anomaly_score.")] = None,
    descending: Annotated[bool, Field(description="Sort direction; true = largest first.")] = True,
    limit: Annotated[int, Field(description=f"Maximum rows or groups to return (hard cap {_CSV_QUERY_ROW_CAP}). The result is trimmed further if needed so it fits the {_CSV_QUERY_CHAR_BUDGET}-character budget the agent prompt allows per tool result; check returned_rows/truncated.")] = 20,
) -> str:
    """Read individual rows out of a CSV, with filtering, sorting and per-group summaries.

    Use this — not csv_stats — whenever you need concrete values rather than
    aggregates: which timestamps are anomalous, which sensor (KPI) they belong
    to, how severe each one is. csv_stats drops non-numeric columns such as
    timestamp, KPI and anomaly_label, so it cannot answer those questions.
    """
    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:
        return json.dumps({"error": f"Cannot read CSV '{csv_path}': {exc}"})

    total_rows = int(len(df))
    try:
        for spec in filters or []:
            df = _apply_filter(df, spec)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    matched_rows = int(len(df))
    limit = max(1, min(int(limit), _CSV_QUERY_ROW_CAP))

    if group_by:
        missing = [c for c in group_by if c not in df.columns]
        if missing:
            return json.dumps({"error": f"Unknown group_by columns: {missing}. Available: {list(df.columns)}"})
        # A summary is deliberately lean: with 10 KPIs per chiller, carrying
        # min/max/mean for every numeric column plus a whole top row costs ~500
        # bytes per group, so only two groups survived the output budget and the
        # caller saw 2 of 10 sensors. Keep what a per-group overview is actually
        # read for; the caller can drop group_by to inspect individual rows.
        measure = sort_by if (sort_by and sort_by in df.columns
                              and pd.api.types.is_numeric_dtype(df[sort_by])) else None
        label_cols = [c for c in ("timestamp", "time", "datetime") if c in df.columns]
        groups = []
        for key, chunk in df.groupby(group_by, dropna=False):
            key_tuple = key if isinstance(key, tuple) else (key,)
            entry = {
                "key": {c: (None if pd.isna(v) else str(v)) for c, v in zip(group_by, key_tuple)},
                "count": int(len(chunk)),
            }
            if measure:
                series = chunk[measure].dropna()
                if not series.empty:
                    entry[measure] = {
                        "max": round(float(series.max()), 4),
                        "mean": round(float(series.mean()), 4),
                    }
                ordered = chunk.sort_values(measure, ascending=not descending)
                if label_cols and len(ordered):
                    entry["peak_at"] = str(ordered.iloc[0][label_cols[0]])
            groups.append(entry)
        groups.sort(key=lambda g: g["count"], reverse=True)
        kept = groups[:limit]
        payload = {
            "csv_path": csv_path, "all_columns": list(pd.read_csv(csv_path, nrows=0).columns),
            "total_rows": total_rows, "matched_rows": matched_rows,
            "group_by": group_by, "total_groups": len(groups), "groups": kept,
        }
        return _fit_to_budget(payload, "groups", len(groups))

    if sort_by:
        if sort_by not in df.columns:
            return json.dumps({"error": f"Unknown sort_by column '{sort_by}'. Available: {list(df.columns)}"})
        df = df.sort_values(sort_by, ascending=not descending)

    if columns:
        missing = [c for c in columns if c not in df.columns]
        if missing:
            return json.dumps({"error": f"Unknown columns: {missing}. Available: {list(df.columns)}"})
        df = df[columns]

    rows = json.loads(df.head(limit).to_json(orient="records", date_format="iso"))
    payload = {
        "csv_path": csv_path,
        "all_columns": list(pd.read_csv(csv_path, nrows=0).columns),
        "total_rows": total_rows,
        "matched_rows": matched_rows,
        "rows": rows,
    }
    return _fit_to_budget(payload, "rows", matched_rows)


def main():
    # Initialize and run the server
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
