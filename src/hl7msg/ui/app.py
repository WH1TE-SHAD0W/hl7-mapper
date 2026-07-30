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

from ..export import ExportError, suggested_filename, write_xlsx
from ..search import SearchEngine, SearchResult
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

        # The most recent result, kept so export can write the *whole* match
        # set. The table only ever holds MAX_DISPLAYED_ROWS of it.
        self.last_result: SearchResult | None = None

        # The most recent ingest, kept so the load report can explain which
        # files were damaged or unreadable.
        self.last_load: list[LoadResult] = []

        self.report_button = ft.Button(
            "Load report",
            icon=ft.Icons.REPORT_PROBLEM,
            on_click=self.on_show_report,
            disabled=True,
        )

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
        self.page.title = "HL7 Message Data Explorer"
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
                        "Export to Excel…",
                        icon=ft.Icons.TABLE_VIEW,
                        on_click=self.on_export,
                    ),
                    self.report_button,
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

        self.last_load = results
        self.report_button.disabled = not any(r.needs_attention for r in results)
        self._render(self.engine.search(self.search_field.value or ""))
        self.status.value = self._describe_load(results)
        self.page.update()

    async def on_show_report(self, _event: ft.ControlEvent) -> None:
        """Show what went wrong with any file that was not read cleanly."""
        problems = [r for r in self.last_load if r.needs_attention]
        if not problems:
            self.status.value = "Every file loaded cleanly — nothing to report."
            self.page.update()
            return

        # Outright failures first, then partial recoveries, then by name.
        problems.sort(key=lambda r: (r.ok, r.file_name))

        self.page.show_dialog(
            ft.AlertDialog(
                title=ft.Text(f"Load report — {len(problems)} files"),
                content=ft.Container(
                    content=ft.Column(
                        controls=[self._build_report_table(problems)],
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    width=1000,
                    height=460,
                ),
                actions=[ft.Button("Close", on_click=self.on_close_report)],
            )
        )

    async def on_close_report(self, _event: ft.ControlEvent) -> None:
        self.page.pop_dialog()

    async def on_search(self, _event: ft.ControlEvent) -> None:
        if not self.dataset.rows:
            self.status.value = "No messages loaded yet."
            self.page.update()
            return

        result = self.engine.search(self.search_field.value or "")
        self._render(result)
        self.status.value = self._describe_search(result)
        self.page.update()

    async def on_export(self, _event: ft.ControlEvent) -> None:
        """Write the full current result set to an .xlsx workbook.

        Exports ``last_result``, never the table -- the grid holds at most
        MAX_DISPLAYED_ROWS, and silently exporting only what happened to be
        rendered would hand the analyst an incomplete extract.
        """
        result = self.last_result
        if result is None or not result.rows:
            self.status.value = "Nothing to export — load messages and search first."
            self.page.update()
            return

        destination = await self.picker.save_file(
            dialog_title="Export results to Excel",
            file_name=suggested_filename(result.query),
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["xlsx"],
        )
        if not destination:
            return

        total = len(result)
        self.status.value = f"Exporting {total:,} rows…"
        self.page.update()

        source_files = sorted({row.file_name for row in result.rows})
        try:
            # Writing tens of thousands of rows takes a noticeable moment.
            written = await asyncio.to_thread(
                write_xlsx,
                result.rows,
                destination,
                query=result.query,
                mode=result.mode_label,
                source_files=source_files,
                recovered_files=sorted(self.dataset.recovered_files),
            )
        except (ExportError, OSError) as exc:
            self.status.value = f"Export failed: {exc}"
        else:
            self.status.value = (
                f"Exported {total:,} rows from {len(source_files)} "
                f"file{'s' if len(source_files) != 1 else ''} to {written.name}"
            )
        self.page.update()

    async def on_clear(self, _event: ft.ControlEvent) -> None:
        self.dataset.clear()
        self.search_field.value = ""
        self.last_load = []
        self.report_button.disabled = True
        self._render(self.engine.search(""))
        self.status.value = "Cleared. No messages loaded."
        self.page.update()

    # -- rendering -------------------------------------------------------

    def _render(self, result: SearchResult) -> None:
        # Every code path that changes what is on screen goes through here, so
        # this is the one place last_result needs updating.
        self.last_result = result
        self.table = self._build_table(result.rows[:MAX_DISPLAYED_ROWS])
        self.results_area.controls = [self.table]

    @staticmethod
    def _build_report_table(problems: list[LoadResult]) -> ft.DataTable:
        widths = {"file": 320, "outcome": 110, "rows": 80, "detail": 460}

        def cell(text: str, width: int, colour: str | None = None) -> ft.DataCell:
            return ft.DataCell(
                ft.Container(
                    content=ft.Text(
                        text, selectable=True, max_lines=3, color=colour
                    ),
                    width=width,
                )
            )

        def header(text: str, width: int) -> ft.DataColumn:
            return ft.DataColumn(
                ft.Container(
                    content=ft.Text(text, weight=ft.FontWeight.BOLD), width=width
                )
            )

        rows = []
        for result in problems:
            if result.ok:
                outcome, colour = "Recovered", ft.Colors.AMBER
                detail = result.issues[0] if result.issues else ""
            else:
                outcome, colour = "Failed", ft.Colors.RED
                detail = result.error or ""
            rows.append(
                ft.DataRow(
                    cells=[
                        cell(result.file_name, widths["file"]),
                        cell(outcome, widths["outcome"], colour),
                        cell(f"{result.rows_added:,}", widths["rows"]),
                        cell(detail, widths["detail"]),
                    ]
                )
            )

        return ft.DataTable(
            columns=[
                header("File", widths["file"]),
                header("Outcome", widths["outcome"]),
                header("Rows", widths["rows"]),
                header("First problem", widths["detail"]),
            ],
            rows=rows,
            column_spacing=20,
            heading_row_height=40,
        )

    @staticmethod
    def _describe_load(results: list[LoadResult]) -> str:
        loaded = [r for r in results if r.ok]
        recovered = [r for r in loaded if r.recovered]
        failed = [r for r in results if not r.ok]
        rows = sum(r.rows_added for r in loaded)

        parts = [
            f"Loaded {len(loaded)} file{'s' if len(loaded) != 1 else ''}, "
            f"{rows:,} rows."
        ]
        if recovered:
            # Say plainly that these are incomplete. A partial message that
            # reads as whole is the one genuinely dangerous outcome here.
            parts.append(
                f"{len(recovered)} damaged and only partly recovered "
                f"({sum(r.rows_added for r in recovered):,} rows)."
            )
        if failed:
            parts.append(f"{len(failed)} could not be read at all.")
        if recovered or failed:
            parts.append("See Load report.")
        return " ".join(parts)

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
