"""Row shape produced by flattening an HL7 XML message.

One FieldRow per XML leaf node carrying a value, equivalent to one row of the
MasterFile sheet in the Excel workbook this application replaces.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FieldRow:
    """A single resolved value located at one path within one message.

    Three path representations are kept because each answers a different
    question:

    ``path``
        Collapsed dot notation retaining datatype tokens, e.g. ``MSH.4.HD.1``
        or ``OBR.4.CE.2``. This is what the results grid shows and what a path
        spec query is matched against.
    ``numeric_path``
        The same path with datatype tokens dropped, e.g. ``MSH.4.1``. Also a
        match target, so a user can type either form and find the row.
    ``full_path``
        The raw, uncollapsed tag chain with occurrence indices, e.g.
        ``MSH.MSH.4.HD.1``. Never matched against; kept so any row can be
        traced back to an exact node in the source document.
    """

    file_name: str
    path: str
    value: str
    full_path: str
    numeric_path: str
    depth: int

    #: The chain of repeating elements this value sits inside, outermost
    #: first, e.g. ``("ORU_R01.ORDER_OBSERVATION[2]", "ORU_R01.OBSERVATION[1]")``.
    #: Empty for a value outside every repeat, such as anything under MSH.
    #:
    #: This is what lets values be correlated into a table: two rows describe
    #: the same observation when they share a chain, and a value belongs to a
    #: row when its chain is a prefix of that row's. Recorded by the parser
    #: rather than parsed back out of ``full_path``, where the dotted tag
    #: names have already run together and ``PID.3[2]`` is indistinguishable
    #: from any other field numbered 3.
    occurrence: tuple[str, ...] = ()
