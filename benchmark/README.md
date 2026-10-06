# Benchmark suite

`python -m benchmark.runner` (or `casuality-benchmark` after `uv sync`) runs
the benchmark without coupling Agent-Casuality to any coding-agent vendor.

Modes are `offline`, `failure-injection`, `scenarios`, `experiment1`,
`experiment2`, `experiment3`, `baseline`, `opencode`, and `all`. `all` stays
offline unless you explicitly select `--provider fastino` for `experiment1`.
The `opencode` mode is the only one that executes a real coding agent; it is
never part of `all`, CI, or the default `pytest` suite.

## Running the benchmarks

Run these commands from the repository root after `uv sync`:

```powershell
# Five deterministic causal scenarios
uv run casuality-benchmark scenarios

# Failure-injection checks
uv run casuality-benchmark failure-injection

# Shared-state dependency recovery
uv run casuality-benchmark experiment2 --dependencies 100

# Experiment 1, offline and deterministic
uv run casuality-benchmark experiment1 --repetitions 3 --max-requests 24

# Experiment 3, offline parser/schema/decision execution
uv run casuality-benchmark experiment3

# Baseline status and reproducibility metadata
uv run casuality-benchmark baseline

# Run the complete offline suite
uv run casuality-benchmark all
```

The commands write JSON and Markdown artifacts to `benchmark/results/`.
`experiment1` records both the Agent-Casuality Shapley interaction and the
direct 2x2 comparison over the same `00`, `01`, `10`, and `11` replay cells.
`experiment3` records the original input, both interventions, parser result,
schema result, decision result, and failure classification for all 20 cases.
The baseline command does not invent measurements when the historical Phase 2
executable is unavailable.

### Optional Fastino execution

Fastino is opt-in and requires `FASTINO_API_KEY`, `FASTINO_MODEL`, and optionally
`FASTINO_BASE_URL`. The repository also supports the existing `FASTINO_LABS_*`
aliases. Keep external runs separate from the official offline artifacts:

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$output = "benchmark/results/fastino-validation-$stamp"
New-Item -ItemType Directory -Path $output | Out-Null

uv run casuality-benchmark experiment1 `
	--provider fastino `
	--model "fastino/GLiNER-2.5-Decide" `
	--repetitions 1 `
	--max-requests 8 `
	--results-dir $output `
	--cache "$output/model-cache.jsonl"
```

Use `--dry-run` to inspect the request plan without making uncached provider
requests. Cache keys include provider, model, messages, temperature, seed, and
generation parameters. A provider error does not silently fall back to offline
results.

Ground truth is canonical JSON under `benchmark/ground_truth/`; Python loads it
instead of duplicating expected slices in assertions. The historical customer
fixture remains its own canonical ground truth at `fixture/fixture.json`.

### Real OpenCode coding-agent benchmark

The `opencode` mode measures Agent-Casuality on live OpenCode executions
through the validated `.opencode/plugins/agent-casuality.ts` integration. It
scores capture completeness and diagnosis quality separately across five
small tasks: `stale_research`, `conflicting_review`, `failed_test_retry`,
`subagent_disagreement`, and `shared_state_contamination`. Task definitions
are single-source-of-truth JSON under `benchmark/opencode/ground_truth/`;
the harness (`benchmark/opencode/`) only loads and executes them.

Flow per task run: setup workdir → start ingest receiver → real
`opencode run` → persisted SQLite trace → causal graph →
slice/provenance/interaction/why → scoring. No payload contents or secrets
are stored in the artifacts.

```powershell
# Full suite: 5 tasks x 1 run (takes ~15-30 minutes, requires OpenCode + a model)
uv run casuality-benchmark opencode --timeout 420

# Single task, e.g. for a quick smoke of the harness
uv run casuality-benchmark opencode --task failed_test_retry --timeout 300

# Repeat runs, custom binary / output / receiver / model / timeout
uv run casuality-benchmark opencode `
  --task stale_research --task failed_test_retry `
  --runs 2 --timeout 300 `
  --opencode-bin "C:/path/to/opencode.exe" `
  --output-dir benchmark/results/opencode `
  --model "opencode/muse-spark-1.3-contributor-free"
```

Options: `--task` (repeatable, default all five), `--runs` (runs per task),
`--timeout` (seconds per run), `--opencode-bin` (default auto-detect),
`--output-dir` (default `benchmark/results/opencode`), `--ingest-url`
(use an existing receiver instead of starting an ephemeral one per run),
`--model` (passed as `opencode run -m`; recorded from the trace otherwise).

Artifacts: `benchmark/results/opencode/opencode.json` (per-run + aggregate
results) and `opencode.md` (methodology, version, task descriptions,
capture/diagnosis results, failures, limitations). Per-run SQLite traces
live under `<output-dir>/runs/<run-id>/trace.db` and are git-ignored;
`opencode.json` records each trace location plus run ID, OpenCode version,
model/provider, workdir, timestamps, and ground-truth version.

Reading the results: capture is minimum expected event-class coverage
(captured / expected minimum; NOT general precision/recall), averaged only
over event classes OpenCode actually exposes (terminal `completion` events
are documented as unavailable in `run` mode, not penalized). Both the
micro-average (all runs) and the macro-average (mean of per-task means) are
reported so repeated runs of one scenario cannot dominate silently.
Diagnosis is reported per dimension with no single opaque score.
`minimal_slice` is a required-cause preservation proxy (ddmin with a
ground-truth membership predicate), NOT causal minimality (not measurable:
live traces carry no DecisionContract or observable failure predicate).
`interaction` is joint-branch ancestry detection (both branches ancestors of
the failure), NOT causal interaction (unsupported: no counterfactual
intervention from live traces). Explanation grounding requires
summary-level event-ID citation; package presence alone does not pass. A run
whose agent skips the injected actions (e.g. refusing the unsafe
`shared_state_contamination` override) shows unresolved roles and fallback
failure resolution, which is agent deviation — not a benchmark pass and not
an adapter or engine failure — and is listed under "Failures / missing
data" with diagnosis means reported both measured-only and all-runs.

Offline coverage without OpenCode: `tests/test_opencode_benchmark.py`
replays hand-recorded traces from `benchmark/opencode/recorded/` through
the real mapper and scorer, so `uv run pytest -q` stays hermetic.

Artifacts contain exact slice-link metrics (precision, recall, exact match),
interaction TP/FP/FN and false-interaction rate, provenance links, and slice
reduction. A `met` field means that particular executed result crossed its
documented target; `not_evaluated` means no claim is made. Cache entries include
provider, model, message payload, temperature, seed, and maximum-token setting.
