# Sick Certificate Data Explorer

A single-user desktop tool for reviewing HL7 v2 ORU_R01 sick-certificate
messages delivered as XML. It replaces the manual Excel workbook
(`Sick_Cert_Data_Analysis.xlsx`, MasterFile sheet) in which each message was
flattened by hand into helper columns and filtered with AutoFilter/Slicers.

Load one or more messages, type either an HL7 path or a piece of text, and
every matching field across every loaded message is listed.

## Status

MVP, per the High-Level Design. Implemented: ingestion, flattening, the
search engine, and the desktop UI. Not yet implemented (Phase 2 in the HLD):
the Field Dictionary of business field names, the slicer panel, SQLite
persistence, and CSV/Excel export.

Validated against a real corpus of 909 anonymized messages: 836 parsed into
393,255 rows across 224 distinct paths, with every field named in the HLD
resolving to the expected path. See [Corpus findings](#corpus-findings).

> The fixture in `tests/fixtures/sample_oru_r01.xml` is synthetic —
> hand-written test data, not a real message. It is kept deliberately, so no
> patient data of any kind lives in version control. Real messages belong in
> `data/`, which is gitignored.

## Requirements

Python 3.10 or newer (developed on 3.14).

## Setup

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Running

```bash
.venv\Scripts\python.exe main.py
```

Click **Load HL7 XML…**, select one or more `.xml` message files, then search.

## Searching

One box handles both kinds of lookup; it works out which you meant.

| You type | Treated as | Finds |
|---|---|---|
| `OBX.3` | path spec | every `OBX.3` field and its components |
| `CE.2` | path spec | every `CE.2` component, wherever it sits — e.g. `OBR.4.CE.2`, `OBX.3.CE.2` |
| `OBR.4.CE.2` | path spec | that exact path |
| `OBR.*.CE.2` | path spec | `*` stands for exactly one path token |
| `MSH.4.1` | path spec | the same field as `MSH.4.HD.1`; datatype tokens are optional |
| `Thyroid` | free text | any field whose value contains "thyroid", case-insensitively |
| `OBR` | segment name | every field in the OBR segment |

A query counts as a path spec when it is dotted and contains only HL7 token
characters. Path matching is on whole tokens, so `OBX.3` never matches
`OBX.30`. The status line under the search box reports which rule matched, so
a surprising result is always explainable.

Results are capped at 500 displayed rows; the status line reports the true
total.

## How paths are built

HL7 XML repeats each parent's name in its children, so the raw tag chain for a
sending facility is `ORU_R01 / MSH / MSH.4 / HD.1`. Rendering that verbatim
gives `MSH.MSH.4.HD.1`. The parser collapses it:

- message-structure groups (`ORU_R01.PATIENT_RESULT`) are dropped entirely
- a tag's prefix is elided when it just repeats its parent (`MSH` + `MSH.4` → `MSH.4`)
- a datatype boundary is kept (`MSH.4` + `HD.1` → `MSH.4.HD.1`)

Each row therefore carries three paths: `path` (`MSH.4.HD.1`, shown in the
grid), `numeric_path` (`MSH.4.1`, also searchable), and `full_path`
(`ORU_R01.MSH.MSH.4.HD.1`, kept for traceability, with `[n]` occurrence
indices on repeated segments).

## Layout

```
src/sickcert/
  model.py      FieldRow - one row per XML leaf node
  pathspec.py   tag-chain collapsing; path-spec detection and matching
  parser.py     HL7 XML -> rows, with per-file validation
  search.py     the four-branch search engine
  store.py      in-memory Dataset + search index (the Phase 2 SQLite seam)
  ui/app.py     Flet desktop UI - the only module that imports flet
```

Only `ui/app.py` depends on Flet. Everything else is standard library, which
is why the whole engine is testable without a GUI.

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q
```

92 tests covering the collapsing rules, parsing (including mixed content),
all four search branches, the dataset index, UI wiring driven through a stub
page, and a benchmark asserting search stays under the HLD's one-second
budget at 50,000 rows.

## Corpus findings

Measured over 909 real anonymized messages in `data/AllXml`:

| | |
|---|---|
| Files | 909 — 836 parsed, **73 rejected as malformed** |
| Rows | 393,255 |
| Distinct paths | 224 |
| Message types | `ORU_R01` (646), `REF_I12` (180), `ORM_O01` (10) |
| Full ingest | ~4 seconds |
| Search | under 11 ms for any query |

Three things this surfaced that were not anticipated by the HLD:

**Three message types, not one.** The corpus is mostly `ORU_R01` but also
contains `REF_I12` referrals and `ORM_O01` orders. The parser accepts any
root matching an HL7 message-structure name, so all three flatten correctly.

**Mixed content is pervasive.** 304 files carry clinical narrative
interleaved with HL7 escape sequences encoded as child elements:

```xml
<NTE.3>COMPLAINT:Chest Pain<escape V=".br"/>OUTCOME:Admitted</NTE.3>
```

Treating any element with children as a non-value node — the obvious reading
of "one row per leaf node" — silently discards every one of these narratives,
which is precisely the free text an analyst searches by condition. `NTE.3`
and `OBX.5` are the fields affected. See `_own_text` in `parser.py`.

**73 files (8%) are corrupt** and are rejected rather than partially read.
The damage is single-character, consistent with a fault in whatever produced
the anonymized copies rather than with the messages themselves:

| Defect | Files | Example |
|---|---|---|
| Closing tag missing `>` | 45 | `</NTE.3` then a newline |
| Root never closed | 16 | file ends `</REF_I12` |
| Wrong root / truncated body | 10 | `<REF_I12>` wrapping `<OML_O21>`, never closed |
| Corrupted tag name | 2 | `<CE.6>` closed by `</CxE.6>` |

These are worth regenerating at source. The application reports each rejected
file by name in the status line and loads the rest; it deliberately does not
attempt partial recovery, since silently ingesting a truncated message would
undermine an audit tool.

## Packaging

```bash
.venv\Scripts\python.exe -m flet pack main.py --name SickCertExplorer
```

Produces a standalone Windows executable so end users need no Python install.
Not yet verified on a clean machine.

## Notes on Flet

Pinned to `flet==0.86.4`, which is the 1.0-beta line. Its API differs from
most published Flet examples: the entry point is `ft.run(main)`, controls are
dataclasses, `FilePicker` is registered in `page.services`, and `pick_files`
is a coroutine that returns the selected files rather than firing an
`on_result` event. Check the installed package's signatures, not older
tutorials.
