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
- Pure logic lives in framework-free `lib/` modules (`store`, `viewport`,
  `render`, `timeline`, `api`) with explicit `.ts` relative imports, so the
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
- Pure helpers (`viewport.js`, `render.js`) hold all math/class logic so
  behavior is unit-testable without a DOM.

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

Causal chain (slice in order, capped at 80 rows), Provenance (per-resource
vertical chains + honest "no graded provenance" note when the evidence
package has none + expected edges collapsed), Interaction (joint-ancestry
framed as NOT causal), Evidence (summary + grounding), Metrics (plain
summary list first, raw metric fields collapsed).

**Why:** the first four tabs are human-readable; Metrics owns the research
vocabulary. Provenance chains are built only from slice events referencing
the resource via capture metadata — no invented edges.

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
  endpoints, demo shape) + unit tests for selection, viewport, render,
  inspector, and timeline — all in TypeScript, run directly by Node's type
  stripping.
- `npx tsc --noEmit` (strict) and `npm run build` (static export) must pass.
- `uv run ruff check .`, `uv run ty check .`, `uv run pytest -q`
  (194 passed, 1 postgres skip).
- Live-server smoke: static 200s (including `/_next/*` assets with correct
  MIME), demo slice/diagnosis/provenance values, live 934-event overview.

## 13. Ideas for a future redesign (not yet built)

Worth considering, in rough priority order:

- **Run selector**: pick `run_id`/session when a DB holds many runs
  (today: single dataset per server start).
- **Branching demo**: bundle a recorded trace with real fan-out/merge so
  the DAG demonstrates `Branch A ─┐ ├──→ merge → failure` instead of a
  line. (Requires capturing such a trace; never synthesize one.)
- **SVG virtualization / canvas renderer**: the 934-node live DAG still
  mounts every node (only the timeline clips are culled); cap, window, or
  switch renderers.
- **Chain-tab pagination**: beyond the 80-row cap, page instead of
  truncating.
- **Failure-target picker**: let the user override the fallback target
  (explicitly labeled as manual, not ground truth).
- **Diff view for file edits**: render before/after payloads of `edit`
  events side by side.
- **Search/filter**: by event type, tool, role, resource, or free text,
  with non-matching nodes dimmed.
- **Export**: download the evidence package / diagnosis JSON from the UI.
- **Light theme + density toggle** for screenshots vs. deep debugging.
- **Deep links**: URL hash carrying dataset + selected event for sharing.
- **Multi-failure support**: the model assumes one failure target; runs
  with several failures need a target switcher.
- **WebSocket/live tail**: stream new events as the agent runs (backend
  work; keep the read-only contract).
- **Accessibility pass**: focus states, ARIA live regions for selection,
  sufficient-contrast audit of the dimmed states.

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
  one clip of margin); the 934-event live trace renders a ~15-clip slice.

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
