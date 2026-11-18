#!/usr/bin/env python3
"""Reproducible, memory-bounded analysis of the DSCPM 1.5 uL/min video.

The color-front tracker is checked against the grayscale edge detector from
DSCPM_Fig4_edgedetection.ipynb. No commercial flow sensor is assumed.

The conversion reproduces the original notebook's calibration: 150 mm across
the cropped video width, and 0.127 mm tubing inner radius.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageFilter
from scipy.ndimage import gaussian_filter1d


def video_metadata(path: Path) -> dict:
    raw = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,avg_frame_rate,nb_frames:format=duration", "-of", "json", str(path)]
    )
    obj = json.loads(raw)
    stream = obj["streams"][0]
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "nominal_frame_rate": stream.get("avg_frame_rate", "60/1"),
        "declared_frames": int(stream.get("nb_frames", 0)),
        "duration_sec": float(obj["format"]["duration"]),
    }


def frame_timestamps(path: Path) -> np.ndarray:
    lines = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "frame=best_effort_timestamp_time", "-of", "csv=p=0", str(path)],
        text=True,
    ).splitlines()
    values = []
    for line in lines:
        value = line.strip().rstrip(",")
        if value and value != "N/A":
            values.append(float(value))
    return np.asarray(values, dtype=float)


def original_gray_edge(rgb: np.ndarray, threshold: int = 7) -> float:
    """Exact scanning/blur/threshold logic from the supplied notebook."""
    grayscale = np.asarray(Image.fromarray(rgb).convert("L").filter(ImageFilter.GaussianBlur(2)))
    gradient = np.abs(np.diff(grayscale.astype(np.int16), axis=1)) > threshold
    matches = np.flatnonzero(gradient)
    if len(matches) == 0:
        return float("nan")
    return float(matches[0] % (rgb.shape[1] - 1) + 1)


def blue_front(rgb: np.ndarray, threshold: float = 25.0) -> tuple[float, float]:
    """Independent fluid-front estimate based on the blue dye color signal."""
    height = rgb.shape[0]
    y_low, y_high = round(height * 0.34), round(height * 0.50)
    channel = rgb[y_low:y_high].astype(np.int16)
    signal = np.median(channel[:, :, 2] - channel[:, :, 0], axis=0)
    signal = gaussian_filter1d(signal.astype(float), 3.0)
    hits = np.flatnonzero(signal > threshold)
    if not len(hits):
        return float("nan"), 0.0
    front = int(hits[-1])
    # Quantifies how much of the path preceding the front is identified as blue.
    connected_fraction = len(hits[hits <= front]) / (front + 1)
    return float(front), float(connected_fraction)


def read_and_track(path: Path, width: int, height: int, sample_every: int):
    process = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-map", "0:v:0", "-vsync", "0", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=8 * 1024 * 1024,
    )
    frame_size = width * height * 3
    color_positions = []
    color_coverage = []
    legacy_samples = []
    count = 0
    try:
        while True:
            raw = process.stdout.read(frame_size)
            if not raw:
                break
            if len(raw) != frame_size:
                raise ValueError(f"Partial frame encountered: {len(raw)} bytes")
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3))
            position, coverage = blue_front(frame)
            color_positions.append(position)
            color_coverage.append(coverage)
            if count % sample_every == 0:
                old_position = original_gray_edge(frame)
                legacy_samples.append((count, old_position, position))
            count += 1
            if count % 3000 == 0:
                print(f"Tracked {count:,} frames ...", flush=True)
    finally:
        if process.stdout is not None:
            process.stdout.close()
    code = process.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg exited with code {code}: {process.stderr.read().decode()[:1000]}")
    return np.asarray(color_positions), np.asarray(color_coverage), np.asarray(legacy_samples)


def bin_rates(time: np.ndarray, volume: np.ndarray, *, start: float, stop: float, seconds: float):
    edges = np.arange(start, stop + seconds / 2, seconds)
    edges = edges[edges <= stop + 1e-6]
    vals = np.interp(edges, time, volume)
    rates = np.diff(vals) * 60 / seconds
    centers = (edges[:-1] + edges[1:]) / 2
    return centers, rates


def stats(rates: np.ndarray) -> dict:
    rates = np.asarray(rates, dtype=float)
    mean = float(np.nanmean(rates))
    return {
        "n_windows": int(np.count_nonzero(np.isfinite(rates))),
        "mean_uL_min": mean,
        "sd_uL_min": float(np.nanstd(rates, ddof=1)) if len(rates) > 1 else None,
        "cv_percent": float(100 * np.nanstd(rates, ddof=1) / mean) if len(rates) > 1 and mean else None,
        "min_uL_min": float(np.nanmin(rates)),
        "max_uL_min": float(np.nanmax(rates)),
        "peak_to_peak_uL_min": float(np.nanmax(rates) - np.nanmin(rates)),
    }


def write_csv(path: Path, names: list[str], rows):
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(names)
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output/pump_1p5_results"))
    parser.add_argument("--legacy-every", type=int, default=30,
                        help="Sample the original grayscale detector every N frames")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    meta = video_metadata(args.video)
    print("Video metadata:", meta, flush=True)
    time = frame_timestamps(args.video)
    position, coverage, legacy = read_and_track(
        args.video, meta["width"], meta["height"], args.legacy_every
    )
    if len(time) != len(position):
        raise ValueError(f"Timestamp count ({len(time)}) != frames ({len(position)})")

    # No dye is visible at the start of this recording: approximate its front as x=0.
    pos = position.copy()
    pos[~np.isfinite(pos)] = 0.0
    area_mm2 = np.pi * 0.127**2
    volume_per_pixel_uL = area_mm2 * (150 / meta["width"])
    volume = pos * volume_per_pixel_uL
    fill_fraction = float(np.mean(np.isfinite(position)))
    suspect = (coverage < 0.95) & np.isfinite(position)

    valid_legacy = legacy[np.isfinite(legacy[:, 1]) & np.isfinite(legacy[:, 2])]
    legacy_difference = valid_legacy[:, 1] - valid_legacy[:, 2]
    time_legacy = time[valid_legacy[:, 0].astype(int)]
    write_csv(args.output / "legacy_tracker_validation.csv",
              ["time_s", "legacy_edge_px", "blue_edge_px", "difference_px"],
              zip(time_legacy, valid_legacy[:, 1], valid_legacy[:, 2], legacy_difference))

    write_csv(args.output / "fluid_front_full_resolution.csv",
              ["time_s", "blue_front_px", "volume_uL", "blue_coverage_fraction"],
              zip(time, position, volume, coverage))

    # Exclude entrance and right-edge saturation for steady-state comparisons.
    start, stop = 20.0, min(280.0, float(time[-1] - 4))
    segment = (time >= start) & (time <= stop)
    slope_uL_sec = float(np.polyfit(time[segment], volume[segment], 1)[0])
    linear_rate = slope_uL_sec * 60
    endpoint_mean_rate = float((np.interp(stop, time, volume) - np.interp(start, time, volume)) * 60 / (stop - start))
    full_movie_mean_rate = float((volume[-1] - volume[0]) * 60 / (time[-1] - time[0]))
    all_window_stats = {}
    window_series = {}
    for seconds in (0.25, 1.0, 5.0, 10.0, 20.0, 60.0):
        centers, rates = bin_rates(time, volume, start=start, stop=stop, seconds=seconds)
        all_window_stats[f"{seconds:g}s"] = stats(rates)
        window_series[seconds] = (centers, rates)
        write_csv(args.output / f"flow_{seconds:g}s_nonoverlap.csv",
                  ["window_center_s", "flow_uL_min"], zip(centers, rates))

    # The transition near 159 s is visible in both trackers and is consistent
    # with a syringe handoff, but actuator/valve logs would be needed to confirm.
    regimes = {}
    for name, (begin, end) in {
        "before_possible_handoff": (20.0, 150.0),
        "after_possible_handoff": (180.0, 280.0),
    }.items():
        inside = (time >= begin) & (time <= end)
        measured = float(np.polyfit(time[inside], volume[inside], 1)[0] * 60)
        local_rates = {}
        for seconds in (1.0, 5.0, 10.0):
            _, values = bin_rates(time, volume, start=begin, stop=end, seconds=seconds)
            local_rates[f"{seconds:g}s"] = stats(values)
        regimes[name] = {
            "interval_s": [begin, end],
            "linear_fit_mean_rate_uL_min": measured,
            "linear_fit_error_percent": 100 * (measured / 1.5 - 1),
            "window_stats": local_rates,
        }

    handoff_start, handoff_end = 159.0, 165.0
    handoff_vol = np.interp([handoff_start, handoff_end], time, volume)
    handoff_net_rate = float((handoff_vol[-1] - handoff_vol[0]) * 60 / 6)

    # Frequency analysis: 0.25-s sampled rate fluctuations reveal periodic stepping.
    from scipy.signal import find_peaks, periodogram

    c025, q025 = window_series[0.25]
    fs = 4.0
    freqs, power = periodogram(q025 - np.mean(q025), fs=fs, window="hann")
    search = (freqs >= 0.15) & (freqs <= 1.2)
    principal_hz = float(freqs[search][np.argmax(power[search])])
    # Peaks are exploratory only: conversion from front motion to q(t) is noisy.
    q_smoothed = gaussian_filter1d(q025, 1.0)
    peak_idxs, _ = find_peaks(q_smoothed, distance=round(1.5 * fs), prominence=0.8)
    peak_times = c025[peak_idxs]
    peak_intervals = np.diff(peak_times)

    summary = {
        "video": str(args.video),
        **meta,
        "decoded_frames": int(len(time)),
        "time_last_frame_s": float(time[-1]),
        "calibration": {"tube_inner_diameter_mm": 0.254, "tube_radius_mm": 0.127,
                        "visible_length_mm": 150.0, "uL_per_pixel": volume_per_pixel_uL},
        "blue_front_visible_fraction": fill_fraction,
        "low_coverage_frame_fraction": float(np.mean(suspect)),
        "legacy_samples_compared": int(len(valid_legacy)),
        "legacy_difference_median_abs_px": float(np.median(np.abs(legacy_difference))),
        "legacy_difference_95th_abs_px": float(np.percentile(np.abs(legacy_difference), 95)),
        "analysis_interval_s": [start, stop],
        "linear_fit_mean_rate_uL_min": linear_rate,
        "linear_fit_error_percent": 100 * (linear_rate / 1.5 - 1),
        "endpoint_mean_rate_20_to_280s_uL_min": endpoint_mean_rate,
        "endpoint_mean_error_20_to_280s_percent": 100 * (endpoint_mean_rate / 1.5 - 1),
        "full_movie_endpoint_mean_rate_uL_min": full_movie_mean_rate,
        "full_movie_endpoint_mean_error_percent": 100 * (full_movie_mean_rate / 1.5 - 1),
        "window_stats": all_window_stats,
        "stable_regimes": regimes,
        "candidate_handoff": {
            "status": "probable, not synchronized to motor/valve event logs",
            "rapid_front_displacement_interval_s": [158.5, 159.0],
            "rapid_displacement_volume_uL": float(np.interp(159, time, volume) - np.interp(158.5, time, volume)),
            "near_plateau_interval_s": [handoff_start, handoff_end],
            "near_plateau_net_flow_uL_min": handoff_net_rate,
        },
        "periodogram_peak_hz": principal_hz,
        "periodogram_peak_interval_s": 1 / principal_hz,
        "exploratory_peak_count": int(len(peak_idxs)),
        "exploratory_peak_interval_median_s": float(np.median(peak_intervals)) if len(peak_intervals) else None,
        "exploratory_peak_interval_iqr_s": [float(v) for v in np.percentile(peak_intervals, [25, 75])]
        if len(peak_intervals) else None,
    }
    (args.output / "analysis_summary.json").write_text(json.dumps(summary, indent=2))

    fig, axs = plt.subplots(3, 1, figsize=(12, 9), sharex=False, layout="constrained")
    axs[0].plot(time, volume, lw=1.2, color="#1262a0", label="Video-derived delivered volume")
    axs[0].axvspan(158.5, 165.0, color="#e0b36b", alpha=0.3, label="Probable handoff")
    axs[0].set(xlabel="Time (s)", ylabel="Delivered volume (µL)", title="Fluid-front tracking: complete 5-minute recording")
    axs[0].legend(frameon=False)
    axs[1].plot(*window_series[1.0], lw=0.8, color="#2b77b7", label="1-s window")
    axs[1].axhline(1.5, color="#dc573c", ls="--", lw=1.3, label="Programmed rate: 1.5 µL/min")
    axs[1].axvspan(158.5, 165.0, color="#e0b36b", alpha=0.3, label="Probable handoff")
    axs[1].set(xlim=(start, stop), xlabel="Time (s)", ylabel="Flow rate (µL/min)", title="Measured average flow rate (1-second nonoverlapping intervals)")
    axs[1].legend(frameon=False)
    axs[2].plot(*window_series[10.0], color="#1262a0", marker="o", ms=4, lw=1.2, label="10-s window")
    axs[2].axhline(1.5, color="#dc573c", ls="--", lw=1.3, label="Programmed rate")
    axs[2].axvspan(158.5, 165.0, color="#e0b36b", alpha=0.3)
    axs[2].set(xlim=(start, stop), xlabel="Time (s)", ylabel="Flow rate (µL/min)", title="Measured average flow rate (10-second nonoverlapping intervals)")
    axs[2].legend(frameon=False)
    fig.savefig(args.output / "overview_volume_and_flow.png", dpi=200)
    plt.close(fig)

    fig, axs = plt.subplots(2, 1, figsize=(12, 7), layout="constrained")
    axs[0].plot(*window_series[0.25], lw=0.8, color="#1262a0")
    axs[0].axhline(1.5, color="#dc573c", ls="--")
    axs[0].set(xlim=(145, 185), xlabel="Time (s)", ylabel="Flow rate (µL/min)",
               title="Representative 40-second segment (0.25-second averaging)")
    axs[1].plot(freqs[search], power[search], color="#1262a0")
    axs[1].axvline(principal_hz, color="#dc573c", ls="--", label=f"Dominant frequency: {principal_hz:.3f} Hz")
    axs[1].set(xlabel="Frequency (Hz)", ylabel="Periodogram power", title="Frequency content of measured low-flow fluctuations")
    axs[1].legend(frameon=False)
    fig.savefig(args.output / "pulsatility_frequency.png", dpi=200)
    plt.close(fig)

    fig, axs = plt.subplots(2, 1, figsize=(11, 7), layout="constrained")
    axs[0].plot(time, volume, lw=1.3, color="#1262a0")
    axs[0].axvspan(158.5, 165.0, color="#e0b36b", alpha=0.35,
                   label="Probable syringe handoff")
    axs[0].set(xlim=(148, 175), ylim=(3.85, 4.5),
               xlabel="Time (s)", ylabel="Infused volume (µL)",
               title="Video-tracked fluid front around candidate handoff")
    axs[0].legend(frameon=False)
    c1, q1 = window_series[1.0]
    axs[1].plot(c1, q1, color="#1262a0", marker="o", ms=3,
                label="1-second average flow rate")
    axs[1].axhline(1.5, color="#dc573c", ls="--", label="Target")
    axs[1].axvspan(158.5, 165.0, color="#e0b36b", alpha=0.35)
    axs[1].set(xlim=(148, 175), xlabel="Time (s)", ylabel="Flow rate (µL/min)",
               title="Transient: rapid advance followed by near-stationary fluid front")
    axs[1].legend(frameon=False)
    fig.savefig(args.output / "possible_handoff_event.png", dpi=200)
    plt.close(fig)

    report = f"""# DSCPM positional-mode video characterization — 1.5 µL/min

## Source and calibration

- Source: `{args.video.name}`, {len(time):,} decoded frames, {meta['duration_sec']:.3f} seconds.
- Working measurement method: front position of dyed fluid in horizontal tubing (no flow sensor).
- Tube inner diameter: 0.254 mm (radius 0.127 mm); physical width of full video: 150 mm (assumed correct by author).
- Color-front tracker independently checked against the original PIL grayscale-blur edge detector on {len(valid_legacy)} frames; median absolute difference {np.median(np.abs(legacy_difference)):.1f} px; 95th percentile {np.percentile(np.abs(legacy_difference),95):.1f} px.
- Original published notebook printed a 1.4886 µL/min mean for this video; this reanalysis estimates a linear-trend mean of {linear_rate:.4f} µL/min over 20–280 s.

## Main findings

- Programmed flow: 1.500 µL/min.
- Full movie (0–{time[-1]:.1f} s) endpoint-derived mean: {full_movie_mean_rate:.4f} µL/min ({100*(full_movie_mean_rate/1.5-1):+.2f}% relative error).
- Central interval (20–280 s) endpoint-derived mean: {endpoint_mean_rate:.4f} µL/min ({100*(endpoint_mean_rate/1.5-1):+.2f}% relative error).
- Central interval (20–280 s) linear-fit trend: {linear_rate:.4f} µL/min ({100*(linear_rate/1.5-1):+.2f}% relative error). These estimators differ because of transient behavior and nonconstant slope, so specify the estimator in any manuscript claim.
- Dominant flow-fluctuation frequency: {principal_hz:.4f} Hz (period {1/principal_hz:.2f} s), close to the calculated 2.84-second minimum-step interval.
- **Full 20–280 s window statistics (including suspected handoff):** 1-s CV {all_window_stats['1s']['cv_percent']:.1f}%; 10-s CV {all_window_stats['10s']['cv_percent']:.1f}%; 60-s CV {all_window_stats['60s']['cv_percent']:.1f}%. These are within-run temporal CVs, not inter-run reproducibility.
- **Before suspected handoff (20–150 s):** 1-s CV {regimes['before_possible_handoff']['window_stats']['1s']['cv_percent']:.1f}%, 10-s CV {regimes['before_possible_handoff']['window_stats']['10s']['cv_percent']:.1f}%, window-mean rate {regimes['before_possible_handoff']['window_stats']['10s']['mean_uL_min']:.3f} µL/min.
- **After suspected handoff (180–280 s):** 1-s CV {regimes['after_possible_handoff']['window_stats']['1s']['cv_percent']:.1f}%, 10-s CV {regimes['after_possible_handoff']['window_stats']['10s']['cv_percent']:.1f}%, window-mean rate {regimes['after_possible_handoff']['window_stats']['10s']['mean_uL_min']:.3f} µL/min.

## Candidate syringe-handoff transient

- Around 158.5–159.0 s the dyed front moved forward by approximately {summary['candidate_handoff']['rapid_displacement_volume_uL']:.3f} µL.
- During 159–165 s the net change was approximately {handoff_vol[-1]-handoff_vol[0]:.4f} µL, equivalent to {handoff_net_rate:.3f} µL/min, i.e., little movement at the optical measurement resolution.
- The shape is consistent with a syringe exchange but **cannot be confirmed as such without motor/valve event logs**. We should show this transient explicitly and avoid claiming strictly uninterrupted instantaneous flow.

## Interpretation and limitations

- The method gives the movement of a dyed liquid front in the measurement tubing, not a direct flow sensor output inside a loaded biological device.
- The 60-fps numerical derivative is noisy and pixel-quantized. Pulsatility metrics therefore specify their flow averaging window, and reported extrema cannot be interpreted as true millisecond-scale peak flow.
- This is **one video/run**, not three independent replicates; temporal windows are correlated and cannot establish inter-run precision.
- The 150 mm field-of-view calibration is an author-confirmed assumption. The 0.030-inch inner diameter in the submitted Methods should be corrected to **0.010 inch (0.254 mm)**.
- The probable handoff is shorter than a full five-day run and does not by itself establish repeatability of automatic switching over days.

## Recommended language for the revision

*Continuous operation* should be defined as unattended operation through automated syringe refilling, not constant instantaneous outlet flow. *Positional-mode low-flow delivery* should be described as time-averaged delivery with measurable periodic fluctuations and a characterized switching transient. These results belong with the Methods/SI and revised Figure 6.
"""
    (args.output / "analysis_notes.md").write_text(report)

    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
