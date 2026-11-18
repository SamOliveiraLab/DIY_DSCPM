import argparse
import math
import os
import subprocess
import sys
from array import array
from collections import deque
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def load_flow(path, window_seconds, flow_column=None):
    elapsed = array("d")
    flow = array("d")
    moving_average = array("d")
    history = deque()
    running_sum = 0.0
    skipped = 0
    headers = None
    flow_index = None
    time_index = None
    first_time = None
    last_time = None

    with path.open("r", encoding="utf-8-sig", newline="") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue

            values = line.rstrip("\r\n").split("\t")

            if headers is None:
                headers = [item.strip() for item in values]
                if flow_column is not None:
                    if flow_column not in headers:
                        raise ValueError(f"Flow column '{flow_column}' is not in the EDF header")
                    flow_index = headers.index(flow_column)
                else:
                    channels = [i for i, name in enumerate(headers) if name.startswith("F_")]
                    if not channels:
                        channels = [
                            i for i, name in enumerate(headers)
                            if "flow" in name.lower()
                            and "high" not in name.lower()
                            and "air" not in name.lower()
                        ]
                    if len(channels) != 1:
                        raise ValueError(
                            "Could not identify one flow column. "
                            f"Available columns: {', '.join(headers)}. "
                            "Use --flow-column to select one."
                        )
                    flow_index = channels[0]

                for name in ("Elapsed_s", "Epoch_UTC", "Time_s", "Time (s)"):
                    if name in headers:
                        time_index = headers.index(name)
                        break
                if time_index is None:
                    raise ValueError(
                        "EDF needs an Elapsed_s or Epoch_UTC column to plot elapsed time"
                    )
                continue

            try:
                timestamp = float(values[time_index])
                reading = float(values[flow_index])
            except (ValueError, IndexError):
                skipped += 1
                continue

            if not (math.isfinite(timestamp) and math.isfinite(reading)):
                skipped += 1
                continue

            if first_time is None:
                first_time = timestamp
            seconds = timestamp - first_time
            if last_time is not None and seconds < last_time - 1e-6:
                raise ValueError(f"Time decreases at EDF line {line_number}")
            last_time = seconds

            history.append((seconds, reading))
            running_sum += reading
            while history and seconds - history[0][0] > window_seconds:
                running_sum -= history.popleft()[1]

            elapsed.append(seconds / 3600.0)
            flow.append(reading)
            moving_average.append(running_sum / len(history))

    if not flow:
        raise ValueError("No valid flow measurements found in the EDF")

    return (
        np.frombuffer(elapsed, dtype=np.float64),
        np.frombuffer(flow, dtype=np.float64),
        np.frombuffer(moving_average, dtype=np.float64),
        skipped,
    )


def draw_raw(ax, hours, flow, max_points):
    if len(flow) <= max_points:
        ax.plot(
            hours, flow, color="#217e9c", linewidth=0.46,
            alpha=0.62, label="Flow Rate", rasterized=True,
        )
        return

    step = math.ceil(len(flow) / max_points)
    starts = np.arange(0, len(flow), step)
    lows = np.minimum.reduceat(flow, starts)
    highs = np.maximum.reduceat(flow, starts)
    centers = hours[np.minimum(starts + step // 2, len(hours) - 1)]
    ax.vlines(
        centers, lows, highs, color="#217e9c", linewidth=0.43,
        alpha=0.60, label="Flow Rate", rasterized=True,
    )


def select_nearest_rows(hours, sample_seconds):
    targets = np.arange(
        0.0, float(hours[-1]) * 3600.0 + 0.5 * sample_seconds,
        sample_seconds, dtype=np.float64,
    ) / 3600.0
    positions = np.searchsorted(hours, targets, side="left")
    before = np.clip(positions - 1, 0, len(hours) - 1)
    after = np.clip(positions, 0, len(hours) - 1)
    nearest = np.where(
        np.abs(hours[after] - targets) < np.abs(hours[before] - targets),
        after, before,
    )
    return np.unique(nearest)


def plot_flow(hours, flow, moving_average, output, window_minutes, max_raw_points,
              y_max, show, sample_seconds=None, show_average=True):
    fig, ax = plt.subplots(figsize=(18.8, 5.7), dpi=170)
    if sample_seconds is None:
        draw_raw(ax, hours, flow, max_raw_points)
        step = max(1, math.ceil(len(hours) / 75000))
        chosen = np.arange(0, len(hours), step)
        if chosen[-1] != len(hours) - 1:
            chosen = np.append(chosen, len(hours) - 1)
    else:
        chosen = select_nearest_rows(hours, sample_seconds)
        ax.plot(
            hours[chosen], flow[chosen], color="#217e9c",
            linewidth=0.82, alpha=0.84,
            label="Flow Rate",
        )
    if show_average:
        ax.plot(
            hours[chosen], moving_average[chosen],
            color="#dc722a", linewidth=1.7, alpha=0.97,
            label=f"{window_minutes:g}-min moving average", zorder=4,
        )

    ax.set_xlabel("Elapsed time (hours)", fontsize=17, labelpad=9)
    ax.set_ylabel("Flow (µL/min)", fontsize=17, labelpad=10)
    ax.tick_params(axis="both", labelsize=14, length=4, width=0.8)
    ax.set_xlim(0, max(0.01, float(hours[-1])))

    bottom = min(0.0, float(np.min(flow)))
    top = float(np.max(flow))
    padding = max(2.0, 0.04 * (top - bottom))
    ax.set_ylim(bottom - (padding if bottom < 0 else 0), y_max if y_max is not None else top + padding)

    ax.grid(axis="y", color="#e8edf1", linewidth=0.7)
    ax.grid(axis="x", color="#dce3e8", linestyle="--", linewidth=0.75)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_color("#888f94")
        spine.set_linewidth(0.9)

    ax.legend(loc="upper right", fontsize=13, framealpha=0.95,
              facecolor="white", edgecolor="#d6dde2")
    fig.tight_layout(pad=1.1)
    fig.savefig(output, dpi=170, facecolor="white")
    plt.close(fig)
    if show:
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(output.resolve())])
            elif os.name == "nt":
                os.startfile(str(output.resolve()))
            else:
                subprocess.Popen(["xdg-open", str(output.resolve())],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        except (OSError, AttributeError) as exc:
            print(f"Could not open preview automatically: {exc}")
    return len(chosen)


def main():
    parser = argparse.ArgumentParser(description="Plot EDF flow and its moving average")
    parser.add_argument("--edf", type=Path, default=Path("5day_experiment.edf"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--window-minutes", type=float, default=5.0)
    parser.add_argument("--sample-seconds", type=float, default=60.0)
    parser.add_argument("--flow-column")
    parser.add_argument("--max-raw-points", type=int, default=120000)
    parser.add_argument("--y-max", type=float)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    if args.window_minutes <= 0:
        parser.error("--window-minutes must be positive")
    if args.sample_seconds <= 0:
        parser.error("--sample-seconds must be positive")
    if args.max_raw_points < 100:
        parser.error("--max-raw-points must be at least 100")
    script_directory = Path(__file__).resolve().parent
    if args.edf.is_absolute():
        input_path = args.edf
    else:
        adjacent_path = script_directory / args.edf
        input_path = adjacent_path if adjacent_path.is_file() else Path.cwd() / args.edf
    if not input_path.is_file():
        parser.error(f"EDF file not found: {input_path}")

    output = args.output or input_path.with_name(input_path.stem + "_flow.png")
    if output.resolve() == input_path.resolve():
        parser.error("Output path must differ from the EDF input")
    output.parent.mkdir(parents=True, exist_ok=True)

    hours, flow, average, skipped = load_flow(
        input_path, args.window_minutes * 60, args.flow_column
    )
    if args.y_max is not None and args.y_max <= min(0.0, float(np.min(flow))):
        parser.error("--y-max must be above the bottom of the flow range")

    raw_only_output = output.with_name(
        f"{output.stem}_without_moving_average{output.suffix}"
    )
    sampled_count = plot_flow(
        hours, flow, average, output, args.window_minutes,
        args.max_raw_points, args.y_max, args.show, args.sample_seconds,
    )
    plot_flow(
        hours, flow, average, raw_only_output, args.window_minutes,
        args.max_raw_points, args.y_max, args.show, args.sample_seconds,
        show_average=False,
    )
    print(f"{args.sample_seconds:g}-s sampled flow with moving average: {output.resolve()}")
    print(f"{args.sample_seconds:g}-s sampled flow without moving average: {raw_only_output.resolve()}")
    print(f"Flow readings plotted: {len(flow):,}")
    print(f"Original readings selected every {args.sample_seconds:g} s: {sampled_count:,}")
    print(f"Duration: {hours[-1]:.3f} hours")
    print(f"Moving-average window: {args.window_minutes:g} minutes")
    if skipped:
        print(f"Skipped non-numeric or missing flow rows: {skipped:,}")
    print("Input EDF was not modified")


if __name__ == "__main__":
    main()
