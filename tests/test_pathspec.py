"""Collapsing rules and path-spec query matching.

The expected paths below are the literals the HLD itself uses, so these tests
pin the notation analysts already read in the workbook.
"""

import pytest

from hl7msg.pathspec import (
    collapse_tags,
    is_group_tag,
    is_path_spec,
    path_matches,
    tokenize,
)


@pytest.mark.parametrize(
    "tag, expected",
    [
        ("ORU_R01", True),
        ("ORU_R01.PATIENT_RESULT", True),
        ("ORU_R01.ORDER_OBSERVATION", True),
        ("ADT_A01.INSURANCE", True),
        ("MSH", False),
        ("MSH.4", False),
        ("HD.1", False),
        ("OBX", False),
    ],
)
def test_group_tags_are_message_structures(tag, expected):
    assert is_group_tag(tag) is expected


@pytest.mark.parametrize(
    "tags, expected_path, expected_numeric",
    [
        # The HLD's own examples.
        (["ORU_R01", "MSH", "MSH.4", "HD.1"], "MSH.4.HD.1", "MSH.4.1"),
        (
            ["ORU_R01", "ORU_R01.PATIENT_RESULT", "ORU_R01.ORDER_OBSERVATION",
             "OBR", "OBR.4", "CE.2"],
            "OBR.4.CE.2",
            "OBR.4.2",
        ),
        (
            ["ORU_R01", "ORU_R01.PATIENT_RESULT", "ORU_R01.PATIENT",
             "PID", "PID.5", "XPN.1"],
            "PID.5.XPN.1",
            "PID.5.1",
        ),
        # Subcomponent nesting: the datatype changes twice.
        (
            ["ORU_R01", "PID", "PID.5", "XPN.1", "FN.1"],
            "PID.5.XPN.1.FN.1",
            "PID.5.1.1",
        ),
        # A field with no components collapses to just segment and field.
        (["ORU_R01", "MSH", "MSH.10"], "MSH.10", "MSH.10"),
        # A bare segment on its own.
        (["ORU_R01", "OBX"], "OBX", "OBX"),
    ],
)
def test_collapse_tags(tags, expected_path, expected_numeric):
    assert collapse_tags(tags) == (expected_path, expected_numeric)


def test_collapse_drops_every_group_level():
    tags = ["ORU_R01", "ORU_R01.PATIENT_RESULT", "ORU_R01.ORDER_OBSERVATION",
            "ORU_R01.OBSERVATION", "OBX", "OBX.3", "CE.2"]
    assert collapse_tags(tags) == ("OBX.3.CE.2", "OBX.3.2")


@pytest.mark.parametrize(
    "query, expected",
    [
        ("OBX.3", True),
        ("CE.2", True),
        ("OBR.4.CE.2", True),
        ("PID.5.XPN.1", True),
        ("OBR.*.CE.2", True),
        ("MSH.4.1", True),
        # No dot: a bare segment name is free text, which is what routes it to
        # the segment fallback in the search engine.
        ("OBR", False),
        ("", False),
        # Free text never masquerades as a path.
        ("Thyroid disorder", False),
        ("Dr. Walsh", False),
        ("RIVERSIDE MEDICAL PRACTICE", False),
        # A trailing dot is not a valid spec.
        ("OBX.", False),
    ],
)
def test_is_path_spec(query, expected):
    assert is_path_spec(query) is expected


@pytest.mark.parametrize(
    "query, path, expected",
    [
        # Contiguous run anywhere in the path.
        ("OBX.3", "OBX.3.CE.2", True),
        ("CE.2", "OBR.4.CE.2", True),
        ("CE.2", "OBX.3.CE.2", True),
        ("OBX.3.CE.2", "OBX.3.CE.2", True),
        # Whole-token matching: a numeric prefix must not match.
        ("OBX.3", "OBX.30.CE.2", False),
        ("OBX.3", "OBX.13.CE.2", False),
        # Wildcard stands for exactly one token.
        ("OBR.*.CE.2", "OBR.4.CE.2", True),
        ("OBR.*.CE.2", "OBR.4.CE.1", False),
        ("OBR.*", "OBR.4", True),
        # Not contiguous.
        ("OBX.CE", "OBX.3.CE.2", False),
        # Query longer than the path.
        ("OBX.3.CE.2.EXTRA", "OBX.3.CE.2", False),
        # Case-insensitive.
        ("obx.3", "OBX.3.CE.2", True),
    ],
)
def test_path_matches(query, path, expected):
    assert path_matches(tokenize(query), tokenize(path)) is expected


def test_path_matches_checks_every_supplied_path():
    numeric = tokenize("MSH.4.1")
    displayed = tokenize("MSH.4.HD.1")
    # Matches only the numeric form, but is found because both are searched.
    assert path_matches(tokenize("MSH.4.1"), displayed, numeric) is True
