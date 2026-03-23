"""
Baseline test runner for five different directed graph orientations.

Creates five distinct directed graphs using the same edge-grouping rules as
GA-Experiment1.py (via identify_air_corridor_edge_groups) and runs 100 replications
per graph using the same Python+Godot execution path (SimulationAdapter).

Saves data the same way as Baseline Undirected Graph test.py:
- Per-replication metrics CSV per graph
- Aggregate summary CSV per graph
- Config JSON per graph
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
from typing import Dict, List, Tuple

import numpy as np

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))


def load_ga_module():
    """
    Dynamically load GA-Experiment1.py as a module so we can reuse its adapter
    and edge-selection logic.
    """
    ga_path = THIS_DIR / "GA-Experiment1.py"
    spec = importlib.util.spec_from_file_location("ga_experiment1_runtime", ga_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module spec from {ga_path}")
    module = importlib.util.module_from_spec(spec)
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
        description="Run five different directed graph orientations, 100 replications each."
    )
    parser.add_argument(
        "--pickle-file",
        type=str,
        default="./Experiments/Ex1-ShtPath-GA/regular_lattice_graph.pkl",
    )
    parser.add_argument("--replications", type=int, default=100)
    parser.add_argument("--workers", type=int, default=18)
    parser.add_argument("--seed", type=int, default=42)

    parser.add_argument("--eval-mode", type=str, default="integrated", choices=["integrated", "command", "mock"])
    parser.add_argument(
        "--sim-command",
        type=str,
        default="",
        help="Used when --eval-mode=command.",
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
    parser.add_argument("--run-root", type=str, default="./Experiments/Ex0-Baseline/directed_graph_5_runs")
    return parser.parse_args()


def make_five_chromosomes(
    num_variables: int,
    rng: np.random.Generator,
) -> List[Tuple[str, np.ndarray]]:
    """
    Create five distinct directed graph orientations using GA chromosome rules.

    - Graph 0: All zeros (all forward edges)
    - Graph 1: All ones (all reverse edges)
    - Graph 2: Alternating 010101...
    - Graph 3: Random orientation (seed-derived)
    - Graph 4: Different random orientation
    """
    chromosomes: List[Tuple[str, np.ndarray]] = []

    # Graph 0: all forward
    c0 = np.zeros(num_variables, dtype=np.int8)
    chromosomes.append(("all_forward", c0))

    # Graph 1: all reverse
    c1 = np.ones(num_variables, dtype=np.int8)
    chromosomes.append(("all_reverse", c1))

    # Graph 2: alternating
    c2 = np.array([i % 2 for i in range(num_variables)], dtype=np.int8)
    chromosomes.append(("alternating", c2))

    # Graph 3: random
    c3 = rng.integers(0, 2, size=num_variables, dtype=np.int8)
    chromosomes.append(("random_a", c3))

    # Graph 4: different random
    c4 = rng.integers(0, 2, size=num_variables, dtype=np.int8)
    chromosomes.append(("random_b", c4))

    return chromosomes


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

    run_id = datetime.now().strftime("DirectedGraph5_%Y%m%d_%H%M%S")
    run_root = Path(args.run_root).resolve()
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    graph, metadata = ga.load_graph_pickle_safe(args.pickle_file)
    _group_dict, variable_to_group_list = ga.identify_air_corridor_edge_groups(graph)
    num_variables = len(variable_to_group_list)
    if num_variables <= 0:
        raise RuntimeError("No air-corridor variables found; cannot run directed graph test.")

    rng = np.random.default_rng(args.seed)
    chromosome_list = make_five_chromosomes(num_variables, rng)

    adapter = ga.SimulationAdapter(
        mode=args.eval_mode,
        sim_command=args.sim_command.strip() or None,
        timeout_seconds=float(args.sim_timeout_seconds),
        log_level=args.log_level,
        working_dir=Path(__file__).resolve().parents[2],
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

    print("=" * 88)
    print("DIRECTED GRAPH 5 TEST: FIVE DIRECTED ORIENTATIONS × 100 REPLICATIONS")
    print("=" * 88)
    print(f"Replications per graph: {args.replications}")
    print(f"Workers: {args.workers}")
    print(f"Num variables (chromosome length): {num_variables}")

    def run_single(rep_idx: int, seed: int, payload_base: dict, run_tmp_dir: Path) -> dict:
        rep_start = time.time()
        success = True
        error_message = ""

        try:
            sim_result = adapter.run_replication(
                payload=payload_base, seed=int(seed), run_tmp_dir=run_tmp_dir
            )
            collisions = float(sim_result.get("collisions", 0.0))
            no_path_count = int(sim_result.get("no_path_count", 0))
            timeout_count = int(sim_result.get("timeout_count", 0))
            server_error_count = int(sim_result.get("server_error_count", 0))
            no_response_count = int(sim_result.get("no_response_count", 0))
            no_valid_route_count = int(sim_result.get("no_valid_route_count", 0))
            artifacts = sim_result.get("artifacts", {})
        except Exception as e:
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

    all_graph_rows: Dict[int, List[dict]] = {i: [] for i in range(5)}

    for graph_idx, (graph_name, chromosome) in enumerate(chromosome_list):
        bitstring = ga.bitstring_from_array(chromosome)
        selected_edges = ga.select_edges_from_chromosome(variable_to_group_list, chromosome)

        payload_base = {
            "bitstring": bitstring,
            "chromosome": [int(x) for x in chromosome.tolist()],
            "selected_edges": [[u, v] for u, v in selected_edges],
        }

        graph_dir = run_dir / f"graph_{graph_idx}"
        run_tmp_dir = graph_dir / "tmp"
        graph_dir.mkdir(parents=True, exist_ok=True)
        run_tmp_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n--- Graph {graph_idx}: {graph_name} (bitstring len={len(bitstring)}) ---")

        rows: List[dict] = []
        completed = 0
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_rep = {
                executor.submit(run_single, idx, seed, payload_base, run_tmp_dir): idx
                for idx, seed in enumerate(seeds)
            }
            for future in as_completed(future_to_rep):
                rows.append(future.result())
                completed += 1
                if completed % 20 == 0 or completed == args.replications:
                    print(f"  Graph {graph_idx} completed {completed}/{args.replications}")

        rows.sort(key=lambda r: int(r["replication_index"]))
        all_graph_rows[graph_idx] = rows

        per_rep_csv = graph_dir / "directed_experiment.csv"
        with per_rep_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

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

        summary_row = {
            "run_id": run_id,
            "graph_index": graph_idx,
            "graph_name": graph_name,
            "bitstring": bitstring,
            "replications": int(args.replications),
            "workers": int(args.workers),
            "seed": int(args.seed),
            "eval_mode": args.eval_mode,
            "num_variables": num_variables,
            "selected_edges": int(len(selected_edges)),
            "success_rate": success_rate,
            "invalid_rate": invalid_rate,
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

        summary_csv = graph_dir / "directed_summary.csv"
        with summary_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary_row.keys()))
            writer.writeheader()
            writer.writerow(summary_row)

        config_json = graph_dir / "directed_run_config.json"
        with config_json.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "args": vars(args),
                    "run_id": run_id,
                    "graph_index": graph_idx,
                    "graph_name": graph_name,
                    "bitstring": bitstring,
                    "chromosome": [int(x) for x in chromosome.tolist()],
                    "run_dir": str(graph_dir),
                    "seed_list": seeds,
                    "num_variables": num_variables,
                    "selected_edges": len(selected_edges),
                },
                f,
                indent=2,
            )

        print(
            f"  Graph {graph_idx} ({graph_name}): success={success_rate:.3f}, "
            f"invalid={invalid_rate:.3f}, collisions_mean={collisions_stats['mean']:.3f}, "
            f"collisions_std={collisions_stats['std']:.3f}, "
            f"fitness_mean={fitness_stats['mean']:.3f}, fitness_std={fitness_stats['std']:.3f}"
        )

    wall_total_seconds = float(time.time() - start_wall)

    overall_config = run_dir / "directed_graph_5_run_config.json"
    with overall_config.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "run_id": run_id,
                "run_dir": str(run_dir),
                "args": vars(args),
                "num_graphs": 5,
                "replications_per_graph": args.replications,
                "graph_names": [name for name, _ in chromosome_list],
                "bitstrings": [ga.bitstring_from_array(c) for _, c in chromosome_list],
                "wall_total_seconds": wall_total_seconds,
            },
            f,
            indent=2,
        )

    print("=" * 88)
    print("DIRECTED GRAPH 5 TEST COMPLETE")
    print("=" * 88)
    print(f"Run directory: {run_dir}")
    print(f"Per-graph outputs: graph_0/..graph_4/ (directed_experiment.csv, directed_summary.csv, directed_run_config.json)")
    print(f"Wall time: {wall_total_seconds:.2f}s")


if __name__ == "__main__":
    main()
