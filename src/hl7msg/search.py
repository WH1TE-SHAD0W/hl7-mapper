"""The single-search-box engine described in HLD 7.1.

One query syntax covers both lookups the Excel workflow needed: locate a
technical HL7 path, or locate a value such as a medical condition. The engine
decides which the user meant, so there is no mode to pick.
"""

from dataclasses import dataclass, field
from typing import Sequence

from .model import FieldRow
from .pathspec import is_path_spec, path_matches, tokenize
from .store import Dataset

MODE_ALL = "all"
MODE_PATH = "path"
MODE_VALUE = "value"
MODE_SEGMENT = "segment"
MODE_NONE = "none"

#: Human-readable mode names for the UI status line, so the user can tell why
#: something matched.
MODE_LABELS = {
    MODE_ALL: "all rows",
    MODE_PATH: "path spec",
    MODE_VALUE: "value text",
    MODE_SEGMENT: "segment name",
    MODE_NONE: "no match",
}


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Matching rows plus which branch of the engine produced them."""

    rows: list[FieldRow] = field(default_factory=list)
    mode: str = MODE_NONE
    query: str = ""

    @property
    def mode_label(self) -> str:
        return MODE_LABELS.get(self.mode, self.mode)

    def __len__(self) -> int:
        return len(self.rows)


class SearchEngine:
    """Queries a Dataset using its precomputed index."""

    def __init__(self, dataset: Dataset) -> None:
        self._dataset = dataset

    def search(self, query: str) -> SearchResult:
        """Resolve a query to matching rows.

        A path spec is matched against the path first and falls back to value
        text, so a query that merely looks like a path (for example an
        abbreviation containing dots) still finds a genuine value match rather
        than returning nothing. Free text is matched against the value first
        and falls back to a bare segment name, so typing ``OBR`` alone narrows
        to that segment (HLD 7.1).
        """
        query = query.strip()
        data = self._dataset

        if not query:
            return SearchResult(rows=list(data.rows), mode=MODE_ALL, query=query)

        if is_path_spec(query):
            rows = self._match_path(query)
            if rows:
                return SearchResult(rows=rows, mode=MODE_PATH, query=query)
            rows = self._match_value(query)
            mode = MODE_VALUE if rows else MODE_NONE
            return SearchResult(rows=rows, mode=mode, query=query)

        rows = self._match_value(query)
        if rows:
            return SearchResult(rows=rows, mode=MODE_VALUE, query=query)

        rows = self._match_segment(query)
        mode = MODE_SEGMENT if rows else MODE_NONE
        return SearchResult(rows=rows, mode=mode, query=query)

    def _match_path(self, query: str) -> list[FieldRow]:
        """Rows whose path or numeric path contains the query as a token run.

        Matching runs once per *distinct* path rather than once per row, then
        collects the rows behind the paths that matched.
        """
        tokens: Sequence[str] = tokenize(query)
        data = self._dataset
        matched = [
            path_id
            for path_id in range(len(data.path_tokens))
            if path_matches(
                tokens, data.path_tokens[path_id], data.numeric_tokens[path_id]
            )
        ]
        return self._rows_for(matched)

    def _rows_for(self, path_ids: list[int]) -> list[FieldRow]:
        """Collect rows behind the given path ids, in document order."""
        data = self._dataset
        indices: list[int] = []
        for path_id in path_ids:
            indices.extend(data.path_rows[path_id])
        indices.sort()
        return [data.rows[index] for index in indices]

    def _match_value(self, query: str) -> list[FieldRow]:
        """Rows whose value contains the query, case-insensitively."""
        needle = query.lower()
        data = self._dataset
        return [
            row
            for index, row in enumerate(data.rows)
            if needle in data.values_lower[index]
        ]

    def _match_segment(self, query: str) -> list[FieldRow]:
        """Rows whose path contains the query as a whole token.

        The fallback that makes a bare ``OBR`` or ``PID`` behave the way an
        analyst expects.
        """
        token = query.upper()
        data = self._dataset
        matched = [
            path_id
            for path_id in range(len(data.path_tokens))
            if token in data.path_tokens[path_id]
        ]
        return self._rows_for(matched)
