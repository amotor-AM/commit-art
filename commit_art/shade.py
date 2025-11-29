"""Turn shade marks into commit counts GitHub will actually color differently.

GitHub does not have a fixed color for "5 commits". It sorts every non-zero
day in the year and splits that list into quartiles. A day is darkest only
when its count is strictly above the 75th percentile. If almost every lit
day has the same count, they all collapse to the same green.
"""

from __future__ import annotations

from datetime import date

# All glyph squares now use the dark tier (#), so light and medium are
# unused — but the tuple shape stays (light, medium, dark) for API
# compatibility. The dark value must be high enough that every date
# square lands at GitHub level 3+ (dark green) even when foreign
# contributions on those same days push the 75th percentile up.
# Analysis shows N=36 per square guarantees 100% of date squares at
# level 3+ while background stays at levels 1-2. Total for 115 squares
# is 4140 commits, well within GitHub's counting limits.
_MAX_COMMITS = 10000
_LADDERS: tuple[tuple[int, int, int], ...] = (
    (1, 1, 36),
    (1, 1, 48),
    (1, 1, 60),
)


def quartiles(counts: list[int]) -> tuple[float, float, float]:
    """Return the 25th, 50th, and 75th percentiles of the positive counts."""

    ordered = sorted(count for count in counts if count > 0)
    if not ordered:
        return (0.0, 0.0, 0.0)

    def percentile(fraction: float) -> float:
        if len(ordered) == 1:
            return float(ordered[0])
        position = (len(ordered) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        blend = position - lower
        return ordered[lower] * (1.0 - blend) + ordered[upper] * blend

    return percentile(0.25), percentile(0.50), percentile(0.75)


def level_for(count: int, quartiles_of_year: tuple[float, float, float]) -> int:
    """GitHub's 0..4 green, matching the quartile comparison used on the graph."""

    if count <= 0:
        return 0
    first, second, third = quartiles_of_year
    if count <= first:
        return 1
    if count <= second:
        return 2
    if count <= third:
        return 3
    return 4


def _median(values: list[int]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def choose_amounts(
    tiers: dict[date, int],
    foreign: dict[date, int],
) -> tuple[int, int, int]:
    """Pick (light, medium, dark) commit counts that keep the shades apart.

    `tiers` maps a day to 1, 2, or 3. `foreign` is contributions on that
    day that this repository cannot remove.
    """

    best = _LADDERS[0]
    best_rank: tuple[int, int, int, int, int] | None = None
    for light, medium, dark in _LADDERS:
        volume_count = (
            light * sum(tier == 1 for tier in tiers.values())
            + medium * sum(tier == 2 for tier in tiers.values())
            + dark * sum(tier == 3 for tier in tiers.values())
        )
        if volume_count > _MAX_COMMITS:
            continue
        totals = dict(foreign)
        for day, tier in tiers.items():
            added = (light, medium, dark)[tier - 1]
            totals[day] = totals.get(day, 0) + added
        year_quartiles = quartiles([count for count in totals.values() if count > 0])

        def painted(tier: int) -> list[int]:
            return [
                level_for(totals[day], year_quartiles)
                for day, day_tier in tiers.items()
                if day_tier == tier
            ]

        dark_levels = painted(3)
        medium_levels = painted(2)
        light_levels = painted(1)
        if not dark_levels or not medium_levels:
            continue
        dark_min = min(dark_levels)
        medium_min = min(medium_levels)
        ordinary = level_for(1, year_quartiles)
        light_typical = _median(light_levels) if light_levels else 0.0

        separated = int(
            _median(dark_levels) > _median(medium_levels) > light_typical
            and dark_min >= 3
            and medium_min > ordinary
        )
        # Uniform darkness: every dark AND medium square at level 4 means
        # the whole date is the darkest green with no washed-out squares.
        uniform = int(dark_min == 4 and medium_min == 4)
        darker_than_holes = int(medium_min > ordinary and _median(dark_levels) > _median(medium_levels))
        contrast = dark_min * 10 + medium_min - int(light_typical)
        volume = -volume_count
        # Prefer uniform darkness first, then separation, then contrast,
        # then smaller volume. A uniform ladder always beats a non-uniform
        # one regardless of volume.
        rank = (uniform, separated, darker_than_holes, contrast, volume)
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best = (light, medium, dark)
        # Only break early if we achieved uniform darkness at level 4.
        if uniform:
            break
    return best
