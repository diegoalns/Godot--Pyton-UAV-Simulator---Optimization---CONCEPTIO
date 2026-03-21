# Experiment Folder Template

Use this template when creating a new `Experiments/ExN-*` folder.

## Naming

- Folder: `ExN-ShortPurpose` (example: `Ex3-Route-Policy-Comparison`)
- Main runner: `run_experiment.py` or a descriptive script name
- Optional analysis notebooks: `analysis_*.ipynb`

## Recommended Layout

```text
Experiments/ExN-ShortPurpose/
├── README.md                      # Purpose, assumptions, and commands
├── run_experiment.py              # Main experiment entry script
├── configs/
│   ├── default.json
│   └── sweep_*.json
├── adapters/                      # Optional evaluator adapters
├── outputs/                       # Optional fixed output root for this experiment
└── notes/                         # Optional design notes and validation notes
```

## Required Behavior

- Reuse existing simulation mode contract whenever possible:
  - `--eval-mode integrated`
  - `--eval-mode command`
  - `--eval-mode mock`
- Keep runtime logic in core simulator modules; experiment folders should orchestrate, not duplicate simulator internals.
- Write run artifacts under experiment-owned directories to avoid cross-experiment collisions.

## Minimum README for each experiment

Each experiment folder README should contain:
- Objective and hypothesis
- Entry command examples
- Parameter list and defaults
- Output files and how to interpret them
- Reproducibility notes (seed policy, workers, environment requirements)

## Output Policy

- Do not write experiment outputs to root `logs/` unless the output is specifically intended as a shared runtime log.
- Prefer per-run timestamped folders and include:
  - run configuration snapshot
  - per-replication metrics
  - aggregate summary metrics

## Integration Checklist

- [ ] Script supports at least one execution mode (`integrated`, `command`, or `mock`)
- [ ] Outputs are isolated under experiment folder
- [ ] Experiment README added/updated
- [ ] Top-level `README.md` and `ARCHITECTURE.md` references updated if this experiment adds a new orchestration pattern
