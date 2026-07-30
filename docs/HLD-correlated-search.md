# High-Level Design (HLD)

## Correlated Multi-Path Search — Segment-Correlated Expansion

| Field | Detail |
|---|---|
| Document Type | High-Level Design |
| Subject System | HL7 Message Data Explorer (`hl7msg`) — search subsystem |
| Builds On | `Sick_Cert_App_HLD.docx`, sections 5.5 and 7 |
| Status | **Implemented** — see §13 for where the build diverged from this design |
| Grounding | Measured against the 909-message reference corpus (406,090 rows) |

---

## 1. Purpose

The current search answers *"where does this value appear?"* — one query, one
flat list of `File | Path | Value`. That is the right tool for locating a
field, and the wrong one for analysing a message.

Analysis needs values placed **side by side**. Asking "for each observation,
what was the code, the description, and the result?" means projecting
`OBX.3.CE.1`, `OBX.3.CE.2` and `OBX.5` into three columns and aligning them
so that each row is one observation. Today that requires three separate
searches and manual reassembly in Excel — exactly the work this application
exists to remove.

This HLD specifies **Segment-Correlated Expansion**: a second search mode in
which the user names several HL7 paths, and the engine returns one table whose
rows are message *segments* rather than individual values.

---

## 2. Scope

### 2.1 In scope

- A **projection** of two or more HL7 paths into named columns, typed as a
  space-separated list.
- Correlation of those columns into rows keyed by segment occurrence, not by
  file.
- **Filtering by value, per column** — one substring per column, matched
  against that column only, combining with AND. Kept separate from projection,
  in its own input.
- Export of the resulting table through the existing Excel writer.

### 2.2 Out of scope

- Replacing the existing single-box search. Correlated search is an additional
  mode; the flat search remains, and remains the default.
- Aggregation (counts, sums, group-by). The output is a detail table.
- Joining across *different* messages. Correlation never crosses a file
  boundary.
- A query language. Projection and filters are structured inputs, not parsed
  text.

---

## 3. Current State

`SearchEngine.search()` returns a `SearchResult` holding `list[FieldRow]`.
Each `FieldRow` is one value with its `path`, its `file_name`, and a
`full_path` recording the exact node it came from.

Two consequences:

- **A row is a value, not a record.** There is no notion that
  `OBX.3.CE.2 = "Low back pain"` and `OBX.5 = "14"` describe the *same*
  observation.
- **One query at a time.** Comparing three paths means running three searches
  and correlating them by hand.

What already exists and is reused unchanged: the parser, the path-collapsing
rules, the distinct-path index, and the export writer.

---

## 4. The Correlation Problem, As The Data Actually Is

The proposal that prompted this work described rows keyed by
`Filename + Segment Index` — *"OBX #1, OBX #2"*. Measured against the corpus,
that key does not exist, and three findings reshape the design.

### 4.1 Repetition sits on groups, not segments

The parser records an occurrence index whenever sibling elements repeat.
Across 406,090 rows, the tags carrying an index are:

| Repeating tag | Rows beneath it |
|---|---|
| `ORU_R01.OBSERVATION[n]` | 303,455 |
| `ORU_R01.ORDER_OBSERVATION[n]` | 299,476 |
| `REF_I12.RESULTS_NOTES[n]` | 39,737 |
| `PID.3[n]` *(field-level repeat)* | 6,673 |
| `PRD.PROVIDER_CONTACT[n]` | 4,536 |
| `ORC.13[n]`, `ORDER_PRIOR[n]`, `ORDER[n]`, `DG1[n]` | ~2,900 combined |

**`OBX` itself never carries an index.** In HL7 v2 XML each `OBX` is wrapped
in its own message-structure group, so the repetition is on the group. There
is no "OBX #2" to key on.

### 4.2 Segments nest more than one level deep

A real anchor from the corpus:

```
OBSERVATION[1] . RESULTS_NOTES[1] . OBX
OBSERVATION[1] . RESULTS_NOTES[2] . OBX
OBSERVATION[3] . RESULTS_NOTES[1] . OBX
```

The same file has OBX repeating at two nesting levels at once. A flat counter
would collide `OBSERVATION[1]/RESULTS_NOTES[2]` with
`OBSERVATION[2]/RESULTS_NOTES[1]`. The **whole chain of indices** is the
identity.

### 4.3 Columns live at three different depths

Of the 236 distinct paths in the corpus:

| Cardinality | Paths | Examples |
|---|---|---|
| Exactly 1 per file | 147 | `MSH.4.HD.1`, `MSH.10`, `PID.5.XPN.1.FN.1` |
| 2–5 per file | 36 | `PID.3.CX.1`, `PRD.1.CE.1` |
| 6–50 per file | 32 | `NTE.3`, `ORC.1` |
| 50+ per file | 21 | `OBR.4.CE.2`, `OBX.3.CE.2` (max 55) |

A useful table mixes them — patient ID *and* observation code in one row. So
the design cannot simply group by segment; it must define how a
once-per-message value reaches a per-observation row.

---

## 5. Proposed Solution — Overview

Three concepts, in order.

**Occurrence chain.** The ordered list of repeating elements a value sits
inside. This is the correlation primitive, recorded on every row by the parser
as `FieldRow.occurrence`.

| Row | Signature |
|---|---|
| `MSH.10` | `()` — outside every repeat |
| `OBR.4.CE.2` | `(ORDER_OBSERVATION[2],)` |
| `OBX.3.CE.2` | `(ORDER_OBSERVATION[2], OBSERVATION[1], RESULTS_NOTES[1])` |

**Grain.** The projection's deepest column defines how fine a row is. Rows are
the distinct signatures of that column, within one file.

**Broadcast.** A value belongs in a row when **its signature is a prefix of
that row's signature**. That single rule handles all three cardinality classes
at once: an empty signature is a prefix of everything, so `MSH.10` reaches
every row; `OBR`'s signature is a prefix of the `OBX` signatures beneath it,
so an order's details reach each of its observations; an exact match places a
value in precisely one row.

### Validated against the corpus

Projecting `MSH.10 | OBR.4.CE.2 | OBX.3.CE.1 | OBX.3.CE.2 | OBX.5` over all
909 files:

| Measure | Result |
|---|---|
| Cells evaluated | 153,395 |
| Cells resolving to exactly one value | 93.16% |
| Cells empty (value absent for that row) | 10,457 — 6.82% |
| **Cells ambiguous (more than one candidate)** | **28 — 0.02%** |

A worked example from `300_DS291310_anonymized UHL.xml` — 122 flat rows
becoming 5 correlated rows:

| MSH.10 | OBR.4.CE.2 | OBX.3.CE.1 | OBX.3.CE.2 | OBX.5 |
|---|---|---|---|---|
| XXXXXXXXXXXXX.UN | Evaluation procedure | 386053000 | Evaluation procedure | For Referring Physician ONLY:… |
| XXXXXXXXXXXXX.UN | Evaluation procedure | 386053000 | Evaluation procedure | Anora Ellipta |
| XXXXXXXXXXXXX.UN | Inpatient Care | 394656005 | Inpatient Care | S/B RESPIRATORY: Referred to… |
| XXXXXXXXXXXXX.UN | Medication treatment | 18629005 | Medication treatment | Amlodipine Dosage: 10… |
| XXXXXXXXXXXXX.UN | Medication treatment | 18629005 | Medication treatment | Nexium Dosage: 40… |

`MSH.10` is constant down the column (one per file), `OBR.4.CE.2` repeats per
order, and the `OBX` columns vary per observation. That is the intended
behaviour, unforced.

---

## 6. Component Design

### 6.1 Occurrence signature — `pathspec.py`

Two pure functions beside the existing collapsing rules:

```python
def signature(full_path: str) -> tuple[str, ...]
def covers(value_sig: tuple, row_sig: tuple) -> bool   # prefix test
```

### 6.2 Correlation engine — new module `correlate.py`

```python
@dataclass(frozen=True, slots=True)
class Projection:
    paths: tuple[str, ...]           # the columns, in display order
    anchor: str | None = None        # grain; defaults to the deepest path

    @classmethod
    def parse(cls, text: str) -> "Projection":
        """Split the columns box on whitespace.

        HL7 path tokens are [A-Za-z0-9_.*] and can never contain a space, so
        whitespace is an unambiguous separator and needs no escaping.
        """

@dataclass(frozen=True, slots=True)
class FilterSet:
    """One case-insensitive substring per column, combined with AND.

    A column absent from the mapping filters nothing. There is no operator,
    no value list and no negation -- a filter is the text a cell must contain.
    """
    per_column: dict[str, str]       # column path -> substring

    def accepts(self, columns: tuple[str, ...], cells: tuple[str, ...]) -> bool: ...

@dataclass(frozen=True, slots=True)
class CorrelatedRow:
    file_name: str
    signature: tuple[str, ...]
    cells: tuple[str, ...]           # aligned with Projection.paths
    ambiguous: frozenset[int]        # column indices holding >1 value

@dataclass(frozen=True, slots=True)
class CorrelatedTable:
    columns: tuple[str, ...]
    rows: list[CorrelatedRow]
    files_scanned: int
    files_kept: int
```

`CorrelationEngine(dataset).build(projection) -> CorrelatedTable`
`CorrelatedTable.apply(filters: FilterSet) -> CorrelatedTable`

Building and filtering are separate calls because they have different costs
and different triggers: the projection is built once and re-filtered many
times as the user adjusts columns' filters.

### 6.3 Store support — `store.py`

The existing distinct-path index answers *"which rows have this path?"*, which
is what projection needs. One addition: a per-file row index
(`dict[str, list[int]]`) so correlation can work a file at a time without
scanning 406,090 rows per file. Built during `extend()`, alongside the two
existing indexes.

### 6.4 Presentation — two boxes

The interaction is two text inputs, one per concept. Projection decides the
table's **width**; the value search decides its **height**. Neither can affect
the other, which is what keeps the model explainable.

```
┌─ Columns ──────────────────────────────────────────────────┐
│ OBX.3.CE.1  OBX.3.CE.2  OBX.5                              │
└────────────────────────────────────────────────────────────┘
┌─ Search ───────────────────────────────────────────────────┐
│ Medication                                                 │
└────────────────────────────────────────────────────────────┘
```

**Columns box — what you see.** A space-separated list of HL7 paths, in
display order. Whitespace is a safe separator with no escaping rules, because
an HL7 path token is `[A-Za-z0-9_.*]` and can never contain a space. Typing
`OBX.3.CE.1 OBX.3.CE.2 OBX.5` yields exactly three columns. Order is preserved;
duplicates are collapsed with the first position kept.

**Search box — what you keep.** A filter is a plain substring, and it applies
to **one named column only**. A row survives when that column's cell contains
the text, case-insensitively.

Filtering `OBX.5` with `Ye` keeps every row whose `OBX.5` cell contains those
two characters — `Yes`, `Yes, resolved`, `Yesterday` — and inspects no other
column. That is the whole rule.

A term is written `PATH: value`, and terms are separated by spaces just as
columns are:

```
┌─ Columns ──────────────────────────────────────────────────┐
│ OBX.3.CE.2  OBX.5  OBX.11                                  │
└────────────────────────────────────────────────────────────┘
┌─ Search ───────────────────────────────────────────────────┐
│ OBX.5: Ye   OBX.11: F                                      │
└────────────────────────────────────────────────────────────┘
```

Read as *"`OBX.5` contains `Ye` **and** `OBX.11` contains `F`"*. Several terms
combine with **AND** — each narrows further. One filter per column; naming a
column twice replaces the earlier term rather than accumulating.

Deliberately absent: no value checklists, no operators, no negation, no
ranges. A filter is the text a cell must contain, nothing more.

#### The filter row

The typed syntax is a shortcut over state that is also editable in place. Each
column header carries a one-line text input, and the two are the same thing:
typing `OBX.5: Ye` fills the `OBX.5` header input, and typing `Ye` into that
input writes the term back into the search box.

A substring is the right primitive here rather than a fallback. Measured over
the 30,679-row projection, `OBX.5` holds **4,458 distinct values** and
`OBX.3.CE.2` holds 742 — value lists at that size would be unusable, and
partial matching is what an analyst actually wants against free-text results.

#### Worked check

Over the 30,679-row projection:

| Filter | Rows kept |
|---|---|
| `OBX.11: F` alone | 30,376 |
| `OBX.3.CE.2: Medication` alone | 973 |
| **Both (AND)** | **967** |

967 is smaller than either — the filters intersect. A filter on one column
never widens the result by matching another.

#### The rest of the view

The table carries the same 500-row display cap and true-total status line as
the flat grid. Ambiguous cells are marked rather than silently collapsed, and
rows sourced from a partially recovered message are flagged. Export reuses
`write_xlsx` with the projection's columns replacing the fixed six, and the
Export Info sheet records both box contents verbatim so a table can be
reproduced from the workbook alone.

---

## 7. Execution Sequence

The original proposal gave the order as *Filter Files → Filter Segment Rows →
Project Columns*, separating two filter scopes. Per-column filtering replaces
both: a filter names a column, and the column decides its own reach. So
filtering runs **after** projection, against cells rather than against the
store.

```
BUILD  (re-runs only when the columns box changes)
  1. PARSE COLUMNS   split the columns box on whitespace
                     -> ordered paths; the deepest sets the grain
  2. BUILD GRAIN     per file, collect distinct occurrence signatures
                     of the anchor column -> one empty row each
  3. PROJECT         fill every cell via the prefix rule

FILTER (re-runs on every keystroke, over the cached build)
  4. APPLY           for each active column, keep rows whose cell in
                     THAT column contains the substring
```

Splitting build from filter is what makes the interaction feel right: editing
the columns box rebuilds, editing a filter does not. Building the full
30,679-row projection costs a few hundred milliseconds; re-filtering it is a
scan over cells already in memory.

**Filter scope is a property of the column, not a mode.** Filtering a
once-per-file column such as `MSH.4.HD.1` removes whole messages, because that
value broadcast to every row of its file. Filtering `OBX.5` removes individual
observations. The user never chooses a scope — they choose a column, and the
scope follows from where that column sits in the message.

### Worked example

> *Show the code, description and result of every final observation concerning
> medication, from one sending facility.*

| Step | Input | Result |
|---|---|---|
| Columns box | `MSH.4.HD.1 OBX.3.CE.1 OBX.3.CE.2 OBX.5 OBX.11` | 5 columns, anchor `OBX.3.CE.2` |
| Build grain | 909 files | 30,679 rows |
| Project | prefix rule | 153,395 cells |
| Search box | `OBX.3.CE.2: Medication  OBX.11: F` | 30,679 → **967 rows** |
| Narrow further | add `MSH.4.HD.1: TCH` | filters to that facility's messages |

Each term names its column. Nothing leaks between them.

Note the last step: filtering `MSH.4.HD.1` removes whole messages while
filtering `OBX.5` removes individual observations, and the user did nothing
different to get either. The reach of a filter follows from where its column
sits in the message.

---

## 8. Data Model

Nothing about `FieldRow` changes. The correlated table is a **view** computed
over existing rows; values are referenced, never copied or re-parsed.

| Concept | Derivation | Note |
|---|---|---|
| Signature | Indexed tokens of `full_path` | Already present since the parser added occurrence indices |
| Row identity | `(file_name, signature)` | Never crosses a file |
| Cell | `(row, column)` → value | Resolved by the prefix rule |
| Grain | Signature depth of the anchor column | Defaults to the deepest projected path |

---

## 9. Edge Cases and Their Handling

| Case | Frequency | Handling |
|---|---|---|
| **Ambiguous cell** — several candidates cover one row | 28 of 153,395 (0.02%) | Join with `" ; "`, mark the cell, and count marked cells in the status line. Never silently pick one. |
| **Empty cell** — no candidate | 6.82% | Empty string. Normal message sparsity, not an error. |
| **File lacks the anchor path** | 61 of 909 files for an OBX anchor | Contributes no rows. Reported as "61 files had no OBX" so absence is visible. |
| **All columns at file level** | — | Grain collapses to one row per file, which is the correct degenerate case. |
| **Column deeper than the anchor** | — | Its values would be ambiguous by construction. Rejected at build time with a message naming the offending column. |
| **Rows from a recovered file** | 73 files | Correlation is unaffected, but the message was partial. `Dataset.recovered_files` already marks them; the table flags such rows. |
| **Unknown path in the columns box** | user error | Column is built and stays entirely empty. Flagged beside the box — "`OBX.99` matched no rows" — rather than rejected, since a path may legitimately be absent from the currently loaded messages. |
| **Wildcard in the columns box** (`OBR.*.CE.2`) | user choice | Expanded against `Dataset.distinct_paths()` into one column per concrete match, in sorted order, so the table stays rectangular. A wildcard matching nothing behaves as an unknown path. |
| **Duplicate path in the columns box** | user error | Collapsed to a single column at its first position. |
| **Filter naming a column that is not projected** | user error | Ignored, and flagged beside the box — a filter can only see what is on the table. Adding the column activates it. |
| **Filter value containing spaces** | normal | `OBX.3.CE.2: Low back pain` would split. Quote it: `OBX.3.CE.2: "Low back pain"`. Unquoted, everything up to the next `PATH:` is taken as the value, so the common case still works. |
| **Filtering an ambiguous cell** | 0.02% of cells | Matched against the joined text. A row whose cell reads `A ; B` is kept by a filter for either, and remains marked as ambiguous. |
| **Filtering an empty cell** | 6.82% of cells | An empty cell contains no substring, so an active filter removes rows missing that column. There is no way to ask for empties; `(empty)` is listed as an extension rather than assumed. |

---

## 10. Non-Functional Requirements

| Requirement | Target | Basis |
|---|---|---|
| Build time | < 1s for a 5-column projection over the full corpus | Flat search is 0.7–10ms; correlation adds a per-file grouping pass |
| Re-filter time | < 100ms | Changing a column filter must not rebuild the table — the projection is cached and re-filtered in place. A substring test over ~30,000 cached cells is trivially inside this |
| Table size | ~30,700 rows for an OBX-anchored projection | Measured; a 13× reduction from 406,090 flat rows |
| Memory | No duplication of values | Cells hold references into `Dataset.rows` |
| Display | 500-row cap, true total in the status line | Matches existing behaviour |
| Transparency | Ambiguous and recovered-source rows visibly marked | An analysis table that hides uncertainty is worse than no table |

The re-filter target is what makes the two boxes feel separate in use: editing
the columns box rebuilds, editing the search box does not.

---

## 11. Assumptions and Constraints

- Correlation is **within a file only**. Two messages never share a row.
- The anchor defaults to the deepest projected path; an explicit override is
  available where the user wants a coarser grain.
- No path was observed repeating *within* a single anchor across 6,165
  inspected anchors, which is why single-valued cells are the norm and
  ambiguity is an exception rather than the rule.
- The reference corpus is `ORU_R01`, `REF_I12` and `ORM_O01`. Message
  structures with deeper repetition would still work — the prefix rule is
  general — but the measured percentages above would shift.

---

## 12. Future Enhancements

- **Operators** — `(empty)`, `(not empty)`, negation and numeric comparison,
  extending the per-column filter without changing its shape.
- **Value pick-lists** — a checklist of a column's distinct values, useful only
  for the low-cardinality columns: `OBX.11` has 3 distinct values and
  `MSH.4.HD.1` has 20, against 4,458 for `OBX.5`. Worth adding per column if
  asked for, not worth building generally.
- **Aggregation** — count and group-by over a correlated table, once the
  detail table is proven in use.
- **Saved projections** — a named set of columns and filters, which is the
  natural place for the Phase 2 Field Dictionary to attach: business names
  become column headers.
- **Cross-file correlation** — matching on a shared patient identifier rather
  than on segment position. A materially harder problem, deliberately deferred.

---

## 13. Implementation Notes — Where The Build Diverged

Two things in this design did not survive contact with the data. Both changes
are in the shipped code; the sections above have been corrected to match.

### 13.1 The occurrence chain is recorded, not derived

This design said the chain could be read out of `full_path` and so needed
**no parser change**. It cannot. `full_path` joins already-dotted tag names
with dots, so tag boundaries are gone by the time it is stored: a field-level
repeat such as `PID.3[2]` survives only as a `3[2]` token, indistinguishable
from any other field numbered 3 in any other segment.

`FieldRow` therefore gained an `occurrence` field, populated in `_walk` where
the tag labels are still intact and unambiguous. Chains repeat heavily — most
rows of a message share one — so they are interned, and the memory cost of
adding them to 406,090 rows is negligible.

### 13.2 The grain is the union of the deepest columns, not one of them

This design nominated a single anchor: "the projection's deepest column",
with ties broken by typing order. That is wrong in a way the corpus exposes
immediately. `OBX.3.CE.1`, `OBX.3.CE.2`, `OBX.5` and `OBX.11` all sit at
observation level, and they do not appear in exactly the same observations. A
single anchor silently drops any observation that carries one of the others
but not the anchor — and makes the row count depend on which column happened
to be typed first.

The build instead takes **every** column at the deepest level as an anchor and
grains on the union of their occurrences. An anchor column contributes only
its own occurrence to a row, never a broadcast from a shallower one, so rows
stay exactly as fine as they should be.

Measured difference on the corpus: **30,889 rows against 30,679** — 210
observations that a single anchor would have lost. Ambiguous cells also fell
from 22 to 10, because anchor columns no longer pick up broadcasts.

### 13.3 Measured against the targets

| | Target | Measured |
|---|---|---|
| Build, 6-column projection over 909 files | < 1s | **0.51s** |
| Re-filter cached table | < 100ms | **11.6ms** |
| Rows, OBX-level projection | — | 30,889 from 848 files |
| `OBX.11: F` ∧ `OBX.3.CE.2: Medication` | intersect | 30,586 ∧ 973 → **967** |
| Tests | — | 206 passing |
