"""UI wiring, driven headlessly against a stub page.

Flet renders through Flutter to a canvas, so there is no DOM to assert on.
These tests instead exercise the real ExplorerApp handlers and check the two
things the UI layer is actually responsible for: what the status line says,
and how many rows reach the table.
"""

import asyncio

import pytest

from sickcert.model import FieldRow
from sickcert.ui.app import MAX_DISPLAYED_ROWS, ExplorerApp


class StubPage:
    """The minimum Page surface ExplorerApp touches."""

    def __init__(self) -> None:
        self.services: list = []
        self.controls: list = []
        self.title = ""
        self.padding = 0
        self.updates = 0

    def add(self, *controls) -> None:
        self.controls.extend(controls)

    def update(self) -> None:
        self.updates += 1


@pytest.fixture
def app(sample_rows):
    application = ExplorerApp(StubPage())
    application.build()
    application.dataset.extend(sample_rows)
    return application


def drive(coro):
    return asyncio.run(coro)


def table_row_count(app) -> int:
    return len(app.results_area.controls[0].rows)


def test_build_registers_the_file_picker_as_a_service():
    application = ExplorerApp(StubPage())
    application.build()
    assert application.picker in application.page.services
    assert application.page.title == "Sick Certificate Data Explorer"


def test_search_renders_matching_rows_and_reports_the_mode(app):
    app.search_field.value = "OBR.4.CE.2"
    drive(app.on_search(None))
    assert table_row_count(app) == 1
    assert "1 matches" in app.status.value
    assert "path spec" in app.status.value


def test_free_text_search_reports_value_mode(app):
    app.search_field.value = "Thyroid"
    drive(app.on_search(None))
    assert table_row_count(app) == 2
    assert "value text" in app.status.value


def test_bare_segment_reports_segment_mode(app):
    app.search_field.value = "OBR"
    drive(app.on_search(None))
    assert "segment name" in app.status.value
    assert table_row_count(app) > 0


def test_no_match_renders_an_empty_table_without_error(app):
    app.search_field.value = "zzz-nothing-matches-this"
    drive(app.on_search(None))
    assert table_row_count(app) == 0
    assert app.status.value.startswith("0 matches")


def test_searching_before_loading_says_so():
    application = ExplorerApp(StubPage())
    application.build()
    application.search_field.value = "OBX.3"
    drive(application.on_search(None))
    assert application.status.value == "No messages loaded yet."


def test_results_are_capped_and_the_true_total_is_reported(app):
    filler = [
        FieldRow(
            file_name=f"bulk_{index}.xml",
            path="OBX.3.CE.2",
            value=f"Condition {index}",
            full_path="ORU_R01.OBX.OBX.3.CE.2",
            numeric_path="OBX.3.2",
            depth=3,
        )
        for index in range(MAX_DISPLAYED_ROWS * 3)
    ]
    app.dataset.extend(filler)

    app.search_field.value = "OBX.3.CE.2"
    drive(app.on_search(None))

    # The fixture already contributes 3 rows at this path.
    expected_total = MAX_DISPLAYED_ROWS * 3 + 3
    assert table_row_count(app) == MAX_DISPLAYED_ROWS
    assert (
        f"showing {MAX_DISPLAYED_ROWS:,} of {expected_total:,} matches"
        in app.status.value
    )


def test_clear_empties_the_dataset_and_the_grid(app):
    app.search_field.value = "Thyroid"
    drive(app.on_search(None))
    assert table_row_count(app) > 0

    drive(app.on_clear(None))
    assert len(app.dataset) == 0
    assert app.search_field.value == ""
    assert table_row_count(app) == 0
    assert "Cleared" in app.status.value


def test_load_summary_counts_files_and_reports_failures():
    from sickcert.store import LoadResult

    summary = ExplorerApp._describe_load(
        [
            LoadResult("a.xml", 40),
            LoadResult("b.xml", 38),
            LoadResult("notes.xml", 0, error="root element 'catalog' is not HL7"),
        ]
    )
    assert "Loaded 2 files, 78 rows." in summary
    assert "Skipped 1" in summary
    assert "notes.xml" in summary


def test_load_summary_is_singular_for_one_file():
    from sickcert.store import LoadResult

    assert "Loaded 1 file, 12 rows." in ExplorerApp._describe_load(
        [LoadResult("a.xml", 12)]
    )
