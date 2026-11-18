from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.models import FitnessLevel
from app.schemas import TripRequestCreate

pytestmark = pytest.mark.no_database


def test_trip_departure_uses_demo_business_timezone() -> None:
    class FrozenDateTime:
        @classmethod
        def now(cls, timezone: ZoneInfo) -> datetime:
            assert timezone == ZoneInfo("America/Los_Angeles")
            return datetime(2000, 1, 1, 23, 30, tzinfo=timezone)

    with patch("app.schemas.datetime", FrozenDateTime):
        TripRequestCreate(
            origin="SFO",
            destination="Paris",
            destination_airport="CDG",
            depart_date="2000-01-01",
            age=30,
            fitness_level=FitnessLevel.MODERATE,
        )
