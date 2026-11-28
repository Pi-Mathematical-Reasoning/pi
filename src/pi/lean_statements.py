"""Lean statements: a miniF2F split file read into its theorems.

A split file holds an import header and then `theorem` declarations, each
ending in `:= by sorry` (a few ship a proof). This module is pure text work:
it finds each declaration, its docstring and its statement, and changes nothing.
"""

import re
from dataclasses import dataclass

FAMILY_PREFIXES = ("amc12", "aime", "imo")
FAMILY_NAMES = ("induction", "algebra", "numbertheory")
FAMILY_PAIRS = ("mathd_algebra", "mathd_numbertheory")
SORRY = "by sorry"
NEXT_ITEM = re.compile(r"/-|--|theorem\b|open\b")


class StatementError(Exception):
    """A Lean file is not in the layout of a miniF2F split file."""


@dataclass(frozen=True)
class Theorem:
    id: str
    header: str
    statement: str
    informal: str | None
    shipped_proof: str | None
    subject: str
    level: None = None


def family(name: str) -> str:
    for pair in FAMILY_PAIRS:
        if name.startswith(pair):
            return pair
    for prefix in FAMILY_PREFIXES:
        if name.startswith(prefix):
            return prefix
    for stem in FAMILY_NAMES:
        if name.startswith(stem + "_"):
            return stem
    return "other"


def read_block_comment(lines: list[str], start: int) -> tuple[str, int]:
    """The text of the `/- … -/` comment opening at `start`, and the index after it."""
    opener = 3 if lines[start].startswith("/--") else 2
    first = lines[start][opener:]
    parts = []
    index = start
    text = first
    while "-/" not in text:
        parts.append(text)
        index += 1
        if index == len(lines):
            raise StatementError(f"line {start + 1}: comment is never closed")
        text = lines[index]
    parts.append(text[: text.index("-/")])
    return "\n".join(parts).strip(), index + 1


def read_declaration(lines: list[str], start: int) -> tuple[str, int]:
    """The lines from `start` to the next blank line or column-0 item, and the index after."""
    end = start + (2 if lines[start].startswith("open") else 1)
    while end < len(lines) and lines[end].strip() and not NEXT_ITEM.match(lines[end]):
        end += 1
    return "\n".join(lines[start:end]), end


def split_declaration(declaration: str, line: int) -> tuple[str, str, str | None]:
    """The theorem's name, its statement, and the proof the file ships, if any."""
    match = re.search(r"^theorem\s+(\S+)", declaration, re.MULTILINE)
    cut = declaration.rfind(":=")
    if match is None or cut == -1:
        raise StatementError(f"line {line}: declaration has no proof")
    proof = " ".join(declaration[cut + 2 :].split())
    return match.group(1), declaration[:cut].rstrip(), None if proof == SORRY else proof


def split_theorems(text: str) -> list[Theorem]:
    lines = text.splitlines()
    header: list[str] | None = None
    header_open = True
    docstring: str | None = None
    found: list[tuple[str, str, str | None, str | None]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        number = index + 1
        if not line.strip():
            docstring = None
            if header is not None and header_open:
                header.append("")
            index += 1
        elif line.startswith("/-"):
            comment, index = read_block_comment(lines, number - 1)
            docstring = comment if line.startswith("/--") else None
            header_open = header_open and not line.startswith("/--")
        elif line.startswith("--"):
            index += 1
        elif line.startswith("import") or (line.startswith("open") and not line.endswith(" in")):
            if not header_open or (header is None and not line.startswith("import")):
                raise StatementError(f"line {number}: unexpected {line.split()[0]}")
            header = (header or []) + [line]
            index += 1
        elif line.startswith("theorem") or line.startswith("open"):
            if header is None:
                raise StatementError(f"line {number}: theorem before any import")
            header_open = False
            declaration, index = read_declaration(lines, index)
            name, statement, proof = split_declaration(declaration, number)
            found.append((name, statement, docstring, proof))
            docstring = None
        else:
            raise StatementError(f"line {number}: cannot read {line!r}")
    if header is None:
        raise StatementError("no import line")
    header_text = "\n".join(header).rstrip() + "\n"
    names = [name for name, *_ in found]
    for name in set(names):
        if names.count(name) > 1:
            raise StatementError(f"theorem {name} is declared twice")
    return [
        Theorem(name, header_text, statement, informal, proof, family(name))
        for name, statement, informal, proof in found
    ]
