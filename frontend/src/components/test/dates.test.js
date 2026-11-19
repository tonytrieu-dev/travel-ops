import "../../test/setup.js"
import assert from "node:assert/strict"
import test from "node:test"
import { createElement } from "react"
import { fireEvent, render } from "@testing-library/react"
const { YourTripsPanel } = await import("../YourTripsPanel.tsx")

// UTC midnight renders the previous day in this timezone; trip dates must keep the entered day.
test("date-only trip dates render the entered calendar day in a negative-offset timezone", () => {
  process.env.TZ = "America/Los_Angeles"

  const trip = {
    id: 1, origin: "JFK", destination: "Tokyo", destination_airport: "HND",
    depart_date: "2026-11-10", return_date: "2026-11-20", age: 30, fitness_level: "high",
    status: "created", created_at: new Date(Date.now() + 86_400_000).toISOString(),
  }
  const view = render(createElement(YourTripsPanel, { trips: [trip], selectedTripId: null, onSelectTrip: () => {} }))
  const cells = [...view.container.querySelectorAll("td")].map((cell) => cell.textContent)
  assert.ok(cells.includes("11/10/2026"), `depart date must render 11/10/2026, got ${JSON.stringify(cells)}`)
  assert.ok(cells.includes("11/20/2026"), "return date must render the entered day")
})

test("trip selection is exposed as a keyboard-accessible button", () => {
  let selected = null
  const trip = {
    id: 7, origin: "JFK", destination: "Tokyo", destination_airport: "HND",
    depart_date: "2026-11-10", return_date: "2026-11-20", age: 30, fitness_level: "high",
    status: "created", created_at: new Date().toISOString(),
  }
  const view = render(createElement(YourTripsPanel, { trips: [trip], selectedTripId: null, onSelectTrip: (id) => { selected = id } }))
  const button = view.getByRole("button", { name: "JFK → HND" })
  assert.equal(button.tagName, "BUTTON")
  fireEvent.click(button)
  assert.equal(selected, 7)
})
