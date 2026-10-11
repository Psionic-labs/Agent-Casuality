import type { Plugin } from "@opencode-ai/plugin"

declare const process: {
  env: Record<string, string | undefined>
}

// Telemetry envelope shipped to Agent-Casuality ingest endpoint
type Envelope = {
  kind: string
  timestamp: number
  session_id?: string
  payload: Record<string, unknown>
}

// Configurable endpoint (defaults to local receiver on port 8765)
const endpoint = process.env.CASUALITY_OPENCODE_INGEST_URL ?? "http://127.0.0.1:8765/v1/opencode/events"
const authToken = process.env.CASUALITY_OPENCODE_INGEST_TOKEN

// Bounded in-memory telemetry buffer (max 256 items) to prevent memory growth
const queue: Envelope[] = []
let draining = false

// Observable telemetry counters. Losses are counted and warned (fail-open),
// never thrown, so queue overflows and exhausted retries stay visible.
export const telemetryStats = {
  enqueued: 0,
  delivered: 0,
  droppedQueueOverflow: 0,
  droppedDeliveryFailed: 0,
  rejectedByReceiver: 0,
}

function warn(message: string): void {
  try {
    console.warn(`[agent-casuality] ${message}`)
  } catch {
    // Logging must never interrupt OpenCode (fail-open)
  }
}

// Helper to extract session ID across OpenCode payload variants
// Covers top-level fields plus nested info/session (session.created,
// message.updated) and part (message.part.updated) shapes.
function sessionID(kind: string, payload: Record<string, unknown>): string | undefined {
  const direct = payload.sessionID ?? payload.session_id
  if (typeof direct === "string") return direct
  const info = payload.info as Record<string, unknown> | undefined
  if (info && typeof info === "object") {
    const nested = info.sessionID ?? info.session_id
    if (typeof nested === "string") return nested
    // Session lifecycle events carry only info.id as the session identity.
    if (
      (kind === "event:session.created" ||
        kind === "event:session.updated" ||
        kind === "event:session.deleted") &&
      typeof info.id === "string"
    ) {
      return info.id
    }
  }
  const part = payload.part as Record<string, unknown> | undefined
  if (part && typeof part === "object") {
    const nested = part.sessionID ?? part.session_id
    if (typeof nested === "string") return nested
  }
  return undefined
}

// Push event to queue and trigger asynchronous drain.
// Drops the oldest envelope if full; the drop is counted in
// telemetryStats.droppedQueueOverflow and warned (observable, fail-open).
function enqueue(kind: string, payload: unknown): void {
  if (!payload || typeof payload !== "object") return
  queue.push({
    kind,
    timestamp: Date.now(),
    session_id: sessionID(kind, payload as Record<string, unknown>),
    payload: payload as Record<string, unknown>,
  })
  telemetryStats.enqueued += 1
  if (queue.length > 256) {
    queue.shift()
    telemetryStats.droppedQueueOverflow += 1
    warn(
      `telemetry queue overflow: dropped oldest envelope (${telemetryStats.droppedQueueOverflow} total overflow drops)`,
    )
  }
  void drain()
}

type PostResult = "delivered" | "rejected" | "failed"

// Post one envelope. An HTTP 2xx alone is NOT success: when the receiver
// reports explicit `persisted`/`accepted` counts, zero means the event was
// received but not persisted and must be retried. Bodies without counts
// (e.g. plain 200 `{}`) are treated as delivered for compatibility.
async function postEnvelope(item: Envelope): Promise<PostResult> {
  try {
    const headers: Record<string, string> = { "content-type": "application/json" }
    if (authToken) headers.authorization = `Bearer ${authToken}`
    const response = await fetch(endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify(item),
      signal: AbortSignal.timeout(1000),
    })
    if (!response.ok) return "failed"
    try {
      const body = (await response.json()) as Record<string, unknown> | null
      if (body && typeof body === "object") {
        if (typeof body.persisted === "number") return body.persisted > 0 ? "delivered" : "rejected"
        if (typeof body.accepted === "number") return body.accepted > 0 ? "delivered" : "rejected"
      }
    } catch {
      // Non-JSON body: HTTP success is the only signal; treat as delivered.
    }
    return "delivered"
  } catch {
    return "failed"
  }
}

// Asynchronously post buffered envelopes to receiver with up to 3 retries.
// Envelopes still undelivered after retries are dropped but counted in
// telemetryStats.droppedDeliveryFailed (and rejectedByReceiver when the
// receiver explicitly reported zero persistence) and warned.
async function drain(): Promise<void> {
  if (draining) return
  draining = true
  try {
    while (queue.length > 0) {
      // Take ownership upfront: overflow shifts during the async post below
      // then only affect queued (not in-flight) envelopes, keeping the
      // delivered/dropped accounting exact.
      const item = queue.shift()
      if (!item) continue
      let result: PostResult = "failed"
      for (let attempt = 0; attempt < 3 && result !== "delivered"; attempt += 1) {
        result = await postEnvelope(item)
        // Short exponential backoff between retries (50ms, 100ms)
        if (result !== "delivered" && attempt < 2) {
          await new Promise((resolve) => setTimeout(resolve, 50 * (attempt + 1)))
        }
      }
      if (result === "delivered") {
        telemetryStats.delivered += 1
      } else {
        telemetryStats.droppedDeliveryFailed += 1
        if (result === "rejected") telemetryStats.rejectedByReceiver += 1
        warn(
          `telemetry delivery failed after 3 attempts (${result}): dropped ${item.kind} ` +
            `(${telemetryStats.droppedDeliveryFailed} total delivery drops)`,
        )
      }
    }
  } catch {
    // Fail-open guarantee: telemetry errors must never interrupt OpenCode
  } finally {
    draining = false
  }
}

// Introspection hooks for tests and operators (read-only except reset).
export function __casualityTestReset(): void {
  queue.length = 0
  telemetryStats.enqueued = 0
  telemetryStats.delivered = 0
  telemetryStats.droppedQueueOverflow = 0
  telemetryStats.droppedDeliveryFailed = 0
  telemetryStats.rejectedByReceiver = 0
}

export function __casualityTestQueueLength(): number {
  return queue.length
}

// OpenCode V1 Plugin implementation registering event and lifecycle hooks
export const AgentCasualityPlugin: Plugin = async () => ({
  // Global OpenCode event stream (session lifecycle, file edits, git/file watcher, errors)
  event: async ({ event }) => {
    enqueue(`event:${event.type}`, event.properties)
  },
  // Tool invocation starts (records tool name, arguments, call ID for causality)
  "tool.execute.before": async (input, output) => {
    enqueue("hook:tool.execute.before", {
      sessionID: input.sessionID,
      callID: input.callID,
      tool: input.tool,
      args: output.args,
    })
  },
  // Tool invocation completes (records output, metadata, links back to call ID)
  "tool.execute.after": async (input, output) => {
    enqueue("hook:tool.execute.after", {
      sessionID: input.sessionID,
      callID: input.callID,
      tool: input.tool,
      args: input.args,
      title: output.title,
      output: output.output,
      metadata: output.metadata,
    })
  },
  // User approval / permission dialogs
  "permission.ask": async (input, output) => {
    enqueue("hook:permission.ask", {
      ...input,
      response: output.status,
    })
  },
  // Shell command execution before running
  "command.execute.before": async (input) => {
    enqueue("hook:command.execute.before", input)
  },
  // Message activity between agent and model
  "chat.message": async (input, output) => {
    enqueue("hook:chat.message", {
      sessionID: input.sessionID,
      agent: input.agent,
      model: input.model,
      message: output.message,
      parts: output.parts,
    })
  },
  // Active model, agent, and provider parameters
  "chat.params": async (input) => {
    enqueue("hook:chat.params", {
      sessionID: input.sessionID,
      agent: input.agent,
      model: input.model,
      provider: input.provider,
    })
  },
})

// V1 server-plugin module shape (supported since OpenCode 1.18.29): the
// default export must be an object with server(), not the plugin function
// itself. Named exports are ignored on this path, so helper exports such
// as telemetryStats no longer break loading with
// "Plugin export is not a function" (OpenCode >= 1.19).
export default {
  id: "agent-casuality",
  server: AgentCasualityPlugin,
}

