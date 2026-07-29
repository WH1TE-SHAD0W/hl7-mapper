"""Flattens an HL7 v2 XML message into FieldRow records.

Uses the standard library's ElementTree (HLD 8) -- no third-party XML
dependency is needed to walk a well-formed HL7 document.
"""

import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from .model import FieldRow
from .pathspec import collapse_tags

#: Namespace used by the HL7 v2.x XML encoding.
HL7_NAMESPACE = "urn:hl7-org:v2xml"

#: Message structure names such as ORU_R01, ADT_A01.
_MESSAGE_ROOT_RE = re.compile(r"^[A-Z]{3}_[A-Z]\d{2}$")


class NotHL7XmlError(ValueError):
    """Raised when a file is not a well-formed HL7 v2 XML message.

    Ingestion catches this per file so that one unreadable document does not
    abort a whole batch (HLD 5.1).
    """


def _local_name(tag: str) -> str:
    """Strip any ``{namespace}`` prefix ElementTree puts on a tag."""
    return tag.rsplit("}", 1)[-1]


def _validate_root(root: ET.Element) -> None:
    if root.tag.startswith("{"):
        namespace = root.tag[1:].split("}", 1)[0]
        if namespace == HL7_NAMESPACE:
            return
        raise NotHL7XmlError(
            f"unexpected XML namespace {namespace!r}; expected {HL7_NAMESPACE!r}"
        )
    if _MESSAGE_ROOT_RE.match(root.tag):
        return
    raise NotHL7XmlError(
        f"root element {root.tag!r} is neither in the HL7 namespace nor named "
        f"like an HL7 message structure (e.g. ORU_R01)"
    )


def _own_text(element: ET.Element) -> str:
    """The text belonging to this element, excluding its children's own text.

    Real messages use mixed content: clinical narrative in NTE.3 and OBX.5 is
    interleaved with HL7 escape sequences encoded as empty child elements,
    for example::

        <NTE.3>COMPLAINT:Chest Pain<escape V=".br"/>ED CLINICIAN:...</NTE.3>

    The narrative therefore lives partly in the element's own ``text`` and
    partly in each child's ``tail``. Collecting only ``text``, or treating any
    element with children as a non-value node, loses it entirely -- and it is
    exactly the free text an analyst searches by condition name.

    Segments are joined with a single space so that words either side of an
    escape do not run together.
    """
    segments = [element.text or ""]
    segments.extend(child.tail or "" for child in element)
    return " ".join(segment.strip() for segment in segments if segment.strip())


def _walk(
    element: ET.Element,
    tags: list[str],
    full_tags: list[str],
    file_name: str,
    rows: list[FieldRow],
) -> None:
    children = list(element)

    # An element yields a row whenever it carries text of its own, whether or
    # not it also has children.
    value = _own_text(element)
    if value:
        path, numeric_path = collapse_tags(tags)
        rows.append(
            FieldRow(
                file_name=file_name,
                path=path,
                value=value,
                full_path=".".join(full_tags),
                numeric_path=numeric_path,
                depth=len(full_tags) - 1,
            )
        )

    if not children:
        return

    # Label repeated siblings (several OBX segments, a repeating PID.3) with a
    # 1-based occurrence index so two rows sharing a path stay distinguishable
    # in full_path -- the traceability the workbook's Index column provided.
    totals = Counter(_local_name(child.tag) for child in children)
    seen: dict[str, int] = {}

    for child in children:
        name = _local_name(child.tag)
        occurrence = seen.get(name, 0) + 1
        seen[name] = occurrence
        label = f"{name}[{occurrence}]" if totals[name] > 1 else name
        _walk(child, tags + [name], full_tags + [label], file_name, rows)


def parse_bytes(data: bytes, file_name: str) -> list[FieldRow]:
    """Flatten one HL7 XML document into rows, one per non-empty leaf node.

    Leaf nodes whose text is empty or whitespace carry no information to
    search on and are skipped.

    Raises NotHL7XmlError if the document is malformed or is not HL7 XML.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NotHL7XmlError(f"not well-formed XML: {exc}") from exc

    _validate_root(root)

    rows: list[FieldRow] = []
    _walk(root, [_local_name(root.tag)], [_local_name(root.tag)], file_name, rows)
    return rows


def parse_file(path: str | Path) -> list[FieldRow]:
    """Flatten the HL7 XML document at ``path``."""
    path = Path(path)
    return parse_bytes(path.read_bytes(), path.name)
