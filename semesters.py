"""Semester windows: which semester a date belongs to, and when a semester freezes."""
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Semester:
    name: str
    start: date
    end: date
    is_break: bool = False

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end

    def freezes_on(self, grace_days: int) -> date:
        return self.end + timedelta(days=grace_days)


def _fallback(year: int):
    # Used for any year the config doesn't list: approximate UGA calendar.
    return [Semester(f"Spring {year}", date(year, 1, 8), date(year, 5, 8)),
            Semester(f"Fall {year}", date(year, 8, 15), date(year, 12, 12))]


class Calendar:
    def __init__(self, configured, include_breaks=False):
        self.configured = [Semester(s["name"], date.fromisoformat(str(s["start"])), date.fromisoformat(str(s["end"])))
                           for s in configured or []]
        self.include_breaks = include_breaks

    def _terms(self, year):
        listed = [s for s in self.configured if s.start.year == year]
        names = {s.name.split()[0] for s in listed}
        return sorted(listed + [s for s in _fallback(year) if s.name.split()[0] not in names], key=lambda s: s.start)

    def for_year(self, year: int):
        """Semesters (and, if enabled, the breaks between them) that start in `year`."""
        sems = self._terms(year)
        if self.include_breaks:
            spring, fall = sems[0], sems[-1]
            next_spring = self._terms(year + 1)[0]
            sems += [Semester(f"Summer {year}", spring.end + timedelta(days=1), fall.start - timedelta(days=1), True),
                     Semester(f"Winter Break {year}–{str(year + 1)[2:]}", fall.end + timedelta(days=1),
                              next_spring.start - timedelta(days=1), True)]
        return sorted(sems, key=lambda s: s.start)

    def semester_of(self, d: date):
        return next((s for y in (d.year - 1, d.year) for s in self.for_year(y) if s.contains(d)), None)

    def open_semesters(self, today: date, grace_days: int):
        """Semesters whose playlists should still be updated today (started, not yet frozen)."""
        return [s for y in (today.year - 1, today.year) for s in self.for_year(y)
                if s.start <= today <= s.freezes_on(grace_days)]
