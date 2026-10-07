# Visual DAG Explorer — Design Document

A record of every significant design decision behind the Agent-Casuality
Visual DAG Explorer: **what** was built and **why**, plus ideas deliberately
left out that a future redesign could pick up. Intended audience: anyone
(Claude included) asked to produce new designs for this UI.

## 1. Purpose

The explorer answers one question first:

> **Why did this agent fail?**

Everything else — DAG, inspector, provenance, metrics — exists to support
that answer, in that priority order:

1. Failure diagnosis
2. Causal DAG
3. Event inspector
4. Evidence / provenance
5. Detailed metrics

**Why:** the original UI read as an internal debugging dump. Debugging a
coding agent always starts from the failure and works backward along the
causal path, so the layout follows that workflow top-to-bottom.

## 2. Architecture (read-only by design)

- Backend: `explorer/` package — stdlib only, zero dependencies. It loads
  events (bundled demo trace via the real `OpenCodeEventMapper`, or a live
  SQLite file via `SQLiteEventStore`) and reuses existing analysis functions
  (`structural_slice`, `score_diagnosis`, `build_evidence_package`).
- It serves **five JSON endpoints** (`/api/overview|failure|diagnosis|
  event|evidence`) plus the static frontend. Nothing is ever written.
- Frontend: Next.js (TypeScript, App Router) with `output: 'export'`.
  `npm run build` emits plain HTML/CSS/JS into `frontend/out/`, which the
  Python backend serves at `/` — no Node server in production, and
  `python -m explorer.server` remains the single run command. The only
  backend touch is `FRONTEND_DIR` pointing at `frontend/out`; the five
  endpoints are byte-for-byte unchanged.
- Pure logic lives in framework-free `lib/` modules (`store`,
  `use-selection`, `viewport`, `render`, `timeline`, `filter`, `api`) with
  explicit `.ts` relative imports, so the
  same files load in Next.js and directly under `node --test`.

**Why:** the explorer must never be able to corrupt a trace or diverge from
benchmark scoring. Reusing the exact mapper and scoring functions guarantees
the DAG shows precisely what capture produced and what the benchmark
measured. Static export keeps the deployed artifact dependency-free and
reviewable, while TypeScript + React make the Graph/Timeline dual view
maintainable. (This section replaces the former vanilla-JS stack by explicit
team decision — see §14.)

## 3. Layout

```
Header bar (source · counts · status pill)
"Why did it fail?" strip (lede + causal-path chips + technical details)
Two-column grid:  [ large causal DAG (+ timeline) ] [ event inspector ]
Tab bar + panels: Causal chain · Provenance · Interaction · Evidence · Metrics
```

**Why:** diagnosis and DAG must fit together in one desktop viewport with
minimal scrolling. The two-column grid gives the DAG most of the visual
space (it is the main focus) while keeping the inspector one click away.
Research detail lives behind tabs/collapsibles, never in the first viewport.
Both columns share one height budget (46vh, min 300px): the inspector
scrolls internally rather than stretching the grid row, so the tab bar
always sits directly under the views instead of dropping into dead space
below a long inspector dump.

## 4. Diagnosis section

- A one-sentence **lede**: the first sentence of the backend evidence
  summary — human-readable, e.g. "The first test failed after app.py was
  modified."
- A **causal path** of role-name chips in causal order
  (`first_test_failure → fix_edit → retry_success`), each clickable to
  select the event.
- Without ground-truth roles (live traces): a slice-size note plus
  first/last slice labels instead of a fake path.
- The verbatim backend summary sits collapsed under "Full technical
  explanation".

**Why:** lead with a human sentence, keep the machine evidence one click
away. Role names (not raw IDs) make the path readable; chips keep it
navigable. Never invent causes — every word comes from the API.

## 5. Causal DAG

- Nodes = events, edges = declared `causal_parent_ids` only. The frontend
  performs **no causal inference**; layout uses depth (longest ancestor
  chain) for vertical lanes and logical sequence for horizontal order.
- Selection model: a **single shared `selectedEventId`** store drives DAG,
  timeline, and inspector — no divergent selection states. React subscribes
  through `useSyncExternalStore` (with a null server snapshot for the
  prerendered shell), so the store stays framework-free and unit-testable.
- Highlight: failure node red, slice ancestors gold, terminal (`run_finish`)
  dashed green ring, unrelated nodes dimmed; selected node's ancestor set
  is computed by walking real edges only.
- Viewport: fit-all on load (bounds padded for labels), Reset restores fit,
  drag-to-pan, cursor-anchored scroll zoom (0.2–10x). A 6px movement
  threshold separates drags from clicks so panning never selects nodes.
- Pure helpers (`lib/viewport.ts`, `lib/render.ts`, `lib/timeline.ts`,
  `lib/filter.ts`) hold all math/class/filter logic so behavior is
  unit-testable without a DOM.
- Node clicks must reach the store: `DagView` never calls
  `setPointerCapture` (capturing the pointer to the `<svg>` retargets the
  click to the svg and node `onClick` never fires — this was a real bug).
  Pan tracks move/up on the window instead. Locked by a contract test.

**Why:** a debugging graph must be trustworthy (only backend-declared
edges), explorable (pan/zoom/fit), and unambiguous (one selection
everywhere). Testability without a browser keeps the zero-dependency rule.

## 6. Event inspector

Structured rows, never raw JSON by default:

- For `tool_call`/`tool_result`: prominent **Command hero** (monospace) and
  **Result hero** (status pill + scrollable output). Command falls back to a
  correlated parent/child record, labeled `Source: type · tool`.
- Then: Tool, Result/status, Output/error, File/resource, Call ID,
  Agent/model, Sequence, Timestamp, Session, Parents, Children.
- Missing values render as `—`. Status is only read from explicit
  `exitCode`/`exit_code`/`status` fields — **never inferred from text**.
  Long IDs truncate with ellipsis + copy button + tooltip.
- Full stored record stays collapsed in `<details> Raw event`.

**Why:** in a coding-agent debugger the command and its output are the
payload 90% of the time, so they get hero treatment. Explicit sourcing and
`—` placeholders keep correlated data honest.

## 7. Status language

- Pill reads **"Resolved"** (green, selector matched) or **"Fallback
  target"** (amber, last-event fallback) — never "failure resolved".
- Info lines use "Failure status: …". Capability flags (`not_measurable`,
  `unsupported`) render as neutral grey pills, never error-styled.

**Why:** "resolved" must not imply the failure was fixed — only that the
diagnosis target was found. Neutral styling prevents capability limits from
looking like system errors.

## 8. Terminology constraints (non-negotiable)

These distinctions must survive any redesign:

- `joint ancestry` ≠ causal interaction
- `required-cause preservation proxy` ≠ causal minimality
- `unsupported` ≠ failed; `not measurable` ≠ failed
- structural slice = declared-dependency evidence; influence not proven

**Why:** they encode real methodological limits of the benchmark (no
counterfactuals on live traces). The UI repeats the exact backend
`metric`/`label` strings so wording cannot drift.

## 9. Tabs

Causal chain (slice in order, capped at 80 rows). The other four lead with
**trace facts** — ground-truth-free bodies built only from capture facts —
and keep benchmark scoring collapsed:
- Provenance: expected-resource chains (when ground truth names them) plus
  a "Discovered in this trace" section for resources named in recorded
  capture metadata that no ground truth expected; graded entries and
  expected edges stay collapsed. Honest "no graded provenance" note when
  the evidence package has none.
- Interaction: recorded fan-out/fan-in (branch/merge points from declared
  edges, clickable), with a linear-chain note when there is none; joint
  ancestry and the unsupported-interaction flag stay under "Benchmark
  scoring". Edge shape only — never called causal interaction.
- Evidence: the run's tool story (slice tool calls/results in order with
  recorded commands, click to inspect); the backend summary and grounding
  stay under "Backend evidence summary".
- Metrics: a capture census (dataset/slice counts plus per-type slice
  counts); the metric summary list and raw dimensions stay under
  "Benchmark scoring".

Pure logic lives in `lib/tracefacts.ts` (`sliceNodes`, `branchPoints`,
`mergePoints`, `traceCensus`, `resourcesInDetails`, `nodesForResource`,
`toolStory`) with `node:test` coverage in `tests/tracefacts.test.ts`.
Command borrowing follows declared parents only (a result borrows its
call's command; borrowing downhill from children would misattribute).
Detail fetching reuses the shared `fetchEventDetail` cache with the same
150-cap + truncation note as before.

**Why:** benchmark scorecards compare against ground truth, which live
traces don't have — so those tabs read empty. Trace facts (what ran, what
branched, what files were touched, in what counts) need no answer key.
Provenance chains are built only from slice events referencing the
resource via capture metadata — no invented edges.

## 10. Event-sequence minimap

A minimap strip under the Timeline view (see §14) with a legend
(normal / in failure slice / failure target / terminal / selected) and a
viewport rectangle showing the current pan/zoom window. Segments are
clickable and set the shared selection; the strip shares the selection
store and class helpers with the DAG.

**Why:** position-in-sequence context for long linear traces; shared state
makes sync automatic rather than wired. The rectangle answers "where am I"
once the timeline is zoomed into a 900+ event trace.

## 11. Demo dataset

The bundled `failed_test_retry` trace (10 envelopes: test fails →
`app.py` edited → retry passes) loads by default; verified byte-identical
to the benchmark's recorded trace.

**Known limits:** it is a **linear chain** (no branching), its evidence
package has **no field-level provenance grades**, and its `tool_result`
payloads carry **no exit codes** (status shows `—`). The UI states these
instead of hiding them. Real branching exists only in the live
`.casuality/opencode.db` (viewable via `--db`).

## 12. Validation contract

- `npm test` (node:test, zero test dependencies): contract checks (IDs,
  endpoints, demo shape, pointer-capture ban, shared legend, trace-fact tab
  bodies) + unit tests
  for selection, viewport, render, inspector, timeline, filter, and tracefacts — all in
  TypeScript, run directly by Node's type stripping.
- `npx tsc --noEmit` (strict) and `npm run build` (static export) must pass.
- `uv run ruff check .`, `uv run ty check .`, `uv run pytest -q`
  (194 passed, 1 postgres skip).
- Live-server smoke: static 200s (including `/_next/*` assets with correct
  MIME), demo slice/diagnosis/provenance values, live 1625-event overview.

## 13. Ideas for a future redesign (not yet built)

Worth considering, in rough priority order (done items stay listed with
their § reference so nobody rebuilds them):

- **Run selector**: ~~pick `run_id`/session when a DB holds many runs~~ —
  DONE as the session picker (§14.3).
- **Branching demo**: bundle a recorded trace with real fan-out/merge so
  the DAG demonstrates `Branch A ─┐ ├──→ merge → failure` instead of a
  line. (Requires capturing such a trace; never synthesize one.)
- **SVG virtualization / canvas renderer**: the 1625-node live DAG still
  mounts every node (only the timeline clips are culled); cap, window, or
  switch renderers.
- **Chain-tab pagination**: beyond the 80-row cap, page instead of
  truncating.
- **Failure-target picker**: let the user override the fallback target
  (explicitly labeled as manual, not ground truth).
- **Diff view for file edits**: render before/after payloads of `edit`
  events side by side.
- **Search/filter**: ~~by event type, tool, role, resource, or free text,
  with non-matching nodes dimmed~~ — PARTLY DONE: event-type filter with
  per-type chips + session picker (§14.2, §14.3). Still open: tool, role,
  resource, and free-text search.
- **Export**: download the evidence package / diagnosis JSON from the UI.
- **Light theme + density toggle** for screenshots vs. deep debugging.
- **Deep links**: URL hash carrying dataset + selected event for sharing.
- **Multi-failure support**: the model assumes one failure target; runs
  with several failures need a target switcher.
- **WebSocket/live tail**: stream new events as the agent runs (backend
  work; keep the read-only contract).
- **Accessibility pass**: focus states ~~and ARIA live regions for
  selection~~ (live region DONE — `role="status"` announces selection;
  2px accent focus rings DONE per §14.1), remaining: sufficient-contrast
  audit of the dimmed states.

Constraints any redesign must keep: read-only backend, zero invented
causality, exact honesty vocabulary from §8, demo byte-identical.

## 14. Timeline view

A Premiere-style alternative to the DAG in the same panel, toggled by
"Graph | Timeline" (default stays Graph). Horizontal sequence, stacked
lanes; both views share the selection, inspector, and highlight classes.
- **Lanes:** run (`run_start`, `run_finish`), model (`model_call`),
  context (`context_update`), then one lane per tool name in order of first
  appearance, then `other`. Tool names are resolved from recorded
  `/api/event` details (cached, never guessed): a tool event with no recorded
  tool lands in `other` rather than an invented lane. Lane headers are
  monospace, sticky on the left.
- **Clips:** one `<button>` per event, positioned by sequence index — never
  wall-clock time (demo timestamps are synthetic). Below a width threshold
  only the sequence number shows. States reuse the DAG vocabulary: failure
  target red, slice ancestors gold, normal blue-grey, `run_finish` dashed
  green outline, selected white outline, unrelated dimmed.
- **Ruler + playhead:** sequence numbers across the top (selected
  highlighted); dragging the ruler scrubs the shared selection. A blue
  vertical line and knob mark the selected event.
- **Edges:** a single SVG overlay path (`vector-effect:
  non-scaling-stroke`) drawn only for the selected event's ancestor chain,
  walked from declared `causal_parent_ids`. No parents → no lines.
- **Minimap:** the §10 strip under the clips, with the viewport rectangle
  and clickable segments.
- **Zoom/pan:** cursor-anchored scroll zoom (0.2–10x, same clamp as the
  DAG), drag-to-pan with the 6px drag-vs-click threshold, Reset restores
  fit-all.
- **Keyboard:** Left/Right step through sequence order (clamped at both
  ends), Enter activates the focused clip natively, an ARIA live region
  announces each selection.
- **Large traces:** only clips intersecting the visible window mount (plus
  one clip of margin); the 1625-event live trace renders a ~15-clip slice.

### 14.1 Visual tokens (whole UI, not just Timeline)

One flat dev-tool palette, applied to Graph, inspector, tabs, and Timeline
alike. No shadows, no glows, no pill shapes; 2px radius on controls and
clips; 1px `#111`/`#333` borders; base font is the system UI stack at 12px,
monospace reserved for commands, results, IDs/lane names, and raw blocks.

| Token            | Value                                              |
|------------------|----------------------------------------------------|
| Ground           | `#1e1e1e`                                          |
| Panels           | `#252525`                                          |
| Track header     | `#2a2a2a`                                          |
| Track body / alt | `#232323` / `#272727` (1px `#1c1c1c` dividers)     |
| Text / muted     | `#d4d4d4` / `#8a8a8a`                              |
| Accent           | `#9cc4ec` (links, playhead, focus rings)           |
| Slice clip       | fill `#6f5f2a`, border `#8f7c36`, text `#f3ead0`   |
| Failure clip     | fill `#a8403b`, white text                         |
| Normal clip      | fill `#36424f`, text `#a9b6c6`                     |
| Terminal         | transparent, 1px dashed `#6aa97e`                  |
| Selected         | 2px solid `#fff`                                   |
| Timeline edges   | `#d9bf5c`, 1.25px, `non-scaling-stroke`            |
| Command / Result | plain `#1a1a1a` blocks, no accent borders           |
| Status           | text with a dot (`● Resolved`), not a pill          |

Chrome rules: the header is a plain bar; "Why did it fail?" is a paragraph
with `Causal path:` as inline underlined accent links (sentence case, no
letter-spaced labels); Graph | Timeline and the page tabs are flat text
with a 2px accent underline on the active one; DAG and inspector are flat
regions split by a 1px divider; the inspector is a label/value list with
1px dividers and plain-text tags; the minimap uses square segments with
1px gaps and a 1px accent viewport outline; the playhead is a 1px accent
line with a small triangle knob; buttons and clips keep 2px accent focus
rings. Clip text always meets 4.5:1 on its fill — dimming is opacity 0.5
at most, never a lower-contrast repaint.

Timeline geometry fixes this pass also made: the edge SVG renders
**below** the clip layer with straight parent-right-edge → child-left-edge
segments (no elbows, never crossing their own labels); ruler and clips
share one x-scale (the corner cell is empty); every lane is exactly 56px;
clip labels are the event type only (the ruler owns sequence numbers);
the `other` lane exists only for events with no lane and shares clip
styling (this was already true of `groupLanes` — no invented lanes).

**Why:** the DAG answers "what depends on what"; the timeline answers "what
happened in what order, and where did each kind of work happen". Lanes make
the agent's loop legible (model → bash → edit → bash) in a way a depth
layout hides, and sequence order is the one axis every trace has — even when
timestamps are synthetic. Everything else (shared store, declared edges
only, §8 wording, the "influence is not proven" note) is deliberately the
same as the DAG so the two views can never disagree.

### 14.2 Event-type filter (both views)

Live captures are 75–80% streaming noise: every message-part update is a
`context_update` (161 of 216 events in the `sort_items` session) plus one
`model_call` per turn. A filter bar under the Graph | Timeline header keeps
both views legible: a `Key events` preset (default — hides `context_update`
and `model_call`), an `All events` preset, and per-type chips with live
counts, plus an honest `showing X of N events · Y hidden by filter` line.
Pure logic lives in `lib/filter.ts` (`filterOverview`, `countByType`,
`DEFAULT_HIDDEN_TYPES`) with `node:test` coverage in
 `tests/filter.test.ts`. Rules: filtering hides nodes from the *views* only —
 edges touching a hidden endpoint are dropped, never rewired; dataset counts
 and the failure target are preserved; highlight, inspector, and tabs keep
 the full dataset so chains and details stay truthful. One exception to
 type-only hiding: the failure node itself is always pinned visible
 (`filterOverview` takes the dataset's `failure_event_id`). Fallback
 datasets point at the last captured event — often a trailing
 `context_update` part — so without pinning, Key events would remove the
 very node the diagnosis is about. Edges into the pinned node from visible
 neighbours survive; nothing is rewired.

### 14.3 Session scope + zoom that copes with any size

The overview endpoint returns *every* captured session at once (1625 events
after the live `sort_items` run), so "All events" meant all sessions mashed
into one unnavigable view. Two changes, both frontend-only:
- **Session picker:** a `Session` select in the filter bar, defaulting to
  the latest activity and listing each session as `short id (count)` with
  an opt-in `All sessions (N)`. Pure logic in `lib/filter.ts`
  (`listSessions` latest-first, `filterSession`, `shortSessionId`); grouping
  is by the declared `agent_id` capture fact, so nothing is invented. The
  type filter then applies *within* the session, and the counter reads
  `showing X of Y events`.
- **Zoom limits that scale:** the DAG's historic 0.2–10x clamp made labels
  unreachable once content exceeded ~10 screenfuls (1625 nodes squeeze
  ~179,000 content units into ~1000px). The ceiling is now content-aware
  (`fitZoomMax`: at max zoom ~600 units fill the screen, never below 10x —
  small graphs behave exactly as before; k = 1 still always fits because
  the viewBox spans the bounds). The Timeline's zoom-out floor is now its
  fit-all scale instead of 0.2, so zooming out stops at fit rather than
  jumping. Both are pure helpers with `node:test` coverage; no endpoint,
   engine, or storage changes.

### 14.4 Shared Graph/Timeline legend

The Timeline's color key (normal / in failure slice / failure target /
terminal / selected) now also sits under the Graph view, as a `.dag-foot`
row beneath the DAG. Both views render one shared `components/Legend.tsx`
— the swatch classes (`.sw.*`) live once in `globals.css` next to the
node/clip rules, so the key and the marks can never drift apart. Same
colors by construction: normal `clip-fill`, slice `slice-fill`, failure
`fail-fill`, terminal dashed `terminal` outline, selected 2px `#fff`.
`tests/api_contract.test.ts` locks it: Legend defines all five swatches,
both views render `<Legend`, neither keeps an inline copy.

## 15. Stack change log (do not silently regress)

- The vanilla HTML/CSS/JS frontend was removed by explicit team decision
  ("use Next.js, remove any vanilla JS files first then rebuild from scratch
  or recycle") and rebuilt as Next.js + TypeScript static export. Recycled
  verbatim: the selection store, viewport math, and all render helpers
  (ported to `lib/*.ts`), the token set and component styling, the status
  language, and every §8 term.
- `explorer/server.py` gained one line (`FRONTEND_DIR` → `frontend/out`);
  the five endpoints, the causal engine, the benchmark, the adapter, and
  storage are untouched, and the demo dataset is byte-identical.
