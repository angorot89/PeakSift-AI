"""Posting times: the weekly slots a creator likes to post at, and which ones are still free.

A slot is a weekday and a wall-clock time in the creator's own time zone ("Friday 19:30 in
Africa/Casablanca"). It is a preference, not automation: PeakSift only *offers* the next free
slot when the creator schedules a Short. Slots are kept as wall-clock times so they stay at
19:30 when the clocks change; each occurrence is converted to UTC with that day's offset.

Pure: no database, no clock of its own.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_SLOTS = 28  # four a day is already a lot to keep up with
SAME_SLOT = timedelta(minutes=1)  # a post this close to a slot has taken it
MIN_LEAD = timedelta(minutes=10)  # a slot this soon is not offered: no time to review
MAX_WEEKS_AHEAD = 8


class SlotError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True, order=True)
class Slot:
    weekday: int  # 0 = Monday … 6 = Sunday
    at: time

    def read(self) -> dict:
        return {"weekday": self.weekday, "time": self.at.strftime("%H:%M")}


def timezone(name: str | None) -> ZoneInfo:
    """The IANA zone ``name``, or :class:`SlotError`."""
    try:
        if not name or len(name) > 64:
            raise ZoneInfoNotFoundError(name)
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise SlotError("Unknown time zone") from None


def normalize(raw: Iterable[object]) -> list[Slot]:
    """Validated slots, without duplicates, in week order."""
    slots: set[Slot] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise SlotError("Each posting time needs a weekday and a time")
        weekday, clock = item.get("weekday"), item.get("time")
        if isinstance(weekday, bool) or not isinstance(weekday, int) or not 0 <= weekday <= 6:
            raise SlotError("A weekday is a number from 0 (Monday) to 6 (Sunday)")
        try:
            hour, minute = (int(part) for part in str(clock).split(":"))
            at = time(hour, minute)
        except (TypeError, ValueError):
            raise SlotError("A time looks like 19:30") from None
        if len(str(clock)) != 5:
            raise SlotError("A time looks like 19:30")
        slots.add(Slot(weekday, at))
    if len(slots) > MAX_SLOTS:
        raise SlotError(f"Keep at most {MAX_SLOTS} posting times")
    return sorted(slots)


def stored(raw: object) -> list[Slot]:
    """Slots as saved; anything unreadable counts as none (never an error on read)."""
    try:
        return normalize(raw if isinstance(raw, list) else [])
    except SlotError:
        return []


def upcoming(
    slots: list[Slot],
    zone: ZoneInfo,
    now: datetime,
    taken: Iterable[datetime] = (),
    count: int = 14,
) -> list[datetime]:
    """The next ``count`` free slot times in UTC: after ``now`` (with room to review) and not
    already taken by a scheduled post."""
    if not slots or count <= 0:
        return []
    busy = [moment.astimezone(UTC) for moment in taken]
    earliest = now.astimezone(UTC) + MIN_LEAD
    today = now.astimezone(zone).date()
    free: list[datetime] = []
    for offset in range(MAX_WEEKS_AHEAD * 7 + 1):
        day = today + timedelta(days=offset)
        for slot in slots:
            if slot.weekday != day.weekday():
                continue
            # Wall-clock time on that day, with that day's own UTC offset (DST-safe).
            moment = datetime.combine(day, slot.at, tzinfo=zone).astimezone(UTC)
            if moment < earliest or any(abs(moment - other) <= SAME_SLOT for other in busy):
                continue
            free.append(moment)
            if len(free) >= count:
                return free
    return free
