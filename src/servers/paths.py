"""Shared locations for files the MCP servers write.

Everything used to land flat in /tmp/assetops, mixing three kinds of file with
very different lifetimes: cached sensor exports, per-call scratch space, and
results the agent is meant to keep. Nothing ever removed any of it (534 scratch
directories and 260 MB had accumulated), and a caller could not tell which
entries were safe to delete.

Layout under ASSETOPS_TMP_ROOT (default /tmp/assetops):

    datasets/   deterministic sensor exports; reused across runs, safe to keep
    work/       per-call scratch; safe to delete wholesale between runs
    outputs/    results referenced by returned artifacts; deleting these breaks
                any artifact that points at them
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_DEFAULT_ROOT = "/tmp/assetops"


def tmp_root() -> Path:
    """Base directory for everything the servers write."""
    return Path(os.environ.get("ASSETOPS_TMP_ROOT") or _DEFAULT_ROOT)


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def datasets_dir() -> Path:
    """Sensor exports keyed by asset and time window, reused across runs."""
    return _ensure(tmp_root() / "datasets")


def work_dir() -> Path:
    """Scratch space for a single tool call."""
    return _ensure(tmp_root() / "work")


def outputs_dir() -> Path:
    """Results an artifact may point at; not scratch."""
    return _ensure(tmp_root() / "outputs")


def clear_work() -> int:
    """Delete scratch space. Returns how many entries were removed.

    Only work/ is touched: datasets/ is a cache worth keeping and outputs/ is
    referenced by artifacts.
    """
    work = tmp_root() / "work"
    if not work.is_dir():
        return 0
    removed = 0
    for entry in work.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)
        removed += 1
    return removed
