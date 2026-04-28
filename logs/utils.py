#!/usr/bin/env python3
"""Convert one JSONL log file into a pretty-printed JSON array."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    input_path = Path("./log_timestamp.jsonl")
    output_path = Path("./log_timestamp.json")

    items: list[object] = []
    with input_path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            items.append(json.loads(line))

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=True)
        f.write("\n")

    print(output_path)


if __name__ == "__main__":
    main()
