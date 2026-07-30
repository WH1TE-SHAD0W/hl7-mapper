"""Flattens an HL7 v2 XML message into FieldRow records.

Parsing is attempted twice. The standard library's ElementTree (HLD 8) handles
every well-formed document. Only when that fails does the data get a second
pass through lxml in recovery mode, which salvages whatever survived the
damage. Roughly 8% of a real corpus arrives corrupted -- single dropped or
inserted characters such as a closing tag missing its ``>`` -- and those files
still hold usable data.

Rows from a recovered document are necessarily incomplete, so ParseOutcome
carries that fact to the caller rather than letting partial data pass for
whole.
"""

import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .model import FieldRow
from .pathspec import collapse_tags

#: Namespace used by the HL7 v2.x XML encoding.
HL7_NAMESPACE = "urn:hl7-org:v2xml"

#: Message structure names such as ORU_R01, ADT_A01.
_MESSAGE_ROOT_RE = re.compile(r"^[A-Z]{3}_[A-Z]\d{2}$")

#: How many distinct parser complaints to keep per file. A single damaged
#: document can produce hundreds of near-identical entries.
_MAX_ISSUES = 5


class NotHL7XmlError(ValueError):
    """Raised when a file is not an HL7 v2 XML message at all.

    This means the wrong kind of document -- a foreign namespace, an
    unrecognisable root, or input nothing can be parsed from. Damage to an
    otherwise recognisable HL7 message does not raise; it is recovered and
    reported through ParseOutcome instead.

    Ingestion catches this per file so that one unreadable document does not
    abort a whole batch (HLD 5.1).
    """


@dataclass(frozen=True, slots=True)
class ParseOutcome:
    """Rows from one document, and whether they are the whole of it."""

    rows: list[FieldRow] = field(default_factory=list)

    #: True when the strict parse failed and these rows came from recovery.
    #: The document was damaged and this is only what survived.
    recovered: bool = False

    #: What the recovering parser objected to, deduplicated and capped.
    issues: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.rows)


def _local_name(tag: str) -> str:
    """Strip any ``{namespace}`` prefix the parser puts on a tag."""
    return tag.rsplit("}", 1)[-1]


def _is_element(node) -> bool:
    """False for comments and processing instructions.

    lxml exposes those as nodes whose ``tag`` is a callable rather than a
    string, so anything doing string work on a tag has to filter them out
    first.
    """
    return isinstance(node.tag, str)


def _validate_root(root) -> None:
    if not _is_element(root):
        raise NotHL7XmlError("document has no element at its root")
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


def _occurrence(full_tags: list[str], cache: dict) -> tuple[str, ...]:
    """The chain of repeating elements enclosing this node.

    Read off the tag labels, where an occurrence index is still attached to
    the tag that owns it. Chains repeat heavily -- most rows of a message
    share one -- so they are interned, which keeps a 400,000-row corpus from
    paying for 400,000 near-identical tuples.
    """
    chain = tuple(tag for tag in full_tags if tag.endswith("]"))
    return cache.setdefault(chain, chain)


def _walk(
    element: ET.Element,
    tags: list[str],
    full_tags: list[str],
    file_name: str,
    rows: list[FieldRow],
    cache: dict,
) -> None:
    # Comments and processing instructions contribute no path of their own.
    # Their tail text still belongs to this element and _own_text collects it.
    children = [child for child in element if _is_element(child)]

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
                occurrence=_occurrence(full_tags, cache),
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
        _walk(child, tags + [name], full_tags + [label], file_name, rows, cache)


def _collect(root, file_name: str) -> list[FieldRow]:
    rows: list[FieldRow] = []
    name = _local_name(root.tag)
    _walk(root, [name], [name], file_name, rows, cache={})
    return rows


def _summarise(error_log) -> tuple[str, ...]:
    """Turn an lxml error log into a few readable, deduplicated lines."""
    seen: list[str] = []
    total = 0
    for entry in error_log:
        total += 1
        text = f"line {entry.line}, column {entry.column}: {entry.message}"
        if text not in seen and len(seen) < _MAX_ISSUES:
            seen.append(text)
    if total > len(seen):
        seen.append(f"(and {total - len(seen)} further problems)")
    return tuple(seen)


def _parse_recovering(data: bytes, file_name: str, strict_error) -> ParseOutcome:
    """Second attempt: salvage what survived in a damaged document.

    Reached only when the strict parse has already failed.
    """
    parser = etree.XMLParser(recover=True)
    try:
        root = etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise NotHL7XmlError(f"not well-formed XML, unrecoverable: {exc}") from exc

    # With recover=True lxml returns None rather than raising when there is
    # nothing left to build a tree from.
    if root is None:
        raise NotHL7XmlError(
            f"not well-formed XML and nothing could be recovered: {strict_error}"
        )

    _validate_root(root)
    return ParseOutcome(
        rows=_collect(root, file_name),
        recovered=True,
        issues=_summarise(parser.error_log),
    )


def parse_bytes(data: bytes, file_name: str) -> ParseOutcome:
    """Flatten one HL7 XML document into rows, one per non-empty leaf node.

    Leaf nodes whose text is empty or whitespace carry no information to
    search on and are skipped.

    A well-formed document is parsed strictly and returns
    ``recovered=False``. A damaged one falls back to recovery and returns
    whatever survived with ``recovered=True`` -- those rows are partial.

    Raises NotHL7XmlError only when the input is not an HL7 message at all,
    or when even recovery cannot produce a tree.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as strict_error:
        return _parse_recovering(data, file_name, strict_error)

    _validate_root(root)
    return ParseOutcome(rows=_collect(root, file_name), recovered=False)


def parse_file(path: str | Path) -> ParseOutcome:
    """Flatten the HL7 XML document at ``path``."""
    path = Path(path)
    return parse_bytes(path.read_bytes(), path.name)
