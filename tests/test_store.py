"""Dataset indexing invariants.

The distinct-path table is what makes path search fast, so the properties the
search engine relies on are pinned here.
"""

from hl7msg.model import FieldRow
from hl7msg.search import SearchEngine
from hl7msg.store import Dataset


def row(path: str, value: str, numeric: str = "") -> FieldRow:
    return FieldRow(
        file_name="t.xml",
        path=path,
        value=value,
        full_path=f"ORU_R01.{path}",
        numeric_path=numeric or path,
        depth=2,
    )


def test_rows_sharing_a_path_are_grouped_under_one_entry():
    data = Dataset()
    data.extend([row("OBX.3.CE.2", f"v{n}") for n in range(50)])
    assert len(data) == 50
    assert len(data.path_tokens) == 1
    assert len(data.path_rows[0]) == 50


def test_distinct_paths_get_distinct_entries():
    data = Dataset()
    data.extend([row("OBX.3.CE.2", "a"), row("OBR.4.CE.2", "b"), row("MSH.10", "c")])
    assert len(data.path_tokens) == 3
    assert data.distinct_paths() == ["MSH.10", "OBR.4.CE.2", "OBX.3.CE.2"]


def test_paths_differing_only_in_numeric_form_stay_separate():
    data = Dataset()
    data.extend(
        [
            row("MSH.4.HD.1", "a", numeric="MSH.4.1"),
            row("MSH.4.HD.2", "b", numeric="MSH.4.2"),
        ]
    )
    assert len(data.path_tokens) == 2


def test_search_returns_rows_in_document_order_across_paths():
    data = Dataset()
    # Interleave paths so grouping cannot accidentally preserve order.
    data.extend(
        [
            row("OBR.4.CE.2", "first"),
            row("OBX.3.CE.2", "second"),
            row("OBR.4.CE.2", "third"),
            row("OBX.3.CE.2", "fourth"),
        ]
    )
    result = SearchEngine(data).search("CE.2")
    assert [r.value for r in result.rows] == ["first", "second", "third", "fourth"]


def test_clear_resets_the_path_table_too():
    data = Dataset()
    data.extend([row("OBX.3.CE.2", "a"), row("MSH.10", "b")])
    data.clear()
    assert len(data) == 0
    assert data.path_tokens == []
    assert data.path_rows == []
    assert data.distinct_paths() == []

    # And the table rebuilds cleanly afterwards.
    data.extend([row("MSH.10", "c")])
    assert len(data.path_tokens) == 1
    assert SearchEngine(data).search("MSH.10").rows[0].value == "c"


def test_extend_reports_how_many_rows_it_added():
    data = Dataset()
    assert data.extend([row("MSH.10", "a"), row("MSH.10", "b")]) == 2
    assert data.extend([]) == 0


# -- recovery ------------------------------------------------------------

GOOD = b"""<ORU_R01 xmlns="urn:hl7-org:v2xml">
    <MSH><MSH.10>CERT-OK</MSH.10></MSH>
</ORU_R01>"""

DAMAGED = b"""<REF_I12 xmlns="urn:hl7-org:v2xml">
    <MSH><MSH.10>CERT-DAMAGED</MSH.10></MSH
</REF_I12>"""


def test_a_good_file_loads_without_the_recovered_flag(tmp_path):
    path = tmp_path / "good.xml"
    path.write_bytes(GOOD)

    data = Dataset()
    result = data.add_file(path)

    assert result.ok
    assert result.recovered is False
    assert result.needs_attention is False
    assert data.recovered_files == set()


def test_a_damaged_file_is_recovered_rather_than_skipped(tmp_path):
    path = tmp_path / "damaged.xml"
    path.write_bytes(DAMAGED)

    data = Dataset()
    result = data.add_file(path)

    assert result.ok
    assert result.recovered is True
    assert result.needs_attention is True
    assert result.rows_added > 0
    assert result.issues
    assert data.recovered_files == {"damaged.xml"}
    assert [r.value for r in data.rows] == ["CERT-DAMAGED"]


def test_a_damaged_file_does_not_stop_the_batch(tmp_path):
    (tmp_path / "a_good.xml").write_bytes(GOOD)
    (tmp_path / "b_damaged.xml").write_bytes(DAMAGED)
    (tmp_path / "c_notxml.xml").write_bytes(b"<catalog><book>Dune</book></catalog>")

    data = Dataset()
    results = data.add_files(sorted(tmp_path.glob("*.xml")))

    assert [r.file_name for r in results if r.ok] == ["a_good.xml", "b_damaged.xml"]
    assert [r.file_name for r in results if not r.ok] == ["c_notxml.xml"]
    assert [r.file_name for r in results if r.needs_attention] == [
        "b_damaged.xml",
        "c_notxml.xml",
    ]
    assert len(data) == 2


def test_clear_forgets_which_files_were_recovered(tmp_path):
    path = tmp_path / "damaged.xml"
    path.write_bytes(DAMAGED)

    data = Dataset()
    data.add_file(path)
    assert data.recovered_files

    data.clear()
    assert data.recovered_files == set()
