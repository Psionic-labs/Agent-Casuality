"use client";

/* Structured event inspector. Never raw JSON by default: tool events get a
 * prominent Command hero and Result hero (correlated parent/child records
 * labeled with their source), then the structured field list, declared
 * parents / observed children, and the raw record collapsed. Missing values
 * render as —; status is only read from explicit fields, never inferred. */

import { useEffect, useState } from "react";
import {
  commandForEvent,
  inspectorFieldRows,
  resultForEvent,
  type CommandInfo,
  type ResultInfo,
} from "../lib/render.ts";
import { fetchEventDetail } from "../lib/api.ts";
import { selectEvent } from "../lib/use-selection.ts";
import type { EventDetail, EventRecord } from "../lib/types.ts";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="copy"
      type="button"
      title="copy full value"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        } catch {
          window.prompt("Copy value:", text);
        }
      }}
    >
      {copied ? "✓" : "⧉"}
    </button>
  );
}

interface Props {
  selectedId: string | null;
}

export function Inspector({ selectedId }: Props) {
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [related, setRelated] = useState<EventRecord[]>([]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setRelated([]);
      return;
    }
    let cancelled = false;
    setDetail(null);
    (async () => {
      const d = await fetchEventDetail(selectedId);
      if (cancelled) return;
      setDetail(d);
      const relIds = [
        ...(d.parents ?? []).map((p) => p.event_id),
        ...(d.children ?? []).map((c) => c.event_id),
      ];
      const rels: EventRecord[] = [];
      for (const rid of relIds) {
        try {
          rels.push((await fetchEventDetail(rid)).record);
        } catch {
          continue; // a missing relative simply contributes nothing
        }
      }
      if (!cancelled) setRelated(rels);
    })().catch(() => {
      if (!cancelled) setDetail(null);
    });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  if (!selectedId) {
    return (
      <div id="event-detail">
        <p className="hint">Select a node in the graph.</p>
      </div>
    );
  }
  if (!detail) {
    return (
      <div id="event-detail">
        <p className="hint">loading…</p>
      </div>
    );
  }

  const rec = detail.record ?? {};
  const isTool = rec.event_type === "tool_call" || rec.event_type === "tool_result";
  const cmd: CommandInfo = isTool ? commandForEvent(rec, related) : { command: null, source: null };
  const res: ResultInfo = isTool ? resultForEvent(rec, related) : { status: null, output: null, outputSource: null };
  const ownCommand = (((rec.payload ?? {}) as Record<string, unknown>)["payload"] as Record<string, unknown> | undefined)?.["args"];
  const hasOwnCommand =
    !!ownCommand && typeof ownCommand === "object" && !!(ownCommand as Record<string, unknown>)["command"] && !!cmd.command;

  return (
    <div id="event-detail">
      {detail.role && <span className="pill role">role: {detail.role}</span>}
      {detail.in_failure_slice && <span className="pill slice">in failure slice</span>}
      {isTool && (
        <>
          <div className="cmd-hero">
            <span className="hero-label">Command</span>
            <code className={cmd.command ? "" : "missing"}>{cmd.command ?? "—"}</code>
            {cmd.source && <span className="hero-source">Source: {cmd.source}</span>}
          </div>
          <div className="result-hero">
            <div className="result-head">
              <span className="hero-label">Result</span>
              <span className="pill">{res.status ?? "—"}</span>
              {res.outputSource && (
                <span className="hero-source">Output from {res.outputSource}</span>
              )}
            </div>
            {res.output ? (
              <pre className="out">{res.output}</pre>
            ) : (
              <p className="hint">No recorded output.</p>
            )}
          </div>
        </>
      )}
      <dl>
        {inspectorFieldRows(detail).map(([label, value]) => (
          <div key={label} className="field-row">
            <dt>{label}</dt>
            <dd>
              {(label === "Event ID" || label === "Call ID") && value.length > 24 ? (
                <>
                  <span className="truncate" title={value}>
                    {value}
                  </span>
                  <CopyButton text={value} />
                </>
              ) : (
                value
              )}
            </dd>
          </div>
        ))}
        {isTool && !hasOwnCommand && (
          <>
            <dt>Command</dt>
            <dd>{cmd.command ?? "—"}</dd>
            <dt>Source</dt>
            <dd>{cmd.source ?? "—"}</dd>
          </>
        )}
      </dl>
      {(
        [
          ["Declared parents", detail.parents, "root event: no declared parents"],
          ["Observed children", detail.children, "no observed children"],
        ] as Array<[string, { event_id: string; label: string }[], string]>
      ).map(([title, items, emptyHint]) => (
        <div key={title}>
          <h3>
            {title} ({items.length})
          </h3>
          {items.length === 0 ? (
            <p className="hint">{emptyHint}</p>
          ) : (
            <ul>
              {items.map((item) => (
                <li key={item.event_id}>
                  <button
                    className="pill"
                    type="button"
                    title={item.event_id}
                    onClick={() => selectEvent(item.event_id)}
                  >
                    {item.label}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
      <details>
        <summary>Raw event</summary>
        <pre>{JSON.stringify(rec, null, 2)}</pre>
      </details>
    </div>
  );
}
