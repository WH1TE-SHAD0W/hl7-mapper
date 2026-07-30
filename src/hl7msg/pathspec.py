"""HL7 path construction and path-spec query matching.

Two jobs live here, both pure functions over strings:

1. Collapsing a raw XML tag chain into the dot-notation paths the user sees
   and searches (``collapse_tags``).
2. Deciding whether a search query is an HL7 path spec, and matching it
   (``is_path_spec``, ``path_matches``).

HL7 v2 XML (namespace ``urn:hl7-org:v2xml``) nests as message -> group ->
segment -> field -> component -> subcomponent, and every tag repeats its
parent's context::

    ORU_R01 / ORU_R01.PATIENT_RESULT / ... / MSH / MSH.4 / HD.1

Rendering that chain verbatim gives the unreadable ``MSH.MSH.4.HD.1``. The
collapsing rules below reduce it to ``MSH.4.HD.1``, which is the notation
analysts already use.
"""

import re
from typing import Iterable, Sequence

#: A query counts as a path spec only if it is dotted and made purely of HL7
#: token characters (HLD 7.1). A bare segment name such as ``OBR`` has no dot
#: and is therefore *not* a path spec -- it falls through to free-text search,
#: which is what makes the bare-segment fallback in search.py reachable.
_PATH_SPEC_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*|\*)(\.[A-Za-z0-9_*]+)+$")

#: Matches exactly one token in a path spec, e.g. ``OBR.*.CE.2``.
WILDCARD = "*"


def is_group_tag(tag: str) -> bool:
    """True for message-structure group tags, which carry no data.

    Group tags are named after the message structure, so their first
    dot-token always contains an underscore (``ORU_R01``,
    ``ORU_R01.PATIENT_RESULT``, ``ORU_R01.ORDER_OBSERVATION``). Segment names
    are three alphanumerics and datatype names (``HD``, ``CE``, ``CX``,
    ``XPN``, ``TS``, ``MSG``) never contain one, so the underscore is a
    reliable discriminator.
    """
    return "_" in tag.split(".", 1)[0]


def collapse_tags(tags: Sequence[str]) -> tuple[str, str]:
    """Collapse a root-to-leaf tag chain into ``(path, numeric_path)``.

    Group tags are dropped. For every remaining tag, the part before the first
    dot is elided when it merely repeats the context already established by
    the previous tag::

        MSH + MSH.4  -> MSH.4          (prefix repeats, elide it)
        MSH.4 + HD.1 -> MSH.4.HD.1     (datatype changes, keep it)

    ``numeric_path`` is the same walk with every datatype prefix dropped,
    giving ``MSH.4.1`` -- the form HLD 5.2 calls the normalized path.
    """
    path_tokens: list[str] = []
    numeric_tokens: list[str] = []
    previous_prefix: str | None = None

    for tag in tags:
        if is_group_tag(tag):
            continue

        prefix, _, rest = tag.partition(".")

        if not rest:
            # A bare segment name: MSH, PID, OBX.
            path_tokens.append(prefix)
            numeric_tokens.append(prefix)
        elif prefix == previous_prefix:
            # Same context as the parent, e.g. MSH -> MSH.4.
            path_tokens.append(rest)
            numeric_tokens.append(rest)
        else:
            # A datatype boundary, e.g. MSH.4 -> HD.1. The displayed path
            # keeps the datatype token; the numeric path drops it.
            path_tokens.append(prefix)
            path_tokens.append(rest)
            numeric_tokens.append(rest)

        previous_prefix = prefix

    return ".".join(path_tokens), ".".join(numeric_tokens)


def tokenize(path: str) -> tuple[str, ...]:
    """Split a path into upper-cased tokens for case-insensitive matching."""
    return tuple(part.upper() for part in path.split(".") if part)


def is_path_spec(query: str) -> bool:
    """True if the query should be read as an HL7 path rather than free text."""
    return bool(_PATH_SPEC_RE.match(query.strip()))


def _contains_run(needle: Sequence[str], haystack: Sequence[str]) -> bool:
    """True if ``needle`` appears as a contiguous run of whole tokens."""
    span = len(needle)
    if span == 0 or span > len(haystack):
        return False
    for start in range(len(haystack) - span + 1):
        if all(
            token == WILDCARD or token == haystack[start + offset]
            for offset, token in enumerate(needle)
        ):
            return True
    return False


def path_matches(query_tokens: Sequence[str], *paths: Iterable[str]) -> bool:
    """True if the query tokens match any of the supplied token sequences.

    Matching is on whole tokens, so ``OBX.3`` matches ``OBX.3.CE.2`` but never
    ``OBX.30``. The run may sit anywhere in the path, which is what lets a
    user search for a trailing component such as ``CE.2`` on its own.
    """
    return any(_contains_run(query_tokens, tokens) for tokens in paths)
