from functools import partial

import httpx
import pytest

from app.adapters.flights_searchapi import LiveSearchApiProvider, NormalizedFlightOffer


pytestmark = pytest.mark.no_database


@pytest.mark.parametrize(
    "nonstop_result", ["empty", "http_error", "network_error", "paired", "all_failed"],
)
async def test_round_trip_tries_connecting_only_when_nonstop_cannot_pair(
    monkeypatch: pytest.MonkeyPatch, nonstop_result: str,
) -> None:
    outbound_leg = {"airline": "Test Air", "departure_airport": {"id": "JFK"},
                    "arrival_airport": {"id": "CDG"}}
    return_leg = {"airline": "Test Air", "departure_airport": {"id": "CDG"},
                  "arrival_airport": {"id": "JFK"}}
    connecting_legs = [
        {**outbound_leg, "arrival_airport": {"id": "LHR"}},
        {**outbound_leg, "departure_airport": {"id": "LHR"}},
    ]
    requested_tokens: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        departure_token = request.url.params.get("departure_token")
        if departure_token is None:
            return httpx.Response(200, json={"best_flights": [
                {"flights": [outbound_leg], "price": 100, "departure_token": "nonstop"},
                {"flights": connecting_legs, "price": 200,
                 "departure_token": "connecting"},
            ]})
        requested_tokens.append(departure_token)
        if nonstop_result == "all_failed":
            return httpx.Response(200, json={})
        if departure_token == "nonstop" and nonstop_result == "empty":
            return httpx.Response(200, json={})
        if departure_token == "nonstop" and nonstop_result == "http_error":
            return httpx.Response(500, text="upstream failure")
        if departure_token == "nonstop" and nonstop_result == "network_error":
            raise httpx.ConnectError("upstream unavailable", request=request)
        return httpx.Response(200, json={"best_flights": [
            {"flights": [return_leg], "price": 350,
             "booking_token": f"book-{departure_token}"},
        ]})

    monkeypatch.setattr(httpx, "AsyncClient", partial(
        httpx.AsyncClient, transport=httpx.MockTransport(respond),
    ))

    outcome = await LiveSearchApiProvider("test-key").search_offers(
        "JFK", "CDG", "2026-12-01", "2026-12-08",
    )

    if nonstop_result == "all_failed":
        assert requested_tokens == ["nonstop", "connecting"]
        assert outcome.offers == []
        assert outcome.unavailable_reason == (
            "searchapi could not resolve exact round-trip offers: "
            "searchapi returned no return-leg options for departure_token=connecting"
        )
        return

    expected_token = "nonstop" if nonstop_result == "paired" else "connecting"
    assert requested_tokens == (["nonstop"] if expected_token == "nonstop"
                                else ["nonstop", "connecting"])
    assert outcome.unavailable_reason is None
    assert len(outcome.offers) == 1
    offer = outcome.offers[0]
    assert offer.booking_token == f"book-{expected_token}"
    assert offer.price_usd == 350
    assert offer.stops == (0 if expected_token == "nonstop" else 1)
    assert offer.raw_offer["return_flights"] == [return_leg]
    assert offer.raw_offer["booking_token"] == offer.booking_token


async def test_round_trip_tries_nonstop_candidates_beyond_the_cheapest_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = LiveSearchApiProvider("test-key")
    offers = [
        NormalizedFlightOffer(
            carrier="Test Air", price_usd=price, currency="USD", depart_at="2026-12-01T09:00",
            arrive_at="2026-12-01T10:00", stops=0, booking_token=f"token-{price}", raw_offer={},
        )
        for price in (100, 200, 300, 400)
    ]

    async def resolve_return_offer(booking_token: str, **_: str) -> NormalizedFlightOffer:
        if booking_token != "token-400":
            raise RuntimeError("candidate cannot form a return trip")
        return NormalizedFlightOffer(
            carrier="Test Air", price_usd=450, currency="USD", depart_at="2026-12-08T09:00",
            arrive_at="2026-12-08T10:00", stops=0, booking_token="book-400",
            raw_offer={"flights": [{"flight_number": "TA400"}]},
        )

    monkeypatch.setattr(provider, "_resolve_return_offer", resolve_return_offer)
    outcome = await provider._resolve_round_trip(
        offers, "JFK", "CDG", "2026-12-01", "2026-12-08"
    )

    assert [offer.booking_token for offer in outcome.offers] == ["book-400"]


async def test_malformed_success_payload_returns_unavailable_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leg = {
        "airline": "Test Air",
        "departure_airport": {"id": "JFK"},
        "arrival_airport": {"id": "CDG"},
    }

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "best_flights": [{"flights": [leg], "price": {"unexpected": True}, "departure_token": "x"}],
        })

    monkeypatch.setattr(httpx, "AsyncClient", partial(
        httpx.AsyncClient, transport=httpx.MockTransport(respond),
    ))

    outcome = await LiveSearchApiProvider("test-key").search_offers(
        "JFK", "CDG", "2026-12-01", None,
    )

    assert outcome.offers == []
    assert outcome.unavailable_reason is not None
    assert "malformed data" in outcome.unavailable_reason
