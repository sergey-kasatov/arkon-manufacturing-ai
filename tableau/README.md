# Tableau executive view

The last Phase 3 item of charter 7.5. This directory holds the **extract layer**,
which is built and verified. The workbook is not built yet; publishing it to
Tableau Public was decided on 2026-09-04 and the sections below say what that
settles and what it leaves.

Charter 7.5: "Tableau reads periodic extracts and serves as the executive KPI
view: open incidents by priority, response times, and trend Pareto. A live
Tableau connection would require a paid Tableau Server; extract refresh is the
documented portfolio boundary."

## The extracts

```bash
python tableau/build_extracts.py
```

Four tidy fact tables in `tableau/extracts/`, refreshed from
`GET /webhook/arkon-incident-status` - the same contract the Streamlit cockpit and
the assistant read, so all three report the same state and cannot drift apart.

| File | Grain | What it carries |
|---|---|---|
| `incidents.csv` | one incident | priority, current status, whether open, overdue, the three response times, module, domain, assignee, record id, risk score, both origin labels |
| `transitions.csv` | one lifecycle transition | when, from, to, who, the note, and the incident's priority and module denormalised onto it |
| `store_summary.csv` | one row | the `as_of` stamp and the KPI figures the API computed, so the workbook can show what it was told rather than a number it recomputed |
| `module_metrics.csv` | one module, one metric | long format, so seven modules with heterogeneous metrics sit on one axis |

Three properties of this layer are deliberate.

**They are facts, not answers.** A Pareto and a response-time distribution are
different cuts of the same rows, and deciding them in Python would put the
analysis in a script the workbook then has to agree with.

**`status` is a fold, not a field.** The incident store records the state an
incident was raised in and never rewrites it. `raised_as` is in the extract next
to `status` for exactly that reason: a reader who opens the JSONL and sees `new`
on a closed incident is looking at the record, not at a contradiction.

**The extract says whether it is complete.** The status API caps `limit` at 50 and
has no pagination, so the sweep asks one lifecycle state at a time - every
incident is in exactly one, which makes the union both complete and free of
duplicates - and `store_summary.extract_complete` is false, with a loud message
and a non-zero exit, if any state ever returns fewer rows than it matched. Raising
that ceiling is the move to a queryable store, charter 7.5, not a change here.

Verified 2026-09-04 against the live store: 29 incidents and 11 transitions, and
the counts by status, priority, open and overdue each recomputed from
`incidents.csv` agree with the summary the API computed independently.

## What the three views need

The charter names three. This is what each one is made of, in fields rather than
in marks: the visual design belongs to whoever builds the workbook, in front of
the data.

- **Open incidents by priority.** `incidents.csv`, filter `is_open`, split by
  `priority`. `overdue` and `age_minutes` are the second dimension that makes it
  operational rather than decorative, because an open P1 inside its window and one
  four days past it are not the same fact.
- **Response times.** `incidents.csv` for the distributions
  (`minutes_to_acknowledge`, `minutes_to_resolve`, `minutes_to_close`) and
  `acknowledged_within_window` from the summary for the one number an executive
  actually asks for. `transitions.csv` is the same story as a sequence, and it is
  where a reopened incident shows as the reopen it was.
- **Trend Pareto.** `incidents.csv` grouped by `source_module` and by
  `business_domain`. **Take care with the word trend here.** Six of the seven
  modules publish one event per inspected object, so a Pareto over them is a count
  of what was raised. `nhtsa_nlp` is not: its events are already a trend over an
  aggregate, so it contributes 25 rows standing for 3,080 tested cells, and mixing
  the two on one axis compares a count of parts with a count of signals.

**One honest caveat belongs on the finished dashboard**, in the same spirit as
the caveat on every module page of the cockpit: this store holds 29 incidents from
deliberately small demo slices, so every rate on it is a rate over a sample chosen
to be small. The response times are real measurements of real delays and the
delays are days, because nobody was watching a demo store.

Booleans are written `TRUE` and `FALSE` and nulls as empty cells, which is the
form Tableau's CSV connector types as Boolean and Null rather than as a two-value
string and the word "None".

## Publishing, decided 2026-09-04

**Sergey's decision is to publish to Tableau Public.** So the shape is settled:
the workbook lives at a public URL that this repository and `kasatov.de` can link,
and the extracts are committed here so the published view and the repository can
be checked against each other.

**The sign-in is his and cannot be delegated.** An agent does not enter a password
into any field, so the sequence is: build the workbook against these CSVs, then he
signs in to Tableau Public and saves, which is the publish. Everything before that
step is ordinary work.

**A reference for whoever builds it.** `~/Downloads/P3_Unicorn_SK_Draft_v2025.2.twbx`
is Sergey's own working Tableau file, a real 23-sheet, 2-dashboard workbook at
version 18.1. A `.twbx` is a zip holding a `.twb`, which is XML, so the schema can
be learned from a file that works rather than invented. Tableau Public opens a
local workbook even though it cannot save one, so an authored `.twb` is a route to
a version-controlled workbook rather than a GUI-only artifact. Whether that is
worth it against building in the application is a judgement for that session.

**Load the `dataviz` skill before drawing anything.** This file specifies fields
and stops; the visual design has not been done.

## The constraint that turned out not to be one

**Corrected 2026-09-05, by reading the application instead of assuming.** This
file said Tableau Public saves only to the public cloud, with no local `.twb`, and
flagged it as needing confirmation in the app. The app answered: its own What's
New panel reads "You can now save your work locally or publish to your Tableau
Public profile. Local save is available on Tableau Desktop Public Edition
2026.2.2." The installed build is 2026.1, with an "Update to 2026.2.2 Now" button
in the window.

**So local save exists, behind one update, and the two actions come apart.**
Building the view is no longer the same act as publishing it. Three consequences,
and the middle one is the reason this correction is worth more than the paragraph
it replaces:

- The workbook can be a tracked file in this repository, versioned beside the
  extracts it reads, rather than a GUI-only artifact living in a cloud account.
- **Publishing becomes a separate decision taken after seeing the result**, rather
  than a precondition for starting. Sergey's decision of 2026-09-04 to publish
  still stands; it simply no longer has to be taken blind.
- The paid-licence argument was wrong for this step. It remains true for a live
  connection, which is charter 7.5's own boundary sentence and needs Tableau
  Server, but it does not apply to saving a workbook.

**The first step for whoever builds it is therefore the update to 2026.2.2**, and
then a local save, and only then the publish.

Nothing in the extracts is private either way: the model outputs come from public
datasets and the operational context is generated and labelled `simulated`. The
question was never data safety, only whose account it goes out from and when.

Whatever happens to the workbook, the extract layer stands on its own: one command
refreshes it, it verifies its own completeness, and any BI tool can read four CSVs.
