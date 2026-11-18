from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

import numpy as np
import pandas as pd


PROGRAM_STAGES = [
    dict(name="constant_95", start_h=0, end_h=18, behavior="constant", target_ul_min=95),
    dict(name="scheduled_off_1", start_h=18, end_h=24, behavior="off", target_ul_min=0),
    dict(name="constant_175", start_h=24, end_h=42, behavior="constant", target_ul_min=175),
    dict(name="scheduled_off_2", start_h=42, end_h=48, behavior="off", target_ul_min=0),
    dict(name="pulsed_120", start_h=48, end_h=68, behavior="pulsed", target_ul_min=120,
         duty=0.5, pulse_frequency_hz=1 / 7200),
    dict(name="scheduled_off_3", start_h=68, end_h=72, behavior="off", target_ul_min=0),
    dict(name="oscillatory_145", start_h=72, end_h=92, behavior="oscillatory", target_ul_min=145,
         amplitude_ul_min=25, oscillation_frequency_hz=1 / 7200),
    dict(name="scheduled_off_4", start_h=92, end_h=96, behavior="off", target_ul_min=0),
    dict(name="combined_160", start_h=96, end_h=120, behavior="combined", target_ul_min=160,
         duty=0.5, pulse_frequency_hz=1 / 14400,
         amplitude_ul_min=15, oscillation_frequency_hz=1 / 7200),
]

CONSTANT_ACTIVE_WINDOWS = [
    dict(name="constant_95", start_h=0, end_h=18, target_ul_min=95),
    dict(name="constant_175", start_h=24, end_h=42, target_ul_min=175),
]

OFF_THRESHOLD_UL_MIN = 10.0
DIP_THRESHOLD_FRACTION = 0.70
MIN_DIP_DURATION_S = 0.2
MAX_DIP_DURATION_S = 120.0
SYRINGE_CAPACITY_UL = 50.0
PROGRAM_EDGE_EXCLUSION_S = 5.0


def detect_columns(path: Path) -> tuple[int, str, str]:
    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for row_number, line in enumerate(f):
            columns = line.rstrip("\r\n").split("\t")
            if "Elapsed_s" in columns and "Epoch_UTC" in columns:
                candidates = [c for c in columns if c.startswith("F_")]
                if not candidates:
                    raise ValueError("No F_... flow-rate column found in EDF header")
                if len(candidates) > 1:
                    raise ValueError(f"Multiple flow-rate columns: {candidates}")
                return row_number, "Elapsed_s", candidates[0]
    raise ValueError("Could not locate EDF table header (Epoch_UTC ... Elapsed_s)")


def load_edf(path: Path) -> tuple[np.ndarray, np.ndarray, str]:
    header_row, time_col, flow_col = detect_columns(path)
    data = pd.read_csv(
        path, sep="\t", skiprows=header_row,
        usecols=[time_col, flow_col], low_memory=False,
        encoding="utf-8-sig", encoding_errors="replace",
    )
    time_s = pd.to_numeric(data[time_col], errors="coerce").to_numpy(dtype=float)
    flow = pd.to_numeric(data[flow_col], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(time_s) & np.isfinite(flow)
    bad_rows = int((~valid).sum())
    if bad_rows:
        print(f"Warning: excluded {bad_rows:,} rows with invalid time/flow values.")
    time_s, flow = time_s[valid], flow[valid]
    if len(time_s) < 10:
        raise ValueError("Fewer than ten usable EDF measurements")
    order = np.argsort(time_s, kind="stable")
    time_s, flow = time_s[order], flow[order]
    time_s = time_s - time_s[0]
    return time_s, flow, flow_col


def bounded(t: np.ndarray, q: np.ndarray, a_h: float, b_h: float):
    mask = (t >= a_h * 3600) & (t < b_h * 3600)
    return t[mask], q[mask]


def describe(values: np.ndarray) -> dict:
    if len(values) == 0:
        return dict(count=0, mean=np.nan, sd=np.nan, cv_pct=np.nan,
                    median=np.nan, p05=np.nan, p95=np.nan, minimum=np.nan, maximum=np.nan)
    mean = float(np.mean(values))
    sd = float(np.std(values, ddof=1)) if len(values) > 1 else np.nan
    return dict(
        count=len(values), mean=mean, sd=sd,
        cv_pct=100 * sd / abs(mean) if np.isfinite(sd) and abs(mean) > 1e-12 else np.nan,
        median=float(np.median(values)), p05=float(np.percentile(values, 5)),
        p95=float(np.percentile(values, 95)), minimum=float(np.min(values)),
        maximum=float(np.max(values)),
    )


def integrated_ul(t: np.ndarray, q: np.ndarray) -> float:
    if len(t) < 2:
        return np.nan
    return float(np.trapezoid(q, t) / 60) if hasattr(np, "trapezoid") else float(np.trapz(q, t) / 60)


def bin_to_minutes(t: np.ndarray, q: np.ndarray, start_h: float, end_h: float):
    ts, qs = bounded(t, q, start_h, end_h)
    if len(ts) == 0:
        return np.array([]), np.array([])
    minutes = np.floor((ts - start_h * 3600) / 60).astype(int)
    count = np.bincount(minutes)
    totals = np.bincount(minutes, weights=qs)
    means = np.divide(totals, count, out=np.full_like(totals, np.nan), where=count > 0)
    centers_h = start_h + (np.arange(len(means)) + 0.5) / 60
    return centers_h, means


def boolean_runs(mask: np.ndarray) -> list[tuple[int, int, bool]]:
    if len(mask) == 0:
        return []
    edges = np.flatnonzero(np.diff(mask.astype(np.int8)) != 0) + 1
    starts = np.r_[0, edges]
    ends = np.r_[edges, len(mask)]
    return [(int(a), int(b), bool(mask[a])) for a, b in zip(starts, ends)]


def expected_flow_for_stage(time_s: np.ndarray, stage: dict) -> np.ndarray:
    elapsed = time_s - stage["start_h"] * 3600
    base = stage["target_ul_min"]
    mode = stage["behavior"]
    if mode == "off":
        return np.zeros_like(elapsed)
    if mode == "constant":
        return np.full_like(elapsed, base)
    if mode == "pulsed":
        pulse_on = (elapsed * stage["pulse_frequency_hz"]) % 1 < stage["duty"]
        return np.where(pulse_on, base, 0.0)
    if mode == "oscillatory":
        return base + stage["amplitude_ul_min"] * np.sin(
            2 * np.pi * stage["oscillation_frequency_hz"] * elapsed)
    if mode == "combined":
        pulse_on = (elapsed * stage["pulse_frequency_hz"]) % 1 < stage["duty"]
        waveform = base + stage["amplitude_ul_min"] * np.sin(
            2 * np.pi * stage["oscillation_frequency_hz"] * elapsed)
        return np.where(pulse_on, waveform, 0.0)
    raise ValueError(f"Unknown defined program mode: {mode}")


def phase_statistics(t: np.ndarray, q: np.ndarray) -> tuple[list[dict], list[dict]]:
    phases = []
    cycles = []
    for phase in PROGRAM_STAGES:
        ts, qs = bounded(t, q, phase["start_h"], phase["end_h"])
        if len(qs) == 0:
            continue
        whole = describe(qs)
        active = describe(qs[qs > OFF_THRESHOLD_UL_MIN])
        target = phase["target_ul_min"]
        ideal = expected_flow_for_stage(ts, phase)
        differences = qs - ideal
        row = dict(
            phase=phase["name"], programmed_behavior=phase["behavior"],
            start_h=phase["start_h"], end_h=phase["end_h"],
            target_ul_min=target, sample_count=whole["count"],
            measured_mean_all_ul_min=whole["mean"],
            sd_all_ul_min=whole["sd"], cv_all_pct=whole["cv_pct"],
            median_all_ul_min=whole["median"], p05_ul_min=whole["p05"],
            p95_ul_min=whole["p95"], integrated_volume_ul=integrated_ul(ts, qs),
            active_fraction=float(np.mean(qs > OFF_THRESHOLD_UL_MIN)),
            mean_when_active_ul_min=active["mean"],
            cv_when_active_pct=active["cv_pct"],
            ideal_program_mean_ul_min=float(np.mean(ideal)),
            mean_measured_minus_ideal_ul_min=float(np.mean(differences)),
            mae_to_ideal_ul_min=float(np.mean(np.abs(differences))),
            rmse_to_ideal_ul_min=float(np.sqrt(np.mean(differences ** 2))),
            interpretation_note=("scheduled OFF: assess leakage only" if phase["behavior"] == "off"
                                 else "CV includes intentional modulation; ideal waveform assumes phase alignment"
                                 if phase["behavior"] not in ("constant", "off")
                                 else "constant: includes any brief switching-related dips"),
        )
        if phase["behavior"] == "constant":
            row["error_vs_target_ul_min"] = whole["mean"] - target
            row["error_vs_target_pct"] = 100 * (whole["mean"] - target) / target
        else:
            row["error_vs_target_ul_min"] = np.nan
            row["error_vs_target_pct"] = np.nan
        phases.append(row)

        minute_h, minute_q = bin_to_minutes(t, q, phase["start_h"], phase["end_h"])
        if len(minute_q) == 0:
            continue
        on = np.nan_to_num(minute_q, nan=0) > OFF_THRESHOLD_UL_MIN
        for i, (a, b, active_flag) in enumerate(boolean_runs(on)):
            cycles.append(dict(
                phase=phase["name"], block_number=i + 1,
                observed_state="ON" if active_flag else "OFF",
                start_h=phase["start_h"] + a / 60,
                end_h=phase["start_h"] + b / 60,
                duration_min=b - a,
                mean_flow_ul_min=float(np.nanmean(minute_q[a:b])),
            ))
    return phases, cycles


def constant_phase_metrics(t: np.ndarray, q: np.ndarray):
    metrics = []
    events = []
    for phase in CONSTANT_ACTIVE_WINDOWS:
        ts, qs = bounded(t, q, phase["start_h"], phase["end_h"])
        if len(qs) < 10:
            continue
        q90 = float(np.percentile(qs, 90))
        upper = qs[qs >= 0.6 * q90]
        plateau = float(np.median(upper)) if len(upper) else np.nan
        threshold = DIP_THRESHOLD_FRACTION * plateau
        low = qs < threshold
        raw = describe(qs)
        normal = describe(qs[~low])
        target = phase["target_ul_min"]
        metrics.append(dict(
            window=phase["name"], start_h=phase["start_h"], end_h=phase["end_h"],
            programmed_target_ul_min=target,
            estimated_local_plateau_ul_min=plateau,
            dip_detection_threshold_ul_min=threshold,
            measured_mean_including_dips_ul_min=raw["mean"],
            measured_cv_including_dips_pct=raw["cv_pct"],
            measured_mean_excluding_candidate_dips_ul_min=normal["mean"],
            measured_cv_excluding_candidate_dips_pct=normal["cv_pct"],
            fraction_below_threshold=float(np.mean(low)),
            volume_delivered_ul=integrated_ul(ts, qs),
            mean_error_including_dips_pct=(100 * (raw["mean"] - target) / target
                                           if target else np.nan),
            mean_error_excluding_dips_pct=(100 * (normal["mean"] - target) / target
                                           if target else np.nan),
        ))
        for a, b, is_low in boolean_runs(low):
            if not is_low:
                continue
            dt = np.median(np.diff(ts))
            duration = float(ts[b - 1] - ts[a] + dt)
            if not (MIN_DIP_DURATION_S <= duration <= MAX_DIP_DURATION_S):
                continue
            ev_t = ts[a:b]
            ev_q = qs[a:b]
            deficit = (np.trapezoid(np.maximum(0.0, plateau - ev_q), ev_t) / 60
                       if len(ev_t) > 1 and hasattr(np, "trapezoid") else
                       (np.trapz(np.maximum(0.0, plateau - ev_q), ev_t) / 60
                        if len(ev_t) > 1 else 0.0))
            events.append(dict(
                window=phase["name"], start_h=ts[a] / 3600,
                end_h=ts[b - 1] / 3600,
                duration_s=duration,
                min_flow_ul_min=float(np.min(ev_q)),
                drop_fraction_from_local_plateau=float(1 - np.min(ev_q) / plateau),
                estimated_flow_deficit_ul=float(deficit),
                identity="flow transient identified by experimenter as syringe switching",
            ))
    return metrics, events


def switching_characterization(t: np.ndarray, q: np.ndarray):
    summaries, events = [], []
    for stage in PROGRAM_STAGES:
        if stage["behavior"] == "off":
            continue
        ts, qs = bounded(t, q, stage["start_h"], stage["end_h"])
        if len(ts) < 10:
            continue
        dt = float(np.median(np.diff(ts)))
        ideal = expected_flow_for_stage(ts, stage)
        active = ideal > OFF_THRESHOLD_UL_MIN
        if stage["behavior"] in ("pulsed", "combined"):
            period_s = 1 / stage["pulse_frequency_hz"]
            offset_s = (ts - stage["start_h"] * 3600) % period_s
            active &= (offset_s >= PROGRAM_EDGE_EXCLUSION_S)
            active &= (offset_s < stage["duty"] * period_s - PROGRAM_EDGE_EXCLUSION_S)
        else:
            active &= ts >= stage["start_h"] * 3600 + PROGRAM_EDGE_EXCLUSION_S
            active &= ts < stage["end_h"] * 3600 - PROGRAM_EDGE_EXCLUSION_S
        if not np.any(active):
            continue
        if stage["behavior"] == "constant":
            q90 = float(np.percentile(qs, 90))
            plateau = float(np.median(qs[qs >= 0.6 * q90]))
            scale = plateau / stage["target_ul_min"]
        else:
            scale = float(np.percentile(qs[active] / ideal[active], 70))
        baseline = ideal * scale
        falling = active & (qs < DIP_THRESHOLD_FRACTION * baseline)
        below_90 = active & (qs < 0.9 * baseline)
        wider_runs = [(a, b) for a, b, flagged in boolean_runs(below_90) if flagged]
        wider_starts = np.asarray([a for a, _ in wider_runs], dtype=int)
        on_ids = np.cumsum(active & ~np.r_[False, active[:-1]])
        starts_by_on_segment = {}
        rows = []
        for a, b, flagged in boolean_runs(falling):
            if not flagged:
                continue
            duration = float(ts[b - 1] - ts[a] + dt)
            if duration < MIN_DIP_DURATION_S or duration > MAX_DIP_DURATION_S:
                continue
            depths = 100 * (1 - qs[a:b] / baseline[a:b])
            maximum_depth = float(np.max(depths))
            minimum_position = a + int(np.argmax(depths))
            wider_index = int(np.searchsorted(wider_starts, a, side="right") - 1)
            a90, b90 = wider_runs[wider_index]
            full_duration_s = float(ts[b90 - 1] - ts[a90] + dt)
            fall_s = float(ts[minimum_position] - ts[a90])
            recovery_s = float(ts[b90 - 1] + dt - ts[minimum_position])
            starts_by_on_segment.setdefault(int(on_ids[a]), []).append(float(ts[a]))
            rows.append(dict(
                stage=stage["name"], behavior=stage["behavior"],
                syringe_capacity_ul=SYRINGE_CAPACITY_UL,
                start_h=float(ts[a] / 3600),
                end_h=float(ts[b - 1] / 3600),
                duration_below_threshold_s=duration,
                duration_below_90pct_baseline_s=full_duration_s,
                fall_time_to_min_from_90pct_s=fall_s,
                recovery_time_from_min_to_90pct_s=recovery_s,
                median_normal_baseline_ul_min=float(np.median(baseline[a:b])),
                minimum_measured_flow_ul_min=float(np.min(qs[a:b])),
                maximum_drop_pct_raw=maximum_depth,
                maximum_drop_pct_capped=float(np.clip(maximum_depth, 0, 100)),
            ))
        gaps = np.asarray([gap for starts in starts_by_on_segment.values()
                           for gap in np.diff(starts)], dtype=float)
        durations = np.asarray([r["duration_below_threshold_s"] for r in rows])
        full_durations = np.asarray([r["duration_below_90pct_baseline_s"] for r in rows])
        fall_times = np.asarray([r["fall_time_to_min_from_90pct_s"] for r in rows])
        recovery_times = np.asarray([r["recovery_time_from_min_to_90pct_s"] for r in rows])
        depths = np.asarray([r["maximum_drop_pct_capped"] for r in rows])
        def percentile(x, p):
            return float(np.percentile(x, p)) if len(x) else np.nan
        active_duration_s = float(np.count_nonzero(active) * dt)
        median_gap = percentile(gaps, 50)
        summaries.append(dict(
            stage=stage["name"], behavior=stage["behavior"],
            syringe_capacity_ul=SYRINGE_CAPACITY_UL,
            programmed_target_ul_min=stage["target_ul_min"],
            detection_threshold_pct_of_baseline=100 * DIP_THRESHOLD_FRACTION,
            excluded_seconds_at_programmed_edges=PROGRAM_EDGE_EXCLUSION_S,
            observed_active_hours=active_duration_s / 3600,
            switching_events=len(rows),
            events_per_active_minute=(60 * len(rows) / active_duration_s
                                      if active_duration_s else np.nan),
            median_interevent_interval_s=median_gap,
            p05_interevent_interval_s=percentile(gaps, 5),
            p95_interevent_interval_s=percentile(gaps, 95),
            median_drop_duration_s=percentile(durations, 50),
            p05_drop_duration_s=percentile(durations, 5),
            p95_drop_duration_s=percentile(durations, 95),
            median_full_transient_duration_s=percentile(full_durations, 50),
            p05_full_transient_duration_s=percentile(full_durations, 5),
            p95_full_transient_duration_s=percentile(full_durations, 95),
            median_fall_time_s=percentile(fall_times, 50),
            median_recovery_time_s=percentile(recovery_times, 50),
            median_maximum_drop_pct=percentile(depths, 50),
            p05_maximum_drop_pct=percentile(depths, 5),
            p95_maximum_drop_pct=percentile(depths, 95),
            fraction_active_samples_below_threshold=float(np.mean(falling[active])),
            baseline_scaling_relative_to_command=scale,
            nominal_full_syringe_time_s=(60 * SYRINGE_CAPACITY_UL / stage["target_ul_min"]
                                         if stage["behavior"] == "constant" else np.nan),
            nominal_fluid_volume_per_event_ul=(stage["target_ul_min"] * median_gap / 60
                                                if stage["behavior"] == "constant" else np.nan),
        ))
        events.extend(rows)
    return summaries, events


def hourly_statistics(t: np.ndarray, q: np.ndarray) -> list[dict]:
    rows = []
    for hour in range(int(np.ceil(t[-1] / 3600))):
        ts, qs = bounded(t, q, hour, hour + 1)
        if len(qs) < 2:
            continue
        stage = next((s for s in PROGRAM_STAGES
                      if s["start_h"] <= hour < s["end_h"]), None)
        if stage is None:
            continue
        target = expected_flow_for_stage(ts, stage)
        obs = describe(qs)
        rows.append(dict(
            start_h=hour, end_h=hour + 1, stage=stage["name"],
            commanded_behavior=stage["behavior"],
            mean_observed_ul_min=obs["mean"], sd_observed_ul_min=obs["sd"],
            median_observed_ul_min=obs["median"],
            mean_programmed_ul_min=float(np.mean(target)),
            volume_observed_ul=integrated_ul(ts, qs),
            volume_programmed_ul=integrated_ul(ts, target),
            mean_signed_difference_ul_min=float(np.mean(qs - target)),
            mean_absolute_difference_ul_min=float(np.mean(np.abs(qs - target))),
            fraction_flow_above_off_threshold=float(np.mean(qs > OFF_THRESHOLD_UL_MIN)),
        ))
    return rows


def cycle_characterization(t: np.ndarray, q: np.ndarray) -> tuple[list[dict], list[dict]]:
    cycle_rows = []
    repeats = []
    for stage in PROGRAM_STAGES:
        mode = stage["behavior"]
        if mode not in ("pulsed", "oscillatory", "combined"):
            continue
        freq = (stage["oscillation_frequency_hz"] if mode == "oscillatory"
                else stage["pulse_frequency_hz"])
        period_s = 1 / freq
        ts, qs = bounded(t, q, stage["start_h"], stage["end_h"])
        rel = ts - stage["start_h"] * 3600
        if not len(ts):
            continue
        cycle_index = np.floor(rel / period_s).astype(int)
        for k in np.unique(cycle_index):
            mask = cycle_index == k
            q_k, rel_k = qs[mask], rel[mask]
            elapsed_in_cycle = rel_k - k * period_s
            if mode == "oscillatory":
                requested_on = np.ones(len(q_k), dtype=bool)
            else:
                requested_on = elapsed_in_cycle < stage["duty"] * period_s
            on_q = q_k[requested_on]
            off_q = q_k[~requested_on]
            cycle_rows.append(dict(
                stage=stage["name"], behavior=mode, cycle_number=int(k) + 1,
                cycle_start_h=stage["start_h"] + k * period_s / 3600,
                programmed_period_min=period_s / 60,
                requested_on_fraction=float(np.mean(requested_on)),
                measured_on_mean_ul_min=float(np.mean(on_q)) if len(on_q) else np.nan,
                measured_off_mean_ul_min=float(np.mean(off_q)) if len(off_q) else np.nan,
                measured_on_p05_ul_min=float(np.percentile(on_q, 5)) if len(on_q) else np.nan,
                measured_on_p95_ul_min=float(np.percentile(on_q, 95)) if len(on_q) else np.nan,
                measured_on_cv_pct=describe(on_q)["cv_pct"],
                measured_observed_on_fraction=float(np.mean(q_k > OFF_THRESHOLD_UL_MIN)),
                delivered_volume_ul=integrated_ul(ts[mask], q_k),
                note="cycle-to-cycle repeatability within one experiment only",
            ))
        stage_cycles = [r for r in cycle_rows if r["stage"] == stage["name"]]
        onmeans = np.array([r["measured_on_mean_ul_min"] for r in stage_cycles], dtype=float)
        offmeans = np.array([r["measured_off_mean_ul_min"] for r in stage_cycles], dtype=float)
        on_stats = describe(onmeans[np.isfinite(onmeans)])
        off_stats = describe(offmeans[np.isfinite(offmeans)])
        repeats.append(dict(
            stage=stage["name"], behavior=mode,
            observed_cycles=len(stage_cycles),
            cycle_on_mean_ul_min=on_stats["mean"],
            cycle_on_mean_sd_ul_min=on_stats["sd"],
            cycle_on_mean_cv_pct=on_stats["cv_pct"],
            cycle_off_mean_ul_min=off_stats["mean"],
            cycle_off_mean_sd_ul_min=off_stats["sd"],
            note="within-run cycles are not independent run or syringe replicates",
        ))
    return cycle_rows, repeats


def constant_flow_drift(t: np.ndarray, q: np.ndarray) -> list[dict]:
    drift_rows = []
    for stage in CONSTANT_ACTIVE_WINDOWS:
        ts, qs = bounded(t, q, stage["start_h"], stage["end_h"])
        if len(qs) < 10:
            continue
        plateau = np.median(qs[qs >= 0.6 * np.percentile(qs, 90)])
        normal = qs >= DIP_THRESHOLD_FRACTION * plateau
        half_hour_idx = np.floor((ts - stage["start_h"] * 3600) / 1800).astype(int)
        x_h, medians = [], []
        for j in np.unique(half_hour_idx):
            vals = qs[(half_hour_idx == j) & normal]
            if len(vals) >= 5:
                x_h.append((j + 0.5) / 2)
                medians.append(float(np.median(vals)))
        if len(x_h) < 3:
            continue
        slope = float(np.polyfit(x_h, medians, deg=1)[0])
        drift_rows.append(dict(
            stage=stage["name"], duration_h=stage["end_h"] - stage["start_h"],
            programmed_target_ul_min=stage["target_ul_min"],
            first_half_hour_median_ul_min=medians[0],
            last_half_hour_median_ul_min=medians[-1],
            linear_drift_ul_min_per_hour=slope,
            linear_drift_percent_of_target_per_hour=100 * slope / stage["target_ul_min"],
            n_half_hour_windows=len(medians),
            note="observational trend, not statistical replicates",
        ))
    return drift_rows


def transition_characterization(t: np.ndarray, q: np.ndarray) -> list[dict]:
    rows = []
    for previous, following in zip(PROGRAM_STAGES[:-1], PROGRAM_STAGES[1:]):
        boundary_s = following["start_h"] * 3600
        before = q[(t >= boundary_s - 300) & (t < boundary_s)]
        after = q[(t >= boundary_s) & (t < boundary_s + 300)]
        if not len(before) or not len(after):
            continue
        rows.append(dict(
            boundary_h=following["start_h"], from_stage=previous["name"],
            to_stage=following["name"],
            measured_last_5min_median_ul_min=float(np.median(before)),
            measured_first_5min_median_ul_min=float(np.median(after)),
            first_5min_min_ul_min=float(np.min(after)),
            first_5min_max_ul_min=float(np.max(after)),
            note="commanded mode transition, not an automatic syringe-refill event",
        ))
    return rows


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        all_fields = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(f, fieldnames=all_fields)
        writer.writeheader()
        writer.writerows(rows)


def minute_reference_table(t: np.ndarray, q: np.ndarray) -> list[dict]:
    ideal = np.full_like(q, np.nan)
    for stage in PROGRAM_STAGES:
        mask = (t >= stage["start_h"] * 3600) & (t < stage["end_h"] * 3600)
        if np.any(mask):
            ideal[mask] = expected_flow_for_stage(t[mask], stage)
    minute_index = np.floor(t / 60).astype(int)
    n = np.bincount(minute_index)
    q_mean = np.divide(np.bincount(minute_index, weights=q), n,
                       out=np.full(len(n), np.nan), where=n > 0)
    known = np.isfinite(ideal)
    ideal_count = np.bincount(minute_index[known], minlength=len(n))
    ideal_mean = np.divide(
        np.bincount(minute_index[known], weights=ideal[known], minlength=len(n)),
        ideal_count, out=np.full(len(n), np.nan), where=ideal_count > 0)
    return [
        dict(elapsed_h=(minute + 0.5) / 60,
             measured_flow_ul_min=float(q_mean[minute]),
             programmed_ideal_ul_min=float(ideal_mean[minute]),
             n_native_samples=int(n[minute]))
        for minute in range(len(n)) if n[minute] > 0
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edf", type=Path,
                        default=Path(__file__).resolve().parent / "5day_experiment.edf")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parent / "5day_characterization")
    parser.add_argument("--target-first", type=float,
                        help="Override first programmed constant-flow rate (default 95 uL/min)")
    parser.add_argument("--target-second", type=float,
                        help="Override second programmed constant-flow rate (default 175 uL/min)")
    args = parser.parse_args()
    if not args.edf.is_file():
        parser.error(f"File not found: {args.edf}. Place EDF beside script or use --edf PATH.")
    for i, arg in enumerate((args.target_first, args.target_second)):
        if arg is not None:
            if arg <= 0:
                parser.error("Programmed targets must be > 0")
            PROGRAM_STAGES[2 * i]["target_ul_min"] = arg
            CONSTANT_ACTIVE_WINDOWS[i]["target_ul_min"] = arg

    print("Reading source EDF; this may take a minute for five days at 10 Hz ...")
    t, q, flow_column = load_edf(args.edf)
    positive_diffs = np.diff(t)
    positive_diffs = positive_diffs[positive_diffs > 0]
    interval = float(np.median(positive_diffs)) if len(positive_diffs) else np.nan
    overall_hours = float((t[-1] - t[0]) / 3600)
    phases, blocks = phase_statistics(t, q)
    constant_metrics, candidate_dips = constant_phase_metrics(t, q)
    switching_metrics, switching_events = switching_characterization(t, q)
    hourly = hourly_statistics(t, q)
    cycles, repeatability = cycle_characterization(t, q)
    drift = constant_flow_drift(t, q)
    transitions = transition_characterization(t, q)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    write_csv(args.output_dir / "phase_summary.csv", phases)
    write_csv(args.output_dir / "programmed_schedule.csv", PROGRAM_STAGES)
    write_csv(args.output_dir / "observed_on_off_blocks.csv", blocks)
    write_csv(args.output_dir / "constant_window_metrics.csv", constant_metrics)
    write_csv(args.output_dir / "candidate_dropouts.csv", candidate_dips)
    write_csv(args.output_dir / "switching_characterization_by_stage.csv", switching_metrics)
    write_csv(args.output_dir / "switching_transient_events.csv", switching_events)
    write_csv(args.output_dir / "programmed_vs_measured_1min.csv", minute_reference_table(t, q))
    write_csv(args.output_dir / "hourly_statistics.csv", hourly)
    write_csv(args.output_dir / "programmed_cycle_statistics.csv", cycles)
    write_csv(args.output_dir / "within_run_cycle_repeatability.csv", repeatability)
    write_csv(args.output_dir / "constant_flow_drift.csv", drift)
    write_csv(args.output_dir / "programmed_transitions.csv", transitions)

    summary = [
        "FIVE-DAY FLOW CHARACTERIZATION (known nine-stage reference program)",
        "=" * 65,
        f"Input: {args.edf.name}",
        f"Flow column: {flow_column}",
        f"Usable flow records: {len(q):,}",
        f"Recorded elapsed time: {overall_hours:.3f} h",
        f"Median measurement interval: {interval:.5f} s (nominal EDF metadata: 0.1 s)",
        f"Median flow over entire recording: {np.median(q):.3f} uL/min",
        f"Flow range: {np.min(q):.3f} to {np.max(q):.3f} uL/min",
        f"Integrated delivered volume: {integrated_ul(t, q):,.1f} uL",
        f"Samples below OFF threshold ({OFF_THRESHOLD_UL_MIN} uL/min): "
        f"{100 * np.mean(q < OFF_THRESHOLD_UL_MIN):.2f}%",
        "",
        "Constant-flow intervals (from the previously defined nine-stage program):",
    ]
    for m in constant_metrics:
        summary.extend([
            f"  {m['window']}: {m['start_h']:.1f}–{m['end_h']:.1f} h",
            f"    Mean including dips: {m['measured_mean_including_dips_ul_min']:.3f} uL/min",
            f"    CV including dips: {m['measured_cv_including_dips_pct']:.2f}%",
            f"    Local plateau: {m['estimated_local_plateau_ul_min']:.3f} uL/min",
            f"    CV excluding candidate dips: {m['measured_cv_excluding_candidate_dips_pct']:.2f}%",
            f"    Error vs programmed target, including dips: "
            f"{m['mean_error_including_dips_pct']:.2f}%",
        ])
    summary.append("")
    summary.append("Syringe-switching flow transients (experimenter-identified):")
    for row in switching_metrics:
        summary.append(
            f"  {row['stage']}: n={row['switching_events']:,}; "
            f"median depth={row['median_maximum_drop_pct']:.1f}%; "
            f"median below-70% duration={row['median_drop_duration_s']:.3f} s; "
            f"median below-90% duration={row['median_full_transient_duration_s']:.3f} s; "
            f"median interval={row['median_interevent_interval_s']:.3f} s; "
            f"{row['events_per_active_minute']:.2f} events/active min")
    summary.append("  Depth is measured from a stage-specific normal-flow baseline.")
    summary.append("  Fall and recovery durations use 90% of the normal baseline.")
    summary.append("  Intended OFF periods and programmed switching edges are excluded.")
    summary.append("  Brief negative sensor readings are capped at 100% flow reduction.")
    summary.append("")
    summary.append("Within-run cycles of prescribed dynamic behaviors:")
    for row in repeatability:
        summary.append(
            f"  {row['stage']}: n={row['observed_cycles']} cycles; "
            f"mean ON flow={row['cycle_on_mean_ul_min']:.2f} uL/min; "
            f"cycle-to-cycle CV={row['cycle_on_mean_cv_pct']:.2f}%")
    summary.append("")
    summary.append("Drift of constant-flow plateau (short dips excluded):")
    for row in drift:
        summary.append(
            f"  {row['stage']}: slope={row['linear_drift_ul_min_per_hour']:.4f} "
            f"uL/min/h ({row['linear_drift_percent_of_target_per_hour']:.4f}% of target/h)")
    summary.extend([
        "",
        f"Detected switching-related flow drops in constant-flow windows: {len(candidate_dips)}",
        "  Event identity was confirmed by the experimenter, not independently",
        "  determined from sensor readings or recorded valve-state timestamps.",
        "",
        "Output files:",
        "  programmed_schedule.csv: nine-stage schedule confirmed by experimenter",
        "  phase_summary.csv: per-command-stage metrics, including exploratory ideal-waveform errors",
        "  programmed_vs_measured_1min.csv: one-minute mean measurement and ideal profile",
        "  observed_on_off_blocks.csv: minute-scale flow ON/OFF blocks (not pump commands)",
        "  constant_window_metrics.csv: steady intervals with and without candidate dips",
        "  candidate_dropouts.csv: candidate short transients in constant intervals",
        "  switching_characterization_by_stage.csv: flow-drop statistics for all active modes",
        "  switching_transient_events.csv: individual flow-drop events in all active modes",
        "  hourly_statistics.csv: hourly mean, drift context, and waveform error",
        "  programmed_cycle_statistics.csv: per-cycle ON/OFF characteristics",
        "  within_run_cycle_repeatability.csv: cycle variation within the SAME run",
        "  constant_flow_drift.csv: trend in constant-flow plateaus",
        "  programmed_transitions.csv: 5-minute observations at command boundaries",
        "",
        "Analysis caveats:",
        "  - The nine-stage reference and 50-uL syringe size were confirmed by the experimenter.",
        "  - CV during programmed pulses/oscillations is not pump precision.",
        "  - Dynamic-waveform RMSE/MAE assumes zero command latency and phase offset.",
        "  - Pump-state timestamps are needed for an independent event-by-event",
        "    confirmation of syringe-switching assignments.",
        "  - Inter-run reproducibility requires independent experimental replicates.",
        "  - No matched commercial dual-pump or active-vs-passive valve comparison",
        "    can be established using this one DIY-pump EDF recording.",
    ])
    text = "\n".join(summary) + "\n"
    (args.output_dir / "analysis_summary.txt").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
