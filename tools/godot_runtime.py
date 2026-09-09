"""
Shared Godot executable resolution for this repository.

Single source of truth used by:
- godot.sh (via --print-exe)
- Experiments/Ex1-ShtPath-GA/GA-Experiment1.py
- Experiments/Ex0-Baseline/GA-Experiment1.py
- Experiments/Ex0-Baseline/Baseline *.py runners

Resolution for the "auto" sentinel, in order:
1. Project-local binary at the repository root
2. Project-local binary under tools/godot/
3. PATH commands (godot4, godot)
4. Common per-user download/document folders

Diagnostics go to stderr so callers can capture the resolved path from stdout.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

# Engine version targeted by project.godot config/features.
EXPECTED_GODOT_VERSION = "4.3"

# Value of --godot-exe that triggers automatic resolution.
AUTO_SENTINEL = "auto"

# Directories searched for a project-local engine binary, relative to the repo root.
SEARCH_DIRS: Tuple[Path, ...] = (Path("."), Path("tools") / "godot")

# Archive extensions that must never be treated as an engine binary.
_ARCHIVE_SUFFIXES = frozenset({".zip", ".gz", ".bz2", ".xz", ".7z", ".tar", ".tmp"})


def repo_root() -> Path:
    """Repository root, derived from this file's location (tools/godot_runtime.py)."""
    return Path(__file__).resolve().parents[1]


def _warn(message: str) -> None:
    print(message, file=sys.stderr)


def _local_patterns() -> Tuple[str, ...]:
    """Glob patterns for a project-local engine binary on the current platform."""
    if sys.platform.startswith("win"):
        return ("Godot_v*_console.exe", "Godot*_console.exe", "Godot*.exe")
    if sys.platform == "darwin":
        return ("Godot*.app/Contents/MacOS/Godot", "Godot*.universal", "Godot*.arm64")
    return ("Godot_v*_linux.x86_64", "Godot*_linux.x86_64", "Godot*.x86_64")


def _is_candidate_binary(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() not in _ARCHIVE_SUFFIXES


def project_local_godot() -> Optional[str]:
    """
    Locate an engine binary committed-adjacent to the project (gitignored per machine).

    Returns the highest lexical executable match, or None when nothing is present.
    Raises PermissionError when a matching binary exists but lacks the execute bit,
    since silently skipping it produces a misleading "not found" error later.
    """
    found: List[Path] = []
    for relative_dir in SEARCH_DIRS:
        folder = (repo_root() / relative_dir).resolve()
        if not folder.is_dir():
            continue
        for pattern in _local_patterns():
            for match in sorted(folder.glob(pattern)):
                if _is_candidate_binary(match):
                    found.append(match.resolve())

    if not found:
        return None

    unique = sorted(set(found))
    executable = [p for p in unique if os.access(p, os.X_OK)]
    if executable:
        return str(executable[-1])

    blocked = unique[-1]
    raise PermissionError(
        f"Found a project-local Godot binary that is not executable: {blocked}\n"
        f'Fix it with: chmod +x "{blocked}"'
    )


def resolve_godot_executable(godot_exe_arg: str) -> str:
    """
    Resolve a usable Godot executable path.

    Supports:
    - "auto" sentinel (project-local binary, then PATH, then per-user folders)
    - Direct executable path
    - PATH command names (e.g. godot4)
    - Directory path containing Godot binaries
    - Windows extracted folder named like '*.exe' containing the real .exe inside
    """
    raw = (godot_exe_arg or "").strip().strip('"')
    if not raw:
        raise ValueError("Empty --godot-exe value.")

    if raw.lower() == AUTO_SENTINEL:
        local_hit = project_local_godot()
        if local_hit:
            return local_hit
        auto_hit = auto_detect_godot_executable()
        if auto_hit:
            return auto_hit
        searched = ", ".join(str(repo_root() / d) for d in SEARCH_DIRS)
        raise FileNotFoundError(
            "Could not resolve a Godot executable automatically. "
            f"Searched project-local locations ({searched}), PATH (godot4, godot), "
            "and common per-user download/document folders. "
            f"Place a Godot {EXPECTED_GODOT_VERSION} binary at the repository root "
            "or pass an explicit --godot-exe path."
        )

    candidate_path = Path(raw).expanduser()

    # 1) Existing file path.
    if candidate_path.exists() and candidate_path.is_file():
        resolved = candidate_path.resolve()
        if os.name != "nt" and not os.access(resolved, os.X_OK):
            raise PermissionError(
                f"Godot executable is not executable: {resolved}\n"
                f'Fix it with: chmod +x "{resolved}"'
            )
        return str(resolved)

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
        for pattern in ("*_console.exe", "Godot*.exe", "*.exe") + _local_patterns():
            matches = sorted(folder.glob(pattern))
            for m in matches:
                if _is_candidate_binary(m):
                    return str(m.resolve())

    # 3) Command on PATH.
    from_path = shutil.which(raw)
    if from_path:
        return str(Path(from_path).resolve())

    raise FileNotFoundError(
        "Could not resolve Godot executable from --godot-exe. "
        f"Provided value: '{godot_exe_arg}'. "
        "Pass a real executable path, a directory containing the executable, "
        f"a command available on PATH, or '{AUTO_SENTINEL}' for automatic resolution."
    )


def auto_detect_godot_executable() -> Optional[str]:
    """
    Try to auto-detect Godot executable in common local locations.
    """
    # Project-local binary wins over anything installed system-wide.
    try:
        local_hit = project_local_godot()
    except PermissionError as exc:
        _warn(f"WARNING: {exc}")
        local_hit = None
    if local_hit:
        return local_hit

    # PATH next.
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
        # - <root>/Godot_vX.Y-stable_linux.x86_64 (Linux)
        patterns = [
            "Godot*.exe",
            "Godot*.exe/Godot*.exe",
            "Godot*/Godot*.exe",
            "Godot*_linux.x86_64",
            "Godot*/Godot*_linux.x86_64",
        ]
        for pattern in patterns:
            for match in root.glob(pattern):
                if _is_candidate_binary(match):
                    candidates.append(match.resolve())

    if not candidates:
        return None

    # Prefer console exe for better logs, otherwise highest lexical match.
    candidates = sorted(set(candidates))
    console_hits = [p for p in candidates if p.name.endswith("_console.exe")]
    if console_hits:
        return str(console_hits[-1])
    return str(candidates[-1])


def verify_godot_version(
    godot_exe: str,
    expected: str = EXPECTED_GODOT_VERSION,
) -> Optional[str]:
    """
    Run `<godot_exe> --version` and warn when it does not match the project target.

    Never raises and never blocks a run: a version mismatch is usable but risky,
    because opening the project with a newer engine triggers project conversion.
    Returns the reported version string, or None when it could not be determined.
    """
    try:
        proc = subprocess.run(
            [godot_exe, "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except Exception as exc:
        _warn(f"WARNING: Could not run '{godot_exe} --version': {exc}")
        return None

    combined = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    reported = ""
    for line in combined.splitlines():
        stripped = line.strip()
        if stripped and stripped[0].isdigit():
            reported = stripped
            break

    if not reported:
        _warn(f"WARNING: Could not parse a Godot version from '{godot_exe} --version'.")
        return None

    if not reported.startswith(expected):
        _warn(
            f"WARNING: Godot version mismatch. project.godot targets {expected}, "
            f"but '{godot_exe}' reports '{reported}'. "
            "Opening the project with a newer engine may trigger project conversion."
        )
    return reported


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve the Godot executable used by this project.",
    )
    parser.add_argument(
        "--godot-exe",
        type=str,
        default=AUTO_SENTINEL,
        help=f"Explicit path, directory, PATH command, or '{AUTO_SENTINEL}'.",
    )
    parser.add_argument(
        "--print-exe",
        action="store_true",
        help="Print the resolved executable path to stdout (default action).",
    )
    parser.add_argument(
        "--verify-version",
        action="store_true",
        help=f"Warn on stderr when the binary does not report {EXPECTED_GODOT_VERSION}.",
    )
    args = parser.parse_args(argv)

    try:
        resolved = resolve_godot_executable(args.godot_exe)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        _warn(f"ERROR: {exc}")
        return 1

    if args.verify_version:
        verify_godot_version(resolved)

    print(resolved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
