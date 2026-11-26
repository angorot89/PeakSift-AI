"""Posting times: weekly slots in the creator's time zone, and which ones are still free."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.services.publishing import slots
from app.services.publishing.slots import Slot, SlotError, normalize, stored, upcoming

PASSWORD = "correct horse battery"
CASABLANCA = ZoneInfo("Africa/Casablanca")
# Exact UTC assertions use a zone whose offset never changes (UTC+1): Morocco's own rules have
# changed more than once, and these tests must not depend on the tz database's current answer.
LAGOS = ZoneInfo("Africa/Lagos")
NEW_YORK = ZoneInfo("America/New_York")
THURSDAY = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)  # a Thursday


def test_slots_are_validated_deduplicated_and_ordered():
    assert normalize(
        [
            {"weekday": 4, "time": "19:30"},
            {"weekday": 0, "time": "07:00"},
            {"weekday": 4, "time": "19:30"},
            {"weekday": 4, "time": "07:00"},
        ]
    ) == [Slot(0, time(7, 0)), Slot(4, time(7, 0)), Slot(4, time(19, 30))]


@pytest.mark.parametrize(
    "bad",
    [
        [{"weekday": 7, "time": "10:00"}],
        [{"weekday": -1, "time": "10:00"}],
        [{"weekday": True, "time": "10:00"}],
        [{"weekday": 1, "time": "25:00"}],
        [{"weekday": 1, "time": "7:30"}],
        [{"weekday": 1, "time": "noon"}],
        [{"weekday": 1}],
        ["monday 10:00"],
        [{"weekday": d, "time": f"{h:02d}:00"} for d in range(7) for h in range(5)],  # 35 > 28
    ],
)
def test_bad_slots_are_refused(bad):
    with pytest.raises(SlotError):
        normalize(bad)


def test_unreadable_saved_slots_read_as_none():
    assert stored(None) == [] and stored("x") == [] and stored([{"weekday": 9}]) == []
    assert stored([{"weekday": 1, "time": "10:00"}]) == [Slot(1, time(10, 0))]


def test_unknown_time_zones_are_refused():
    assert slots.timezone("Africa/Casablanca") == CASABLANCA
    for name in (None, "", "Mars/Olympus", "x" * 80):
        with pytest.raises(SlotError):
            slots.timezone(name)


def test_upcoming_slots_are_in_order_in_utc():
    friday_evening = [Slot(4, time(19, 30)), Slot(0, time(7, 0))]

    times = upcoming(friday_evening, LAGOS, THURSDAY, count=3)

    assert [moment.astimezone(LAGOS).strftime("%a %H:%M") for moment in times] == [
        "Fri 19:30", "Mon 07:00", "Fri 19:30",
    ]  # fmt: skip
    assert all(moment.tzinfo == UTC for moment in times) and times == sorted(times)
    assert times[0] == datetime(2026, 11, 27, 18, 30, tzinfo=UTC)  # UTC+1

    # Whatever a zone's rules are, a slot is always at its wall-clock time there.
    local = upcoming(friday_evening, CASABLANCA, THURSDAY, count=4)
    assert {m.astimezone(CASABLANCA).strftime("%a %H:%M") for m in local} == {
        "Fri 19:30", "Mon 07:00",
    }  # fmt: skip


def test_a_slot_too_soon_or_already_taken_is_skipped():
    today = [Slot(3, time(13, 5)), Slot(3, time(20, 0))]  # Thursday 13:05 and 20:00 local

    # 12:00 UTC is 13:00 in Lagos: 13:05 is five minutes away — no time to review.
    first = upcoming(today, LAGOS, THURSDAY, count=1)[0]
    assert first.astimezone(LAGOS).strftime("%a %H:%M") == "Thu 20:00"

    taken = [first + timedelta(seconds=20)]  # a post scheduled in that slot
    after = upcoming(today, LAGOS, THURSDAY, taken=taken, count=2)
    assert [m.astimezone(LAGOS).strftime("%d %H:%M") for m in after] == ["03 13:05", "03 20:00"]


def test_a_slot_keeps_its_wall_clock_time_across_a_clock_change():
    """New York leaves daylight time on 1 November 2026: 09:00 stays 09:00."""
    before_change = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)

    saturday, next_saturday = upcoming([Slot(5, time(9, 0))], NEW_YORK, before_change, count=2)

    assert saturday == datetime(2026, 10, 31, 13, 0, tzinfo=UTC)  # UTC-4
    assert next_saturday == datetime(2026, 11, 7, 14, 0, tzinfo=UTC)  # UTC-5
    assert {m.astimezone(NEW_YORK).hour for m in (saturday, next_saturday)} == {9}


def test_no_slots_means_no_suggestions():
    assert upcoming([], CASABLANCA, THURSDAY) == []
    assert upcoming([Slot(1, time(9, 0))], CASABLANCA, THURSDAY, count=0) == []


# --- the API ------------------------------------------------------------------------------


def sign_up(client: TestClient, email: str = "owner@example.com") -> None:
    response = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201


def test_requires_authentication(client: TestClient):
    assert client.get("/posting-slots").status_code == 401
    assert client.put("/posting-slots", json={"timezone": "UTC", "slots": []}).status_code == 401


def test_a_creator_starts_without_posting_times(client: TestClient):
    sign_up(client)
    assert client.get("/posting-slots").json() == {"timezone": None, "slots": [], "upcoming": []}


def test_saving_posting_times_offers_the_next_free_ones(client: TestClient):
    sign_up(client)
    body = {
        "timezone": "Africa/Casablanca",
        "slots": [{"weekday": 4, "time": "19:30"}, {"weekday": 0, "time": "07:00"},
                  {"weekday": 4, "time": "19:30"}],
    }  # fmt: skip

    saved = client.put("/posting-slots", json=body)

    assert saved.status_code == 200
    data = saved.json()
    assert data["timezone"] == "Africa/Casablanca"
    assert data["slots"] == [{"weekday": 0, "time": "07:00"}, {"weekday": 4, "time": "19:30"}]
    upcoming_times = [datetime.fromisoformat(value) for value in data["upcoming"]]
    assert 0 < len(upcoming_times) <= 21 and upcoming_times == sorted(upcoming_times)
    assert all(moment > datetime.now(UTC) for moment in upcoming_times)
    assert {m.astimezone(CASABLANCA).strftime("%a %H:%M") for m in upcoming_times} == {
        "Mon 07:00", "Fri 19:30",
    }  # fmt: skip
    assert client.get("/posting-slots").json() == data

    cleared = client.put("/posting-slots", json={"timezone": "Africa/Casablanca", "slots": []})
    assert cleared.json()["slots"] == [] and cleared.json()["upcoming"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"timezone": "Mars/Olympus", "slots": []},
        {"timezone": "UTC", "slots": [{"weekday": 1, "time": "25:00"}]},
        {"timezone": "UTC", "slots": [{"weekday": 9, "time": "10:00"}]},
        {"timezone": "UTC", "slots": [{"weekday": 1, "time": "9:00"}]},
        {
            "timezone": "UTC",
            "slots": [{"weekday": d, "time": f"{h:02d}:00"} for d in range(7) for h in range(5)],
        },
        {"slots": []},
    ],  # fmt: skip
)
def test_bad_posting_times_are_refused_and_nothing_is_saved(client: TestClient, body):
    sign_up(client)

    assert client.put("/posting-slots", json=body).status_code == 422
    assert client.get("/posting-slots").json()["slots"] == []


def test_posting_times_belong_to_their_creator(client: TestClient):
    sign_up(client)
    client.put(
        "/posting-slots", json={"timezone": "UTC", "slots": [{"weekday": 1, "time": "10:00"}]}
    )
    client.cookies.clear()
    sign_up(client, "other@example.com")

    assert client.get("/posting-slots").json()["slots"] == []
