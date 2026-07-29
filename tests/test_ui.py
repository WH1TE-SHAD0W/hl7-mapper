"""UI wiring, driven headlessly against a stub page.

Flet renders through Flutter to a canvas, so there is no DOM to assert on.
These tests instead exercise the real ExplorerApp handlers and check the two
things the UI layer is actually responsible for: what the status line says,
and how many rows reach the table.
"""

import asyncio

import pytest
from openpyxl import load_workbook

from hl7msg.model import FieldRow
from hl7msg.ui.app import MAX_DISPLAYED_ROWS, ExplorerApp


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
    assert application.page.title == "HL7 Message Data Explorer"


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


# -- export --------------------------------------------------------------


class StubPicker:
    """Stands in for the native save dialog.

    Returns `destination` from save_file, or None to simulate a cancel, and
    records the arguments it was called with.
    """

    def __init__(self, destination=None):
        self.destination = destination
        self.calls = []

    async def save_file(self, **kwargs):
        self.calls.append(kwargs)
        return self.destination


def test_export_writes_every_match_not_just_the_displayed_page(app, tmp_path):
    """The whole point: the 500-row grid cap must not reach the workbook."""
    app.dataset.extend(
        [
            FieldRow(
                file_name=f"bulk_{n}.xml",
                path="OBX.3.CE.2",
                value=f"Condition {n}",
                full_path="ORU_R01.OBX.OBX.3.CE.2",
                numeric_path="OBX.3.2",
                depth=3,
            )
            for n in range(MAX_DISPLAYED_ROWS * 2)
        ]
    )
    app.search_field.value = "OBX.3.CE.2"
    drive(app.on_search(None))
    assert table_row_count(app) == MAX_DISPLAYED_ROWS

    destination = tmp_path / "out.xlsx"
    app.picker = StubPicker(str(destination))
    drive(app.on_export(None))

    expected = MAX_DISPLAYED_ROWS * 2 + 3  # fixture contributes 3
    written = load_workbook(destination)["Results"].max_row - 1
    assert written == expected
    assert f"Exported {expected:,} rows" in app.status.value


def test_export_passes_the_query_and_mode_through_to_the_workbook(app, tmp_path):
    app.search_field.value = "OBR.4.CE.2"
    drive(app.on_search(None))

    destination = tmp_path / "out.xlsx"
    app.picker = StubPicker(str(destination))
    drive(app.on_export(None))

    info = {
        r[0].value: r[1].value
        for r in load_workbook(destination)["Export Info"].iter_rows(max_row=5)
    }
    assert info["Query"] == "OBR.4.CE.2"
    assert info["Matched on"] == "path spec"


def test_export_suggests_a_filename_derived_from_the_query(app, tmp_path):
    app.search_field.value = "OBX.3"
    drive(app.on_search(None))

    picker = StubPicker(str(tmp_path / "out.xlsx"))
    app.picker = picker
    drive(app.on_export(None))

    suggested = picker.calls[0]["file_name"]
    assert suggested.startswith("hl7msg_OBX-3_")
    assert suggested.endswith(".xlsx")
    assert picker.calls[0]["allowed_extensions"] == ["xlsx"]


def test_cancelling_the_save_dialog_writes_nothing(app, tmp_path):
    app.search_field.value = "OBR.4.CE.2"
    drive(app.on_search(None))
    status_before = app.status.value

    app.picker = StubPicker(None)
    drive(app.on_export(None))

    assert list(tmp_path.iterdir()) == []
    assert app.status.value == status_before


def test_export_before_any_search_says_so():
    application = ExplorerApp(StubPage())
    application.build()
    application.picker = StubPicker("unused.xlsx")
    drive(application.on_export(None))
    assert "Nothing to export" in application.status.value


def test_export_of_an_empty_result_says_so(app, tmp_path):
    app.search_field.value = "zzz-nothing-matches-this"
    drive(app.on_search(None))

    app.picker = StubPicker(str(tmp_path / "out.xlsx"))
    drive(app.on_export(None))

    assert "Nothing to export" in app.status.value
    assert list(tmp_path.iterdir()) == []


def test_export_failure_is_reported_rather_than_raised(app, tmp_path):
    app.search_field.value = "OBR.4.CE.2"
    drive(app.on_search(None))

    # A directory that does not exist and cannot be created (a file is in the way).
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    app.picker = StubPicker(str(blocker / "sub" / "out.xlsx"))

    drive(app.on_export(None))
    assert app.status.value.startswith("Export failed:")


def test_load_summary_counts_files_and_reports_failures():
    from hl7msg.store import LoadResult

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
    from hl7msg.store import LoadResult

    assert "Loaded 1 file, 12 rows." in ExplorerApp._describe_load(
        [LoadResult("a.xml", 12)]
    )
