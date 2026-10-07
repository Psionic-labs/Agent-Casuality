// Spawns the built plugin in a child process against a local HTTP receiver.
// Usage: node test/run-plugin.mjs <mode>
//   mode "ok"    - receiver always returns 200
//   mode "flaky" - receiver returns 500 twice, then 200 (exercises retry)
//   mode "down"  - no receiver is started (exercises fail-open)
import { spawn } from "node:child_process"
import http from "node:http"
import { writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, "..")
const mode = process.argv[2] ?? "ok"

const received = []
let requestCount = 0

const server = http.createServer((req, res) => {
  let body = ""
  req.on("data", (chunk) => (body += chunk))
  req.on("end", () => {
    requestCount += 1
    received.push({
      authorization: req.headers.authorization ?? null,
      body: JSON.parse(body),
    })
    const failFirst = mode === "flaky" && requestCount <= 2
    res.writeHead(failFirst ? 500 : 200, { "content-type": "application/json" })
    res.end("{}")
  })
})

function listen() {
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server.address().port)))
}

const port = mode === "down" ? 0 : await listen()
const ingestUrl = `http://127.0.0.1:${port}/v1/opencode/events`

const driver = `
import plugin from ${JSON.stringify(pathToFileURL(path.join(root, "dist", "index.js")).href)}
const hooks = await plugin({})
await hooks.event({ event: { type: "session.created", properties: { info: { id: "sess-1" } } } })
await hooks.event({ event: { type: "message.part.updated", properties: { sessionID: "sess-2", part: { sessionID: "sess-2" } } } })
await hooks.event({ event: { type: "message.updated", properties: { info: { session_id: "sess-3" } } } })
await hooks.event({ event: { type: "file.edited", properties: { sessionID: "sess-4", filePath: "a.ts" } } })
await hooks.event({ event: { type: "session.deleted", properties: { info: { id: "sess-5" } } } })
await hooks.event({ event: { type: "error", properties: { sessionID: "sess-6", error: { message: "boom" } } } })
await hooks["tool.execute.before"](
  { sessionID: "sess-7", callID: "call-1", tool: "read" },
  { args: { filePath: "b.ts" } },
)
await hooks["tool.execute.after"](
  { sessionID: "sess-7", callID: "call-1", tool: "read", args: { filePath: "b.ts" } },
  { title: "read", output: "file contents", metadata: { duration_ms: 5 } },
)
await hooks["permission.ask"]({ sessionID: "sess-8", permission: { id: "p1" } }, { status: "allow" })
await hooks["command.execute.before"]({ sessionID: "sess-9", command: "ls" })
await hooks["chat.message"](
  { sessionID: "sess-10", agent: "build", model: "muse" },
  { message: { id: "m1" }, parts: [{ type: "text", text: "hi" }] },
)
await hooks["chat.params"]({ sessionID: "sess-11", agent: "build", model: "muse", provider: "opencode" })
await new Promise((r) => setTimeout(r, 1500))
console.log("driver-done")
`

const driverPath = path.join(os.tmpdir(), `casuality-plugin-driver-${process.pid}.mjs`)
writeFileSync(driverPath, driver)

const child = spawn(
  process.execPath,
  [driverPath],
  {
    cwd: root,
    env: {
      ...process.env,
      CASUALITY_OPENCODE_INGEST_URL: ingestUrl,
      CASUALITY_OPENCODE_INGEST_TOKEN: "test-token-123",
    },
    stdio: ["ignore", "pipe", "pipe"],
  },
)

let stderr = ""
child.stderr.on("data", (d) => (stderr += d))
child.stdout.on("data", (d) => process.stdout.write(d))

const exitCode = await new Promise((resolve) => child.on("exit", resolve))
server.close()

if (mode === "down") {
  if (exitCode !== 0) {
    console.error(`FAIL: child exited ${exitCode}\n${stderr}`)
    process.exit(1)
  }
  console.log("PASS: fail-open (receiver unreachable, plugin exited cleanly)")
  process.exit(0)
}

const kinds = received.map((r) => r.body.kind)
const expected = [
  "event:session.created",
  "event:message.part.updated",
  "event:message.updated",
  "event:file.edited",
  "event:session.deleted",
  "event:error",
  "hook:tool.execute.before",
  "hook:tool.execute.after",
  "hook:permission.ask",
  "hook:command.execute.before",
  "hook:chat.message",
  "hook:chat.params",
]

const failures = []
for (const kind of expected) {
  if (!kinds.includes(kind)) failures.push(`missing kind ${kind}`)
}
const sessionIds = Object.fromEntries(received.map((r) => [r.body.kind, r.body.session_id]))
const expectedSessions = {
  "event:session.created": "sess-1",
  "event:message.part.updated": "sess-2",
  "event:message.updated": "sess-3",
  "event:file.edited": "sess-4",
  "event:session.deleted": "sess-5",
  "event:error": "sess-6",
  "hook:tool.execute.before": "sess-7",
  "hook:tool.execute.after": "sess-7",
  "hook:permission.ask": "sess-8",
  "hook:command.execute.before": "sess-9",
  "hook:chat.message": "sess-10",
  "hook:chat.params": "sess-11",
}
for (const [kind, sid] of Object.entries(expectedSessions)) {
  if (sessionIds[kind] !== sid) failures.push(`${kind}: session_id ${sessionIds[kind]} !== ${sid}`)
}
for (const r of received) {
  if (r.authorization !== "Bearer test-token-123") failures.push(`bad auth header on ${r.body.kind}`)
  if (typeof r.body.timestamp !== "number") failures.push(`missing timestamp on ${r.body.kind}`)
}
const toolAfter = received.find((r) => r.body.kind === "hook:tool.execute.after")
if (toolAfter?.body.payload?.callID !== "call-1") failures.push("tool.execute.after lost callID linkage")

if (mode === "flaky" && requestCount < expected.length + 2) {
  failures.push(`retry not exercised: only ${requestCount} requests for ${expected.length} events`)
}

if (failures.length) {
  console.error("FAIL:\n" + failures.join("\n"))
  process.exit(1)
}
console.log(`PASS: ${received.length}/${expected.length} envelopes captured, auth + session_id + retry verified (${requestCount} requests)`)
