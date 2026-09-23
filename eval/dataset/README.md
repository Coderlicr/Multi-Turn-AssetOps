# Multi-turn evaluation dataset

## Layout

```
eval/dataset/
  schema.py        Pydantic models + loader; as_runner_scenarios() feeds the eval runners
  checks.py        Named verification functions for numeric facts
  validate.py      Re-verifies every fact against the live tools
  dialogs/
    dialog_01.yaml ... dialog_16.yaml
```

## What a dialog file contains

Each turn separates three kinds of expectation, because they are verified in different ways and confusing them is what made the old file unreliable:

| Section | Meaning | Verified by |
|---|---|---|
| `facts` | Assertions about the data itself | `validate.py`, automatically |
| `expectations` | What a correct answer must address | LLM judge |
| `pitfalls` | Claims that signal hallucination or a skipped step | LLM judge |

Dialog-level `data_caveats` record constraints every numeric claim must respect (sensor dropouts, timezone conventions, tool parameter quirks).

`assets_named_by_user: []` means the user was deliberately vague. A correct answer resolves or surfaces the ambiguity; it must not silently pick one asset.

## Verifying

```bash
uv run python eval/dataset/validate.py              # all dialogs
uv run python eval/dataset/validate.py --dialogs 1
```

A fact is verified either by `expect_contains` (substrings that must appear in the tool response) or by `fn` (a named function in `checks.py` that receives the CSV the
tool produced). Facts with neither are reported as `MANUAL` and are **not** counted as verified.

## Why the format changed

Reference answers derived from a system's own transcript are circular: score that system against them and it wins by construction. The facts here were therefore re-derived from the tools, and three concrete errors in the old prose file were found this way:

1. It pinned Dialog 1 to "Chiller 6" although the user names no asset and site MAIN has four — penalising the correct behaviour of discovering the inventory first.
2. It asserted "Chiller Efficiency degraded 15-20%". The direction is right, but only once sensor dropouts are excluded: 65.4% of that column reads exactly 0, and a naive mean shows efficiency falling to zero.
3. Its root cause (condenser water-side fouling) is not the dominant anomaly in the data. At 2020-06-08T08:00-04:00 all four chillers report 0.0 on all five temperature channels simultaneously — a telemetry dropout, not a thermal event.

Point 3 also exposed a reporting hazard now recorded as a caveat: `iot.history_csv`timestamps carry a -04:00 offset while `tsfm.run_integrated_tsad` result files carry none and sit 4 hours ahead, so the same event reads as 08:00 or 12:00 depending on which file you are looking at.
