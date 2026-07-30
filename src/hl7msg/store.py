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

    #: True when the file was damaged and only part of it could be read.
    recovered: bool = False

    #: What the recovering parser objected to, for the load report.
    issues: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def needs_attention(self) -> bool:
        """True if this file is worth showing the user afterwards."""
        return not self.ok or self.recovered


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

        #: Files whose rows are only what survived recovery. Lets later
        #: analysis tell partial messages apart without putting a flag on
        #: every FieldRow.
        self.recovered_files: set[str] = set()

        # Distinct-path table. Entry i describes one distinct (path,
        # numeric_path) pair; path_rows[i] lists the rows that have it.
        self.path_tokens: list[tuple[str, ...]] = []
        self.numeric_tokens: list[tuple[str, ...]] = []
        self.path_rows: list[list[int]] = []
        self._path_ids: dict[tuple[str, str], int] = {}

        # Direct lookups used by correlated search, which works one file at a
        # time and one column at a time rather than scanning everything.
        self.rows_by_file: dict[str, list[int]] = {}
        self.rows_by_path: dict[str, list[int]] = {}

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
            self.rows_by_file.setdefault(row.file_name, []).append(index)
            self.rows_by_path.setdefault(row.path, []).append(index)
            added += 1
        return added

    def file_rows(self, file_name: str) -> list[FieldRow]:
        """Every row parsed from one file, in document order."""
        return [self.rows[i] for i in self.rows_by_file.get(file_name, ())]

    def occurrence_depth(self, path: str) -> int:
        """Deepest repeat nesting seen at ``path``.

        Used to pick the anchor of a projection: the column nested inside the
        most repeats defines the finest grain the table can have.
        """
        return max(
            (len(self.rows[i].occurrence) for i in self.rows_by_path.get(path, ())),
            default=0,
        )

    def add_file(self, path: str | Path) -> LoadResult:
        """Parse and index one file, reporting failure rather than raising.

        A damaged file is recovered rather than skipped, and the result says
        so -- its rows are only the part of the message that survived.
        """
        path = Path(path)
        try:
            outcome = parse_file(path)
        except NotHL7XmlError as exc:
            return LoadResult(file_name=path.name, rows_added=0, error=str(exc))
        except OSError as exc:
            return LoadResult(
                file_name=path.name, rows_added=0, error=f"could not read file: {exc}"
            )

        if outcome.recovered:
            self.recovered_files.add(path.name)

        return LoadResult(
            file_name=path.name,
            rows_added=self.extend(outcome.rows),
            recovered=outcome.recovered,
            issues=outcome.issues,
        )

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
        self.recovered_files.clear()
        self.rows_by_file.clear()
        self.rows_by_path.clear()

    def distinct_paths(self) -> list[str]:
        """Every distinct collapsed path present, sorted.

        Not used by the MVP UI; it is what a Phase 2 slicer panel populates
        its multi-select controls from (HLD 7.2).
        """
        return sorted({path for path, _numeric in self._path_ids})
