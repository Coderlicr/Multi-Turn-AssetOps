"""Named verification functions for dataset facts.

A fact whose claim is numeric cannot be checked by substring matching, and a
mini-expression language in YAML would mean eval'ing strings from a data file.
Instead each such fact names a function here; the validator loads the CSV the
tool returned and calls it.

Signature: fn(df: pandas.DataFrame) -> tuple[bool, str]
"""

from __future__ import annotations

import pandas as pd

_REGISTRY: dict[str, callable] = {}


def register(fn):
    _REGISTRY[fn.__name__] = fn
    return fn


def get(name: str):
    if name not in _REGISTRY:
        raise KeyError(f"Unknown check function {name!r}. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def _temperature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if "Temperature" in c]


@register
def june_window_shape(df: pd.DataFrame) -> tuple[bool, str]:
    """2896 rows at 15-minute spacing covering all of June 2020 in -04:00."""
    ts = pd.to_datetime(df["timestamp"])
    ok = (
        len(df) == 2896
        and str(ts.min()) == "2020-06-01 00:00:00-04:00"
        and str(ts.max()) == "2020-06-30 23:45:00-04:00"
    )
    return ok, f"rows={len(df)} range={ts.min()}..{ts.max()}"


@register
def all_temperature_channels_zero_at_0800(df: pd.DataFrame) -> tuple[bool, str]:
    """Every temperature channel reads exactly 0.0 at 08:00 local."""
    ts = pd.to_datetime(df["timestamp"])
    row = df[ts.dt.strftime("%H:%M") == "08:00"]
    if row.empty:
        return False, "no 08:00 row in the returned window"
    cols = _temperature_columns(df)
    values = [float(row.iloc[0][c]) for c in cols]
    return all(v == 0.0 for v in values), f"{len(cols)} channels -> {values}"


@register
def supply_temperature_rises_mid_june(df: pd.DataFrame) -> tuple[bool, str]:
    """Daily-mean Supply Temperature is ~60.8 on Jun 10-14 and ~67.4 on Jun 15-19."""
    col = next(c for c in df.columns if "Supply Temperature" in c)
    ts = pd.to_datetime(df["timestamp"])
    day = ts.dt.day
    early = df.loc[day.between(10, 14), col].mean()
    late = df.loc[day.between(15, 19), col].mean()
    ok = abs(early - 60.80) < 0.5 and abs(late - 67.41) < 0.5 and late > early
    return ok, f"Jun10-14={early:.2f} Jun15-19={late:.2f}"


@register
def efficiency_degrades_once_zeros_excluded(df: pd.DataFrame) -> tuple[bool, str]:
    """kW/ton rises ~0.297 -> ~0.339 over valid samples; 981 of 2896 are valid."""
    col = next(c for c in df.columns if "Chiller Efficiency" in c)
    valid = df[df[col] > 0]
    first = valid[col].head(200).mean()
    last = valid[col].tail(200).mean()
    ok = (
        len(valid) == 981
        and abs(first - 0.2968) < 0.01
        and abs(last - 0.3388) < 0.01
        and last > first
    )
    return ok, f"valid={len(valid)}/{len(df)} first200={first:.4f} last200={last:.4f}"


@register
def chiller6_efficiency_coverage(df: pd.DataFrame) -> tuple[bool, str]:
    """981 of 2896 Chiller 6 efficiency samples are valid (33.9%)."""
    col = next(c for c in df.columns if "Chiller Efficiency" in c)
    valid = int((df[col] > 0).sum())
    return valid == 981 and len(df) == 2896, f"valid={valid}/{len(df)}"


@register
def chiller9_efficiency_coverage(df: pd.DataFrame) -> tuple[bool, str]:
    """1691 of 2925 Chiller 9 efficiency samples are valid (57.8%) — nearly
    double Chiller 6's coverage, so the two are not directly comparable."""
    col = next(c for c in df.columns if "Chiller Efficiency" in c)
    valid = int((df[col] > 0).sum())
    return valid == 1691 and len(df) == 2925, f"valid={valid}/{len(df)}"


@register
def chiller9_degrades_faster_than_chiller6(df: pd.DataFrame) -> tuple[bool, str]:
    """Chiller 9's kW/ton trend is the steeper of the two (7.1e-05 vs 5.5e-05/sample)."""
    import numpy as np
    col = next(c for c in df.columns if "Chiller Efficiency" in c)
    valid = df[df[col] > 0]
    slope = float(np.polyfit(range(len(valid)), valid[col].values, 1)[0])
    return 6.5e-05 < slope < 7.7e-05, f"slope={slope:.3e} over {len(valid)} valid samples"


@register
def chiller3_power_unavailable_on_june_14(df: pd.DataFrame) -> tuple[bool, str]:
    """Every Power Input reading on 2020-06-14 is 0 — the day the user asks about
    has no usable data, so a numeric answer for it would be fabricated."""
    col = next(c for c in df.columns if "Power Input" in c)
    valid = int((df[col] > 0).sum())
    return valid == 0 and len(df) > 0, f"valid={valid}/{len(df)} rows on that day"


@register
def chiller3_power_month_trend(df: pd.DataFrame) -> tuple[bool, str]:
    """Over 2020-06-14..07-14, 2325 of 2923 readings are valid and the mean drifts
    up only slightly (298.7 -> 316.3), i.e. no dramatic rise."""
    col = next(c for c in df.columns if "Power Input" in c)
    valid = df[df[col] > 0]
    first, last = valid[col].head(200).mean(), valid[col].tail(200).mean()
    return (len(valid) == 2325 and abs(first - 298.7) < 5 and abs(last - 316.3) < 5), \
           f"valid={len(valid)}/{len(df)} first200={first:.1f} last200={last:.1f}"


@register
def august_2016_load_bins_incomplete(df: pd.DataFrame) -> tuple[bool, str]:
    """Only the 40-60% and 60-80% load bands carry data in Aug 2016, and their
    efficiencies are nearly equal (0.546 vs 0.550) — the data cannot establish a
    load-dependent efficiency drop, and there is no >80% band at all."""
    eff = next(c for c in df.columns if "Chiller Efficiency" in c)
    load = next(c for c in df.columns if "% Loaded" in c)
    valid = df[(df[eff] > 0) & (df[load] > 0)]
    bins = {}
    for lo, hi in ((0, 40), (40, 60), (60, 80), (80, 101)):
        sel = valid[(valid[load] >= lo) & (valid[load] < hi)]
        if len(sel):
            bins[f"{lo}-{hi}"] = round(float(sel[eff].mean()), 4)
    ok = set(bins) == {"40-60", "60-80"} and abs(bins["40-60"] - bins["60-80"]) < 0.02
    return ok, f"bins={bins}"


@register
def summer_2020_window_truncated(df: pd.DataFrame) -> tuple[bool, str]:
    """A 3-month request returns 5000 rows ending 2020-07-22 — August is absent,
    so 'last summer's peak load' cannot be computed from one call."""
    ts = pd.to_datetime(df["timestamp"])
    return len(df) == 5000 and ts.max().month == 7, \
           f"rows={len(df)} covers {ts.min().date()}..{ts.max().date()}"


@register
def chiller6_supply_diverges_from_setpoint(df: pd.DataFrame) -> tuple[bool, str]:
    """Supply Temperature climbs 45.6 -> 69.8 across June 2020 while Setpoint holds
    at ~45.5-46.0. The divergence is in the measured channel, not the target."""
    sup = next(c for c in df.columns if "Supply Temperature" in c)
    setp = next(c for c in df.columns if "Setpoint Temperature" in c)
    s = df[df[sup] != 0]
    first, last = s[sup].head(200).mean(), s[sup].tail(200).mean()
    sp_first, sp_last = s[setp].head(200).mean(), s[setp].tail(200).mean()
    ok = (abs(first - 45.55) < 1 and abs(last - 69.76) < 1
          and abs(sp_last - sp_first) < 1)
    return ok, (f"supply {first:.2f}->{last:.2f}, setpoint {sp_first:.2f}->{sp_last:.2f}")


@register
def chiller9_june_2021_mostly_empty(df: pd.DataFrame) -> tuple[bool, str]:
    """Power Input and Supply Temperature are ~98% zeros in 2021-06 — there is
    almost no telemetry to diagnose from in that month."""
    p = next(c for c in df.columns if "Power Input" in c)
    s = next(c for c in df.columns if "Supply Temperature" in c)
    zp, zs = (df[p] == 0).mean(), (df[s] == 0).mean()
    return zp > 0.97 and zs > 0.97, f"power {zp*100:.1f}% zeros, supply {zs*100:.1f}% zeros"


@register
def chiller9_power_absent_before_july_2020(df: pd.DataFrame) -> tuple[bool, str]:
    """In the two weeks to 2020-07-01, Power Input is 98.3% zeros while the
    temperature channels are complete — a trip cannot be confirmed from power."""
    p = next(c for c in df.columns if "Power Input" in c)
    s = next(c for c in df.columns if "Supply Temperature" in c)
    zp, zs = (df[p] == 0).mean(), (df[s] == 0).mean()
    return zp > 0.97 and zs < 0.05, f"power {zp*100:.1f}% zeros, supply {zs*100:.1f}% zeros"
