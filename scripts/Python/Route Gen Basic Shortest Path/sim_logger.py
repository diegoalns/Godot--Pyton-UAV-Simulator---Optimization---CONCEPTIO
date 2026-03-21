"""
Structured logger utility for Python simulation services.

Supports three output formats:
- table: Fixed-width columns (default, unified with Godot DebugLogger)
- json: One JSON object per line for parsing/dashboards
- pretty: Compact human-readable [LEVEL][CATEGORY][python] event | key=value
"""

from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Fixed-width column sizes - must match Godot DebugLogger.gd
TABLE_WIDTH_TS = 12
TABLE_WIDTH_LEVEL = 8
TABLE_WIDTH_CATEGORY = 14
TABLE_WIDTH_SOURCE = 6
TABLE_WIDTH_EVENT = 32
TABLE_WIDTH_DATA = 150


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


_LEVEL_TO_INT = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
}


def _get_env_level() -> str:
    level = os.getenv("SIM_LOG_LEVEL", "INFO").strip().upper()
    return level if level in _LEVEL_TO_INT else "INFO"


def _should_emit(level: str) -> bool:
    current = _LEVEL_TO_INT[_get_env_level()]
    requested = _LEVEL_TO_INT.get(level, _LEVEL_TO_INT["INFO"])
    return requested >= current


def _get_log_format() -> str:
    fmt = os.getenv("SIM_LOG_FORMAT", "table").strip().lower()
    return fmt if fmt in {"json", "pretty", "table"} else "table"


def _pad_cell(s: str, width: int, truncate: bool = True) -> str:
    """Pad or truncate string to fixed width."""
    s = str(s)
    if len(s) >= width:
        return s[:width] if truncate else s
    return s + " " * (width - len(s))


def _format_table_row(ts: str, level: str, category: str, source: str, event: str, data: str) -> str:
    """Format a single log line as fixed-width table row. Matches Godot DebugLogger."""
    return "%s %s %s %s %s %s" % (
        _pad_cell(ts, TABLE_WIDTH_TS),
        _pad_cell(level, TABLE_WIDTH_LEVEL),
        _pad_cell(category, TABLE_WIDTH_CATEGORY),
        _pad_cell(source, TABLE_WIDTH_SOURCE),
        _pad_cell(event, TABLE_WIDTH_EVENT),
        _pad_cell(data, TABLE_WIDTH_DATA),
    )


def get_table_header() -> str:
    """Return fixed-width table header row."""
    return _format_table_row("ts", "level", "category", "source", "event", "data")


_table_header_printed = False

_LOGS_DIR = Path(__file__).resolve().parents[3] / "logs"
_ROUTES_RECEIVED_CSV = _LOGS_DIR / "python_routes_received.csv"

_ROUTES_RECEIVED_HEADER = [
    "plan_id",
    "start_node_id",
    "end_node_id",
    "waypoint_index",
    "waypoint_node_id",
    "overfly_time_sim_s",
    "segment_duration_s",
    "cumulative_duration_s",
    "planned_total_duration_s",
    "start_time_sim_s",
    "planned_completion_time_sim_s",
    "waypoint_speed_mps",
    "pathfinding_duration_s",
    "total_processing_time_s",
    "logged_at_unix_s",
]


def reset_route_received_csv() -> None:
    """
    Clear python_routes_received.csv at server startup for run-local logs.
    Header is written lazily on first appended row.
    """
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _ROUTES_RECEIVED_CSV.write_text("", encoding="utf-8")


def _maybe_print_header() -> None:
    """Print table header once on first log."""
    global _table_header_printed
    if not _table_header_printed:
        _table_header_printed = True
        print(get_table_header(), flush=True)


def _append_csv_row(path: Path, header: list[str], row: list[Any]) -> None:
    """
    Append one row to a CSV file and create header on first write.
    """
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if (not file_exists) or path.stat().st_size == 0:
            writer.writerow(header)
        writer.writerow(row)


def log_route_received_csv(
    plan_id: str,
    start_node_id: str,
    end_node_id: str,
    path_nodes: list[str],
    overfly_times: list[float],
    start_time_sim: float,
    waypoint_speed_mps: float,
    pathfinding_duration_s: float,
    total_processing_time_s: float,
) -> None:
    """
    Write one CSV row per waypoint for each received route.
    """
    if not path_nodes or not overfly_times:
        return

    safe_count = min(len(path_nodes), len(overfly_times))
    planned_completion_time = overfly_times[safe_count - 1]
    planned_total_duration = planned_completion_time - start_time_sim
    logged_at_unix = round(time.time(), 6)

    for idx in range(safe_count):
        overfly_time = overfly_times[idx]
        if idx == 0:
            segment_duration = 0.0
            cumulative_duration = 0.0
        else:
            segment_duration = overfly_times[idx] - overfly_times[idx - 1]
            cumulative_duration = overfly_times[idx] - start_time_sim

        _append_csv_row(
            _ROUTES_RECEIVED_CSV,
            _ROUTES_RECEIVED_HEADER,
            [
                plan_id,
                start_node_id,
                end_node_id,
                idx,
                path_nodes[idx],
                round(overfly_time, 6),
                round(segment_duration, 6),
                round(cumulative_duration, 6),
                round(planned_total_duration, 6),
                round(start_time_sim, 6),
                round(planned_completion_time, 6),
                round(waypoint_speed_mps, 6),
                round(pathfinding_duration_s, 6),
                round(total_processing_time_s, 6),
                logged_at_unix,
            ],
        )


def log_event(
    level: str,
    category: str,
    event: str,
    **fields: Any,
) -> None:
    """
    Emit a single structured log event.

    Formats:
    - table (default): Fixed-width columns matching Godot DebugLogger
    - json: One JSON object per line for parsing
    - pretty: Compact [LEVEL][CATEGORY][python] event | key=value
    """
    level = level.upper()
    if not _should_emit(level):
        return

    log_fmt = _get_log_format()
    ts_unix = time.time()
    payload = {
        "ts_unix": round(ts_unix, 6),
        "ts_iso": _iso_utc_now(),
        "side": "python",
        "level": level,
        "category": category,
        "event": event,
    }
    payload.update(fields)

    if log_fmt == "table":
        _maybe_print_header()
        ts_str = "%.2fs" % ts_unix
        data_parts = sorted("%s=%s" % (k, payload[k]) for k in fields.keys())
        data_str = "{%s}" % ", ".join(data_parts) if data_parts else ""
        line = _format_table_row(ts_str, level, category, "python", event, data_str)
        print(line, flush=True)
    elif log_fmt == "pretty":
        details = " ".join("%s=%s" % (k, payload[k]) for k in sorted(fields.keys()))
        print(
            "[%s][%s][%s] %s%s" % [
                level, category, "python", event,
                (" | " + details) if details else "",
            ],
            flush=True,
        )
    else:
        print(json.dumps(payload, ensure_ascii=True), flush=True)

