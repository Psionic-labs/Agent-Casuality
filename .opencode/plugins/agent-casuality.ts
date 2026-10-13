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

// Configurable endpoint (defaults to local receiver on port 8765).
// Resolved per request so env changes apply without reloading the plugin.
function ingestUrl(): string {
  return process.env.CASUALITY_OPENCODE_INGEST_URL ?? "http://127.0.0.1:8765/v1/opencode/events"
}

function ingestTimeoutMs(): number {
  const parsed = Number(process.env.CASUALITY_OPENCODE_INGEST_TIMEOUT_MS ?? 5000)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 5000
}

function batchMax(): number {
  const parsed = Number(process.env.CASUALITY_OPENCODE_BATCH_MAX ?? 25)
  return Number.isFinite(parsed) && parsed >= 1 ? Math.floor(parsed) : 25
}

function authHeaders(): Record<string, string> {
  const token = process.env.CASUALITY_OPENCODE_INGEST_TOKEN
  return token ? { authorization: `Bearer ${token}` } : {}
}

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

// Telemetry is intentionally fail-open and quiet by default: a missing local
// receiver must not obscure OpenCode's UI. Set this to "1" or "true" when
// diagnosing capture issues.
function telemetryWarningsEnabled(): boolean {
  const value = process.env.CASUALITY_OPENCODE_LOG_TELEMETRY_FAILURES?.toLowerCase()
  return value === "1" || value === "true"
}

// Warning throttle applies only when diagnostic logging is explicitly enabled.
let warnedEndpointHint = false
let lastWarnAt = 0
let lastWarnedDrops = 0

function warn(message: string): void {
  if (!telemetryWarningsEnabled()) return
  try {
    console.warn(`[agent-casuality] ${message}`)
  } catch {
    // Logging must never interrupt OpenCode (fail-open)
  }
}

function warnDeliveryExhausted(result: PostResult, batch: Envelope[]): void {
  const now = Date.now()
  const total = telemetryStats.droppedDeliveryFailed
  const shouldWarn =
    !warnedEndpointHint || total - lastWarnedDrops >= 10 || now - lastWarnAt > 5000
  if (!shouldWarn) return
  lastWarnAt = now
  lastWarnedDrops = total
  const kinds = [...new Set(batch.map((item) => item.kind))].slice(0, 3).join(", ")
  const hint = warnedEndpointHint
    ? ""
    : ` is the receiver running? start it with \`uv run casuality-opencode-ingest --db .casuality/opencode.db\` (endpoint ${ingestUrl()}).`
  warnedEndpointHint = true
  warn(
    `telemetry delivery failed after 3 attempts (${result}): dropped ${batch.length} event(s) [${kinds}] ` +
      `(${total} total delivery drops).${hint}`,
  )
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

// Post a batch of envelopes in one request. The receiver accepts both a
// single envelope object and an array; singletons stay objects for
// backward compatibility. An HTTP 2xx alone is NOT success: when the
// receiver reports explicit `persisted`/`accepted` counts, fewer than the
// batch size means at least one event was received but not persisted and
// the batch must be retried (idempotency keys make retries safe).
// Bodies without counts (e.g. plain 200 `{}`) are treated as delivered
// for compatibility.
async function postBatch(batch: Envelope[]): Promise<PostResult> {
  try {
    const response = await fetch(ingestUrl(), {
      method: "POST",
      headers: { "content-type": "application/json", ...authHeaders() },
      body: JSON.stringify(batch.length === 1 ? batch[0] : batch),
      signal: AbortSignal.timeout(ingestTimeoutMs()),
    })
    if (!response.ok) return "failed"
    try {
      const body = (await response.json()) as Record<string, unknown> | null
      if (body && typeof body === "object") {
        if (typeof body.persisted === "number")
          return body.persisted >= batch.length ? "delivered" : "rejected"
        if (typeof body.accepted === "number")
          return body.accepted >= batch.length ? "delivered" : "rejected"
      }
    } catch {
      // Non-JSON body: HTTP success is the only signal; treat as delivered.
    }
    return "delivered"
  } catch {
    return "failed"
  }
}

// Asynchronously post buffered envelopes to the receiver in batches with up
// to 3 attempts per batch. Envelopes still undelivered after retries are
// dropped but counted in telemetryStats.droppedDeliveryFailed (and
// rejectedByReceiver when the receiver explicitly reported short
// persistence) and warned (rate-limited).
async function drain(): Promise<void> {
  if (draining) return
  draining = true
  try {
    while (queue.length > 0) {
      // Take ownership upfront: overflow shifts during the async post below
      // then only affect queued (not in-flight) envelopes, keeping the
      // delivered/dropped accounting exact.
      const batch: Envelope[] = []
      const limit = batchMax()
      while (queue.length > 0 && batch.length < limit) {
        const item = queue.shift()
        if (item) batch.push(item)
      }
      if (batch.length === 0) continue
      let result: PostResult = "failed"
      for (let attempt = 0; attempt < 3 && result !== "delivered"; attempt += 1) {
        result = await postBatch(batch)
        // Backoff between retries (200ms, 400ms) to give a busy receiver room
        if (result !== "delivered" && attempt < 2) {
          await new Promise((resolve) => setTimeout(resolve, 200 * (attempt + 1)))
        }
      }
      if (result === "delivered") {
        telemetryStats.delivered += batch.length
      } else {
        telemetryStats.droppedDeliveryFailed += batch.length
        if (result === "rejected") telemetryStats.rejectedByReceiver += batch.length
        warnDeliveryExhausted(result, batch)
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
  warnedEndpointHint = false
  lastWarnAt = 0
  lastWarnedDrops = 0
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
