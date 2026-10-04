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

// Push event to queue and trigger asynchronous drain (drops oldest if full)
function enqueue(kind: string, payload: unknown): void {
  if (!payload || typeof payload !== "object") return
  queue.push({
    kind,
    timestamp: Date.now(),
    session_id: sessionID(kind, payload as Record<string, unknown>),
    payload: payload as Record<string, unknown>,
  })
  if (queue.length > 256) queue.shift()
  void drain()
}

// Asynchronously post buffered envelopes to receiver with up to 3 retries
async function drain(): Promise<void> {
  if (draining) return
  draining = true
  try {
    while (queue.length > 0) {
      const item = queue[0]
      let sent = false
      for (let attempt = 0; attempt < 3 && !sent; attempt += 1) {
        try {
          const headers: Record<string, string> = { "content-type": "application/json" }
          if (authToken) headers.authorization = `Bearer ${authToken}`
          const response = await fetch(endpoint, {
            method: "POST",
            headers,
            body: JSON.stringify(item),
            signal: AbortSignal.timeout(1000),
          })
          sent = response.ok
        } catch {
          sent = false
        }
        // Short exponential backoff between retries (50ms, 100ms)
        if (!sent && attempt < 2) {
          await new Promise((resolve) => setTimeout(resolve, 50 * (attempt + 1)))
        }
      }
      queue.shift()
    }
  } catch {
    // Fail-open guarantee: telemetry errors must never interrupt OpenCode
  } finally {
    draining = false
  }
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

export default AgentCasualityPlugin

