import "./test/setup.js"
import { deferred, response } from "./test/setup.js"
import assert from "node:assert/strict"
import test from "node:test"
import { createElement } from "react"
import { render, act, fireEvent } from "@testing-library/react"
const { LoginPanel, default: App } = await import("./App.tsx")

for (const role of ["trip-planner", "traveler"]) {
  test(`${role} booking controls follow booking permissions after selecting a flight`, async (context) => {
    localStorage.setItem("travel-agent.activeTripId", "1")
    const trip = { id: 1, origin: "OAK", destination: "London", destination_airport: "LHR", depart_date: "2030-08-01" }
    const offer = { id: 5, carrier: "Test Air", price_usd: 100, currency: "USD", stops: 0, legs: [], depart_at: "2030-08-01T10:00:00Z", arrive_at: "2030-08-01T14:00:00Z" }
    let bookingRequests = 0
    context.mock.method(globalThis, "fetch", async (url) => {
      if (url.endsWith("/auth/config")) return response({ enforced: true })
      if (url.endsWith("/auth/browser/session")) return response({ session_id: role, role, mfa_verified: true })
      if (url.endsWith("/trips")) return response([trip])
      if (url.endsWith("/snapshot")) return response({ trip, flight_search: { offers: [offer] }, plan: null })
      if (url.endsWith("/booking/request")) { bookingRequests += 1; return response({ id: 2, state: "PENDING_USER_CONFIRMATION" }) }
      if (url.endsWith("/execution")) return response({ agent_runs: [], events: [] })
      throw Error(`unexpected request: ${url}`)
    })
    const view = render(createElement(App))
    await act(async () => {})
    fireEvent.click(view.getByRole("radio"))
    assert.ok(view.getByRole("heading", { name: "Itinerary" }))
    if (role === "trip-planner") {
      assert.equal(view.queryByRole("heading", { name: "Continue to airline booking" }), null)
      assert.equal(view.queryByRole("button", { name: "Review booking" }), null)
    } else {
      await act(async () => fireEvent.click(view.getByRole("button", { name: "Review booking" })))
      assert.ok(view.getByRole("button", { name: "Approve this flight" }))
    }
    assert.equal(bookingRequests, role === "trip-planner" ? 0 : 1)
  })
}

for (const role of ["traveler", "trip-planner", "security-operator", "platform-operator", "admin"]) {
  test(`${role} navigation follows the verified session role`, async (context) => {
    const requests = []
    context.mock.method(globalThis, "fetch", async (url) => {
      requests.push(url)
      if (url.endsWith("/auth/config")) return response({ enforced: true })
      if (url.endsWith("/auth/browser/session")) return response({ session_id: role, role, mfa_verified: true })
      if (url.endsWith("/trips")) return response([])
      if (url.endsWith("/monitoring")) return response({ stale: false, assessments: [] })
      if (url.endsWith("/connectors")) return response({ slack: { configured: false, enabled: false } })
      throw Error(`unexpected request: ${url}`)
    })
    const view = render(createElement(App))
    await act(async () => {})
    const history = ["trip-planner", "admin"].includes(role)
    const security = ["security-operator", "platform-operator", "admin"].includes(role)
    assert.equal(!!view.queryByRole("button", { name: "Agent execution history" }), history)
    assert.equal(!!view.queryByRole("button", { name: "Approval history" }), history)
    assert.equal(!!view.queryByRole("button", { name: "Security monitoring" }), security)
    assert.equal(!!view.queryByRole("button", { name: "Connectors" }), ["security-operator", "admin"].includes(role))
    if (role === "traveler") assert.equal(requests.some((url) => /connectors|execution|monitoring|bookings/.test(url)), false)
  })
}

// F8: an expired/failed MFA challenge must be recoverable without a page reload.
test("MFA restart returns to the email/password step", async (context) => {
  context.mock.method(globalThis, "fetch", async (url, init) => {
    if (url.endsWith("/auth/browser/login")) return response({ mfa_required: true, session_id: "s1", access_token: "", expires_at: "" })
    if (url.endsWith("/auth/browser/mfa")) return response({ code: "forbidden", detail: "challenge expired" }, 403)
    throw new Error(`unexpected ${init?.method} ${url}`)
  })
  const view = render(createElement(LoginPanel, { onAuthenticated: () => {} }))
  fireEvent.change(view.getByLabelText("Password"), { target: { value: "demo-password" } })
  await act(async () => fireEvent.submit(view.getByText("Continue to MFA").closest("form")))
  assert.ok(view.getByLabelText("MFA code"), "reached the MFA step")
  await act(async () => fireEvent.submit(view.getByText("Verify and sign in").closest("form")))
  assert.match(view.getByRole("alert").textContent, /challenge expired/)

  fireEvent.click(view.getByText("Start over"))
  assert.ok(view.getByLabelText("Email"), "restart returns to the email/password step")
  assert.equal(view.queryByLabelText("MFA code"), null)
})

// F4: a plan that resolves for a previously selected trip must not overwrite the trip the user
// has since selected.
test("a stale plan response does not overwrite the newly selected trip", async (context) => {
  const slowPlan = deferred()
  context.mock.method(globalThis, "fetch", async (url, init) => {
    const { pathname } = new URL(url, "http://localhost")
    if (pathname.endsWith("/auth/config")) return response({ enforced: false })
    if (pathname === "/api/trips" && init?.method !== "POST")
      return response([
        { id: 1, origin: "JFK", destination: "Tokyo", destination_airport: "HND", depart_date: "2030-08-01", return_date: null, age: 30, fitness_level: "high", status: "created", created_at: "2030-01-02T00:00:00Z" },
        { id: 2, origin: "JFK", destination: "London", destination_airport: "LHR", depart_date: "2030-08-01", return_date: null, age: 30, fitness_level: "high", status: "created", created_at: "2030-01-01T00:00:00Z" },
      ])
    if (pathname === "/api/trips/1/snapshot")
      return response({ trip: { id: 1, origin: "JFK", destination: "Tokyo", destination_airport: "HND", depart_date: "2030-08-01", return_date: null, age: 30, fitness_level: "high", status: "created", created_at: "2030-01-02T00:00:00Z" }, flight_search: null, plan: null })
    if (pathname === "/api/trips/2/snapshot")
      return response({ trip: { id: 2, origin: "JFK", destination: "London", destination_airport: "LHR", depart_date: "2030-08-01", return_date: null, age: 30, fitness_level: "high", status: "created", created_at: "2030-01-01T00:00:00Z" }, flight_search: null, plan: null })
    if (pathname === "/api/trips/1/plan") return slowPlan.promise
    throw new Error(`unexpected ${init?.method ?? "GET"} ${pathname}`)
  })

  const view = render(createElement(App))
  await act(async () => {})
  await act(async () => {})

  // Select trip 1 (Tokyo/HND), start planning it (plan stays in flight).
  fireEvent.click(view.getByText("Your trips"))
  await act(async () => fireEvent.click(view.getByText(/HND/)))
  await act(async () => fireEvent.click(view.getByText("Plan itinerary")))

  // Switch to trip 2 (London/LHR) while trip 1's plan is still pending.
  fireEvent.click(view.getByText("Your trips"))
  await act(async () => fireEvent.click(view.getByText(/LHR/)))
  assert.match(view.container.textContent, /LHR/)
  assert.equal(view.getByRole("button", { name: "Plan itinerary" }).disabled, false)

  // Trip 1's plan finally resolves needing clarification — it must not land on London.
  await act(async () => slowPlan.resolve(response({ status: "needs_clarification", questions: ["Which Tokyo?"] })))
  assert.doesNotMatch(view.container.textContent, /Which Tokyo\?/, "stale plan must not render under the new trip")
  assert.equal(view.getByRole("button", { name: "Plan itinerary" }).disabled, false)
})

for (const fails of [false, true]) {
  test(`trip actions wait for the selected snapshot (failure=${fails})`, async (context) => {
    const snapshot = deferred()
    const trip = (id) => ({
      id, origin: "JFK", destination: id === 1 ? "Tokyo" : "London",
      destination_airport: id === 1 ? "HND" : "LHR", depart_date: "2030-08-01",
      return_date: null, age: 30, fitness_level: "high", status: "created",
      created_at: "2030-01-01T00:00:00Z",
    })
    context.mock.method(globalThis, "fetch", async (url) => {
      const path = new URL(url, "http://localhost").pathname
      if (path.endsWith("/auth/config")) return response({ enforced: false })
      if (path === "/api/trips") return response([trip(1), trip(2)])
      if (path === "/api/trips/1/snapshot") return response({ trip: trip(1), flight_search: null, plan: null })
      if (path === "/api/trips/2/snapshot") return snapshot.promise
      throw Error(`unexpected request during switch: ${path}`)
    })
    const view = render(createElement(App))
    await act(async () => {})
    await act(async () => {})
    fireEvent.click(view.getByText("Your trips"))
    await act(async () => fireEvent.click(view.getByText(/HND/)))
    fireEvent.click(view.getByText("Your trips"))
    await act(async () => fireEvent.click(view.getByText(/LHR/)))
    assert.equal(view.queryByText("Plan itinerary"), null)
    assert.equal(view.queryByText("Search flights"), null)
    assert.match(view.getByRole("status").textContent, /Loading trip/)
    await act(async () => snapshot.resolve(fails
      ? response({ detail: "snapshot unavailable" }, 500)
      : response({ trip: trip(2), flight_search: null, plan: null })))
    assert.ok(view.getByText("Plan itinerary"))
    assert.match(view.container.textContent, fails ? /HND/ : /LHR/)
    if (fails) assert.match(view.getByRole("alert").textContent, /snapshot unavailable/)
  })
}
