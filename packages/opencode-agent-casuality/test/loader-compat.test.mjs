// Loader-compatibility regression test (no OpenCode binary required).
//
// OpenCode >= 1.19 rejects plugin modules whose legacy export surface
// contains a non-function export ("Plugin export is not a function"),
// which silently disables every hook in the module. The shape supported
// on every OpenCode >= 1.18.29 is the V1 server-plugin module: a default
// export object with a server() factory (named exports are ignored on
// that path). This test pins that contract so a bare-function default
// export can never be reintroduced. Actual binary loading on 1.19.0 and
// 1.18.34 is covered separately by scripts/check-opencode-plugin-compat.py.
import { test } from "node:test"
import assert from "node:assert/strict"

const pluginModule = await import("../dist/index.js")

test("default export is a V1 server-plugin module, not a bare function", () => {
  const mod = pluginModule.default
  assert.notEqual(
    typeof mod,
    "function",
    "a bare-function default export falls through to the legacy loader, " +
      "where any non-function named export aborts the whole plugin",
  )
  assert.equal(typeof mod, "object")
  assert.equal(typeof mod?.id, "string")
  assert.equal(typeof mod?.server, "function")
})

test("server() resolves to a hooks object with the expected hook keys", async () => {
  const hooks = await pluginModule.default.server({})
  assert.equal(typeof hooks, "object")
  for (const key of [
    "event",
    "tool.execute.before",
    "tool.execute.after",
    "permission.ask",
    "command.execute.before",
    "chat.message",
    "chat.params",
  ]) {
    assert.equal(typeof hooks[key], "function", `missing hook ${key}`)
  }
})
