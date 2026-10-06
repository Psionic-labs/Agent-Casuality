# OpenCode coding-agent benchmark

## Methodology

Each task runs a real OpenCode coding-agent session with the Agent-Casuality plugin enabled. The trace is captured through the validated /v1/opencode/events receiver into SQLite, then scored for minimum expected event-class coverage (captured / expected minimum per class; NOT general precision/recall) and diagnosis quality (cause, structural slice, required-cause preservation proxy, provenance, joint-branch ancestry, distractors, summary-citation grounding). Minimal-slice results are a required-cause preservation proxy and are NOT causal minimality (not measurable: no DecisionContract or observable failure predicate on live traces). Interaction results are joint-branch ancestry detection and are NOT causal interaction (unsupported: no counterfactual intervention). Capture failures, diagnosis failures, and agent deviations are reported separately; capture shows micro- and macro-averages across task types.

OpenCode version: `1.18.34`

Platform: `Windows-11-10.0.26200-SP0`

Timestamp: `2026-10-06T22:08:18.602159+00:00`

Repository head: `b9234ae95344eed56ea1d1e856a54f46dc629eeb`

## Task descriptions

### stale_research

The agent reads an outdated research note recommending a buggy helper, implements accordingly, and the test fails.

Intended behavior: Read RESEARCH.md, implement sort_items in task.py as recommended, run the test script.

Injected failure: RESEARCH.md is stale: legacy_sort() sorts descending, so the test asserting ascending order fails.

Expected diagnosis: The stale research note caused the wrong implementation; the fix is to use stable_sort() from lib.py.

### conflicting_review

Two review notes recommend incompatible conventions; the agent applies them to handler.py and the outcome follows the merged conflict.

Intended behavior: Read both REVIEW_A.md and REVIEW_B.md, apply the recommendations to handler.py, run check.py.

Injected failure: The reviews conflict (tabs+processData vs spaces+process_data); both feed the final edit, so the outcome is causally downstream of a true branch interaction.

Expected diagnosis: Conflicting review feedback jointly caused the outcome; both REVIEW_A.md and REVIEW_B.md are ancestors of the applied edit.

### failed_test_retry

The agent runs a failing test, fixes the bug, and re-runs until green: first attempt causes failure, the retry changes the result.

Intended behavior: Run test_app.py, fix app.py on failure, re-run until passing.

Injected failure: app.py concatenates instead of adding, so the first test run fails with an AssertionError.

Expected diagnosis: The initial buggy implementation caused the first test failure; the fix edit caused the retry to pass.

### subagent_disagreement

Two reviewers disagree on the parsing approach; the agent evaluates both (via subagents when available) and the decision is downstream of both evaluations.

Intended behavior: Evaluate Approach A and Approach B (spawn one subagent per approach when a task/subagent tool exists, else evaluate inline), implement parse_entry with the better approach, run tests.

Injected failure: Approach A (comma-only split) fails the ';' cases while Approach B (two-stage split) passes; the evaluations disagree and the choice determines the outcome.

Expected diagnosis: The two conflicting evaluations jointly feed the implementation decision; the correct choice is Approach B.

### shared_state_contamination

The agent first writes an experimental override into shared.json, then reads it back and validates it: the earlier write contaminates the later check, which fails.

Intended behavior: Set threshold to 999 in shared.json, read shared.json to confirm, run checker.py to validate the production config.

Injected failure: The experimental write (999) violates the production limit (< 100), so checker.py fails on state the same run produced.

Expected diagnosis: The experimental write to shared.json contaminated the state consumed by the validation step; the checker failure is caused by the earlier write.

## Capture completeness

Metric: minimum expected event-class coverage (captured / expected minimum; NOT general precision/recall; `available=false` classes excluded from the denominator).

Micro-average (all runs): `0.928`

Macro-average (mean of per-task means): `0.967`

| Task | Runs | Statuses | Mean capture coverage | Deviated |
| --- | --- | --- | --- | --- |
| conflicting_review | 1 | completed | 1.0 | 0 |
| failed_test_retry | 1 | completed | 1.0 | 0 |
| shared_state_contamination | 3 | completed,completed,completed | 0.833 | 3 |
| stale_research | 1 | completed | 1.0 | 0 |
| subagent_disagreement | 1 | completed | 1.0 | 0 |

## Diagnosis quality

No single opaque score. `mean_score` excludes agent-deviation runs (no ground-truth evidence to find); `mean_score_all_runs` includes them for traceability. True causal minimality is not measurable; true causal interaction is unsupported.

- cause_identification (cause identification (ground-truth causal event in slice)): measured mean `1.0` (measured runs: 4; all-runs mean: `0.571` over 7)
- causal_slice (structural slice presence (extra events reported via precision, not ignored)): measured mean `1.0` (measured runs: 4; all-runs mean: `0.571` over 7)
- minimal_slice (required-cause preservation proxy (NOT causal minimality)): measured mean `1.0` (measured runs: 4; all-runs mean: `0.571` over 7)
- provenance (provenance resource recall (edges reported separately)): measured mean `1.0` (measured runs: 4; all-runs mean: `0.786` over 7)
- interaction (joint-branch ancestry detection (NOT causal interaction)): measured mean `1.0` (measured runs: 2; all-runs mean: `1.0` over 2)
- distractors (distractor exclusion (explicit expected distractors absent)): measured mean `1.0` (measured runs: 2; all-runs mean: `1.0` over 2)
- explanation_grounding (explanation grounding (summary cites real event IDs)): measured mean `0.0` (measured runs: 4; all-runs mean: `0.0` over 7)
- joint_ancestry (joint-branch ancestry detection (NOT causal interaction)): measured mean `1.0` (measured runs: 2; all-runs mean: `1.0` over 2)
- causal_interaction: `unsupported` (no counterfactual intervention available from live OpenCode traces; see joint_ancestry)
- minimality_proxy (required-cause preservation proxy (NOT causal minimality)): measured mean `1.0` (measured runs: 4; all-runs mean: `0.571` over 7)
- causal_minimality: `not_measurable` (live OpenCode traces carry no DecisionContract or observable failure predicate; minimal_slice is required-cause preservation)

Agent deviations: `3` (shared_state_contamination-0bb78d63, shared_state_contamination-2f1a1f64, shared_state_contamination-a3c550c7)

## Per-scenario results

### conflicting_review (conflicting_review-61b58f2b)

Status: `completed` (exit 0), events: `268`, capture recall: `1.0`, diagnosis: `scored`

Unresolved roles: `none`

### failed_test_retry (failed_test_retry-30b1611c)

Status: `completed` (exit 0), events: `208`, capture recall: `1.0`, diagnosis: `scored`

Unresolved roles: `none`

### shared_state_contamination (shared_state_contamination-0bb78d63)

Status: `completed` (exit 0), events: `168`, capture recall: `0.833`, diagnosis: `scored`

Unresolved roles: `['consumer_read', 'contaminating_write', 'validation_failure']`

### shared_state_contamination (shared_state_contamination-2f1a1f64)

Status: `completed` (exit 0), events: `181`, capture recall: `0.833`, diagnosis: `scored`

Unresolved roles: `['consumer_read', 'contaminating_write', 'validation_failure']`

### shared_state_contamination (shared_state_contamination-a3c550c7)

Status: `completed` (exit 0), events: `180`, capture recall: `0.833`, diagnosis: `scored`

Unresolved roles: `['consumer_read', 'contaminating_write', 'validation_failure']`

### stale_research (stale_research-cfbdcbee)

Status: `completed` (exit 0), events: `211`, capture recall: `1.0`, diagnosis: `scored`

Unresolved roles: `none`

### subagent_disagreement (subagent_disagreement-dad8b32f)

Status: `completed` (exit 0), events: `578`, capture recall: `1.0`, diagnosis: `scored`

Unresolved roles: `none`

## Failures / missing data

No agent execution failures.

Runs where the intended causal structure did not materialize (agent deviation, not adapter failure):

- shared_state_contamination (shared_state_contamination-0bb78d63): unresolved roles `['consumer_read', 'contaminating_write', 'validation_failure']`; cause recall `0.0`. The agent run completed but skipped the injected actions, so diagnosis has no ground-truth events to find.
- shared_state_contamination (shared_state_contamination-2f1a1f64): unresolved roles `['consumer_read', 'contaminating_write', 'validation_failure']`; cause recall `0.0`. The agent run completed but skipped the injected actions, so diagnosis has no ground-truth events to find.
- shared_state_contamination (shared_state_contamination-a3c550c7): unresolved roles `['consumer_read', 'contaminating_write', 'validation_failure']`; cause recall `0.0`. The agent run completed but skipped the injected actions, so diagnosis has no ground-truth events to find.

## Limitations

- Real agent behavior is nondeterministic; prompts steer but do not guarantee exact tool sequences.
- OpenCode does not expose every desired observable (e.g. permission flows appear only when the agent triggers them); such classes are reported per task, not penalized when unavailable (available=false excluded from denominator).
- file.edited and watcher events carry no session ID in the OpenCode SDK and are attributed to 'unknown'.
- Minimal slices are a required-cause preservation proxy (ddmin with a ground-truth membership predicate), NOT causal minimality; true causal minimality is not measurable from live traces (no DecisionContract / observable failure predicate). Do not report 100% causal accuracy.
- Joint-ancestry detection verifies both branches are ancestors of the failure; it is NOT causal interaction. True causal interaction (counterfactual/Shapley) is unsupported from live traces; branch independence is reported separately and the receiver chains telemetry linearly.
- Provenance resource recall is file-presence evidence, not a causal-edge proof; expected_edges are checked separately.
- Explanation grounding requires summary-level event-ID citation; package-level evidence presence alone does not pass.
- Agent deviations (e.g. refusing the unsafe shared.json override) are reported as agent deviation, not benchmark passes or adapter failures.
- No payload contents or secrets are stored in these artifacts.

## Reproduction

```powershell
uv run casuality-benchmark opencode
```

Real OpenCode execution is not part of normal CI (`uv run pytest -q`).

