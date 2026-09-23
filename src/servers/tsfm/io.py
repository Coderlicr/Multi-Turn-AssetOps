"""Path/IO helpers and dataset reader for the TSFM MCP server."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime
from typing import Optional

import numpy as np

from servers.paths import outputs_dir
import pandas as pd


# ── Path helpers ──────────────────────────────────────────────────────────────


_DEFAULT_MODELS_DIR = os.path.join(
    os.path.dirname(__file__), "artifacts", "tsfm_models"
)


def _get_model_checkpoint_path(model_checkpoint: str) -> str:
    if os.path.isabs(model_checkpoint):
        return model_checkpoint
    return os.path.join(
        os.environ.get("PATH_TO_MODELS_DIR", _DEFAULT_MODELS_DIR), model_checkpoint
    )


def _get_dataset_path(dataset: str) -> str:
    if os.path.isabs(dataset):
        return dataset
    return os.path.join(os.environ.get("PATH_TO_DATASETS_DIR", ""), dataset)


def _get_outputs_path(outputs: str) -> str:
    """Anchor a relative outputs path under the shared outputs directory.

    The fallback base used to be "", which silently turned "relative to outputs
    dir" into "relative to the current working directory": with the MCP server
    started from the repo root, a fine-tuning run wrote its checkpoint into the
    source tree.
    """
    if os.path.isabs(outputs):
        return outputs
    base = os.environ.get("PATH_TO_OUTPUTS_DIR") or str(outputs_dir())
    return os.path.join(base, outputs)


def _parse_timestamps(values) -> pd.Series:
    """Parse ISO-like timestamps, including fractional seconds and timezone offsets."""
    for kwargs in (
        {"format": "ISO8601"},
        {"format": "mixed"},
        {},
    ):
        try:
            return pd.to_datetime(values, **kwargs)
        except (TypeError, ValueError):
            continue
    return pd.to_datetime(values)


# ── JSON utilities ────────────────────────────────────────────────────────────


def _write_json_to_temp(json_data: str) -> str:
    """Write a result file an artifact will point at.

    These are returned to the agent as results_file, so they belong in outputs/,
    not in the system temp directory where they used to land.
    """
    temp_file_path = os.path.join(str(outputs_dir()), f"{uuid.uuid4().hex}.json")
    with open(temp_file_path, "w") as f:
        f.write(json_data)
    return temp_file_path


def _make_json_compatible(obj):
    """Recursively convert an object to a JSON-serializable form."""
    if isinstance(obj, dict):
        return {str(k): _make_json_compatible(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_json_compatible(i) for i in obj]
    if isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


# ── Dataset reading ───────────────────────────────────────────────────────────


def _read_ts_data(dataset_path: str, dataset_config_dictionary=None) -> pd.DataFrame:
    if dataset_config_dictionary is not None:
        timestamp_column = dataset_config_dictionary["column_specifiers"][
            "timestamp_column"
        ]
    else:
        timestamp_column = "Date"

    valid_extensions = {".csv", ".json", ".xlsx"}
    _, file_extension = os.path.splitext(dataset_path)
    if file_extension.lower() not in valid_extensions:
        raise ValueError(
            f"Invalid file type received: {dataset_path}. "
            f"Expected file types are: {', '.join(valid_extensions)}."
        )

    if ".csv" in dataset_path:
        if dataset_config_dictionary is not None:
            col_spec = dataset_config_dictionary["column_specifiers"]
            data_df = pd.read_csv(dataset_path)
            timestamp_col = col_spec["timestamp_column"]
            if timestamp_col in data_df.columns:
                data_df[timestamp_col] = _parse_timestamps(data_df[timestamp_col])
        else:
            data_df = pd.read_csv(dataset_path)

    elif ".json" in dataset_path:
        try:
            with open(dataset_path) as _f:
                result_dict = json.load(_f)
            ts: dict = {}
            for input_data in result_dict:
                dt = datetime.fromisoformat(input_data["timestamp"])
                if (dt.minute % 15) != 0:
                    continue
                input_data[timestamp_column] = dt
                ts[dt] = input_data
            data_df = pd.DataFrame()
            for dt, v in ts.items():
                data_df = pd.concat([data_df, pd.DataFrame(v, index=[dt])])
        except Exception as ex:
            raise ValueError(
                f"input file {dataset_path} is not in the correct format"
            ) from ex

    elif ".xlsx" in dataset_path:
        if dataset_config_dictionary is not None:
            col_spec = dataset_config_dictionary["column_specifiers"]
            data_df = pd.read_excel(dataset_path)
            timestamp_col = col_spec["timestamp_column"]
            if timestamp_col in data_df.columns:
                data_df[timestamp_col] = _parse_timestamps(data_df[timestamp_col])
        else:
            data_df = pd.read_excel(dataset_path)

    else:
        raise ValueError(
            f"file extension must be: .json, .csv, or .xlsx. file: {dataset_path}"
        )

    return data_df
