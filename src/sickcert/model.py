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
