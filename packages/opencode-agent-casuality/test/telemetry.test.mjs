import { test } from "node:test"
import assert from "node:assert/strict"
import path from "node:path"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, "..")

// ---- Fetch mock (installed before the plugin module is imported) ----
let fetchMode = "ok" // ok | fail | reject | down | gate
let requestCount = 0
let bodies = []
let gateOpen = false
let gatePending = []

globalThis.fetch = async (_url, opts) => {
  requestCount += 1
  bodies.push(JSON.parse(opts.body))
  if (fetchMode === "fail") return { ok: false, status: 500, json: async () => ({}) }
  if (fetchMode === "reject") {
    return {
      ok: true,
      status: 202,
      json: async () => ({ received: 1, normalized: 1, persisted: 0, accepted: 0 }),
    }
  }
  if (fetchMode === "down") throw new Error("connect ECONNREFUSED")
  if (fetchMode === "gate") {
    if (gateOpen) return { ok: true, status: 200, json: async () => ({}) }
    await new Promise((resolve) => gatePending.push(resolve))
    return { ok: true, status: 200, json: async () => ({}) }
  }
  return { ok: true, status: 200, json: async () => ({}) }
}

const pluginModule = await import("../dist/index.js")
const { telemetryStats, __casualityTestReset, __casualityTestQueueLength } = pluginModule
const plugin = pluginModule.default

function resetHarness() {
  fetchMode = "ok"
  requestCount = 0
  bodies = []
  gateOpen = false
  gatePending = []
  __casualityTestReset()
}

async function settle(timeoutMs = 15000) {
  // Completion signal: every non-overflowed envelope is either delivered or
  // counted as a delivery drop. Queue length alone is insufficient because
  // drain takes ownership of the in-flight envelope upfront.
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const done =
      telemetryStats.delivered + telemetryStats.droppedDeliveryFailed ===
      telemetryStats.enqueued - telemetryStats.droppedQueueOverflow
    if (__casualityTestQueueLength() === 0 && done) break
    await new Promise((r) => setTimeout(r, 25))
  }
  assert.equal(__casualityTestQueueLength(), 0, "queue did not drain in time")
  assert.equal(
    telemetryStats.delivered + telemetryStats.droppedDeliveryFailed,
    telemetryStats.enqueued - telemetryStats.droppedQueueOverflow,
    "drain did not settle in time",
  )
}

test("local and published plugin sources stay in sync with observable telemetry", () => {
  const local = readFileSync(
    path.resolve(root, "..", "..", ".opencode", "plugins", "agent-casuality.ts"),
    "utf8",
  )
  const published = readFileSync(path.resolve(root, "src", "index.ts"), "utf8")
  const norm = (s) => s.replace(/\r\n/g, "\n").trimEnd()
  assert.equal(norm(local), norm(published), "plugin sources diverged")
  for (const needle of ["telemetryStats", "droppedQueueOverflow", "rejectedByReceiver", "persisted"]) {
    assert.match(local, new RegExp(needle), `local source missing ${needle}`)
    assert.match(published, new RegExp(needle), `published source missing ${needle}`)
  }
})

test("queue overflow is counted and observable (fail-open)", async () => {
  resetHarness()
  fetchMode = "gate"
  const hooks = await plugin({})
  const total = 300
  const pending = []
  for (let i = 0; i < total; i += 1) {
    pending.push(
      hooks.event({ event: { type: "session.status", properties: { sessionID: "s-flood", n: i } } }),
    )
  }
  await Promise.all(pending)
  assert.equal(telemetryStats.enqueued, total)
  assert.ok(
    telemetryStats.droppedQueueOverflow > 0,
    `expected overflow drops, got ${telemetryStats.droppedQueueOverflow}`,
  )
  assert.ok(__casualityTestQueueLength() <= 256, "queue exceeded its bound")
  gateOpen = true
  for (const resolve of gatePending) resolve()
  gatePending = []
  await settle()
  assert.equal(__casualityTestQueueLength(), 0)
  assert.equal(
    telemetryStats.delivered,
    telemetryStats.enqueued - telemetryStats.droppedQueueOverflow,
    `delivered (${telemetryStats.delivered}) must equal enqueued minus overflow`,
  )
  assert.equal(telemetryStats.droppedDeliveryFailed, 0)
})

test("exhausted retries are dropped but counted (fail-open)", async () => {
  await settle()
  resetHarness()
  fetchMode = "fail"
  const hooks = await plugin({})
  await hooks.event({ event: { type: "session.status", properties: { sessionID: "s-retry" } } })
  await settle()
  assert.equal(requestCount, 3, `expected 3 attempts, got ${requestCount}`)
  assert.equal(telemetryStats.delivered, 0)
  assert.equal(telemetryStats.droppedDeliveryFailed, 1)
})

test("HTTP 202 with zero persisted is retried, not treated as delivered", async () => {
  await settle()
  resetHarness()
  fetchMode = "reject"
  const hooks = await plugin({})
  await hooks.event({ event: { type: "session.status", properties: { sessionID: "s-reject" } } })
  await settle()
  assert.equal(requestCount, 3, `expected 3 attempts against rejecting receiver, got ${requestCount}`)
  assert.equal(telemetryStats.delivered, 0)
  assert.equal(telemetryStats.droppedDeliveryFailed, 1)
  assert.equal(telemetryStats.rejectedByReceiver, 1)
})

test("session-less events are preserved without invented session IDs", async () => {
  await settle()
  resetHarness()
  fetchMode = "ok"
  const hooks = await plugin({})
  await hooks.event({ event: { type: "file.edited", properties: { file: "src/a.ts" } } })
  await settle()
  assert.equal(telemetryStats.delivered, 1)
  assert.equal(bodies.length, 1)
  assert.equal(bodies[0].kind, "event:file.edited")
  assert.ok(!("session_id" in bodies[0]) || bodies[0].session_id === undefined)
  assert.deepEqual(bodies[0].payload, { file: "src/a.ts" })
})

test("fail-open: unreachable receiver never rejects the hook", async () => {
  await settle()
  resetHarness()
  fetchMode = "down"
  const hooks = await plugin({})
  await hooks.event({ event: { type: "session.status", properties: { sessionID: "s-down" } } })
  await hooks["tool.execute.before"](
    { sessionID: "s-down", callID: "call-1", tool: "read" },
    { args: { filePath: "b.ts" } },
  )
  await settle()
  assert.equal(telemetryStats.delivered, 0)
  assert.equal(telemetryStats.droppedDeliveryFailed, 2)
  assert.equal(__casualityTestQueueLength(), 0)
})
