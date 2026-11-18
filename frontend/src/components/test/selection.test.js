import "../../test/setup.js"
import { deferred, response, session } from "../../test/setup.js"
import assert from "node:assert/strict"
import test from "node:test"
import { createElement } from "react"
import { render, act, fireEvent } from "@testing-library/react"
const { CompliancePanel } = await import("../CompliancePanel.tsx")
const assessment = (id) => ({ id, assessed_at: "2026-10-29", window_start: "2026-10-28", window_end: "2026-10-29", evaluator_version: "1", results: [{ control: "privileged_mfa", status: "pass", summary: "checked", evidence_event_ids: [id], details: {} }] })

for (const outboundStops of [0, 1]) {
test(`round-trip offers remain selectable with accurate direction stops (outbound=${outboundStops}, return=1)`, async () => {
  const { FlightSearch } = await import("../FlightSearch.tsx")
  const leg = (departure_airport, arrival_airport) => ({ departure_airport, arrival_airport, depart_at: "2030-01-01T10:00:00Z", arrive_at: "2030-01-01T14:00:00Z" })
  const legs = [...(outboundStops ? [leg("OAK", "SFO"), leg("SFO", "ONT")] : [leg("OAK", "ONT")]), leg("ONT", "SFO"), leg("SFO", "OAK")]
  const offer = { id: 4, carrier: "Connecting Air", stops: outboundStops, legs, price_usd: 250, currency: "USD", depart_at: "2030-01-01T10:00:00Z", arrive_at: "2030-01-01T14:00:00Z" }
  let selected
  const view = render(createElement(FlightSearch, {
    trip: { origin: "OAK", destination_airport: "ONT", depart_date: "2030-01-01", return_date: "2030-01-05" },
    searchResult: { offers: [offer] }, isLoading: false, selectedOfferId: null,
    onSearchFlights() {}, onSearchNewFlight() {}, onSelectOffer(value) { selected = value },
  }))
  assert.match(view.getByText("Outbound").parentElement.textContent, outboundStops ? /1 stop/ : /Nonstop/)
  assert.match(view.getByText("Return").parentElement.textContent, /1 stop/)
  assert.equal(view.queryByText("Nonstop", { exact: true }), null, "a round trip must not have a misleading overall nonstop label")
  fireEvent.click(view.getByRole("radio"))
  assert.equal(selected, offer)
  view.rerender(createElement(FlightSearch, {
    trip: { origin: "OAK", destination_airport: "ONT", depart_date: "2030-01-01", return_date: "2030-01-05" },
    searchResult: { offers: [offer] }, isLoading: false, selectedOfferId: offer.id,
    selectionDisabled: true, onSearchFlights() {}, onSearchNewFlight() {}, onSelectOffer() {},
  }))
  assert.equal(view.getByRole("radio").disabled, true)
})
}

for (const fails of [false, true]) {
test(`switching assessments discards outstanding evidence responses (failure=${fails})`, async (context) => {
  const pending = deferred()
  let evidenceSignal
  context.mock.method(globalThis, "fetch", async (url, options) => {
    if (url.endsWith("/monitoring")) return response({ stale: false, assessments: [assessment(1), assessment(2)] })
    evidenceSignal = options.signal
    return pending.promise
  })
  const view = render(createElement(CompliancePanel))
  await act(async () => {})
  fireEvent.click(view.getByText("Event #1"))
  fireEvent.change(view.getByRole("combobox"), { target: { value: "2" } })
  await act(async () => pending.resolve(fails ? response({ detail: "obsolete evidence" }, 500) : response({ marker: "obsolete evidence" })))
  assert.doesNotMatch(view.container.textContent, /obsolete evidence/)
  assert.equal(evidenceSignal?.aborted, true)
})
}

for (const fails of [false, true]) {
test(`a replaced session discards pending evidence (failure=${fails})`, async (context) => {
  await session("evidence-original")
  const pending = deferred()
  context.mock.method(globalThis, "fetch", async (url) => url.endsWith("/monitoring")
    ? response({ stale: false, assessments: [assessment(1)] }) : pending.promise)
  const view = render(createElement(CompliancePanel))
  await act(async () => {})
  fireEvent.click(view.getByText("Event #1"))
  await session("evidence-replacement")
  await act(async () => pending.resolve(fails ? response({ detail: "previous session evidence" }, 500) : response({ marker: "previous session evidence" })))
  assert.doesNotMatch(view.container.textContent, /previous session evidence/)
  assert.equal(view.queryByText("Selected evidence"), null)
  assert.equal(view.queryByRole("alert"), null)
})
}

for (const evidenceState of ["pending", "loaded", "error"]) {
test(`a new latest assessment clears ${evidenceState} evidence`, async (context) => {
  const pending = deferred()
  let poll, monitoringRequests = 0, evidenceSignal
  context.mock.method(globalThis, "setInterval", (callback) => { poll = callback; return 1 })
  context.mock.method(globalThis, "clearInterval", () => {})
  context.mock.method(globalThis, "fetch", async (url, options) => {
    if (url.endsWith("/monitoring")) return response({ stale: false, assessments: ++monitoringRequests === 1
      ? [assessment(1)] : [assessment(2), assessment(1)] })
    evidenceSignal = options.signal
    return pending.promise
  })
  const view = render(createElement(CompliancePanel))
  await act(async () => {})
  fireEvent.click(view.getByText("Event #1"))
  if (evidenceState !== "pending") {
    await act(async () => pending.resolve(evidenceState === "error"
      ? response({ detail: "old assessment evidence" }, 500) : response({ marker: "old assessment evidence" })))
    assert.match(view.container.textContent, /old assessment evidence/)
  }
  await act(async () => { await poll() })
  assert.equal(view.getByRole("combobox").value, "2")
  if (evidenceState === "pending") await act(async () => pending.resolve(response({ marker: "old assessment evidence" })))
  assert.doesNotMatch(view.container.textContent, /old assessment evidence/)
  assert.equal(view.queryByText("Selected evidence"), null)
  assert.equal(view.queryByRole("alert"), null)
  assert.equal(evidenceSignal?.aborted, true)
})
}

test("execution history keeps older pages reachable without fetching every run", async (context) => {
  const { ExecutionPanel } = await import("../ExecutionPanel.tsx")
  const requestedCursors = []
  const run = (id) => ({ id, trip_request_id: 1, status: "completed", model: "test", total_input_tokens: 0, total_output_tokens: 0, total_ms: 1, started_at: "2030-01-01T00:00:00Z", steps: [], events: [] })
  context.mock.method(globalThis, "fetch", async (url) => {
    const cursor = new URL(url).searchParams.get("before_run_id")
    requestedCursors.push(cursor)
    return response(cursor ? { agent_runs: [run(1)], next_before_run_id: null } : { agent_runs: [run(2)], next_before_run_id: 2 })
  })
  const view = render(createElement(ExecutionPanel, { trips: [], isRunActive: false }))
  await act(async () => {})
  assert.ok(view.getByText("Run #2"))
  assert.equal(view.getByRole("button", { name: "Newer runs" }).disabled, true)
  await act(async () => fireEvent.click(view.getByRole("button", { name: "Older runs" })))
  assert.ok(view.getByText("Run #1"))
  assert.equal(view.getByRole("button", { name: "Older runs" }).disabled, true)
  await act(async () => fireEvent.click(view.getByRole("button", { name: "Newer runs" })))
  assert.ok(view.getByText("Run #2"))
  assert.deepEqual(requestedCursors, [null, "2", null])
})
