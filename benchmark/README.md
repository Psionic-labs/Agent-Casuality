# Benchmark suite

`python -m benchmark.runner` (or `casuality-benchmark` after `uv sync`) runs
the benchmark without coupling Agent-Casuality to any coding-agent vendor.

Modes are `offline`, `failure-injection`, `scenarios`, `experiment1`,
`experiment2`, `experiment3`, `baseline`, and `all`. `all` stays offline unless
you explicitly select `--provider fastino` for `experiment1`.

Ground truth is canonical JSON under `benchmark/ground_truth/`; Python loads it
instead of duplicating expected slices in assertions. The historical customer
fixture remains its own canonical ground truth at `fixture/fixture.json`.

Artifacts contain exact slice-link metrics (precision, recall, exact match),
interaction TP/FP/FN and false-interaction rate, provenance links, and slice
reduction. A `met` field means that particular executed result crossed its
documented target; `not_evaluated` means no claim is made. Cache entries include
provider, model, message payload, temperature, seed, and maximum-token setting.
