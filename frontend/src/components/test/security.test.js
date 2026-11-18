import "../../test/setup.js"
import { deferred, response } from "../../test/setup.js"
import assert from "node:assert/strict"
import test from "node:test"
import { createElement } from "react"
import { render, act, fireEvent } from "@testing-library/react"
const { BookingModule } = await import("../BookingModule.tsx")

test("a booking poll slower than the cadence completes without being aborted", async (context) => {
  const pendingPoll = deferred()
  const booking = { id: 1, state: "PENDING_USER_CONFIRMATION" }
  let poll, pollSignal, requests = 0
  context.mock.method(globalThis, "setInterval", (callback) => { poll = callback; return 1 })
  context.mock.method(globalThis, "clearInterval", () => {})
  context.mock.method(globalThis, "fetch", async (url, options) => {
    if (url.endsWith("/auth/config")) return response({ enforced: true })
    if (url.endsWith("/booking/request")) return response(booking)
    if (url.endsWith("/bookings/1")) {
      requests += 1
      pollSignal = options.signal
      return pendingPoll.promise
    }
    throw Error(`unexpected request: ${url}`)
  })
  const view = render(createElement(BookingModule, {
    trip: { id: 1 }, selectedOffer: { id: 1, carrier: "Test Air", price_usd: 100, currency: "USD" },
  }))
  await act(async () => fireEvent.click(view.getByRole("button", { name: "Review booking" })))
  let polling
  act(() => { polling = poll() })
  const originalSignal = pollSignal
  act(() => { poll(); poll() })
  assert.equal(requests, 1)
  assert.equal(originalSignal.aborted, false)
  await act(async () => { pendingPoll.resolve(response({ ...booking, state: "CONFIRMED" })); await polling })
  assert.ok(view.getByRole("button", { name: "Continue to airline" }))
  assert.equal(view.queryByRole("button", { name: "Approve this flight" }), null)
})

test("a pending booking poll cannot undo an approval", async (context) => {
    const pendingPoll = deferred()
    const booking = { id: 1, state: "PENDING_USER_CONFIRMATION" }
    let poll
    context.mock.method(globalThis, "setInterval", (callback) => { poll = callback; return 1 })
    context.mock.method(globalThis, "clearInterval", () => {})
    context.mock.method(globalThis, "fetch", async (url) => {
      if (url.endsWith("/auth/config")) return response({ enforced: true })
      if (url.endsWith("/bookings/1")) return pendingPoll.promise
      if (url.endsWith("/confirm")) return response({ ...booking, state: "CONFIRMED" })
      if (url.endsWith("/execute")) return response({ ...booking, state: "EXECUTED" })
      if (url.endsWith("/cancel")) return response({ ...booking, state: "CANCELLED" })
      if (url.endsWith("/booking/request")) return response(booking)
      throw Error(`unexpected request: ${url}`)
    })
    const view = render(createElement(BookingModule, {
      trip: { id: 1 }, selectedOffer: { id: 1, carrier: "Test Air", price_usd: 100, currency: "USD" },
    }))
    await act(async () => fireEvent.click(view.getByRole("button", { name: "Review booking" })))
    let polling
    act(() => { polling = poll() })
    await act(async () => fireEvent.click(view.getByRole("button", { name: "Approve this flight" })))
    const terminalMessage = /Your flight hasn't been purchased/
    assert.match(view.container.textContent, terminalMessage)
    await act(async () => { pendingPoll.resolve(response(booking)); await polling })
    assert.match(view.container.textContent, terminalMessage)
    assert.equal(view.queryByRole("button", { name: "Approve this flight" }), null)
  })
