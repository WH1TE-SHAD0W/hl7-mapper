"""Flet desktop UI -- the only module in the project that imports flet.

Everything below the UI (parsing, path logic, search) is plain Python and is
tested without a GUI, so a Flet upgrade can only ever break this one file.

Written against Flet 0.86.4, whose API differs from the widely published 0.2x
examples: the entry point is ``ft.run``, controls are dataclasses,
``FilePicker`` is registered in ``page.services`` rather than ``page.overlay``,
and ``pick_files`` is a coroutine returning the selected files directly
instead of firing an ``on_result`` event.
"""

import asyncio

import flet as ft

from ..search import SearchEngine
from ..store import Dataset, LoadResult

#: Flet's DataTable materialises every row it is given, so the grid is capped
#: and the status line reports the true match count. HLD 9 anticipates 50,000
#: parsed rows, which no table widget will render interactively.
MAX_DISPLAYED_ROWS = 500

_COLUMN_WIDTHS = {"file": 210, "path": 230, "value": 540}


class ExplorerApp:
    """The single-search-box explorer described in HLD 5.6."""

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.dataset = Dataset()
        self.engine = SearchEngine(self.dataset)

        self.picker = ft.FilePicker()
        page.services.append(self.picker)

        self.search_field = ft.TextField(
            label="Search",
            hint_text="HL7 path (OBX.3, CE.2, OBR.*.CE.2) or free text (a condition, a facility)",
            expand=True,
            autofocus=True,
            on_submit=self.on_search,
        )
        self.status = ft.Text(
            "No messages loaded. Choose “Load HL7 XML…” to begin.",
            selectable=True,
        )
        self.table = self._build_table([])
        self.results_area = ft.Column(
            controls=[self.table],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    # -- layout ----------------------------------------------------------

    def build(self) -> None:
        self.page.title = "Sick Certificate Data Explorer"
        self.page.padding = 16
        self.page.add(
            ft.Row(
                controls=[
                    ft.Button(
                        "Load HL7 XML…",
                        icon=ft.Icons.FOLDER_OPEN,
                        on_click=self.on_load,
                    ),
                    ft.Button(
                        "Clear",
                        icon=ft.Icons.DELETE_SWEEP,
                        on_click=self.on_clear,
                    ),
                ]
            ),
            ft.Row(
                controls=[
                    self.search_field,
                    ft.Button(
                        "Search",
                        icon=ft.Icons.SEARCH,
                        on_click=self.on_search,
                    ),
                ]
            ),
            self.status,
            ft.Divider(),
            self.results_area,
        )

    def _build_table(self, rows) -> ft.DataTable:
        def cell(text: str, width: int) -> ft.DataCell:
            return ft.DataCell(
                ft.Container(
                    content=ft.Text(text, selectable=True, max_lines=3),
                    width=width,
                )
            )

        def header(text: str, width: int) -> ft.DataColumn:
            return ft.DataColumn(
                ft.Container(
                    content=ft.Text(text, weight=ft.FontWeight.BOLD),
                    width=width,
                )
            )

        return ft.DataTable(
            columns=[
                header("File", _COLUMN_WIDTHS["file"]),
                header("Path", _COLUMN_WIDTHS["path"]),
                header("Value", _COLUMN_WIDTHS["value"]),
            ],
            rows=[
                ft.DataRow(
                    cells=[
                        cell(row.file_name, _COLUMN_WIDTHS["file"]),
                        cell(row.path, _COLUMN_WIDTHS["path"]),
                        cell(row.value, _COLUMN_WIDTHS["value"]),
                    ]
                )
                for row in rows
            ],
            column_spacing=24,
            heading_row_height=40,
        )

    # -- event handlers --------------------------------------------------

    async def on_load(self, _event: ft.ControlEvent) -> None:
        files = await self.picker.pick_files(
            dialog_title="Select HL7 XML message files",
            allow_multiple=True,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["xml"],
        )
        if not files:
            return

        paths = [file.path for file in files if file.path]
        # Parsing is CPU work; keep it off the UI thread so a large batch
        # cannot freeze the window.
        results = await asyncio.to_thread(self.dataset.add_files, paths)

        self._render(self.engine.search(self.search_field.value or ""))
        self.status.value = self._describe_load(results)
        self.page.update()

    async def on_search(self, _event: ft.ControlEvent) -> None:
        if not self.dataset.rows:
            self.status.value = "No messages loaded yet."
            self.page.update()
            return

        result = self.engine.search(self.search_field.value or "")
        self._render(result)
        self.status.value = self._describe_search(result)
        self.page.update()

    async def on_clear(self, _event: ft.ControlEvent) -> None:
        self.dataset.clear()
        self.search_field.value = ""
        self._render(self.engine.search(""))
        self.status.value = "Cleared. No messages loaded."
        self.page.update()

    # -- rendering -------------------------------------------------------

    def _render(self, result) -> None:
        self.table = self._build_table(result.rows[:MAX_DISPLAYED_ROWS])
        self.results_area.controls = [self.table]

    @staticmethod
    def _describe_load(results: list[LoadResult]) -> str:
        loaded = [r for r in results if r.ok]
        failed = [r for r in results if not r.ok]
        rows = sum(r.rows_added for r in loaded)

        parts = [
            f"Loaded {len(loaded)} file{'s' if len(loaded) != 1 else ''}, "
            f"{rows:,} rows."
        ]
        if failed:
            detail = "; ".join(f"{r.file_name}: {r.error}" for r in failed)
            parts.append(f"Skipped {len(failed)}: {detail}")
        return "  ".join(parts)

    def _describe_search(self, result) -> str:
        total = len(result)
        if total == 0:
            return f"0 matches for {result.query!r}."

        shown = min(total, MAX_DISPLAYED_ROWS)
        counted = (
            f"{total:,} matches"
            if shown == total
            else f"showing {shown:,} of {total:,} matches"
        )
        return f"{counted} · matched on {result.mode_label}."


def main(page: ft.Page) -> None:
    ExplorerApp(page).build()


def run() -> None:
    ft.run(main)
