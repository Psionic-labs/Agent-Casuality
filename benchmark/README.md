# Benchmark suite

`python -m benchmark.runner` (or `casuality-benchmark` after `uv sync`) runs
the benchmark without coupling Agent-Casuality to any coding-agent vendor.

Modes are `offline`, `failure-injection`, `scenarios`, `experiment1`,
`experiment2`, `experiment3`, `baseline`, and `all`. `all` stays offline unless
you explicitly select `--provider fastino` for `experiment1`.

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

Artifacts contain exact slice-link metrics (precision, recall, exact match),
interaction TP/FP/FN and false-interaction rate, provenance links, and slice
reduction. A `met` field means that particular executed result crossed its
documented target; `not_evaluated` means no claim is made. Cache entries include
provider, model, message payload, temperature, seed, and maximum-token setting.
