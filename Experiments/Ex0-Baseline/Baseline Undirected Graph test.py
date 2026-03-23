"""
Baseline test runner (no optimization) for GA Experiment 1 simulation pipeline.

Runs the original graph orientation (all existing directed edges preserved) over
multiple replications using the same Python+Godot execution path as
GA-Experiment1.py (via SimulationAdapter), then writes:
1) per-replication metrics CSV
2) aggregate summary CSV
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import numpy as np


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))


def load_ga_module():
    """
    Dynamically load GA-Experiment1.py as a module so we can reuse its adapter.
    """
    ga_path = THIS_DIR / "GA-Experiment1.py"
    spec = importlib.util.spec_from_file_location("ga_experiment1_runtime", ga_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module spec from {ga_path}")
    module = importlib.util.module_from_spec(spec)
    # Register module before execution so decorators (e.g., dataclass)
    # can resolve the module namespace during import-time processing.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def summarize_numeric(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "sum": 0.0}
    arr = np.array(values, dtype=float)
    return {
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "sum": float(np.sum(arr)),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run baseline (no optimization) simulations using GA integrated pipeline."
    )
    parser.add_argument(
        "--pickle-file",
        type=str,
        default="./Experiments/Ex1-ShtPath-GA/regular_lattice_graph.pkl",
    )
    parser.add_argument("--replications", type=int, default=100)
    parser.add_argument("--workers", type=int, default=18)
    parser.add_argument("--seed", type=int, default=42)

    # Keep evaluator options aligned with GA-Experiment1.py.
    parser.add_argument("--eval-mode", type=str, default="integrated", choices=["integrated", "command", "mock"])
    parser.add_argument(
        "--sim-command",
        type=str,
        default="",
        help="Used when --eval-mode=command. Supports {seed}, {input_json}, {output_json}.",
    )
    parser.add_argument("--sim-timeout-seconds", type=float, default=360.0)
    parser.add_argument("--log-level", type=str, default="quiet", choices=["quiet", "normal", "verbose"])
    parser.add_argument("--python-exe", type=str, default=sys.executable)
    parser.add_argument(
        "--websocket-server-script",
        type=str,
        default="./scripts/Python/Route Gen Basic Shortest Path/WebSocketServer.py",
    )
    parser.add_argument("--godot-exe", type=str, default="godot4")
    parser.add_argument("--godot-project-dir", type=str, default=".")
    parser.add_argument("--integrated-max-sim-time", type=float, default=15000.0)
    parser.add_argument("--server-start-timeout", type=float, default=20.0)

    parser.add_argument("--invalid-threshold", type=int, default=1000)
    parser.add_argument("--invalid-penalty", type=float, default=10000.0)
    parser.add_argument("--run-root", type=str, default="./Experiments/Ex0-Baseline/baseline_runs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start_wall = time.time()
    ga = load_ga_module()

    if args.replications < 1:
        raise ValueError("--replications must be >= 1.")
    if args.workers < 1:
        raise ValueError("--workers must be >= 1.")
    if args.eval_mode == "command" and not args.sim_command.strip():
        raise ValueError("When --eval-mode=command, --sim-command is required.")

    if args.eval_mode == "integrated":
        try:
            args.godot_exe = ga.resolve_godot_executable(args.godot_exe)
        except FileNotFoundError:
            auto_hit = ga.auto_detect_godot_executable()
            if auto_hit:
                args.godot_exe = auto_hit
                print(f"Auto-detected Godot executable: {args.godot_exe}")
            else:
                raise

        ws_script = Path(args.websocket_server_script).resolve()
        if not ws_script.exists():
            raise FileNotFoundError(
                f"WebSocket server script not found: {ws_script}. "
                "Set --websocket-server-script to the correct path."
            )
        project_dir = Path(args.godot_project_dir).resolve()
        if not (project_dir / "project.godot").exists():
            raise FileNotFoundError(f"No project.godot found in --godot-project-dir: {project_dir}")
        print(f"Integrated mode preflight OK. Godot executable: {args.godot_exe}")
        print(f"Integrated mode preflight OK. Godot project dir: {project_dir}")

    run_id = datetime.now().strftime("BaselineTest_%Y%m%d_%H%M%S")
    run_root = Path(args.run_root).resolve()
    run_dir = run_root / run_id
    run_tmp_dir = run_dir / "tmp"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_tmp_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 88)
    print("BASELINE TEST: GODOT SIMULATION-BASED EVALUATION (NO OPTIMIZATION)")
    print("=" * 88)

    graph, metadata = ga.load_graph_pickle_safe(args.pickle_file)
    rng = np.random.default_rng(args.seed)
    selected_edges = sorted(
        (u, v)
        for u, v, attrs in graph.edges(data=True)
        if attrs.get("layer_type") == "Horizontal"
    )
    if not selected_edges:
        raise RuntimeError("No horizontal edges found in the graph; cannot run baseline test.")

    payload_base = {
        "bitstring": "ALL_EDGES_BASELINE",
        "chromosome": [],
        "selected_edges": [[u, v] for u, v in selected_edges],
    }

    adapter = ga.SimulationAdapter(
        mode=args.eval_mode,
        sim_command=args.sim_command.strip() or None,
        timeout_seconds=float(args.sim_timeout_seconds),
        log_level=args.log_level,
        working_dir=Path(__file__).resolve().parents[2],  # repository root
        base_graph=graph,
        base_metadata=metadata if isinstance(metadata, dict) else {},
        python_exe=args.python_exe,
        websocket_server_script=Path(args.websocket_server_script).resolve(),
        godot_exe=args.godot_exe,
        godot_project_dir=Path(args.godot_project_dir).resolve(),
        integrated_max_sim_time=float(args.integrated_max_sim_time),
        server_start_timeout=float(args.server_start_timeout),
    )

    seeds = (
        rng.integers(0, 2_000_000_000, size=args.replications, dtype=np.int64)
        .astype(int)
        .tolist()
    )

    print("Baseline graph mode: original directed graph (all horizontal directions preserved)")
    print(f"Replications: {args.replications}")
    print(f"Workers: {args.workers}")
    print(f"Selected horizontal edges from graph: {len(selected_edges)}")

    def run_single(rep_idx: int, seed: int) -> dict:
        rep_start = time.time()
        success = True
        error_message = ""

        try:
            sim_result = adapter.run_replication(payload=payload_base, seed=int(seed), run_tmp_dir=run_tmp_dir)
            collisions = float(sim_result.get("collisions", 0.0))
            no_path_count = int(sim_result.get("no_path_count", 0))
            timeout_count = int(sim_result.get("timeout_count", 0))
            server_error_count = int(sim_result.get("server_error_count", 0))
            no_response_count = int(sim_result.get("no_response_count", 0))
            no_valid_route_count = int(sim_result.get("no_valid_route_count", 0))
            artifacts = sim_result.get("artifacts", {})
        except Exception as e:
            # Keep failure handling aligned with GA evaluator pressure.
            success = False
            error_message = str(e)
            collisions = float(args.invalid_penalty)
            no_path_count = int(args.invalid_threshold)
            timeout_count = 0
            server_error_count = 0
            no_response_count = 0
            no_valid_route_count = 0
            artifacts = {}

        invalid_count = no_path_count + timeout_count
        is_invalid = invalid_count >= int(args.invalid_threshold)
        fitness = float(collisions + no_path_count + timeout_count)
        elapsed_s = float(time.time() - rep_start)

        return {
            "replication_index": int(rep_idx),
            "seed": int(seed),
            "success": bool(success),
            "error_message": error_message,
            "elapsed_seconds": elapsed_s,
            "collisions": collisions,
            "no_path_count": int(no_path_count),
            "timeout_count": int(timeout_count),
            "server_error_count": int(server_error_count),
            "no_response_count": int(no_response_count),
            "no_valid_route_count": int(no_valid_route_count),
            "invalid_count": int(invalid_count),
            "is_invalid": bool(is_invalid),
            "fitness": fitness,
            "rep_dir": str(artifacts.get("rep_dir", "")),
            "server_log": str(artifacts.get("server_log", "")),
            "godot_log": str(artifacts.get("godot_log", "")),
            "collision_csv": str(artifacts.get("collision_csv", "")),
            "ga_summary_json": str(artifacts.get("ga_summary_json", "")),
            "websocket_port": artifacts.get("websocket_port", ""),
        }

    rows: List[dict] = []
    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_idx = {
            executor.submit(run_single, idx, seed): idx
            for idx, seed in enumerate(seeds)
        }
        for future in as_completed(future_to_idx):
            rows.append(future.result())
            completed += 1
            if completed % 10 == 0 or completed == args.replications:
                print(f"Completed {completed}/{args.replications} replications")

    rows.sort(key=lambda r: int(r["replication_index"]))

    per_rep_csv = run_dir / "baseline_experiment.csv"
    with per_rep_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # Aggregate summary metrics.
    collisions_stats = summarize_numeric([float(r["collisions"]) for r in rows])
    no_path_stats = summarize_numeric([float(r["no_path_count"]) for r in rows])
    timeout_stats = summarize_numeric([float(r["timeout_count"]) for r in rows])
    server_error_stats = summarize_numeric([float(r["server_error_count"]) for r in rows])
    no_response_stats = summarize_numeric([float(r["no_response_count"]) for r in rows])
    no_valid_stats = summarize_numeric([float(r["no_valid_route_count"]) for r in rows])
    invalid_stats = summarize_numeric([float(r["invalid_count"]) for r in rows])
    fitness_stats = summarize_numeric([float(r["fitness"]) for r in rows])
    elapsed_stats = summarize_numeric([float(r["elapsed_seconds"]) for r in rows])

    invalid_rate = float(sum(1 for r in rows if bool(r["is_invalid"])) / len(rows))
    success_rate = float(sum(1 for r in rows if bool(r["success"])) / len(rows))
    wall_total_seconds = float(time.time() - start_wall)

    summary_row = {
        "run_id": run_id,
        "replications": int(args.replications),
        "workers": int(args.workers),
        "seed": int(args.seed),
        "baseline_mode": "original_graph_all_directions",
        "eval_mode": args.eval_mode,
        "num_variables": 0,
        "bitstring": payload_base["bitstring"],
        "selected_edges": int(len(selected_edges)),
        "success_rate": success_rate,
        "invalid_rate": invalid_rate,
        "wall_total_seconds": wall_total_seconds,
        "elapsed_seconds_mean": elapsed_stats["mean"],
        "collisions_mean": collisions_stats["mean"],
        "collisions_std": collisions_stats["std"],
        "collisions_min": collisions_stats["min"],
        "collisions_max": collisions_stats["max"],
        "collisions_sum": collisions_stats["sum"],
        "no_path_mean": no_path_stats["mean"],
        "no_path_sum": no_path_stats["sum"],
        "timeout_mean": timeout_stats["mean"],
        "timeout_sum": timeout_stats["sum"],
        "server_error_mean": server_error_stats["mean"],
        "server_error_sum": server_error_stats["sum"],
        "no_response_mean": no_response_stats["mean"],
        "no_response_sum": no_response_stats["sum"],
        "no_valid_route_mean": no_valid_stats["mean"],
        "no_valid_route_sum": no_valid_stats["sum"],
        "invalid_count_mean": invalid_stats["mean"],
        "invalid_count_sum": invalid_stats["sum"],
        "fitness_mean": fitness_stats["mean"],
        "fitness_std": fitness_stats["std"],
        "fitness_min": fitness_stats["min"],
        "fitness_max": fitness_stats["max"],
        "fitness_sum": fitness_stats["sum"],
    }

    summary_csv = run_dir / "baseline_summary.csv"
    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_row.keys()))
        writer.writeheader()
        writer.writerow(summary_row)

    config_json = run_dir / "baseline_run_config.json"
    with config_json.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "args": vars(args),
                "run_id": run_id,
                "run_dir": str(run_dir),
                "seed_list": seeds,
                "num_variables": 0,
                "baseline_mode": "original_graph_all_directions",
                "selected_horizontal_edges": len(selected_edges),
            },
            f,
            indent=2,
        )

    print("=" * 88)
    print("BASELINE TEST COMPLETE")
    print("=" * 88)
    print(f"Run directory: {run_dir}")
    print(f"Per-replication CSV: {per_rep_csv}")
    print(f"Summary CSV: {summary_csv}")
    print(f"Config JSON: {config_json}")
    print(f"Success rate: {success_rate:.3f}")
    print(f"Invalid rate: {invalid_rate:.3f}")
    print(f"Mean collisions: {collisions_stats['mean']:.3f}")
    print(f"Std collisions: {collisions_stats['std']:.3f}")
    print(f"Mean fitness: {fitness_stats['mean']:.3f}")
    print(f"Std fitness: {fitness_stats['std']:.3f}")


if __name__ == "__main__":
    main()

