# HL7 Message Data Explorer

A single-user desktop tool for reviewing HL7 v2 messages delivered as XML. It
replaces the manual Excel workbook (`Sick_Cert_Data_Analysis.xlsx`, MasterFile
sheet) in which each message was flattened by hand into helper columns and
filtered with AutoFilter/Slicers.

Load one or more messages, type either an HL7 path or a piece of text, and
every matching field across every loaded message is listed — then export the
result to Excel.

Nothing in the parser or search engine is tied to a particular message type.
The original brief covered sick certificates (`ORU_R01`), but the real corpus
also contains `REF_I12` referrals and `ORM_O01` orders, and all three flatten
through the same rules.

## Status

MVP, per the High-Level Design. Implemented: ingestion, flattening, the
search engine, the desktop UI, Excel export, and a packaged Windows
executable. Not yet implemented (Phase 2 in the HLD): the Field Dictionary of
business field names, the slicer panel, SQLite persistence, and CSV export.

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

## Exporting

**Export to Excel…** writes the current result set to an `.xlsx` workbook.

It exports **every match, not the 500 rows on screen** — the display cap is a
limit of the table widget, not of the data. Searching `CE.2` on the real
corpus shows 500 rows and exports 58,709.

The *Results* sheet carries all six fields per row — File, Path, Value, Full
Path, Numeric Path, Depth — with the header frozen and AutoFilter already
switched on, since filtering is the usual next step. A second *Export Info*
sheet records the query, which rule matched it, the row count, the timestamp
and the source file names, so an extract can be traced back to how it was
produced.

Values are always written as literal text. openpyxl otherwise treats a
leading `=` as a formula, and these values come from third-party messages —
a field reading `=1+1` must stay `=1+1`. Control characters Excel rejects are
stripped; tabs and newlines in clinical narrative are kept.

Measured on the full corpus:

| Export | Rows | Time | Size |
|---|---|---|---|
| `OBR.4.CE.2` | 7,455 | 0.5s | 0.2 MB |
| `CE.2` | 58,709 | 3.7s | 2.0 MB |
| everything (blank query) | 393,255 | 25s | 12.3 MB |

Writing runs off the UI thread, so the window stays responsive.

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
src/hl7msg/
  model.py      FieldRow - one row per XML leaf node
  pathspec.py   tag-chain collapsing; path-spec detection and matching
  parser.py     HL7 XML -> rows; strict first, lxml recovery as fallback
  search.py     the four-branch search engine
  store.py      in-memory Dataset + search index (the Phase 2 SQLite seam)
  export.py     filtered results -> .xlsx
  ui/app.py     Flet desktop UI - the only module that imports flet
```

Only `ui/app.py` depends on Flet. Everything else is standard library plus
openpyxl and lxml, which is why the whole engine is testable without a GUI.

One side effect worth knowing: **openpyxl switches to lxml as its XML backend
whenever lxml is installed.** That subtly changes export behaviour — a CRLF in
a value now round-trips intact instead of being normalised to two newlines.
Nothing is lost either way, but do not write tests that pin one backend's
normalisation.

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q
```

128 tests covering the collapsing rules, parsing (including mixed content),
all four search branches, the dataset index, Excel export (read back from the
written workbooks), UI wiring driven through a stub page, and a benchmark
asserting search stays under the HLD's one-second budget at 50,000 rows.

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

**73 files (8%) are corrupt** and are recovered rather than read whole. The
damage is single-character, consistent with a fault in whatever produced the
anonymized copies rather than with the messages themselves:

| Defect | Files | Example |
|---|---|---|
| Closing tag missing `>` | 45 | `</NTE.3` then a newline |
| Root never closed | 16 | file ends `</REF_I12` |
| Wrong root / truncated body | 10 | `<REF_I12>` wrapping `<OML_O21>`, never closed |
| Corrupted tag name | 2 | `<CE.6>` closed by `</CxE.6>` |

These are worth regenerating at source. See [Damaged files](#damaged-files)
for what the parser does with them meanwhile.

## Damaged files

A well-formed document is parsed strictly with ElementTree. Only when that
fails does the same call make a second pass with lxml in recovery mode, which
salvages whatever survived. Nothing chooses between the two — one parse
function, with recovery as its fallback — and the clean path is byte-identical
to what it was before recovery existed.

On the reference corpus all 909 files now load, and the 836 undamaged ones
still produce **exactly 393,255 rows**, which is the check that proves the
strict path was not disturbed.

| | Files | Rows |
|---|---|---|
| Clean | 836 | 393,255 |
| Recovered (partial) | 73 | 12,835 |
| Failed | 0 | — |
| **Total** | **909** | **406,090** |

**Recovered rows are partial — about 37% of what those files would hold if
intact.** The status line says so after loading, and the **Load report**
button lists every affected file with the parser's own complaint
(`line 258, column 2: expected '>'`). `Dataset.recovered_files` carries the
set, and the Export Info sheet records which sources were partial, so an
extract can be traced back long after the fact.

### Recovery can misplace data, not only lose it

Where a closing tag is missing, the following siblings become *children* of
the unclosed element. One real example: `OBX.5` is opened and never closed, so
`OBX.11` nests inside it and its value ends up at path `OBX.5.11` — a search
for `OBX.11` will not find it.

Measured scope: 125 of the 12,835 recovered rows (1.0%) sit at a path that
never appears in a clean file, and most of those are legitimate — the 10
`ORM_O01` files genuinely contain `ORC` segments the other message types lack.
Actual mis-nesting is 3 rows, 0.02%. Small, but it is silent, so treat paths
seen only in recovered files with suspicion.

## Building the executable

Install the build-time extras once — they are not runtime dependencies:

```bash
.venv\Scripts\python.exe -m pip install flet-cli==0.86.4 pyinstaller
```

Then:

```bash
.\build_exe.ps1
```

Produces `dist\HL7MessageExplorer.exe`, a single self-contained file (~58 MB)
that needs no Python installation. Verified by running it from a directory
containing no source tree.

Three traps are worth knowing before changing [build_exe.ps1](build_exe.ps1):

**`--paths=src` is mandatory.** `hl7msg` lives under `src/` and is only
importable because `main.py` adds that directory to `sys.path` at runtime.
PyInstaller resolves imports statically, long before that line executes, so
without it the build *succeeds* and produces an exe that dies instantly with
`ModuleNotFoundError`.

**Only one pass-through argument is possible.** `flet pack`'s
`--pyinstaller-build-args` uses `nargs="*"`, and argparse rejects a value
starting with `-` unless attached with `=`. Passing two
(`--pyinstaller-build-args="--paths=src --exclude-module=x"`) hands PyInstaller
a single nonsense path named `src --exclude-module=x`; the build reports
success and yields a broken 9 MB executable.

**Trim the environment, not the build.** Because of the above, the way to
shrink the bundle is to uninstall what you do not want before building.
`flet[desktop]` also installs `flet-web`, which pulls fastapi, starlette,
uvicorn, websockets and pydantic into the exe even though a packaged desktop
app never serves HTTP. Removing them is safe and saves ~5 MB:

```bash
.venv\Scripts\python.exe -m pip uninstall -y flet-web fastapi starlette uvicorn websockets pydantic pydantic-core
```

Most of the remaining size is the bundled Flutter engine, which is not
optional.

To confirm a build really contains the application code:

```bash
.venv\Scripts\python.exe -c "from PyInstaller.archive.readers import CArchiveReader; print(len(CArchiveReader(r'dist\HL7MessageExplorer.exe').toc))"
```

Pure-Python packages live inside the embedded PYZ archive, *not* in the
`_MEI` folder the onefile exe unpacks at runtime — only binaries and data
files land there. Looking for `hl7msg` in `_MEI` will always suggest, wrongly,
that it is missing.

## Notes on Flet

Pinned to `flet==0.86.4`, which is the 1.0-beta line. Its API differs from
most published Flet examples: the entry point is `ft.run(main)`, controls are
dataclasses, `FilePicker` is registered in `page.services`, and `pick_files`
is a coroutine that returns the selected files rather than firing an
`on_result` event. Check the installed package's signatures, not older
tutorials.
