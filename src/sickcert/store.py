"""In-memory store for parsed rows, plus the index the search engine scans.

This class is the Phase 2 seam. Persisting parsed messages across sessions
(HLD 5.4) means reimplementing Dataset against SQLite; nothing above it needs
to change.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .model import FieldRow
from .parser import NotHL7XmlError, parse_file
from .pathspec import tokenize


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Outcome of ingesting a single file."""

    file_name: str
    rows_added: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class Dataset:
    """Holds every parsed row for the session, with a precomputed search index.

    Two things are precomputed at load rather than per query:

    Lower-cased values
        so free-text search is a plain substring test.

    A distinct-path table
        paths repeat massively -- a real corpus of 393,000 rows contained only
        224 distinct paths. Grouping rows by path means a path query runs the
        token matcher a couple of hundred times instead of once per row, which
        is the difference between a noticeable pause and an instant result.
    """

    def __init__(self) -> None:
        self.rows: list[FieldRow] = []
        self.values_lower: list[str] = []

        # Distinct-path table. Entry i describes one distinct (path,
        # numeric_path) pair; path_rows[i] lists the rows that have it.
        self.path_tokens: list[tuple[str, ...]] = []
        self.numeric_tokens: list[tuple[str, ...]] = []
        self.path_rows: list[list[int]] = []
        self._path_ids: dict[tuple[str, str], int] = {}

    def __len__(self) -> int:
        return len(self.rows)

    def _path_id(self, row: FieldRow) -> int:
        key = (row.path, row.numeric_path)
        path_id = self._path_ids.get(key)
        if path_id is None:
            path_id = len(self.path_tokens)
            self._path_ids[key] = path_id
            self.path_tokens.append(tokenize(row.path))
            self.numeric_tokens.append(tokenize(row.numeric_path))
            self.path_rows.append([])
        return path_id

    def extend(self, rows: Iterable[FieldRow]) -> int:
        """Add already-parsed rows and index them. Returns the number added."""
        added = 0
        for row in rows:
            index = len(self.rows)
            self.rows.append(row)
            self.values_lower.append(row.value.lower())
            self.path_rows[self._path_id(row)].append(index)
            added += 1
        return added

    def add_file(self, path: str | Path) -> LoadResult:
        """Parse and index one file, reporting failure rather than raising."""
        path = Path(path)
        try:
            rows = parse_file(path)
        except NotHL7XmlError as exc:
            return LoadResult(file_name=path.name, rows_added=0, error=str(exc))
        except OSError as exc:
            return LoadResult(
                file_name=path.name, rows_added=0, error=f"could not read file: {exc}"
            )
        return LoadResult(file_name=path.name, rows_added=self.extend(rows))

    def add_files(self, paths: Sequence[str | Path]) -> list[LoadResult]:
        """Parse and index several files; one bad file does not stop the rest."""
        return [self.add_file(path) for path in paths]

    def clear(self) -> None:
        self.rows.clear()
        self.values_lower.clear()
        self.path_tokens.clear()
        self.numeric_tokens.clear()
        self.path_rows.clear()
        self._path_ids.clear()

    def distinct_paths(self) -> list[str]:
        """Every distinct collapsed path present, sorted.

        Not used by the MVP UI; it is what a Phase 2 slicer panel populates
        its multi-select controls from (HLD 7.2).
        """
        return sorted({path for path, _numeric in self._path_ids})
