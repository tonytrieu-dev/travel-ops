import "../test/setup.js"
import { deferred, response, session } from "../test/setup.js"
import assert from "node:assert/strict"
import test from "node:test"
import { act, renderHook } from "@testing-library/react"
const { useActiveTrip } = await import("./useActiveTrip.ts")

for (const firstAction of ["search", "plan"]) {
  test(`flight search and planning both complete when ${firstAction} starts first`, async (context) => {
    const pendingSearch = deferred(), pendingPlan = deferred()
    const flights = { offers: [{ id: 8 }] }
    const plan = { status: "ready", itinerary: { days: [] } }
    const signals = []
    context.mock.method(globalThis, "fetch", async (url, options) => {
      if (url.endsWith("/snapshot")) return response({ trip: { id: 1 }, flight_search: null, plan: null })
      if (url.endsWith("/trips")) return response([])
      signals.push(options.signal)
      if (url.endsWith("/flights/search")) return pendingSearch.promise
      if (url.endsWith("/plan")) return pendingPlan.promise
      throw Error(`unexpected ${url}`)
    })
    const hook = renderHook(() => useActiveTrip(true))
    await act(async () => { await hook.result.current.handleSelectTrip(1) })
    let searchRequest, planRequest
    const startSearch = () => { searchRequest = hook.result.current.handleSearchFlights() }
    const startPlan = () => { planRequest = hook.result.current.handleRequestPlan() }
    act(firstAction === "search" ? startSearch : startPlan)
    act(firstAction === "search" ? startPlan : startSearch)
    assert.ok(signals.every((signal) => !signal.aborted))
    await act(async () => { pendingSearch.resolve(response(flights)); await searchRequest })
    assert.deepEqual(hook.result.current.flightSearchResult, flights)
    assert.equal(hook.result.current.isSearchingFlights, false)
    assert.equal(hook.result.current.isPlanning, true)
    assert.equal(hook.result.current.isRunActive, true)
    await act(async () => { pendingPlan.resolve(response(plan)); await planRequest })
    assert.deepEqual(hook.result.current.planResult, plan)
    assert.equal(hook.result.current.isPlanning, false)
    assert.equal(hook.result.current.isRunActive, false)
  })
}

for (const invalidation of ["trip selection", "new search", "session replacement"]) {
  test(`${invalidation} discards concurrent flight search and planning results`, async (context) => {
    await session("original")
    const pendingSearch = deferred(), pendingPlan = deferred()
    context.mock.method(globalThis, "fetch", async (url) => {
      if (url.endsWith("/snapshot")) return response({ trip: { id: url.includes("/2/") ? 2 : 1 }, flight_search: null, plan: null })
      if (url.endsWith("/trips")) return response([])
      if (url.endsWith("/flights/search")) return pendingSearch.promise
      if (url.endsWith("/plan")) return pendingPlan.promise
      throw Error(`unexpected ${url}`)
    })
    const hook = renderHook(() => useActiveTrip(true))
    await act(async () => { await hook.result.current.handleSelectTrip(1) })
    let search, plan
    act(() => { search = hook.result.current.handleSearchFlights() })
    act(() => { plan = hook.result.current.handleRequestPlan() })
    await act(async () => {
      if (invalidation === "trip selection") hook.result.current.handleSelectTrip(2)
      if (invalidation === "new search") hook.result.current.handleStartNewSearch()
      if (invalidation === "session replacement") await session("replacement")
    })
    await act(async () => {
      pendingSearch.resolve(response({ offers: [{ id: 8 }] }))
      pendingPlan.resolve(response({ status: "needs_clarification", questions: ["Obsolete question"] }))
      await Promise.all([search, plan])
    })
    assert.equal(hook.result.current.trip?.id ?? null, invalidation === "trip selection" ? 2 : invalidation === "new search" ? null : 1)
    assert.equal(hook.result.current.flightSearchResult, null)
    assert.equal(hook.result.current.planResult, null)
    assert.equal(hook.result.current.flightSearchError, null)
    assert.equal(hook.result.current.planError, null)
    if (invalidation !== "session replacement") assert.equal(hook.result.current.isRunActive, false)
  })
}

for (const status of ["needs_clarification", "too_complex"]) {
  test(`a ${status} plan discards a still-pending flight search`, async (context) => {
    const pendingSearch = deferred()
    const flights = { offers: [{ id: 8 }] }
    context.mock.method(globalThis, "fetch", async (url) => {
      if (url.endsWith("/snapshot")) return response({ trip: { id: 1 }, flight_search: flights, plan: null })
      if (url.endsWith("/trips")) return response([])
      if (url.endsWith("/flights/search")) return pendingSearch.promise
      if (url.endsWith("/plan")) return response({ status })
      throw Error(`unexpected ${url}`)
    })
    const hook = renderHook(() => useActiveTrip(true))
    await act(async () => { await hook.result.current.handleSelectTrip(1) })
    let search
    act(() => { search = hook.result.current.handleSearchFlights() })
    act(() => hook.result.current.setSelectedOffer(flights.offers[0]))
    await act(async () => { await hook.result.current.handleRequestPlan() })
    assert.equal(hook.result.current.isSearchingFlights, false)
    await act(async () => { pendingSearch.resolve(response(flights)); await search })
    assert.equal(hook.result.current.planResult.status, status)
    assert.equal(hook.result.current.flightSearchResult, null)
    assert.equal(hook.result.current.selectedOffer, null)
    assert.equal(hook.result.current.isRunActive, false)
  })
}

test("a late initial list preserves local creations and older trips without duplicates", async (context) => {
  const pendingList = deferred()
  const created = { id: 17, destination: "London" }
  context.mock.method(globalThis, "fetch", async (url, options) => options?.method === "POST"
    ? response(created) : pendingList.promise)
  const hook = renderHook(() => useActiveTrip(true))
  await act(async () => { await hook.result.current.handleCreateTrip({}) })
  await act(async () => pendingList.resolve(response([{ ...created, destination: "stale" }, { id: 3 }])))
  assert.equal(hook.result.current.trip.id, 17)
  assert.deepEqual(hook.result.current.trips, [created, { id: 3 }])
})

for (const searchTiming of ["before clarification", "during update", "completed during update"]) {
for (const lateSearchFails of [false, true]) {
  test(`clarification discards old flights (${searchTiming}, failure=${lateSearchFails})`, async (context) => {
    const pendingSearch = deferred(), pendingUpdate = deferred(), pendingPlan = deferred()
    const originalTrip = { id: 1, destination_airport: "ONT" }
    const oldFlights = { offers: [{ id: 8 }] }
    context.mock.method(globalThis, "fetch", async (url, options) => {
      if (url.endsWith("/snapshot")) return response({ trip: originalTrip, flight_search: oldFlights, plan: null })
      if (url.endsWith("/flights/search")) return pendingSearch.promise
      if (options?.method === "PATCH") return pendingUpdate.promise
      if (url.endsWith("/plan")) return pendingPlan.promise
      if (url.endsWith("/trips")) return response([originalTrip])
      throw Error(`unexpected ${options?.method} ${url}`)
    })
    const hook = renderHook(() => useActiveTrip(true))
    await act(async () => { await hook.result.current.handleSelectTrip(1) })
    let search, plan
    const startSearch = () => { search = hook.result.current.handleSearchFlights() }
    if (searchTiming === "before clarification") {
      act(startSearch)
      act(() => hook.result.current.setSelectedOffer(oldFlights.offers[0]))
    }
    act(() => { plan = hook.result.current.handleAnswerClarification({ destination_airport: "LHR" }) })
    if (searchTiming !== "before clarification") act(startSearch)
    if (searchTiming === "completed during update") {
      await act(async () => {
        pendingSearch.resolve(lateSearchFails ? response({ detail: "obsolete search failed" }, 500) : response(oldFlights))
        await search
      })
      if (!lateSearchFails) act(() => hook.result.current.setSelectedOffer(oldFlights.offers[0]))
    }
    await act(async () => pendingUpdate.resolve(response({ ...originalTrip, destination_airport: "LHR" })))
    assert.equal(hook.result.current.flightSearchResult, null)
    assert.equal(hook.result.current.selectedOffer, null)
    assert.equal(hook.result.current.isSearchingFlights, false)
    await act(async () => {
      pendingSearch.resolve(lateSearchFails ? response({ detail: "obsolete search failed" }, 500) : response(oldFlights))
      await search
    })
    await act(async () => { pendingPlan.resolve(response({ status: "ready", itinerary: { days: [] } })); await plan })
    assert.equal(hook.result.current.trip.destination_airport, "LHR")
    assert.equal(hook.result.current.planResult.status, "ready")
    assert.equal(hook.result.current.flightSearchResult, null)
    assert.equal(hook.result.current.selectedOffer, null)
    assert.equal(hook.result.current.flightSearchError, null)
    assert.equal(hook.result.current.isPlanning, false)
  })
}
}

test("an obsolete create cannot clear the latest create's loading state", async (context) => {
  const first = deferred(), second = deferred()
  let creates = 0
  context.mock.method(globalThis, "fetch", async (url, options) => options?.method === "POST"
    ? (++creates === 1 ? first.promise : second.promise) : response([]))
  const hook = renderHook(() => useActiveTrip(true))
  await act(async () => {})
  let firstRequest, secondRequest
  act(() => { firstRequest = hook.result.current.handleCreateTrip({}) })
  act(() => { secondRequest = hook.result.current.handleCreateTrip({}) })
  await act(async () => { first.resolve(response({ id: 1 })); await firstRequest })
  assert.equal(hook.result.current.isCreatingTrip, true)
  await act(async () => { second.resolve(response({ id: 2 })); await secondRequest })
  assert.equal(hook.result.current.trip.id, 2)
  assert.equal(hook.result.current.isCreatingTrip, false)
})

test("a trip action from a replaced session cannot publish its result", async (context) => {
  await session("original")
  const pending = deferred()
  context.mock.method(globalThis, "fetch", async (url, options) => options?.method === "POST" ? pending.promise : response([]))
  const hook = renderHook(() => useActiveTrip(true))
  await act(async () => {})
  let request
  act(() => { request = hook.result.current.handleCreateTrip({}) })
  await session("replacement")
  await act(async () => { pending.resolve(response({ id: 9 })); await request })
  assert.equal(hook.result.current.trip, null)
  assert.equal(localStorage.getItem("travel-agent.activeTripId"), null)
})
