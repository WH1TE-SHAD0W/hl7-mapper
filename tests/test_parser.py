"""Parsing a real HL7 XML document into rows."""

import pytest

from sickcert.parser import NotHL7XmlError, parse_bytes, parse_file


def paths(rows):
    return [row.path for row in rows]


def value_at(rows, path):
    return [row.value for row in rows if row.path == path]


def test_namespace_is_stripped_from_paths(sample_rows):
    assert not any("{" in row.path for row in sample_rows)
    assert not any("urn:hl7-org" in row.full_path for row in sample_rows)


def test_group_levels_do_not_appear_in_paths(sample_rows):
    assert not any("ORU_R01" in row.path for row in sample_rows)


def test_hld_example_paths_are_produced(sample_rows):
    found = set(paths(sample_rows))
    assert "MSH.4.HD.1" in found
    assert "OBR.4.CE.2" in found
    assert "PID.5.XPN.1.FN.1" in found
    assert "OBX.3.CE.2" in found


def test_values_resolve_at_the_expected_paths(sample_rows):
    assert value_at(sample_rows, "MSH.4.HD.1") == ["RIVERSIDE MEDICAL PRACTICE"]
    assert value_at(sample_rows, "MSH.10") == ["CERT-2026-0007741"]
    assert value_at(sample_rows, "PID.3.CX.1") == ["1234567FA"]
    assert value_at(sample_rows, "OBR.4.CE.2") == ["Thyroid disorder, unspecified"]


def test_numeric_path_is_the_datatype_free_form(sample_rows):
    row = next(r for r in sample_rows if r.path == "MSH.4.HD.1")
    assert row.numeric_path == "MSH.4.1"


def test_full_path_keeps_the_uncollapsed_chain(sample_rows):
    row = next(r for r in sample_rows if r.path == "MSH.4.HD.1")
    assert row.full_path == "ORU_R01.MSH.MSH.4.HD.1"


def test_repeated_segments_share_a_path_but_differ_in_full_path(sample_rows):
    condition_rows = [r for r in sample_rows if r.path == "OBX.3.CE.2"]
    assert len(condition_rows) == 3
    assert {r.value for r in condition_rows} == {
        "Thyroid disorder, unspecified",
        "Low back pain",
        "Certified days absent",
    }
    # Occurrence indices keep otherwise identical rows traceable.
    assert len({r.full_path for r in condition_rows}) == 3
    assert all("ORU_R01.OBSERVATION[" in r.full_path for r in condition_rows)


def test_unrepeated_siblings_carry_no_occurrence_index(sample_rows):
    row = next(r for r in sample_rows if r.path == "MSH.10")
    assert "[" not in row.full_path


def test_empty_leaf_nodes_are_skipped():
    xml = b"""<ORU_R01 xmlns="urn:hl7-org:v2xml">
        <MSH><MSH.10>ABC</MSH.10><MSH.11></MSH.11><MSH.12>   </MSH.12></MSH>
    </ORU_R01>"""
    rows = parse_bytes(xml, "t.xml")
    assert paths(rows) == ["MSH.10"]


def test_mixed_content_narrative_is_captured():
    """Clinical narrative interleaved with HL7 escape elements must survive.

    This shape is pervasive in real messages (NTE.3, OBX.5). Treating any
    element with children as a non-value node loses the whole narrative.
    """
    xml = b"""<REF_I12 xmlns="urn:hl7-org:v2xml">
        <NTE>
          <NTE.1>1</NTE.1>
          <NTE.3>COMPLAINT:Chest Pain<escape V=".br" /><escape V=".br" />OUTCOME:Admitted</NTE.3>
        </NTE>
    </REF_I12>"""
    rows = parse_bytes(xml, "t.xml")
    narrative = value_at(rows, "NTE.3")
    assert narrative == ["COMPLAINT:Chest Pain OUTCOME:Admitted"]


def test_escape_elements_do_not_produce_rows_of_their_own():
    xml = b"""<REF_I12 xmlns="urn:hl7-org:v2xml">
        <NTE><NTE.3>Head Injury<escape V=".br" />Discharged</NTE.3></NTE>
    </REF_I12>"""
    rows = parse_bytes(xml, "t.xml")
    assert paths(rows) == ["NTE.3"]


def test_text_before_a_real_child_element_is_still_captured():
    xml = b"""<ORU_R01 xmlns="urn:hl7-org:v2xml">
        <OBX><OBX.5>Free text<escape V=".br" />more<CE.1>CODE</CE.1></OBX.5></OBX>
    </ORU_R01>"""
    rows = parse_bytes(xml, "t.xml")
    assert value_at(rows, "OBX.5") == ["Free text more"]
    assert value_at(rows, "OBX.5.CE.1") == ["CODE"]


def test_elements_holding_only_whitespace_around_children_yield_no_row():
    xml = b"""<ORU_R01 xmlns="urn:hl7-org:v2xml">
        <MSH>
            <MSH.4>
                <HD.1>FACILITY</HD.1>
            </MSH.4>
        </MSH>
    </ORU_R01>"""
    rows = parse_bytes(xml, "t.xml")
    assert paths(rows) == ["MSH.4.HD.1"]


def test_depth_counts_levels_below_the_root(sample_rows):
    row = next(r for r in sample_rows if r.path == "MSH.10")
    # ORU_R01 -> MSH -> MSH.10
    assert row.depth == 2


def test_file_name_is_recorded(sample_rows, sample_path):
    assert {row.file_name for row in sample_rows} == {sample_path.name}


def test_parses_without_a_namespace_when_root_looks_like_a_message():
    xml = b"<ORU_R01><MSH><MSH.10>ABC</MSH.10></MSH></ORU_R01>"
    rows = parse_bytes(xml, "t.xml")
    assert value_at(rows, "MSH.10") == ["ABC"]


def test_rejects_non_hl7_xml():
    with pytest.raises(NotHL7XmlError, match="neither in the HL7 namespace"):
        parse_bytes(b"<catalog><book>Dune</book></catalog>", "t.xml")


def test_rejects_a_foreign_namespace():
    with pytest.raises(NotHL7XmlError, match="unexpected XML namespace"):
        parse_bytes(b'<ORU_R01 xmlns="urn:example:other"><MSH/></ORU_R01>', "t.xml")


def test_rejects_malformed_xml():
    with pytest.raises(NotHL7XmlError, match="not well-formed"):
        parse_bytes(b"<ORU_R01><MSH>", "t.xml")


def test_parse_file_reads_from_disk(sample_path):
    assert len(parse_file(sample_path)) > 0
