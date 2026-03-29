"""
GA-Experiment1: Godot simulation-based combinatorial optimization.

This script optimizes binary air-corridor orientation settings using a Genetic Algorithm (GA):
- Gene: one corridor-group orientation (0=forward, 1=reverse)
- Chromosome: full binary vector over all corridor groups
- Objective: minimize (collisions + no_path + timeout)

Evaluation protocol implemented from experiment requirements:
- Common random numbers: same seed list across individuals per generation
- Fitness: sum(collisions) + no_path_count + timeout_count over k replications
- Track no_path_count, timeout_count, invalid_count
- Invalid rule: invalid_count is tracked; fitness no longer uses invalid penalty
- Fitness cache key: chromosome bitstring + seed-set signature

TensorBoard logs are written per generation for live monitoring.
"""

from __future__ import annotations

import argparse
import atexit
import csv
import hashlib
import json
import os
import pickle
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, TextIO, Tuple

import networkx as nx
import numpy as np

# Ensure local experiment modules are importable.
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from edge_grouping import (
    identify_air_corridor_edge_groups,
)

try:
    from torch.utils.tensorboard import SummaryWriter  # type: ignore
except Exception:  # pragma: no cover - fallback path
    try:
        from tensorboardX import SummaryWriter  # type: ignore
    except Exception:  # pragma: no cover - fallback path
        SummaryWriter = None  # type: ignore


@dataclass
class EvalResult:
    fitness: float
    mean_collisions: float
    no_path_count: int
    timeout_count: int
    server_error_count: int
    no_response_count: int
    no_valid_route_count: int
    invalid_count: int
    is_invalid: bool
    replications: int
    per_seed_fitness: List[float]
    replication_fitness_std: float


class NullSummaryWriter:
    def add_scalar(self, *_args, **_kwargs) -> None:
        return

    def flush(self) -> None:
        return

    def close(self) -> None:
        return


LOG_MODE_CHOICES = ("quiet", "normal", "verbose")
ARTIFACT_MODE_CHOICES = ("keep_all", "keep_failures", "minimal")


def resolve_log_mode_settings(log_mode: str) -> dict:
    """
    Map runner log mode to Python/Godot logging environment variables.
    """
    mode = (log_mode or "").strip().lower()
    if mode == "quiet":
        return {
            "python_log_level": "ERROR",
            "python_log_format": "json",
            "godot_log_level": "quiet",
            "print_every_generation": False,
        }
    if mode == "verbose":
        return {
            "python_log_level": "DEBUG",
            "python_log_format": "json",
            "godot_log_level": "verbose",
            "print_every_generation": True,
        }
    return {
        "python_log_level": "INFO",
        "python_log_format": "table",
        "godot_log_level": "normal",
        "print_every_generation": True,
    }


class TeeTextIO:
    """
    Mirror writes to the original stream and a run-scoped log file.
    """

    def __init__(self, primary: TextIO, mirror: TextIO) -> None:
        self.primary = primary
        self.mirror = mirror

    def write(self, text: str) -> int:
        written = self.primary.write(text)
        self.mirror.write(text)
        return written

    def flush(self) -> None:
        self.primary.flush()
        self.mirror.flush()

    def isatty(self) -> bool:
        return bool(getattr(self.primary, "isatty", lambda: False)())


def launch_tensorboard(
    logdir: Path,
    run_dir: Path,
    port: int,
    host: str,
    open_browser: bool,
) -> Tuple[Optional[subprocess.Popen], str]:
    """
    Start TensorBoard process in background for this run.
    """
    tb_url = f"http://{host}:{port}"
    tb_log_path = run_dir / "tensorboard_process.log"
    tb_log_file = tb_log_path.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tensorboard.main",
                "--logdir",
                str(logdir),
                "--host",
                host,
                "--port",
                str(port),
            ],
            cwd=str(run_dir),
            stdout=tb_log_file,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
        )
    except Exception:
        tb_log_file.close()
        return None, tb_url
    tb_log_file.close()
    time.sleep(1.25)
    # Detect immediate startup failures (for example: port already in use).
    if process.poll() is not None:
        return None, tb_url
    if open_browser:
        try:
            webbrowser.open_new_tab(tb_url)
        except Exception:
            pass
    return process, tb_url


class SimulationAdapter:
    """
    Runs one simulation replication for a chromosome and seed.

    Expected simulation output keys (JSON):
    - collisions (number)
    - no_path_count (int)
    - timeout_count (int)
    """

    def __init__(
        self,
        mode: str,
        sim_command: Optional[str],
        timeout_seconds: float,
        working_dir: Path,
        base_graph: nx.DiGraph,
        base_metadata: dict,
        python_exe: str,
        websocket_server_script: Path,
        godot_exe: str,
        godot_project_dir: Path,
        integrated_max_sim_time: float,
        server_start_timeout: float,
        log_mode: str = "normal",
        artifact_mode: str = "keep_all",
    ) -> None:
        self.mode = mode
        self.log_mode = (log_mode or "normal").strip().lower()
        self.artifact_mode = (artifact_mode or "keep_all").strip().lower()
        self.sim_command = sim_command
        self.timeout_seconds = timeout_seconds
        self.working_dir = working_dir
        self.base_graph = base_graph
        self.base_metadata = base_metadata
        self.python_exe = python_exe
        self.websocket_server_script = websocket_server_script
        self.godot_exe = godot_exe
        self.godot_project_dir = godot_project_dir
        self.integrated_max_sim_time = integrated_max_sim_time
        self.server_start_timeout = server_start_timeout
        self._port_lock = threading.Lock()
        self._reserved_ports: set[int] = set()

    @staticmethod
    def _apply_rep_artifact_policy(
        rep_dir: Path,
        artifact_mode: str,
        had_route_failures: bool,
    ) -> None:
        """
        Apply retention policy to one replication directory after metrics are parsed.
        """
        mode = (artifact_mode or "keep_all").strip().lower()
        if mode == "keep_all":
            return

        if mode == "keep_failures":
            if had_route_failures:
                return
            shutil.rmtree(rep_dir, ignore_errors=True)
            return

        # minimal: keep only audit-relevant files and remove the rest.
        keep_names = {
            "python_server.log",
            "godot.log",
            "collision_log.csv",
            "python_routes_received.csv",
            "godot_summary.json",
        }
        for entry in rep_dir.iterdir():
            if entry.name in keep_names:
                continue
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                try:
                    entry.unlink()
                except FileNotFoundError:
                    pass

    @staticmethod
    def _parse_json_from_text(text: str) -> Optional[dict]:
        # Try line-by-line JSON first (useful when command prints logs and one JSON line).
        for line in reversed(text.splitlines()):
            candidate = line.strip()
            if not candidate:
                continue
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue
        return None

    def _run_mock(self, bitstring: str, seed: int) -> dict:
        # Deterministic mock for dry-runs and pipeline checks.
        key = f"{bitstring}|{seed}".encode("utf-8")
        h = int(hashlib.sha256(key).hexdigest()[:12], 16)
        rng = np.random.default_rng(h)
        collisions = int(rng.integers(0, 20))
        no_path_count = int(rng.integers(0, 3))
        timeout_count = int(rng.integers(0, 3))
        return {
            "collisions": collisions,
            "no_path_count": no_path_count,
            "timeout_count": timeout_count,
        }

    def _run_command(self, payload: dict, seed: int, run_tmp_dir: Path) -> dict:
        if not self.sim_command:
            raise ValueError("sim_command is required when eval_mode='command'.")

        input_json = run_tmp_dir / f"sim_input_seed_{seed}.json"
        output_json = run_tmp_dir / f"sim_output_seed_{seed}.json"
        with input_json.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        command_str = self.sim_command.format(
            seed=seed,
            input_json=str(input_json),
            output_json=str(output_json),
        )
        command_parts = shlex.split(command_str, posix=False)

        env = os.environ.copy()
        env["GA_SEED"] = str(seed)
        env["GA_INPUT_JSON"] = str(input_json)
        env["GA_OUTPUT_JSON"] = str(output_json)
        env["GA_CHROMOSOME_BITSTRING"] = payload["bitstring"]

        proc = subprocess.run(
            command_parts,
            cwd=str(self.working_dir),
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            env=env,
            check=False,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"Simulation command failed (code={proc.returncode}). stderr={proc.stderr.strip()}"
            )

        if output_json.exists():
            with output_json.open("r", encoding="utf-8") as f:
                parsed = json.load(f)
            if not isinstance(parsed, dict):
                raise ValueError("Simulation output JSON is not an object.")
            return parsed

        parsed_stdout = self._parse_json_from_text(proc.stdout)
        if parsed_stdout is None:
            raise ValueError(
                "Simulation command did not produce parseable JSON on stdout and no output_json was written."
            )
        return parsed_stdout

    def _build_oriented_graph_pickle(self, payload: dict, out_path: Path) -> None:
        selected_edges = {tuple(edge) for edge in payload.get("selected_edges", [])}
        g_new = nx.DiGraph()
        for node, attrs in self.base_graph.nodes(data=True):
            g_new.add_node(node, **attrs)
        for u, v, attrs in self.base_graph.edges(data=True):
            if attrs.get("layer_type") == "Horizontal":
                if (u, v) in selected_edges:
                    g_new.add_edge(u, v, **attrs)
            else:
                g_new.add_edge(u, v, **attrs)
        with out_path.open("wb") as f:
            pickle.dump({"graph": g_new, "metadata": self.base_metadata}, f)

    @staticmethod
    def _wait_for_server_ready(server_log_path: Path, timeout_s: float, server_host: str, server_port: int) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            # Fast path: try a minimal WebSocket handshake so we know the right
            # service is actually listening, not just "something" on the port.
            try:
                sock = socket.create_connection((server_host, int(server_port)), timeout=0.25)
                try:
                    sock.settimeout(0.5)
                    host_header = f"{server_host}:{int(server_port)}"
                    # Minimal, syntactically valid WebSocket handshake request.
                    request = (
                        "GET /healthcheck HTTP/1.1\r\n"
                        f"Host: {host_header}\r\n"
                        "Upgrade: websocket\r\n"
                        "Connection: Upgrade\r\n"
                        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                        "Sec-WebSocket-Version: 13\r\n"
                        "\r\n"
                    )
                    sock.sendall(request.encode("ascii"))
                    # Read up to some bytes for the HTTP response headers.
                    response = sock.recv(1024).decode("iso-8859-1", errors="ignore")
                    response_lower = response.lower()
                    if "101" in response.splitlines()[0] and "upgrade: websocket" in response_lower:
                        # Correct WebSocket server is up and responding.
                        return
                    # If the handshake does not look like a WebSocket upgrade,
                    # fall through and continue waiting.
                finally:
                    try:
                        sock.close()
                    except OSError:
                        pass
            except OSError:
                # Connection failed; fall back to log-based readiness checks.
                pass
            if server_log_path.exists():
                text = server_log_path.read_text(encoding="utf-8", errors="ignore")
                if "server_running" in text:
                    return
                if "server_startup_failed" in text:
                    raise RuntimeError("WebSocket server failed during startup.")
            time.sleep(0.25)
        raise TimeoutError("Timed out waiting for WebSocket server startup.")

    @staticmethod
    def _count_collision_starts(collision_csv: Path) -> int:
        if not collision_csv.exists():
            return 0
        count = 0
        with collision_csv.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get("Event_Type", "") or "").strip() == "COLLISION_START":
                    count += 1
        return count

    @staticmethod
    def _parse_pathfinder_status_counts(server_log_path: Path) -> Tuple[int, int]:
        if not server_log_path.exists():
            return 0, 0
        text = server_log_path.read_text(encoding="utf-8", errors="ignore")
        no_path_count = text.count("pathfinding_no_path")
        timeout_count = text.count("pathfinding_timeout")
        return int(no_path_count), int(timeout_count)

    @staticmethod
    def _count_lines_with_any_token(text: str, tokens: Sequence[str]) -> int:
        """
        Count log lines containing at least one token.
        Avoids double-counting when both full and truncated event names are provided.
        """
        if not text:
            return 0
        lines = text.splitlines()
        return int(sum(1 for line in lines if any(token in line for token in tokens)))

    @staticmethod
    def _parse_server_error_count(server_log_path: Path) -> int:
        if not server_log_path.exists():
            return 0
        text = server_log_path.read_text(encoding="utf-8", errors="ignore")
        # Server-side validation and processing failures reported by Python server.
        # Include truncated variants to remain robust with fixed-width table formatting.
        invalid_nodes = SimulationAdapter._count_lines_with_any_token(
            text,
            (
                "route_request_rejected_invalid_nodes",
                "route_request_rejected_invalid_no",
            ),
        )
        pathfinding_errors = SimulationAdapter._count_lines_with_any_token(
            text, ("pathfinding_error",)
        )
        return int(invalid_nodes + pathfinding_errors)

    @staticmethod
    def _parse_godot_response_failure_counts(godot_log_path: Path) -> Tuple[int, int]:
        if not godot_log_path.exists():
            return 0, 0
        text = godot_log_path.read_text(encoding="utf-8", errors="ignore")
        no_response_count = SimulationAdapter._count_lines_with_any_token(
            text, ("pre_request_timeout_no_response",)
        ) + SimulationAdapter._count_lines_with_any_token(
            text, ("flight_cancelled_route_timeout",)
        )
        no_valid_route_count = SimulationAdapter._count_lines_with_any_token(
            text,
            (
                "route_request_failed_no_valid_route",
                "route_request_failed_no_valid_ro",
            ),
        )
        return int(no_response_count), int(no_valid_route_count)

    @staticmethod
    def _is_port_available(host: str, port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
                s.bind((host, port))
            return True
        except OSError:
            return False

    def _select_available_ws_port(self, rep_hash: str) -> int:
        """
        Pick a deterministic-but-probed localhost port for per-rep isolation.
        """
        ws_host = "127.0.0.1"
        port_min = 20000
        port_span = 20000  # [20000, 39999]
        base = int(rep_hash, 16) % port_span
        with self._port_lock:
            for offset in range(port_span):
                candidate = port_min + ((base + offset) % port_span)
                if candidate in self._reserved_ports:
                    continue
                if self._is_port_available(ws_host, candidate):
                    self._reserved_ports.add(candidate)
                    return candidate
        raise RuntimeError("No available WebSocket port found in configured range 20000-39999.")

    def _release_ws_port(self, port: int) -> None:
        with self._port_lock:
            self._reserved_ports.discard(int(port))

    def _run_integrated(self, payload: dict, seed: int, run_tmp_dir: Path) -> dict:
        rep_hash = hashlib.sha1(f"{payload['bitstring']}|{seed}".encode("utf-8")).hexdigest()[:10]
        rep_dir = run_tmp_dir / f"rep_{rep_hash}_{seed}"
        rep_dir.mkdir(parents=True, exist_ok=True)

        oriented_graph_pickle = rep_dir / "oriented_graph.pkl"
        self._build_oriented_graph_pickle(payload, oriented_graph_pickle)

        server_log = rep_dir / "python_server.log"
        godot_log = rep_dir / "godot.log"
        ga_summary = rep_dir / "godot_summary.json"
        collision_csv = rep_dir / "collision_log.csv"
        simple_log_csv = rep_dir / "simple_log.csv"
        python_routes_csv = rep_dir / "python_routes_received.csv"
        ws_host = "127.0.0.1"
        ws_port = self._select_available_ws_port(rep_hash=rep_hash)

        mode_settings = resolve_log_mode_settings(self.log_mode)
        env_server = os.environ.copy()
        env_server["GRAPH_PICKLE_PATH"] = str(oriented_graph_pickle)
        env_server["SIM_LOG_FORMAT"] = mode_settings["python_log_format"]
        env_server["SIM_LOG_LEVEL"] = mode_settings["python_log_level"]
        env_server["SIM_ROUTES_RECEIVED_CSV"] = str(python_routes_csv)
        env_server["WS_SERVER_HOST"] = ws_host
        env_server["WS_SERVER_PORT"] = str(ws_port)

        env_godot = os.environ.copy()
        env_godot["GA_AUTORUN"] = "1"
        env_godot["GA_HEADLESS"] = "1"
        env_godot["GA_MAX_SIM_TIME"] = str(self.integrated_max_sim_time)
        env_godot["GA_SUMMARY_JSON"] = str(ga_summary)
        env_godot["GA_SEED"] = str(seed)
        env_godot["GA_WEBSOCKET_URL"] = f"ws://{ws_host}:{ws_port}"
        env_godot["GA_COLLISION_LOG_CSV"] = str(collision_csv)
        env_godot["GA_SIMPLE_LOG_CSV"] = str(simple_log_csv)
        env_godot["GA_LOG_LEVEL"] = mode_settings["godot_log_level"]

        server_proc = None
        godot_proc = None
        try:
            startup_attempts = 6
            startup_last_error: Optional[Exception] = None
            for attempt in range(startup_attempts):
                env_server["WS_SERVER_PORT"] = str(ws_port)
                env_godot["GA_WEBSOCKET_URL"] = f"ws://{ws_host}:{ws_port}"
                log_mode = "w" if attempt == 0 else "a"
                with server_log.open(log_mode, encoding="utf-8") as server_out:
                    if attempt > 0:
                        server_out.write(
                            f"\n# Retry attempt {attempt + 1}/{startup_attempts} "
                            f"with ws_port={ws_port}\n"
                        )
                    server_proc = subprocess.Popen(
                        [self.python_exe, str(self.websocket_server_script)],
                        cwd=str(self.websocket_server_script.parent),
                        stdout=server_out,
                        stderr=subprocess.STDOUT,
                        env=env_server,
                    )

                try:
                    self._wait_for_server_ready(
                        server_log,
                        self.server_start_timeout,
                        server_host=ws_host,
                        server_port=ws_port,
                    )
                    startup_last_error = None
                    break
                except Exception as e:
                    startup_last_error = e
                    if server_proc is not None and server_proc.poll() is None:
                        server_proc.terminate()
                        try:
                            server_proc.wait(timeout=5)
                        except Exception:
                            server_proc.kill()
                    if attempt == startup_attempts - 1:
                        raise RuntimeError(
                            f"WebSocket server startup failed after {startup_attempts} attempts."
                        ) from e
                    self._release_ws_port(ws_port)
                    ws_port = self._select_available_ws_port(rep_hash=f"{rep_hash}_{attempt + 1}")

            if startup_last_error is not None:
                raise startup_last_error

            with godot_log.open("w", encoding="utf-8") as godot_out:
                godot_proc = subprocess.Popen(
                    [self.godot_exe, "--headless", "--path", str(self.godot_project_dir)],
                    cwd=str(self.godot_project_dir),
                    stdout=godot_out,
                    stderr=subprocess.STDOUT,
                    env=env_godot,
                )
                godot_proc.wait(timeout=self.timeout_seconds)

            if godot_proc.returncode != 0:
                raise RuntimeError(f"Godot run failed with exit code {godot_proc.returncode}.")

            # Give Python server a small grace period to flush logs.
            time.sleep(0.75)
        finally:
            if godot_proc is not None and godot_proc.poll() is None:
                godot_proc.terminate()
                try:
                    godot_proc.wait(timeout=5)
                except Exception:
                    godot_proc.kill()
            if server_proc is not None and server_proc.poll() is None:
                server_proc.terminate()
                try:
                    server_proc.wait(timeout=5)
                except Exception:
                    server_proc.kill()
            self._release_ws_port(ws_port)

        collisions = self._count_collision_starts(collision_csv)
        no_path_count, timeout_count = self._parse_pathfinder_status_counts(server_log)
        server_error_count = self._parse_server_error_count(server_log)
        no_response_count, no_valid_route_count = self._parse_godot_response_failure_counts(godot_log)
        had_route_failures = (
            no_path_count > 0
            or timeout_count > 0
            or server_error_count > 0
            or no_response_count > 0
            or no_valid_route_count > 0
        )
        self._apply_rep_artifact_policy(
            rep_dir=rep_dir,
            artifact_mode=self.artifact_mode,
            had_route_failures=had_route_failures,
        )
        return {
            "collisions": collisions,
            "no_path_count": no_path_count,
            "timeout_count": timeout_count,
            "server_error_count": server_error_count,
            "no_response_count": no_response_count,
            "no_valid_route_count": no_valid_route_count,
            "artifacts": {
                "rep_dir": str(rep_dir),
                "server_log": str(server_log),
                "godot_log": str(godot_log),
                "ga_summary_json": str(ga_summary),
                "collision_csv": str(collision_csv),
                "python_routes_received_csv": str(python_routes_csv),
                "websocket_port": ws_port,
            },
        }

    def run_replication(self, payload: dict, seed: int, run_tmp_dir: Path) -> dict:
        if self.mode == "mock":
            return self._run_mock(payload["bitstring"], seed)
        if self.mode == "integrated":
            return self._run_integrated(payload, seed, run_tmp_dir)
        return self._run_command(payload, seed, run_tmp_dir)


def bitstring_from_array(bits: np.ndarray) -> str:
    return "".join("1" if int(x) == 1 else "0" for x in bits.tolist())


def load_graph_pickle_safe(pickle_file: str) -> Tuple[nx.DiGraph, dict]:
    with open(pickle_file, "rb") as f:
        loaded = pickle.load(f)
    if isinstance(loaded, dict):
        if "graph" in loaded:
            graph = loaded["graph"]
            metadata = loaded.get("metadata", {})
        elif "G" in loaded:
            graph = loaded["G"]
            metadata = loaded.get("metadata", {})
        else:
            graph = loaded
            metadata = {}
    else:
        graph = loaded
        metadata = {}
    if not isinstance(graph, (nx.Graph, nx.DiGraph, nx.MultiGraph, nx.MultiDiGraph)):
        raise ValueError("Loaded object is not a NetworkX graph.")
    if isinstance(graph, (nx.MultiGraph, nx.MultiDiGraph)):
        # Keep GA orientation logic simple and deterministic on DiGraph.
        graph = nx.DiGraph(graph)
    elif isinstance(graph, nx.Graph) and not isinstance(graph, nx.DiGraph):
        graph = nx.DiGraph(graph)
    return graph, metadata if isinstance(metadata, dict) else {}


def resolve_godot_executable(godot_exe_arg: str) -> str:
    """
    Resolve a usable Godot executable path.

    Supports:
    - Direct executable path
    - PATH command names (e.g. godot4)
    - Directory path containing Godot binaries
    - Windows extracted folder named like '*.exe' containing the real .exe inside
    """
    raw = (godot_exe_arg or "").strip().strip('"')
    if not raw:
        raise ValueError("Empty --godot-exe value.")

    candidate_path = Path(raw).expanduser()

    # 1) Existing file path.
    if candidate_path.exists() and candidate_path.is_file():
        return str(candidate_path.resolve())

    # 2) Existing directory path (or extracted folder with .exe suffix).
    if candidate_path.exists() and candidate_path.is_dir():
        folder = candidate_path
        base_name = candidate_path.name
        stem = candidate_path.stem
        preferred = [
            folder / base_name,  # e.g. <dir>/Godot_v4.3-stable_win64.exe
            folder / f"{stem}_console.exe",
            folder / f"{stem}.exe",
        ]
        for p in preferred:
            if p.exists() and p.is_file():
                return str(p.resolve())

        # Then broader search: prefer console binary for better diagnostics.
        for pattern in ("*_console.exe", "Godot*.exe", "*.exe"):
            matches = sorted(folder.glob(pattern))
            for m in matches:
                if m.is_file():
                    return str(m.resolve())

    # 3) Command on PATH.
    from_path = shutil.which(raw)
    if from_path:
        return str(Path(from_path).resolve())

    raise FileNotFoundError(
        "Could not resolve Godot executable from --godot-exe. "
        f"Provided value: '{godot_exe_arg}'. "
        "Pass a real executable path, a directory containing the executable, or a command available on PATH."
    )


def auto_detect_godot_executable() -> Optional[str]:
    """
    Try to auto-detect Godot executable in common local locations.
    """
    # PATH first.
    for cmd in ("godot4", "godot"):
        path_hit = shutil.which(cmd)
        if path_hit:
            return str(Path(path_hit).resolve())

    home = Path.home()
    search_roots = [
        home / "Downloads",
        home / "Documents",
        home / "OneDrive" / "Documents",
        home / "OneDrive" / "Divesos" / "Documentos",
    ]

    candidates: List[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        # Common extracted layouts:
        # - <root>/Godot_vX.Y-stable_win64.exe/Godot_vX.Y-stable_win64.exe
        # - <root>/Godot.../Godot*.exe
        patterns = [
            "Godot*.exe",
            "Godot*.exe/Godot*.exe",
            "Godot*/Godot*.exe",
        ]
        for pattern in patterns:
            for match in root.glob(pattern):
                if match.is_file():
                    candidates.append(match.resolve())

    if not candidates:
        return None

    # Prefer console exe for better logs, otherwise highest lexical match.
    candidates = sorted(set(candidates))
    console_hits = [p for p in candidates if p.name.endswith("_console.exe")]
    if console_hits:
        return str(console_hits[-1])
    return str(candidates[-1])


def mutation_probability(num_variables: int) -> float:
    base = 1.0 / max(1, num_variables)
    return float(np.clip(base, 0.002, 0.03))


def select_edges_from_chromosome(
    variable_to_group_list,
    chromosome: np.ndarray,
) -> List[Tuple[str, str]]:
    """
    Silent edge selector equivalent to the visualizer logic:
    - gene=0 -> forward_edges
    - gene=1 -> reverse_edges
    """
    selected = set()
    for i, (_group_key, forward_edges, reverse_edges) in enumerate(variable_to_group_list):
        if int(chromosome[i]) == 0:
            for edge in forward_edges:
                selected.add(edge)
        else:
            for edge in reverse_edges:
                selected.add(edge)
    out = list(selected)
    out.sort()
    return out


def mean_pairwise_hamming(population: np.ndarray) -> float:
    pop_size = population.shape[0]
    if pop_size <= 1:
        return 0.0
    pair_count = 0
    total = 0.0
    for i in range(pop_size - 1):
        a = population[i]
        for j in range(i + 1, pop_size):
            b = population[j]
            total += float(np.mean(a != b))
            pair_count += 1
    return total / pair_count if pair_count else 0.0


def tournament_select_indices(
    fitness_values: np.ndarray, tournament_size: int, rng: np.random.Generator
) -> Tuple[int, int]:
    pop_size = len(fitness_values)

    def pick_one() -> int:
        idxs = rng.integers(0, pop_size, size=tournament_size)
        best_local = idxs[0]
        best_fit = fitness_values[best_local]
        for idx in idxs[1:]:
            if fitness_values[idx] < best_fit:
                best_fit = fitness_values[idx]
                best_local = idx
        return int(best_local)

    return pick_one(), pick_one()


def uniform_crossover(
    parent_a: np.ndarray, parent_b: np.ndarray, crossover_p: float, rng: np.random.Generator
) -> Tuple[np.ndarray, np.ndarray]:
    if rng.random() >= crossover_p:
        return parent_a.copy(), parent_b.copy()
    mask = rng.integers(0, 2, size=parent_a.shape[0], dtype=np.int8).astype(bool)
    child_1 = np.where(mask, parent_a, parent_b).astype(np.int8)
    child_2 = np.where(mask, parent_b, parent_a).astype(np.int8)
    return child_1, child_2


def bitflip_mutation(chromosome: np.ndarray, mutation_p: float, rng: np.random.Generator) -> np.ndarray:
    flips = rng.random(size=chromosome.shape[0]) < mutation_p
    mutated = chromosome.copy()
    mutated[flips] = 1 - mutated[flips]
    return mutated.astype(np.int8)


def build_generation_seed_list(base_seed: int, generation: int, max_k: int) -> List[int]:
    # Same seed list used across all individuals in a generation (CRN protocol).
    gen_rng = np.random.default_rng(base_seed * 100_000 + generation)
    return gen_rng.integers(0, 2_000_000_000, size=max_k, dtype=np.int64).astype(int).tolist()


def seed_signature(seeds: Sequence[int]) -> str:
    return ",".join(str(s) for s in seeds)


def evaluate_chromosome(
    chromosome: np.ndarray,
    seeds: Sequence[int],
    adapter: SimulationAdapter,
    invalid_threshold: int,
    invalid_penalty: float,
    variable_to_group_list,
    cache: Dict[Tuple[str, str], EvalResult],
    run_tmp_dir: Path,
) -> EvalResult:
    bitstring = bitstring_from_array(chromosome)
    sig = seed_signature(seeds)
    cache_key = (bitstring, sig)
    if cache_key in cache:
        return cache[cache_key]

    collisions: List[float] = []
    per_seed_fitness: List[float] = []
    no_path_count = 0
    timeout_count = 0
    server_error_count = 0
    no_response_count = 0
    no_valid_route_count = 0

    # Build selected edge list payload once per chromosome evaluation.
    selected_edges = select_edges_from_chromosome(variable_to_group_list, chromosome)
    payload_base = {
        "bitstring": bitstring,
        "chromosome": [int(x) for x in chromosome.tolist()],
        "selected_edges": [[u, v] for u, v in selected_edges],
    }

    for seed in seeds:
        try:
            sim_result = adapter.run_replication(payload=payload_base, seed=int(seed), run_tmp_dir=run_tmp_dir)
            c = float(sim_result.get("collisions", 0.0))
            n = int(sim_result.get("no_path_count", 0))
            t = int(sim_result.get("timeout_count", 0))
            se = int(sim_result.get("server_error_count", 0))
            nr = int(sim_result.get("no_response_count", 0))
            nv = int(sim_result.get("no_valid_route_count", 0))
        except Exception:
            # Treat simulation failures as invalid pressure.
            c = invalid_penalty
            n = invalid_threshold
            t = 0
            se = 0
            nr = 0
            nv = 0

        collisions.append(c)
        per_seed_fitness.append(float(c + n + t))
        no_path_count += n
        timeout_count += t
        server_error_count += se
        no_response_count += nr
        no_valid_route_count += nv

    mean_c = float(np.mean(collisions)) if collisions else float(invalid_penalty)
    total_collisions = float(np.sum(collisions)) if collisions else float(invalid_penalty)
    invalid_count = no_path_count + timeout_count
    is_invalid = invalid_count >= invalid_threshold
    fitness = float(total_collisions + no_path_count + timeout_count)
    replication_fitness_std = float(np.std(per_seed_fitness)) if per_seed_fitness else 0.0
    result = EvalResult(
        fitness=fitness,
        mean_collisions=mean_c,
        no_path_count=no_path_count,
        timeout_count=timeout_count,
        server_error_count=server_error_count,
        no_response_count=no_response_count,
        no_valid_route_count=no_valid_route_count,
        invalid_count=invalid_count,
        is_invalid=is_invalid,
        replications=len(collisions),
        per_seed_fitness=per_seed_fitness,
        replication_fitness_std=replication_fitness_std,
    )
    cache[cache_key] = result
    return result


def evaluate_population_batch(
    chromosomes: np.ndarray,
    seeds: Sequence[int],
    adapter: SimulationAdapter,
    invalid_threshold: int,
    invalid_penalty: float,
    variable_to_group_list,
    cache: Dict[Tuple[str, str], EvalResult],
    run_tmp_dir: Path,
    workers: int,
) -> List[EvalResult]:
    """
    Evaluate a chromosome batch with cache-aware de-duplication and optional threading.

    Notes:
    - cache key remains (bitstring, seed_signature) exactly as before.
    - duplicate chromosomes in the same batch are evaluated once.
    - threaded mode helps integrated/command runs where work is dominated by external processes.
    """
    if chromosomes.ndim != 2:
        raise ValueError("chromosomes must be a 2D array (batch_size, chromosome_length).")
    if workers < 1:
        raise ValueError("--workers must be >= 1.")

    seed_sig = seed_signature(seeds)
    batch_size = int(chromosomes.shape[0])
    evals: List[Optional[EvalResult]] = [None] * batch_size
    pending: Dict[Tuple[str, str], List[int]] = {}

    for idx in range(batch_size):
        bitstring = bitstring_from_array(chromosomes[idx])
        key = (bitstring, seed_sig)
        cached = cache.get(key)
        if cached is not None:
            evals[idx] = cached
        else:
            pending.setdefault(key, []).append(idx)

    if not pending:
        return [x for x in evals if x is not None]

    unique_jobs: List[Tuple[Tuple[str, str], int]] = []
    for key, idxs in pending.items():
        unique_jobs.append((key, idxs[0]))

    def run_one(local_idx: int) -> EvalResult:
        # Keep per-task local cache so evaluate_chromosome logic stays unchanged.
        return evaluate_chromosome(
            chromosome=chromosomes[local_idx],
            seeds=seeds,
            adapter=adapter,
            invalid_threshold=invalid_threshold,
            invalid_penalty=invalid_penalty,
            variable_to_group_list=variable_to_group_list,
            cache={},
            run_tmp_dir=run_tmp_dir,
        )

    if workers == 1 or len(unique_jobs) == 1:
        for key, idx0 in unique_jobs:
            result = run_one(idx0)
            cache[key] = result
            for idx in pending[key]:
                evals[idx] = result
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_key: Dict = {}
            for key, idx0 in unique_jobs:
                fut = pool.submit(run_one, idx0)
                future_to_key[fut] = key

            for fut in as_completed(future_to_key):
                key = future_to_key[fut]
                result = fut.result()
                cache[key] = result
                for idx in pending[key]:
                    evals[idx] = result

    if any(x is None for x in evals):
        raise RuntimeError("Batch evaluation did not produce results for all chromosomes.")
    return [x for x in evals if x is not None]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GA Experiment 1 - Godot simulation-based combinatorial optimization")
    parser.add_argument("--pickle-file", type=str, default="./Experiments/Ex1-ShtPath-GA/regular_lattice_graph.pkl")
    parser.add_argument("--population", type=int, default=120)
    parser.add_argument("--generations", type=int, default=120)
    parser.add_argument("--tournament-size", type=int, default=3)
    parser.add_argument("--crossover-prob", type=float, default=0.85)
    parser.add_argument("--elitism", type=int, default=2)
    parser.add_argument("--early-stop-patience", type=int, default=20)
    parser.add_argument("--invalid-threshold", type=int, default=1000)
    parser.add_argument("--invalid-penalty", type=float, default=10000.0)
    parser.add_argument("--workers", type=int, default=18)
    parser.add_argument("--seed", type=int, default=160)
    parser.add_argument("--log-mode", type=str, default="normal", choices=list(LOG_MODE_CHOICES))
    parser.add_argument(
        "--artifact-mode",
        type=str,
        default="keep_all",
        choices=list(ARTIFACT_MODE_CHOICES),
        help=(
            "Replication artifact retention policy in integrated mode: "
            "keep_all, keep_failures, or minimal."
        ),
    )
    parser.add_argument("--eval-mode", type=str, default="integrated", choices=["integrated", "command", "mock"])
    parser.add_argument(
        "--sim-command",
        type=str,
        default="",
        help=(
            "Simulation command template. Supports {seed}, {input_json}, {output_json}. "
            "The command should emit/produce JSON with collisions, no_path_count, timeout_count."
        ),
    )
    parser.add_argument("--sim-timeout-seconds", type=float, default=360.0)
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
    parser.add_argument("--tensorboard-port", type=int, default=6007)
    parser.add_argument("--tensorboard-host", type=str, default="127.0.0.1")
    parser.add_argument("--auto-launch-tensorboard", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--auto-open-tensorboard-browser", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--final-validation-top-k", type=int, default=5)
    parser.add_argument("--final-validation-seeds", type=int, default=20)
    parser.add_argument("--run-sensitivity", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--sensitivity-max-bits",
        type=int,
        default=0,
        help="Maximum bit count for sensitivity sweep (0 = all bits).",
    )
    parser.add_argument("--run-root", type=str, default="./Experiments/Ex1-ShtPath-GA/ga_runs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start_wall = time.time()

    if args.population < 2:
        raise ValueError("--population must be >= 2.")
    if args.elitism < 0:
        raise ValueError("--elitism must be >= 0.")
    if args.elitism > args.population:
        raise ValueError("--elitism must be <= --population.")
    if args.workers < 1:
        raise ValueError("--workers must be >= 1.")
    assert args.log_mode in LOG_MODE_CHOICES
    assert args.artifact_mode in ARTIFACT_MODE_CHOICES
    if args.final_validation_top_k < 1:
        raise ValueError("--final-validation-top-k must be >= 1.")
    if args.final_validation_seeds < 1:
        raise ValueError("--final-validation-seeds must be >= 1.")
    if args.sensitivity_max_bits < 0:
        raise ValueError("--sensitivity-max-bits must be >= 0.")

    if args.eval_mode == "command" and not args.sim_command.strip():
        raise ValueError("When --eval-mode=command, --sim-command is required.")
    if args.eval_mode == "integrated":
        try:
            args.godot_exe = resolve_godot_executable(args.godot_exe)
        except FileNotFoundError:
            auto_hit = auto_detect_godot_executable()
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
            raise FileNotFoundError(
                f"No project.godot found in --godot-project-dir: {project_dir}"
            )
        print(f"Integrated mode preflight OK. Godot executable: {args.godot_exe}")
        print(f"Integrated mode preflight OK. Godot project dir: {project_dir}")

    run_id = datetime.now().strftime("GA-Experiment1_%Y%m%d_%H%M%S")
    run_root = Path(args.run_root).resolve()
    run_dir = run_root / run_id
    run_tmp_dir = run_dir / "tmp"
    tb_dir = run_dir / "tensorboard"
    terminal_output_path = run_dir / "terminal_output.txt"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_tmp_dir.mkdir(parents=True, exist_ok=True)
    tb_dir.mkdir(parents=True, exist_ok=True)

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    terminal_output_file = terminal_output_path.open("w", encoding="utf-8")
    sys.stdout = TeeTextIO(original_stdout, terminal_output_file)
    sys.stderr = TeeTextIO(original_stderr, terminal_output_file)

    def _restore_streams_and_close_terminal_log() -> None:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        try:
            terminal_output_file.flush()
        except Exception:
            pass
        terminal_output_file.close()

    atexit.register(_restore_streams_and_close_terminal_log)
    print(f"Terminal output log: {terminal_output_path}")

    writer = SummaryWriter(log_dir=str(tb_dir)) if SummaryWriter is not None else NullSummaryWriter()
    if SummaryWriter is None:
        print("WARNING: TensorBoard SummaryWriter is unavailable. Install torch or tensorboardX for event logging.")
    tb_process: Optional[subprocess.Popen] = None
    tb_url = f"http://{args.tensorboard_host}:{args.tensorboard_port}"
    if args.auto_launch_tensorboard:
        tb_process, tb_url = launch_tensorboard(
            logdir=tb_dir,
            run_dir=run_dir,
            port=int(args.tensorboard_port),
            host=str(args.tensorboard_host),
            open_browser=bool(args.auto_open_tensorboard_browser),
        )
        if tb_process is not None:
            print(f"TensorBoard auto-started at: {tb_url}")
            print(f"TensorBoard process log: {run_dir / 'tensorboard_process.log'}")
        else:
            print("WARNING: TensorBoard auto-start failed. Check tensorboard_process.log and launch manually if needed.")

    print("=" * 88)
    print("GA-EXPERIMENT1: GODOT SIMULATION-BASED COMBINATORIAL OPTIMIZATION")
    print("=" * 88)

    # 1) Load graph and build decision-variable mapping exactly like the air-corridor visualizer.
    graph, _metadata = load_graph_pickle_safe(args.pickle_file)
    _group_dict, variable_to_group_list = identify_air_corridor_edge_groups(graph)
    num_variables = len(variable_to_group_list)
    if num_variables <= 0:
        raise RuntimeError("No air-corridor variables found; cannot run GA.")

    mut_p = mutation_probability(num_variables)
    print(f"Variables (chromosome length): {num_variables}")
    print(f"Mutation probability (per-bit): {mut_p:.6f}")
    print(f"Evaluation workers: {args.workers}")

    # 2) Initialize GA state.
    rng = np.random.default_rng(args.seed) 
    population = rng.integers(0, 2, size=(args.population, num_variables), dtype=np.int8) 

    adapter = SimulationAdapter(
        mode=args.eval_mode,
        log_mode=args.log_mode,
        artifact_mode=args.artifact_mode,
        sim_command=args.sim_command.strip() or None,
        timeout_seconds=float(args.sim_timeout_seconds),
        working_dir=Path(__file__).resolve().parents[2],  # repository root
        base_graph=graph,
        base_metadata=_metadata if isinstance(_metadata, dict) else {},
        python_exe=args.python_exe,
        websocket_server_script=Path(args.websocket_server_script).resolve(),
        godot_exe=args.godot_exe,
        godot_project_dir=Path(args.godot_project_dir).resolve(),
        integrated_max_sim_time=float(args.integrated_max_sim_time),
        server_start_timeout=float(args.server_start_timeout),
    )
    cache: Dict[Tuple[str, str], EvalResult] = {}

    best_global_selection_score = float("inf")
    best_global_fitness_raw = float("inf")
    best_global_chromosome: Optional[np.ndarray] = None
    best_global_eval: Optional[EvalResult] = None
    best_candidate_archive: Dict[str, float] = {}
    no_improve_counter = 0
    generation_rows: List[dict] = []

    # 3) Evolution loop.
    for gen in range(1, args.generations + 1):
        gen_start = time.time()
        max_k = 2 if gen <= 40 else 6
        gen_seeds = build_generation_seed_list(base_seed=args.seed, generation=gen, max_k=max_k)
        base_seeds = gen_seeds[:2]

        evals = evaluate_population_batch(
            chromosomes=population,
            seeds=base_seeds,
            adapter=adapter,
            invalid_threshold=args.invalid_threshold,
            invalid_penalty=args.invalid_penalty,
            variable_to_group_list=variable_to_group_list,
            cache=cache,
            run_tmp_dir=run_tmp_dir,
            workers=args.workers,
        )

        # Re-evaluate top 20% with k=6 for generations 41-120.
        if gen >= 41:
            fitness_array = np.array([x.fitness for x in evals], dtype=float)
            top_count = max(1, int(np.ceil(0.20 * args.population)))
            top_indices = np.argsort(fitness_array)[:top_count]
            refined_batch = evaluate_population_batch(
                chromosomes=population[top_indices],
                seeds=gen_seeds[:6],
                adapter=adapter,
                invalid_threshold=args.invalid_threshold,
                invalid_penalty=args.invalid_penalty,
                variable_to_group_list=variable_to_group_list,
                cache=cache,
                run_tmp_dir=run_tmp_dir,
                workers=args.workers,
            )
            for local_i, idx in enumerate(top_indices.tolist()):
                evals[idx] = refined_batch[local_i]

        fitness_values = np.array([x.fitness for x in evals], dtype=float)
        replications = np.array([max(1, int(x.replications)) for x in evals], dtype=float)
        selection_scores = fitness_values / replications
        invalid_counts = np.array([x.invalid_count for x in evals], dtype=int)
        invalid_flags = np.array([1 if x.is_invalid else 0 for x in evals], dtype=int)
        mean_no_path = float(np.mean([x.no_path_count for x in evals]))
        mean_planner_timeout = float(np.mean([x.timeout_count for x in evals]))
        mean_server_error = float(np.mean([x.server_error_count for x in evals]))
        mean_no_response = float(np.mean([x.no_response_count for x in evals]))
        mean_no_valid_route = float(np.mean([x.no_valid_route_count for x in evals]))

        gen_best_idx = int(np.argmin(selection_scores))
        gen_best_selection = float(selection_scores[gen_best_idx])
        gen_best_fit_raw = float(fitness_values[gen_best_idx])
        gen_best_eval = evals[gen_best_idx]
        gen_mean_selection = float(np.mean(selection_scores))
        gen_std_selection = float(np.std(selection_scores))
        gen_mean_fit_raw = float(np.mean(fitness_values))
        gen_std_fit_raw = float(np.std(fitness_values))
        num_invalid = int(np.sum(invalid_flags))
        best_invalid_count = int(gen_best_eval.invalid_count)
        best_replication_fitness_std = float(gen_best_eval.replication_fitness_std)
        best_seed_scores = [float(x) for x in gen_best_eval.per_seed_fitness]
        best_seed_ids = gen_seeds[: len(best_seed_scores)]
        best_seed_scores_str = ",".join(
            f"{int(seed)}:{score:.2f}" for seed, score in zip(best_seed_ids, best_seed_scores)
        )
        diversity = float(mean_pairwise_hamming(population))

        best_bitstring = bitstring_from_array(population[gen_best_idx])
        best_candidate_archive[best_bitstring] = min(
            gen_best_selection, best_candidate_archive.get(best_bitstring, float("inf"))
        )

        if gen_best_selection < best_global_selection_score:
            best_global_selection_score = gen_best_selection
            best_global_fitness_raw = gen_best_fit_raw
            best_global_chromosome = population[gen_best_idx].copy()
            best_global_eval = evals[gen_best_idx]
            no_improve_counter = 0
        else:
            no_improve_counter += 1

        gen_seconds = float(time.time() - gen_start)
        row = {
            "generation": gen,
            "fitness_best": gen_best_fit_raw,
            "fitness_best_selection": gen_best_selection,
            "fitness_best_raw": gen_best_fit_raw,
            "fitness_mean": gen_mean_fit_raw,
            "fitness_std": gen_std_fit_raw,
            "fitness_mean_selection": gen_mean_selection,
            "fitness_std_selection": gen_std_selection,
            "fitness_mean_raw": gen_mean_fit_raw,
            "fitness_std_raw": gen_std_fit_raw,
            "invalid_best_individual_invalid_count": best_invalid_count,
            "invalid_num_invalid_individuals": num_invalid,
            "route_mean_no_path_python": mean_no_path,
            "route_mean_planner_timeout_python": mean_planner_timeout,
            "route_mean_server_error_python": mean_server_error,
            "route_mean_no_response_godot": mean_no_response,
            "route_mean_no_valid_route_payload_godot": mean_no_valid_route,
            "ga_diversity_hamming_mean": diversity,
            "time_generation_seconds": gen_seconds,
            "k_base": 2,
            "k_refined_top20": 6 if gen >= 41 else 0,
            "seed_signature_base": seed_signature(base_seeds),
            "seed_signature_full": seed_signature(gen_seeds),
            "best_replication_fitness_std": best_replication_fitness_std,
            "best_seed_fitness_scores": best_seed_scores_str,
        }
        generation_rows.append(row)

        writer.add_scalar("fitness/best", gen_best_fit_raw, gen)
        writer.add_scalar("fitness/best_selection", gen_best_selection, gen)
        writer.add_scalar("fitness/best_raw", gen_best_fit_raw, gen)
        writer.add_scalar("fitness/mean", gen_mean_fit_raw, gen)
        writer.add_scalar("fitness/mean_selection", gen_mean_selection, gen)
        writer.add_scalar("fitness/mean_raw", gen_mean_fit_raw, gen)
        writer.add_scalar("fitness/std", gen_std_fit_raw, gen)
        writer.add_scalar("fitness/std_selection", gen_std_selection, gen)
        writer.add_scalar("fitness/std_raw", gen_std_fit_raw, gen)
        writer.add_scalar("invalid/best_individual_invalid_count", best_invalid_count, gen)
        writer.add_scalar("invalid/num_invalid_individuals", num_invalid, gen)
        writer.add_scalar("route/mean_no_path_python", mean_no_path, gen)
        writer.add_scalar("route/mean_planner_timeout_python", mean_planner_timeout, gen)
        writer.add_scalar("route/mean_server_error_python", mean_server_error, gen)
        writer.add_scalar("route/mean_no_response_godot", mean_no_response, gen)
        writer.add_scalar("route/mean_no_valid_route_payload_godot", mean_no_valid_route, gen)
        writer.add_scalar("ga/diversity_hamming_mean", diversity, gen)
        writer.add_scalar("time/generation_seconds", gen_seconds, gen)
        writer.flush()

        mode_settings = resolve_log_mode_settings(args.log_mode)
        should_print_gen_line = bool(mode_settings["print_every_generation"]) or gen == 1 or gen % 10 == 0
        if should_print_gen_line:
            print(
                f"[Gen {gen:03d}] best_sel={gen_best_selection:.4f} best_raw={gen_best_fit_raw:.4f} "
                f"mean_sel={gen_mean_selection:.4f} std_sel={gen_std_selection:.4f} "
                f"invalid={num_invalid}/{args.population} "
                f"mean_no_path_py={mean_no_path:.2f} "
                f"mean_timeout_py={mean_planner_timeout:.2f} "
                f"mean_error_py={mean_server_error:.2f} "
                f"mean_no_resp_gd={mean_no_response:.2f} "
                f"mean_no_valid_gd={mean_no_valid_route:.2f} "
                f"best_seed_scores=[{best_seed_scores_str}] "
                f"best_rep_std={best_replication_fitness_std:.4f} "
                f"diversity={diversity:.4f} t={gen_seconds:.2f}s"
            )

        if no_improve_counter >= args.early_stop_patience:
            print(
                f"Early stopping at generation {gen} (no best-fitness improvement for "
                f"{args.early_stop_patience} generations)."
            )
            break

        # Selection + reproduction.
        elite_indices = np.argsort(selection_scores)[: args.elitism]
        elites = population[elite_indices].copy()

        offspring_target = args.population - args.elitism
        if offspring_target <= 0:
            # Fully elitist replacement: carry elites only (safe for tiny diagnostic runs).
            population = elites[: args.population].copy()
        else:
            offspring: List[np.ndarray] = []
            while len(offspring) < offspring_target:
                p1_idx, p2_idx = tournament_select_indices(
                    fitness_values=selection_scores, tournament_size=args.tournament_size, rng=rng
                )
                c1, c2 = uniform_crossover(
                    parent_a=population[p1_idx],
                    parent_b=population[p2_idx],
                    crossover_p=args.crossover_prob,
                    rng=rng,
                )
                c1 = bitflip_mutation(c1, mutation_p=mut_p, rng=rng)
                c2 = bitflip_mutation(c2, mutation_p=mut_p, rng=rng)
                offspring.append(c1)
                if len(offspring) < offspring_target:
                    offspring.append(c2)

            offspring_array = np.array(offspring[:offspring_target], dtype=np.int8)
            population = np.vstack((elites, offspring_array))
            population = population[: args.population]

    # 4) Final validation on held-out seeds for configurable top-K.
    if best_global_chromosome is None:
        raise RuntimeError("GA finished without a best solution.")

    # Build candidate list from archive + final population.
    final_candidates: Dict[str, np.ndarray] = {}
    for i in range(population.shape[0]):
        bs = bitstring_from_array(population[i])
        final_candidates[bs] = population[i].copy()
    final_candidates[bitstring_from_array(best_global_chromosome)] = best_global_chromosome.copy()

    # Rank by best-known archived selection score (fallback inf).
    ranked_candidates = sorted(
        final_candidates.items(),
        key=lambda kv: best_candidate_archive.get(kv[0], float("inf")),
    )
    top_k = min(len(ranked_candidates), int(args.final_validation_top_k))
    top_candidates = ranked_candidates[:top_k]

    heldout_seeds = build_generation_seed_list(
        base_seed=args.seed + 99991,
        generation=999,
        max_k=int(args.final_validation_seeds),
    )
    heldout_sig = seed_signature(heldout_seeds)
    print(
        f"[FinalVal] start top_k={top_k}/{len(ranked_candidates)} heldout_seeds={len(heldout_seeds)}"
    )
    final_val_start = time.time()
    final_validation = []
    for cand_i, (bitstring, chrom) in enumerate(top_candidates, start=1):
        cand_start = time.time()
        res = evaluate_chromosome(
            chromosome=chrom,
            seeds=heldout_seeds,
            adapter=adapter,
            invalid_threshold=args.invalid_threshold,
            invalid_penalty=args.invalid_penalty,
            variable_to_group_list=variable_to_group_list,
            cache=cache,
            run_tmp_dir=run_tmp_dir,
        )
        final_validation.append(
            {
                "bitstring": bitstring,
                "fitness": res.fitness,
                "mean_collisions": res.mean_collisions,
                "no_path_count": res.no_path_count,
                "timeout_count": res.timeout_count,
                "server_error_count": res.server_error_count,
                "no_response_count": res.no_response_count,
                "no_valid_route_count": res.no_valid_route_count,
                "invalid_count": res.invalid_count,
                "is_invalid": res.is_invalid,
                "replications": res.replications,
                "seed_signature": heldout_sig,
            }
        )
        cand_elapsed = float(time.time() - cand_start)
        print(
            f"[FinalVal {cand_i:03d}/{top_k:03d}] fit={res.fitness:.4f} "
            f"invalid={res.invalid_count} bits={bitstring[:16]}... t={cand_elapsed:.2f}s"
        )
    final_validation.sort(key=lambda x: float(x["fitness"]))
    best_validated = final_validation[0]
    best_validated_bits = np.array([int(ch) for ch in best_validated["bitstring"]], dtype=np.int8)
    print(
        f"[FinalVal] done best_fit={float(best_validated['fitness']):.4f} "
        f"elapsed={float(time.time() - final_val_start):.2f}s"
    )

    sensitivity_rows = []
    sensitivity_bit_count_used = 0
    # 5) One-bit sensitivity analysis from best validated chromosome on held-out seeds.
    if args.run_sensitivity:
        best_val_result = evaluate_chromosome(
            chromosome=best_validated_bits,
            seeds=heldout_seeds,
            adapter=adapter,
            invalid_threshold=args.invalid_threshold,
            invalid_penalty=args.invalid_penalty,
            variable_to_group_list=variable_to_group_list,
            cache=cache,
            run_tmp_dir=run_tmp_dir,
        )
        base_fit = best_val_result.fitness
        if args.sensitivity_max_bits == 0:
            bit_count = num_variables
        else:
            bit_count = min(num_variables, int(args.sensitivity_max_bits))
        sensitivity_bit_count_used = int(bit_count)
        print(
            f"[Sensitivity] start bits={sensitivity_bit_count_used}/{num_variables} "
            f"heldout_seeds={len(heldout_seeds)}"
        )
        sensitivity_start = time.time()
        progress_every = 10
        max_abs_delta = 0.0
        last_delta = 0.0
        for bit_idx in range(bit_count):
            flipped = best_validated_bits.copy()
            flipped[bit_idx] = 1 - flipped[bit_idx]
            flipped_res = evaluate_chromosome(
                chromosome=flipped,
                seeds=heldout_seeds,
                adapter=adapter,
                invalid_threshold=args.invalid_threshold,
                invalid_penalty=args.invalid_penalty,
                variable_to_group_list=variable_to_group_list,
                cache=cache,
                run_tmp_dir=run_tmp_dir,
            )
            delta = float(flipped_res.fitness - base_fit)
            sensitivity_rows.append(
                {
                    "bit_index": bit_idx,
                    "base_bit": int(best_validated_bits[bit_idx]),
                    "flipped_bit": int(flipped[bit_idx]),
                    "base_fitness": base_fit,
                    "flipped_fitness": float(flipped_res.fitness),
                    "delta_fitness": delta,
                    "abs_delta_fitness": abs(delta),
                    "is_invalid_after_flip": bool(flipped_res.is_invalid),
                }
            )
            max_abs_delta = max(max_abs_delta, abs(delta))
            last_delta = delta
            processed = bit_idx + 1
            if processed % progress_every == 0 or processed == bit_count:
                elapsed = float(time.time() - sensitivity_start)
                if processed > 0:
                    eta = float((elapsed / processed) * (bit_count - processed))
                else:
                    eta = 0.0
                print(
                    f"[Sensitivity {processed:03d}/{bit_count:03d}] "
                    f"last_delta={last_delta:.4f} max_abs_delta={max_abs_delta:.4f} "
                    f"elapsed={elapsed:.2f}s eta={eta:.2f}s"
                )
        sensitivity_rows.sort(key=lambda x: float(x["abs_delta_fitness"]), reverse=True)
        top_bit = int(sensitivity_rows[0]["bit_index"]) if sensitivity_rows else -1
        top_abs_delta = float(sensitivity_rows[0]["abs_delta_fitness"]) if sensitivity_rows else 0.0
        print(
            f"[Sensitivity] done top_bit={top_bit} top_abs_delta={top_abs_delta:.4f} "
            f"elapsed={float(time.time() - sensitivity_start):.2f}s"
        )
    else:
        print("[Sensitivity] skipped (--no-run-sensitivity).")

    # 6) Persist outputs.
    generation_csv = run_dir / "generation_metrics.csv"
    with generation_csv.open("w", newline="", encoding="utf-8") as f:
        writer_csv = csv.DictWriter(f, fieldnames=list(generation_rows[0].keys()))
        writer_csv.writeheader()
        writer_csv.writerows(generation_rows)

    best_solution_path = run_dir / "best_solution.json"
    with best_solution_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "bitstring": best_validated["bitstring"],
                "chromosome": [int(ch) for ch in best_validated["bitstring"]],
                "best_fitness": float(best_validated["fitness"]),
                "mean_collisions": float(best_validated["mean_collisions"]),
                "invalid_count": int(best_validated["invalid_count"]),
                "replications": int(best_validated["replications"]),
                "seed_signature": best_validated["seed_signature"],
            },
            f,
            indent=2,
        )

    final_validation_path = run_dir / "final_validation_summary.json"
    with final_validation_path.open("w", encoding="utf-8") as f:
        summary = {
            "heldout_seed_signature": heldout_sig,
            "top_k_requested": int(args.final_validation_top_k),
            "top_k_used": int(top_k),
            "heldout_seeds_count": int(len(heldout_seeds)),
            "top_results": final_validation,
        }
        if int(top_k) == 5:
            summary["top5_results"] = final_validation
        json.dump(
            summary,
            f,
            indent=2,
        )

    sensitivity_csv = run_dir / "sensitivity_analysis.csv"
    if args.run_sensitivity and sensitivity_rows:
        with sensitivity_csv.open("w", newline="", encoding="utf-8") as f:
            writer_csv = csv.DictWriter(f, fieldnames=list(sensitivity_rows[0].keys()))
            writer_csv.writeheader()
            writer_csv.writerows(sensitivity_rows)

    config_path = run_dir / "run_config.json"
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "population": args.population,
                "generations": args.generations,
                "tournament_size": args.tournament_size,
                "crossover_prob": args.crossover_prob,
                "mutation_prob": mut_p,
                "elitism": args.elitism,
                "early_stop_patience": args.early_stop_patience,
                "invalid_threshold": args.invalid_threshold,
                "invalid_penalty": args.invalid_penalty,
                "workers": args.workers,
                "eval_mode": args.eval_mode,
                "sim_command": args.sim_command,
                "sim_timeout_seconds": args.sim_timeout_seconds,
                "python_exe": args.python_exe,
                "websocket_server_script": args.websocket_server_script,
                "godot_exe": args.godot_exe,
                "godot_project_dir": args.godot_project_dir,
                "integrated_max_sim_time": args.integrated_max_sim_time,
                "server_start_timeout": args.server_start_timeout,
                "tensorboard_port": args.tensorboard_port,
                "tensorboard_host": args.tensorboard_host,
                "auto_launch_tensorboard": args.auto_launch_tensorboard,
                "auto_open_tensorboard_browser": args.auto_open_tensorboard_browser,
                "final_validation_top_k": args.final_validation_top_k,
                "final_validation_seeds": args.final_validation_seeds,
                "run_sensitivity": args.run_sensitivity,
                "sensitivity_max_bits": args.sensitivity_max_bits,
                "sensitivity_bit_count_used": sensitivity_bit_count_used,
                "pickle_file": args.pickle_file,
                "num_variables": num_variables,
                "run_id": run_id,
                "base_seed": args.seed,
                "log_mode": args.log_mode,
                "artifact_mode": args.artifact_mode,
            },
            f,
            indent=2,
        )

    # Close TensorBoard writer and print final summary.
    writer.close()
    elapsed = time.time() - start_wall

    print("=" * 88)
    print("GA EXPERIMENT COMPLETE")
    print("=" * 88)
    print(f"Best GA selection score: {best_global_selection_score:.6f}")
    print(f"Best GA raw fitness: {best_global_fitness_raw:.6f}")
    print(f"Run directory: {run_dir}")
    print(f"Best fitness: {best_validated['fitness']}")
    print(f"Best chromosome bitstring: {best_validated['bitstring']}")
    print(f"Generation metrics CSV: {generation_csv}")
    print(f"Final validation summary: {final_validation_path}")
    if args.run_sensitivity and sensitivity_rows:
        print(f"Sensitivity CSV: {sensitivity_csv}")
    elif args.run_sensitivity:
        print("Sensitivity CSV: not generated (no sensitivity rows were produced).")
    else:
        print("Sensitivity CSV: skipped (--no-run-sensitivity).")
    print(f"TensorBoard logdir: {tb_dir}")
    print(f"TensorBoard launch command: tensorboard --logdir \"{tb_dir}\"")
    print(f"TensorBoard URL: {tb_url}")
    print(f"Terminal output log: {terminal_output_path}")
    if tb_process is not None:
        print(f"TensorBoard PID: {tb_process.pid}")
    print(f"Total elapsed: {elapsed:.2f}s")
    print("=" * 88)


if __name__ == "__main__":
    main()

