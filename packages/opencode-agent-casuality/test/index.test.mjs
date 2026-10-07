import { test } from "node:test"
import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import path from "node:path"
import { fileURLToPath } from "node:url"

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, "..")

function run(mode) {
  return execFileSync(process.execPath, [path.join(here, "run-plugin.mjs"), mode], {
    cwd: root,
    encoding: "utf8",
    timeout: 60000,
  })
}

test("captures all event kinds with session ids, auth header, and retry", () => {
  const out = run("ok")
  assert.match(out, /PASS: 12\/12 envelopes/)
})

test("retries failed posts before succeeding", () => {
  const out = run("flaky")
  assert.match(out, /PASS: 14\/12 envelopes/)
  assert.match(out, /14 requests/)
})

test("fails open when the ingest endpoint is unreachable", () => {
  const out = run("down")
  assert.match(out, /PASS: fail-open/)
})
