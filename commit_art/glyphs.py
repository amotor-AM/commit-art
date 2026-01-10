"""A 7-row font for the contribution graph.

Row 0 is Sunday, the top row of the graph. Each character is three weeks
wide, with one blank week between characters.

Cell marks are the shade we want, before GitHub's quartile coloring:

- '.' off, so that day gets no commit from this repo
- '-' light
- '+' medium
- '#' dark
"""

from __future__ import annotations

# Every visible square uses '#' (dark) so the whole date renders as
# uniformly the darkest green.  Mixed tiers (+ / -) produced a washed-out
# look because foreign contributions on "off" days inside the letters
# pushed the quartile thresholds above what medium-tier squares could reach.
_DIGITS: dict[str, tuple[str, ...]] = {
    "0": ("###", "#.#", "#.#", "#.#", "#.#", "#.#", "###"),
    "1": (".##", "..#", "..#", "..#", "..#", "..#", "###"),
    "2": ("###", "..#", "..#", "###", "#..", "#..", "###"),
    "3": ("###", "..#", "..#", "###", "..#", "..#", "###"),
    "4": ("#.#", "#.#", "#.#", "###", "..#", "..#", "..#"),
    "5": ("###", "#..", "#..", "###", "..#", "..#", "###"),
    "6": ("###", "#..", "#..", "###", "#.#", "#.#", "###"),
    "7": ("###", "..#", "..#", "..#", "..#", "..#", "..#"),
    "8": ("###", "#.#", "#.#", "###", "#.#", "#.#", "###"),
    "9": ("###", "#.#", "#.#", "###", "..#", "..#", "###"),
}

# A hyphen sits on Wednesday, the middle row, so it reads as a dash.
_HYPHEN: tuple[str, ...] = ("...", "...", "...", "###", "...", "...", "...")
_GAP: tuple[str, ...] = (".", ".", ".", ".", ".", ".", ".")

WEEKDAY_NAMES = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
SHADE_BY_MARK = {"-": 1, "+": 2, "#": 3}


def glyph_rows(text: str) -> tuple[str, ...]:
    """Seven strings, one per weekday, Sunday first."""

    pieces: list[tuple[str, ...]] = []
    for index, character in enumerate(text):
        if index:
            pieces.append(_GAP)
        if character in _DIGITS:
            pieces.append(_DIGITS[character])
        elif character == "-":
            pieces.append(_HYPHEN)
        else:
            raise ValueError(f"Cannot draw {character!r}. Use digits and '-'.")
    return tuple("".join(piece[row] for piece in pieces) for row in range(7))


def preview(text: str, rows: tuple[str, ...]) -> str:
    lines = [text]
    for name, row in zip(WEEKDAY_NAMES, rows):
        lines.append(f"{name}  {row}")
    return "\n".join(lines)
