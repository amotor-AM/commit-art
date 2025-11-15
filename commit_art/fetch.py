"""Load a GitHub contribution calendar.

This is the same year of squares as the profile graph: commits, pull
requests, reviews, and issues. GitHub's API returns at most one year, and
calling it with no date range always means "the last year ending today",
so the picture keeps up without a date that has to be edited later.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from datetime import date

from commit_art.model import Calendar, Day, Week

GRAPHQL_URL = "https://api.github.com/graphql"
USER_AGENT = "commit-art"

QUERY = """
query($login: String!) {
  user(login: $login) {
    login
    name
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            weekday
            contributionCount
          }
        }
      }
    }
  }
}
"""


class FetchError(Exception):
    """The contribution calendar could not be loaded."""


def resolve_token(explicit: str | None) -> str:
    """Flag, then environment, then Git's stored login, then the GitHub CLI."""

    if explicit:
        return explicit.strip()
    for variable in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(variable)
        if value:
            return value.strip()
    stored = _token_from_git_credential()
    if stored:
        return stored
    command_token = _token_from_gh_cli()
    if command_token:
        return command_token
    raise FetchError(
        "Missing a GitHub token. Pass --token, set GH_TOKEN, or run `gh auth login`."
    )


def _token_from_git_credential() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in completed.stdout.splitlines():
        if line.startswith("password="):
            token = line.split("=", 1)[1].strip()
            return token or None
    return None


def _token_from_gh_cli() -> str | None:
    try:
        completed = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    token = completed.stdout.strip()
    return token or None


def fetch_calendar(login: str, token: str) -> Calendar:
    if not login or not _login_is_plausible(login):
        raise FetchError(
            "Pass a GitHub username with --user, for example --user octocat."
        )

    payload = json.dumps({"query": QUERY, "variables": {"login": login}}).encode("utf-8")
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:300]
        if error.code == 401:
            raise FetchError("GitHub rejected the token. Check GH_TOKEN or run `gh auth login`.") from error
        raise FetchError(f"GitHub returned HTTP {error.code}. {detail}") from error
    except urllib.error.URLError as error:
        raise FetchError(f"Could not reach GitHub. {error.reason}") from error

    parsed = json.loads(body)
    if parsed.get("errors"):
        message = parsed["errors"][0].get("message", "Unknown GraphQL error")
        raise FetchError(f"GitHub could not load that contribution graph. {message}")

    user = (parsed.get("data") or {}).get("user")
    if user is None:
        raise FetchError(f"No GitHub user named '{login}'.")

    calendar = user["contributionsCollection"]["contributionCalendar"]
    weeks: list[Week] = []
    for week in calendar["weeks"]:
        days = tuple(
            Day(
                date=date.fromisoformat(day["date"]),
                count=int(day["contributionCount"]),
                weekday=int(day["weekday"]),
            )
            for day in week["contributionDays"]
        )
        if days:
            weeks.append(Week(days=days))

    return Calendar(
        login=user["login"],
        name=user.get("name"),
        total=int(calendar["totalContributions"]),
        weeks=tuple(weeks),
    )


def _login_is_plausible(login: str) -> bool:
    if len(login) > 39:
        return False
    return all(character.isalnum() or character == "-" for character in login)
