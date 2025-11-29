"""Put the current date onto the GitHub contribution graph.

A day is on when this repository has one or more commits authored that
day, and off when it has none. Rebuilding the branch is how a day is
turned off: yesterday's commits are not in the new history, so those
squares go dark unless some other repository still has a contribution
there.

More commits on a day make a darker green, fewer make a lighter one.
GitHub picks the four greens from the year's quartiles, so the counts
are chosen to land on different quartiles instead of using a fixed number.
"""

from __future__ import annotations

import os
import subprocess
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_PACIFIC = ZoneInfo("America/Los_Angeles")
from pathlib import Path

from commit_art.fetch import FetchError, fetch_calendar, resolve_token
from commit_art.glyphs import SHADE_BY_MARK, WEEKDAY_NAMES, glyph_rows, preview
from commit_art.shade import choose_amounts, level_for, quartiles

LOGIN = os.environ.get("COMMIT_ART_LOGIN", "amotor-AM")
AUTHOR_NAME = os.environ.get("COMMIT_ART_NAME", "Alex Motor")
AUTHOR_EMAIL = os.environ.get(
    "COMMIT_ART_EMAIL",
    "66324211+amotor-AM@users.noreply.github.com",
)
REPO_NAME = "commit-art"
PLACEMENT_FILE = "placement.txt"
_LEVEL_MARK = ".-+=#"


def label_for(day: date) -> str:
    return day.strftime("%m-%d-%Y")


def last_saturday(day: date) -> date:
    """The Saturday that ends the latest complete week on or before day."""

    return day - timedelta(days=(day.weekday() - 5) % 7)


def pixel_tiers(rows: tuple[str, ...], start_sunday: date) -> dict[date, int]:
    """Map each lit day to shade tier 1 (light), 2 (medium), or 3 (dark)."""

    tiers: dict[date, int] = {}
    width = len(rows[0])
    for column in range(width):
        sunday = start_sunday + timedelta(weeks=column)
        for row in range(7):
            mark = rows[row][column]
            tier = SHADE_BY_MARK.get(mark)
            if tier is None:
                continue
            tiers[sunday + timedelta(days=row)] = tier
    return tiers


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise SystemExit(f"{' '.join(args)} failed.\n{detail}")
    return completed


def _git(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd, env)


def _counts_by_day(login: str) -> dict[date, int]:
    try:
        calendar = fetch_calendar(login, resolve_token(None))
    except FetchError as error:
        raise SystemExit(
            f"Could not read the current graph ({error}). Refusing to place the date without it."
        ) from error
    counts: dict[date, int] = {}
    for week in calendar.weeks:
        for day in week.days:
            counts[day.date] = day.count
    return counts


def _authored_counts(project: Path) -> dict[date, int]:
    """Commits already in this repository, by the day GitHub will count them."""

    completed = subprocess.run(
        ["git", "log", "--format=%aI"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {}
    counts: dict[date, int] = {}
    for line in completed.stdout.splitlines():
        if len(line) < 10:
            continue
        day = date.fromisoformat(line[:10])
        counts[day] = counts.get(day, 0) + 1
    return counts


def _foreign_counts(calendar_counts: dict[date, int], ours: dict[date, int]) -> dict[date, int]:
    """Contributions that stay even after this repository is rebuilt."""

    foreign: dict[date, int] = {}
    for day, count in calendar_counts.items():
        remaining = count - ours.get(day, 0)
        if remaining > 0:
            foreign[day] = remaining
    return foreign


def _candidate_starts(width: int, today: date) -> list[date]:
    end_limit = last_saturday(today)
    earliest = today - timedelta(days=364)
    first = earliest + timedelta(days=(6 - earliest.weekday()) % 7)
    starts: list[date] = []
    start = first
    while True:
        block_end = start + timedelta(weeks=width - 1, days=6)
        if block_end > end_limit:
            break
        if start >= earliest:
            starts.append(start)
        start += timedelta(weeks=1)
    return starts


def _hole_penalty(start: date, rows: tuple[str, ...], foreign: dict[date, int]) -> tuple[int, int, int, int]:
    """Worst hole, then busy holes, then any holes, then their total weight.

    One day with dozens of outside contributions punches a dark square
    through a letter. That is worse than several faint specks.
    """

    worst = 0
    busy = 0
    dirty = 0
    weight = 0
    width = len(rows[0])
    for column in range(width):
        sunday = start + timedelta(weeks=column)
        for row in range(7):
            if rows[row][column] != ".":
                continue
            count = foreign.get(sunday + timedelta(days=row), 0)
            if count > worst:
                worst = count
            if count >= 3:
                busy += 1
            if count:
                dirty += 1
                weight += count
    return worst, busy, dirty, weight


def _placement_is_usable(start: date, width: int, today: date) -> bool:
    return start in _candidate_starts(width, today)


def choose_start(
    rows: tuple[str, ...],
    today: date,
    foreign: dict[date, int],
    saved: date | None,
) -> date:
    width = len(rows[0])
    starts = _candidate_starts(width, today)
    if not starts:
        raise SystemExit("No stretch of weeks is available for the date.")
    # Fewest occupied holes, then the lightest of those, then the latest start.
    best = min(starts, key=lambda start: (*_hole_penalty(start, rows, foreign), -start.toordinal()))
    if saved is not None and _placement_is_usable(saved, width, today):
        saved_worst, saved_busy, saved_dirty, _saved_weight = _hole_penalty(saved, rows, foreign)
        best_worst, best_busy, best_dirty, _best_weight = _hole_penalty(best, rows, foreign)
        # Stay put unless another window is clearly cleaner, so the date
        # does not jump to a new set of weeks every night.
        if (saved_worst, saved_busy, saved_dirty) <= (best_worst, best_busy, best_dirty + 2):
            return saved
    return best


def _read_saved_start(project: Path) -> date | None:
    path = project / PLACEMENT_FILE
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    return date.fromisoformat(text.splitlines()[0])


def _year_levels(
    tiers: dict[date, int],
    foreign: dict[date, int],
    amounts: tuple[int, int, int],
) -> dict[date, int]:
    light, medium, dark = amounts
    totals = dict(foreign)
    for day, tier in tiers.items():
        totals[day] = totals.get(day, 0) + (light, medium, dark)[tier - 1]
    year_quartiles = quartiles([count for count in totals.values() if count > 0])
    return {day: level_for(count, year_quartiles) for day, count in totals.items() if count > 0}


def describe(today: date, foreign: dict[date, int] | None = None) -> str:
    rows = glyph_rows(label_for(today))
    project = _project_root()
    if foreign is None:
        foreign = _foreign_counts(_counts_by_day(LOGIN), _authored_counts(project))
    saved = _read_saved_start(project)
    start = choose_start(rows, today, foreign, saved)
    tiers = pixel_tiers(rows, start)
    amounts = choose_amounts(tiers, foreign)
    levels = _year_levels(tiers, foreign, amounts)
    end = start + timedelta(weeks=len(rows[0]) - 1, days=6)
    worst, busy, dirty, _weight = _hole_penalty(start, rows, foreign)
    commits = sum(amounts[tier - 1] for tier in tiers.values())
    level_rows = _level_rows(rows, start, levels)
    lines = [
        preview(label_for(today), rows),
        "",
        "How the date should read (. off, - light, + medium, = dark, # darkest):",
        *(f"{name}  {row}" for name, row in zip(WEEKDAY_NAMES, level_rows)),
        "",
        (
            f"{len(tiers)} days on, {commits} commits "
            f"({amounts[0]} / {amounts[1]} / {amounts[2]} for light / medium / dark), "
            f"{start.isoformat()} through {end.isoformat()}."
        ),
        (
            f"{dirty} off-days inside the letters already have contributions from outside this repo"
            f" ({busy} of them are busy, the strongest is {worst})."
        ),
    ]
    return "\n".join(lines)


def _level_rows(rows: tuple[str, ...], start: date, levels: dict[date, int]) -> tuple[str, ...]:
    width = len(rows[0])
    built: list[str] = []
    for row in range(7):
        chars: list[str] = []
        for column in range(width):
            day = start + timedelta(weeks=column, days=row)
            chars.append(_LEVEL_MARK[levels.get(day, 0)])
        built.append("".join(chars))
    return tuple(built)


def _ensure_dedicated_repo(project: Path) -> None:
    if not (project / ".git").exists():
        _git(["init", "-b", "main"], project)
    completed = _git(["rev-parse", "--show-toplevel"], project)
    toplevel = Path(completed.stdout.strip()).resolve()
    if toplevel != project.resolve():
        raise SystemExit(
            "Refusing to rewrite history. This folder is inside another git repository, "
            f"and the root of that repository is {toplevel}."
        )


def _origin(project: Path) -> str | None:
    completed = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    url = completed.stdout.strip()
    return url or None


def _remember_origin(project: Path) -> str | None:
    return _origin(project)


def _restore_origin(project: Path, url: str | None) -> None:
    if not url:
        return
    if _origin(project) is None:
        _git(["remote", "add", "origin", url], project)


def _write_picture(project: Path, start: date, tiers: dict[date, int], amounts: tuple[int, int, int]) -> None:
    (project / PLACEMENT_FILE).write_text(start.isoformat() + "\n", encoding="utf-8", newline="\n")
    days_dir = project / "days"
    if days_dir.exists():
        for child in days_dir.iterdir():
            if child.is_file():
                child.unlink()
    else:
        days_dir.mkdir()
    light, medium, dark = amounts
    words = {1: "light", 2: "medium", 3: "dark"}
    for day, tier in sorted(tiers.items()):
        count = (light, medium, dark)[tier - 1]
        path = days_dir / day.isoformat()
        path.write_text(f"{words[tier]} {count}\n", encoding="utf-8", newline="\n")


def _blob_id(project: Path, relative: Path) -> str:
    completed = _git(["hash-object", "-w", "--", relative.as_posix()], project)
    return completed.stdout.strip()


def _picture_files(project: Path) -> list[Path]:
    selected: list[Path] = []
    for path in project.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(project)
        parts = set(relative.parts)
        if ".git" in parts or "__pycache__" in parts:
            continue
        if path.suffix == ".pyc":
            continue
        if path.parent == project and path.suffix == ".py" and path.name.startswith("_"):
            continue
        selected.append(relative)
    selected.sort()
    return selected


def _stamp(day: date) -> int:
    moment = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    return int(moment.timestamp())


def _fast_import(project: Path, tiers: dict[date, int], amounts: tuple[int, int, int], label: str) -> int:
    """Replace this branch with exactly one commit per planned contribution."""

    files = [(relative, _blob_id(project, relative)) for relative in _picture_files(project)]
    light, medium, dark = amounts
    reserved = max(day for day, tier in tiers.items() if tier == 3)
    sequence: list[tuple[date, str]] = []
    for day in sorted(tiers):
        amount = (light, medium, dark)[tiers[day] - 1]
        if day == reserved:
            amount -= 1
        sequence.extend((day, f"art: {day.isoformat()}") for _index in range(amount))
    if not sequence:
        raise SystemExit("The date has no squares to paint.")

    stream = bytearray()
    mark = 1
    first_day, first_message = sequence[0]
    stream += _commit_header(mark, first_day, first_message, parent=None)
    stream += b"deleteall\n"
    for relative, blob in files:
        if relative.as_posix() == "count.txt":
            continue
        stream += f"M 100644 {blob} {relative.as_posix()}\n".encode("utf-8")
    stream += _tick_command(mark)
    stream += b"\n"
    previous = mark
    for day, message in sequence[1:]:
        mark += 1
        stream += _commit_header(mark, day, message, parent=previous)
        stream += _tick_command(mark)
        stream += b"\n"
        previous = mark
    mark += 1
    stream += _commit_header(mark, reserved, f"Show {label} on the contribution graph", parent=previous)
    stream += _tick_command(mark)
    stream += b"\n"

    completed = subprocess.run(
        ["git", "fast-import", "--quiet", "--force"],
        cwd=project,
        input=bytes(stream),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(f"git fast-import failed.\n{detail}")
    _git(["reset", "--hard", "HEAD"], project)
    return len(sequence) + 1


def _commit_header(mark: int, day: date, message: str, parent: int | None) -> bytes:
    raw_message = (message + "\n").encode("utf-8")
    stamp = _stamp(day)
    identity = f"{AUTHOR_NAME} <{AUTHOR_EMAIL}> {stamp} +0000"
    lines = [
        "commit refs/heads/main",
        f"mark :{mark}",
        f"author {identity}",
        f"committer {identity}",
        f"data {len(raw_message)}",
    ]
    header = ("\n".join(lines) + "\n").encode("utf-8") + raw_message
    if parent is not None:
        header += f"from :{parent}\n".encode("utf-8")
    return header


def _tick_command(tick: int) -> bytes:
    """A different file each commit, so GitHub counts every one of them."""

    payload = f"{tick}\n".encode("utf-8")
    return b"M 100644 inline count.txt\n" + f"data {len(payload)}\n".encode("utf-8") + payload


def paint(today: date | None = None) -> str:
    """Rebuild this repository so its commits spell today's date, and nothing else."""

    today = today or datetime.now(_PACIFIC).date()
    project = _project_root()
    _ensure_dedicated_repo(project)
    label = label_for(today)
    rows = glyph_rows(label)
    ours = _authored_counts(project)
    foreign = _foreign_counts(_counts_by_day(LOGIN), ours)
    saved = _read_saved_start(project)
    start = choose_start(rows, today, foreign, saved)
    tiers = pixel_tiers(rows, start)
    amounts = choose_amounts(tiers, foreign)
    origin = _remember_origin(project)

    _write_picture(project, start, tiers, amounts)
    written = _fast_import(project, tiers, amounts, label)
    _git(["symbolic-ref", "HEAD", "refs/heads/main"], project)
    _git(["reset", "--hard", "HEAD"], project)
    _restore_origin(project, origin)
    summary = describe(today, foreign)
    print(summary)
    print(f"Rebuilt {written} commits. Days that are not part of {label} are off.")
    return summary


def _allowed_remote(url: str) -> bool:
    expected = (
        f"https://github.com/{LOGIN}/{REPO_NAME}",
        f"https://github.com/{LOGIN}/{REPO_NAME}.git",
        f"git@github.com:{LOGIN}/{REPO_NAME}.git",
    )
    cleaned = url.strip().rstrip("/")
    return cleaned in {item.rstrip("/") for item in expected}


def _request_json(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    import json
    import urllib.error
    import urllib.request

    token = resolve_token(None)
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "commit-art",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"message": raw[:300]}
        return error.code, parsed


def _ensure_remote_repository(project: Path) -> str:
    status, body = _request_json("GET", f"https://api.github.com/repos/{LOGIN}/{REPO_NAME}")
    clone_url = f"https://github.com/{LOGIN}/{REPO_NAME}.git"
    if status == 404:
        created, created_body = _request_json(
            "POST",
            "https://api.github.com/user/repos",
            {
                "name": REPO_NAME,
                "description": "Writes the current date onto the GitHub contribution graph.",
                "private": False,
                "has_issues": False,
                "has_projects": False,
                "has_wiki": False,
                "auto_init": False,
            },
        )
        if created not in (200, 201):
            message = created_body.get("message", "")
            raise SystemExit(f"Could not create {LOGIN}/{REPO_NAME}. HTTP {created}. {message}")
        return str(created_body.get("clone_url") or clone_url)
    if status != 200:
        raise SystemExit(f"Could not inspect {LOGIN}/{REPO_NAME}. HTTP {status}.")
    # An existing unrelated repository must not be force-pushed.
    commit_status, commit_body = _request_json(
        "GET",
        f"https://api.github.com/repos/{LOGIN}/{REPO_NAME}/commits/main",
    )
    if commit_status == 200:
        message = ((commit_body.get("commit") or {}).get("message") or "").splitlines()[0]
        if not (message.startswith("Show ") or message.startswith("art:")):
            raise SystemExit(
                f"Refusing to replace {LOGIN}/{REPO_NAME}. Its latest commit is {message!r}."
            )
    elif commit_status not in (404, 409):
        raise SystemExit(f"Could not read {LOGIN}/{REPO_NAME}. HTTP {commit_status}.")
    return str(body.get("clone_url") or clone_url)


def push() -> str:
    project = _project_root()
    _ensure_dedicated_repo(project)
    url = _origin(project)
    if url is None:
        url = _ensure_remote_repository(project)
        _git(["remote", "add", "origin", url], project)
    if not _allowed_remote(url):
        raise SystemExit(f"Refusing to push. Origin is {url}, not the dedicated {REPO_NAME} repository.")
    _git(["push", "--force", "-u", "origin", "HEAD:main"], project)
    public = f"https://github.com/{LOGIN}/{REPO_NAME}"
    print(public)
    return public


def run_checks() -> None:
    friday = date(2026, 10, 2)
    assert friday.weekday() == 4
    assert last_saturday(friday) == date(2026, 9, 26)
    assert last_saturday(date(2026, 9, 26)) == date(2026, 9, 26)
    assert label_for(friday) == "10-02-2026"

    rows = glyph_rows("10-02-2026")
    assert len(rows) == 7
    assert len({len(row) for row in rows}) == 1
    assert len(rows[0]) == 39
    # Hyphen glyph row 3 is "###"; the full date string has 3 hyphens.
    from commit_art.glyphs import _HYPHEN
    assert _HYPHEN[3] == "###"
    assert set("".join(rows)) <= set(".#")

    start = _candidate_starts(len(rows[0]), friday)[0]
    assert start.weekday() == 6
    tiers = pixel_tiers(rows, start)
    assert tiers
    for column in range(len(rows[0])):
        sunday = start + timedelta(weeks=column)
        for row in range(7):
            day = sunday + timedelta(days=row)
            mark = rows[row][column]
            if mark == ".":
                assert day not in tiers
            else:
                assert tiers[day] == SHADE_BY_MARK[mark]
            assert (day.weekday() + 1) % 7 == row

    zero = glyph_rows("0")
    assert zero[0] == "###"
    assert zero[1][1] == "."
    hyphen = glyph_rows("-")
    assert hyphen[3] == "###"
    assert hyphen[0] == "..."

    assert _placement_is_usable(start, len(rows[0]), friday)
    assert not _placement_is_usable(date(2025, 9, 28), len(rows[0]), friday)
    assert not _placement_is_usable(date(2026, 9, 20), len(rows[0]), friday)

    foreign = {date(2026, 1, 1) + timedelta(days=index): 1 for index in range(180)}
    synthetic: dict[date, int] = {}
    base = date(2024, 1, 1)
    for index in range(36):
        synthetic[base + timedelta(days=index)] = 3
    for index in range(50):
        synthetic[base + timedelta(days=100 + index)] = 2
    for index in range(6):
        synthetic[base + timedelta(days=200 + index)] = 1
    light, medium, dark = choose_amounts(synthetic, foreign)
    assert dark > light >= 1
    assert dark >= medium >= light
    levels = _year_levels(synthetic, foreign, (light, medium, dark))
    assert min(levels[day] for day, tier in synthetic.items() if tier == 3) > min(
        levels[day] for day, tier in synthetic.items() if tier == 2
    )
    print("All checks passed.")
