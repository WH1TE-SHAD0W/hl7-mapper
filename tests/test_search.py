"""The four branches of the single search box (HLD 7.1)."""

import time

import pytest

from hl7msg.model import FieldRow
from hl7msg.search import (
    MODE_ALL,
    MODE_NONE,
    MODE_PATH,
    MODE_SEGMENT,
    MODE_VALUE,
    SearchEngine,
)
from hl7msg.store import Dataset


@pytest.fixture
def engine(dataset):
    return SearchEngine(dataset)


def test_blank_query_returns_everything(engine, dataset):
    result = engine.search("   ")
    assert result.mode == MODE_ALL
    assert len(result) == len(dataset)


def test_path_spec_matches_full_path(engine):
    result = engine.search("OBR.4.CE.2")
    assert result.mode == MODE_PATH
    assert [row.value for row in result.rows] == ["Thyroid disorder, unspecified"]


def test_path_spec_matches_a_trailing_component_alone(engine):
    # The workbook case that motivated the tool: find every CE.2 anywhere.
    result = engine.search("CE.2")
    assert result.mode == MODE_PATH
    assert {row.path for row in result.rows} == {"OBR.4.CE.2", "OBX.3.CE.2"}


def test_path_spec_matches_a_segment_and_field_prefix(engine):
    result = engine.search("OBX.3")
    assert result.mode == MODE_PATH
    assert all(row.path.startswith("OBX.3") for row in result.rows)


def test_path_spec_accepts_wildcards(engine):
    result = engine.search("OBR.*.CE.2")
    assert result.mode == MODE_PATH
    assert [row.value for row in result.rows] == ["Thyroid disorder, unspecified"]


def test_path_spec_matches_the_numeric_form(engine):
    result = engine.search("MSH.4.1")
    assert result.mode == MODE_PATH
    assert [row.value for row in result.rows] == ["RIVERSIDE MEDICAL PRACTICE"]


def test_path_spec_is_case_insensitive(engine):
    assert engine.search("obr.4.ce.2").rows == engine.search("OBR.4.CE.2").rows


def test_free_text_matches_a_condition_name(engine):
    result = engine.search("Thyroid")
    assert result.mode == MODE_VALUE
    assert all("thyroid" in row.value.lower() for row in result.rows)
    assert {row.path for row in result.rows} == {"OBR.4.CE.2", "OBX.3.CE.2"}


def test_free_text_is_case_insensitive(engine):
    assert engine.search("low back pain").rows == engine.search("LOW BACK PAIN").rows


def test_free_text_matches_a_facility_name(engine):
    result = engine.search("Riverside")
    assert result.mode == MODE_VALUE
    assert [row.path for row in result.rows] == ["MSH.4.HD.1"]


def test_bare_segment_falls_back_to_segment_matching(engine):
    result = engine.search("OBR")
    assert result.mode == MODE_SEGMENT
    assert result.rows
    assert all(row.path.startswith("OBR") for row in result.rows)


def test_segment_fallback_only_fires_when_value_matching_finds_nothing(engine):
    # "F" appears as a value (PID.8 gender, OBX.11 status), so the value
    # branch wins and the segment branch is never reached.
    result = engine.search("F")
    assert result.mode == MODE_VALUE


def test_path_spec_falls_back_to_value_when_no_path_matches(engine):
    dataset = Dataset()
    dataset.extend(
        [
            FieldRow(
                file_name="t.xml",
                path="OBX.3.CE.2",
                value="Diagnosis N.O.S recorded",
                full_path="ORU_R01.OBX.OBX.3.CE.2",
                numeric_path="OBX.3.2",
                depth=3,
            )
        ]
    )
    result = SearchEngine(dataset).search("N.O.S")
    assert result.mode == MODE_VALUE
    assert len(result) == 1


def test_no_match_returns_an_empty_result(engine):
    result = engine.search("zzz-nothing-matches-this")
    assert result.mode == MODE_NONE
    assert result.rows == []


def test_mode_label_is_human_readable(engine):
    assert engine.search("OBR.4.CE.2").mode_label == "path spec"
    assert engine.search("Thyroid").mode_label == "value text"


def test_search_stays_well_inside_the_one_second_budget(sample_rows):
    """HLD 9: results in under 1 second for at least 50,000 parsed rows."""
    dataset = Dataset()
    while len(dataset) < 50_000:
        dataset.extend(sample_rows)
    assert len(dataset) >= 50_000

    engine = SearchEngine(dataset)
    for query in ("OBX.3.CE.2", "CE.2", "Thyroid", "OBR"):
        start = time.perf_counter()
        result = engine.search(query)
        elapsed = time.perf_counter() - start
        assert result.rows, f"{query!r} matched nothing"
        assert elapsed < 1.0, f"{query!r} took {elapsed:.3f}s"
