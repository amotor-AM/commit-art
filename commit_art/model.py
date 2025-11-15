"""The contribution calendar, independent of how it was fetched."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Day:
    """One square on the contribution calendar."""

    date: date
    count: int
    weekday: int  # GitHub's convention: Sunday is 0, Saturday is 6.


@dataclass(frozen=True)
class Week:
    """One column of the contribution calendar, Sunday through Saturday."""

    days: tuple[Day, ...]

    @property
    def total(self) -> int:
        return sum(day.count for day in self.days)

    @property
    def start(self) -> date:
        return self.days[0].date

    @property
    def end(self) -> date:
        return self.days[-1].date

    @property
    def active_days(self) -> int:
        return sum(1 for day in self.days if day.count > 0)


@dataclass(frozen=True)
class Calendar:
    """A rolling year of contributions for one person."""

    login: str
    name: str | None
    total: int
    weeks: tuple[Week, ...]

    @property
    def start(self) -> date | None:
        if not self.weeks:
            return None
        return self.weeks[0].start

    @property
    def end(self) -> date | None:
        if not self.weeks:
            return None
        return self.weeks[-1].end
