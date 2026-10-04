import type { Plugin } from "@opencode-ai/plugin"

declare const process: {
  env: Record<string, string | undefined>
}

type Envelope = {
  kind: string
  timestamp: number
  session_id?: string
  payload: Record<string, unknown>
}

const endpoint = process.env.CASUALITY_OPENCODE_INGEST_URL ?? "http://127.0.0.1:8765/v1/opencode/events"
const authToken = process.env.CASUALITY_OPENCODE_INGEST_TOKEN
const queue: Envelope[] = []
let draining = false

function sessionID(payload: Record<string, unknown>): string | undefined {
  const value = payload.sessionID ?? payload.session_id
  return typeof value === "string" ? value : undefined
}

function enqueue(kind: string, payload: unknown): void {
  if (!payload || typeof payload !== "object") return
  queue.push({
    kind,
    timestamp: Date.now(),
    session_id: sessionID(payload as Record<string, unknown>),
    payload: payload as Record<string, unknown>,
  })
  if (queue.length > 256) queue.shift()
  void drain()
}

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
        if (!sent && attempt < 2) {
          await new Promise((resolve) => setTimeout(resolve, 50 * (attempt + 1)))
        }
      }
      queue.shift()
    }
  } catch {
    // Telemetry is fail-open: OpenCode execution must never depend on the receiver.
  } finally {
    draining = false
  }
}

export const AgentCasualityPlugin: Plugin = async () => ({
  event: async ({ event }) => {
    enqueue(`event:${event.type}`, event.properties)
  },
  "tool.execute.before": async (input, output) => {
    enqueue("hook:tool.execute.before", {
      sessionID: input.sessionID,
      callID: input.callID,
      tool: input.tool,
      args: output.args,
    })
  },
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
  "permission.ask": async (input, output) => {
    enqueue("hook:permission.ask", {
      ...input,
      response: output.status,
    })
  },
  "command.execute.before": async (input) => {
    enqueue("hook:command.execute.before", input)
  },
  "chat.message": async (input, output) => {
    enqueue("hook:chat.message", {
      sessionID: input.sessionID,
      agent: input.agent,
      model: input.model,
      message: output.message,
      parts: output.parts,
    })
  },
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

