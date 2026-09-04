# Tableau executive view

The last Phase 3 item of charter 7.5. This directory holds the **extract layer**,
which is built and verified; the workbook itself is not built, and the reason is
in "What is blocked" below rather than being an omission.

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

## What is blocked, and it is Sergey's call rather than a missing step

**The installed application is Tableau Public 2026.1, not Tableau Desktop.**
Tableau Public is understood to save workbooks only to the Tableau Public cloud,
where they are visible to anyone: there is no local `.twb` or `.twbx` save. That
needs confirming in the application rather than taken from this note, and it
decides the shape of everything after it.

If it holds, publishing this workbook puts it on the public internet. Nothing in
the extracts is private - the model outputs come from public datasets and the
operational context is generated and labelled `simulated` - so the question is not
data safety. It is that publishing is an outward-facing act on Sergey's own
account, and it is his.

There is an upside on the other side of that decision. A published Tableau Public
view is a portfolio artifact with a link, and Tableau is a listed skill on his CV
with nothing behind it yet in this project.

Two paths, and they are not equivalent:

1. **Publish to Tableau Public.** The workbook lives at a public URL that the
   repository and `kasatov.de` can link. The extracts are committed here, so the
   published view and the repository can be checked against each other.
2. **Keep it local.** Needs Tableau Desktop, which is a paid licence, or a
   different tool. The charter's own boundary sentence already says a live
   connection needs a paid Tableau Server; a local-save workbook is the same class
   of constraint arriving one step earlier.

Until that is decided, the extract layer stands on its own: it is refreshed by one
command, it verifies its own completeness, and any BI tool can read four CSVs.
