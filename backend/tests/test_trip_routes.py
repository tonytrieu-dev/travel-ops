"""Trip route boundaries that are easy to regress without an endpoint-level check."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

from sqlalchemy import text

from app.models import ExecutionEvent, ExecutionEventKind
from tests.db_helpers import get_flight_search_results, get_trip, run_db, seed_trip


def _trip_payload(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "origin": "JFK",
        "destination": "Paris",
        "destination_airport": "CDG",
        "depart_date": "2030-08-01",
        "age": 30,
        "fitness_level": "moderate",
    }
    payload.update(overrides)
    return payload


def test_list_trips_returns_only_the_authenticated_users_trips_newest_first(client) -> None:
    """A trip seeded under a different user (e.g. another demo session) must not leak into this
    user's sidebar, and the user's own trips must come back newest-created first so the most
    recently started trip lands at the top of the list."""
    other_users_trip_id = run_db(lambda session: seed_trip(session, depart_date="2026-09-01"))

    first_created = client.post("/api/trips", json=_trip_payload(destination_airport="CDG")).json()
    second_created = client.post("/api/trips", json=_trip_payload(destination_airport="LHR")).json()

    async def tie_creation_times(session):
        first = await get_trip(session, first_created["id"])
        second = await get_trip(session, second_created["id"])
        second.created_at = first.created_at
        await session.commit()

    run_db(tie_creation_times)
    response = client.get("/api/trips")

    assert response.status_code == 200, f"expected 200, got {response.status_code}: {response.text}"
    trip_ids = [trip["id"] for trip in response.json()]
    assert other_users_trip_id not in trip_ids, (
        "GET /api/trips must scope to the authenticated user, not return every trip in the DB"
    )
    assert trip_ids[:2] == [second_created["id"], first_created["id"]], (
        f"expected the two most recently created trips newest-first, got {trip_ids}"
    )


def test_patch_nulling_a_required_field_is_422_not_500(client) -> None:
    """Sending an explicit null for a required field used to reach the DB and 500 on the NOT NULL
    insert (or silently corrupt the trip). It must be rejected at the boundary as a 422, and the
    stored value must be left untouched."""
    trip_id = run_db(lambda session: seed_trip(session, depart_date="2026-09-01"))

    response = client.patch(f"/api/trips/{trip_id}", json={"origin": None})

    assert response.status_code == 422, f"expected 422, got {response.status_code}: {response.text}"
    assert response.json()["code"] == "validation_error"
    trip = run_db(lambda session: get_trip(session, trip_id))
    assert trip.origin == "JFK", (
        f"a rejected PATCH must not persist the null origin, found {trip.origin!r}"
    )


def test_flight_search_finalizes_live_cached_and_failed_runs(client, flight_search_spy, monkeypatch):
    trip = client.post("/api/trips", json=_trip_payload()).json()
    search_url = f"/api/trips/{trip['id']}/flights/search"
    for _ in range(2):
        assert client.post(search_url).status_code == 200
    assert flight_search_spy.calls == 1

    runs = client.get(f"/api/trips/{trip['id']}/execution").json()["agent_runs"]
    assert len(runs) == 2
    for run in runs:
        assert run["status"] == "completed" and run["finished_at"] is not None
        assert [step["name"] for step in run["steps"]] == ["search_flights"]
        assert [event["name"] for event in run["events"]] == ["search_flights"]

    async def fail_search(*arguments, **keywords):
        raise RuntimeError("provider unavailable before recording a result")

    monkeypatch.setattr(flight_search_spy, "search_offers", fail_search)
    other_trip = client.post("/api/trips", json=_trip_payload(destination_airport="SFO")).json()
    assert client.post(f"/api/trips/{other_trip['id']}/flights/search").status_code == 500
    failed_runs = client.get(f"/api/trips/{other_trip['id']}/execution").json()["agent_runs"]
    assert len(failed_runs) == 1
    assert failed_runs[0]["status"] == "failed" and failed_runs[0]["finished_at"] is not None
    assert failed_runs[0]["steps"] == []


def test_concurrent_flight_searches_have_separate_execution_runs(
    client, flight_search_spy, monkeypatch
) -> None:
    trip = client.post("/api/trips", json=_trip_payload()).json()
    search_url = f"/api/trips/{trip['id']}/flights/search"
    started, release = Event(), Event()
    original_search = flight_search_spy.search_offers

    async def synchronized_search(*arguments, **keywords):
        started.set()
        assert await asyncio.to_thread(release.wait, 10), "flight search was never released"
        return await original_search(*arguments, **keywords)

    monkeypatch.setattr(flight_search_spy, "search_offers", synchronized_search)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(client.post, search_url)
        try:
            assert started.wait(10), "first flight search never started"
            second = executor.submit(client.post, search_url)
            deadline = monotonic() + 5
            while not run_db(lambda session: session.scalar(text(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                "WHERE datname = current_database() AND cardinality(pg_blocking_pids(pid)) > 0)"
            ))):
                assert not second.done(), "second search bypassed the trip lock"
                assert monotonic() < deadline, "second search never waited for the first transaction"
                sleep(0.01)
        finally:
            release.set()
        responses = [first.result(timeout=15), second.result(timeout=15)]

    assert [response.status_code for response in responses] == [200, 200]
    assert flight_search_spy.calls == 1
    offers = responses[0].json()["offers"]
    assert offers
    assert responses[1].json()["offers"] == offers
    stored_offers = run_db(lambda session: get_flight_search_results(session, trip["id"]))
    assert {offer.id for offer in stored_offers} == {offer["id"] for offer in offers}
    runs = client.get(f"/api/trips/{trip['id']}/execution").json()["agent_runs"]
    assert len(runs) == 2
    assert len({run["id"] for run in runs}) == 2
    for run in runs:
        assert run["status"] == "completed" and run["finished_at"] is not None
        assert [step["name"] for step in run["steps"]] == ["search_flights"]
        assert [event["name"] for event in run["events"]] == ["search_flights"]


def test_execution_history_pages_owned_runs_with_matching_details(client) -> None:
    from tests.db_helpers import seed_agent_run, seed_execution_event

    trip = client.post("/api/trips", json=_trip_payload()).json()

    async def seed_history(session):
        other_trip_id = await seed_trip(session)
        first = await seed_agent_run(session, trip["id"])
        second = await seed_agent_run(session, trip["id"])
        await seed_agent_run(session, other_trip_id)
        await seed_execution_event(session, trip["id"], agent_run_id=first, name="older")
        await seed_execution_event(session, trip["id"], agent_run_id=second, name="newer")
        return first, second

    first, second = run_db(seed_history)
    page = client.get("/api/execution?page_size=1").json()
    assert [run["id"] for run in page["agent_runs"]] == [second]
    assert [event["name"] for event in page["agent_runs"][0]["events"]] == ["newer"]
    assert len(page["agent_runs"][0]["steps"]) == 1
    assert page["next_before_run_id"] == second
    page = client.get(f"/api/execution?page_size=1&before_run_id={second}").json()
    assert [run["id"] for run in page["agent_runs"]] == [first]
    assert [event["name"] for event in page["agent_runs"][0]["events"]] == ["older"]
    assert page["next_before_run_id"] is None
    for query in ("page_size=0", "page_size=101", "before_run_id=-1"):
        assert client.get(f"/api/execution?{query}").status_code == 422


def test_trip_execution_caps_flat_event_history(client) -> None:
    trip = client.post("/api/trips", json=_trip_payload()).json()

    async def seed_events(session):
        session.add_all(
            [
                ExecutionEvent(
                    trip_request_id=trip["id"],
                    seq=sequence,
                    kind=ExecutionEventKind.API_CALL,
                    name=f"event-{sequence}",
                    status="ok",
                    detail="test event",
                )
                for sequence in range(1, 1002)
            ]
        )
        await session.commit()

    run_db(seed_events)

    response = client.get(f"/api/trips/{trip['id']}/execution")

    assert response.status_code == 200, response.text
    events = response.json()["events"]
    assert len(events) == 1000
    assert events[0]["seq"] == 1
    assert events[-1]["seq"] == 1000
