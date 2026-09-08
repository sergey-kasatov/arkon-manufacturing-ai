# n8n Quality Steering Cell

Operational layer of the Arkon platform: one workflow raises incidents and
alerts, one moves them along their lifecycle, one answers questions about them,
one records an approved escalation, and two run on timers: one tells the Quality
Manager about a P1 or P2 that nobody acknowledged inside its window, one sends the
daily digest; and since 2026-09-07 one keeps the queryable incident store level with
the logs after every write. Process owner: `docs/Project_Charter.md` sections 7 and 8.
All of them run on a self-hosted n8n instance, pinned to `n8nio/n8n:2.29.9`.

| Workflow | Direction | Endpoint | Deployed |
|---|---|---|---|
| `quality_steering_cell_v1.json` | write | `POST /webhook/arkon-event` | 2026-08-30, alert body fixed 2026-09-02 |
| `incident_transition_v1.json` | write | `POST /webhook/arkon-incident-transition` | 2026-09-03 |
| `incident_status_api_v1.json` | read | `GET /webhook/arkon-incident-status` | 2026-08-30, folds transitions since 2026-09-03, answers from the queryable store since 2026-09-07 |
| `escalation_record_v1.json` | write | `POST /webhook/arkon-escalation` | 2026-08-30, folds transitions since 2026-09-03 |
| `comparison_slice_v1.json` | read | `POST /webhook/arkon-slice` | 2026-08-30 |
| `overdue_escalation_v1.json` | scheduled | every 15 minutes, no endpoint | 2026-09-06, record fix the same evening |
| `daily_digest_v1.json` | scheduled | daily at 07:05 Europe/Berlin, no endpoint | 2026-09-06 |
| `store_sync_v1.json` | sync | `POST /webhook/arkon-store-sync`; also started by the two write paths after every append | 2026-09-07 |
| `customer_status_api_v1.json` | read | `GET /webhook/arkon-customer-status` | 2026-09-08 |

**Three of the seven that run the plant share one piece of code.** The incident line is written once,
at `new`, and never rewritten, so the current status of an incident is the fold of
the transition log onto that line. That fold lives in `n8n/build/lifecycle.py` and
is injected verbatim into the three workflows that fold a status: the transition
endpoint, the escalation record and, since 2026-09-07, the store sync, which folds
on the status API's behalf (the API reads the sync's rows and folds nothing itself);
a state machine copied into three generated JS bodies is a state machine that drifts.
`n8n/build/check_lifecycle_js.py` asserts the injection is verbatim and then runs
the fold under node.

## The run log: what has actually been sent through here

**This is where deployment state lives, and it is deliberately not in the
charter.** The charter says which modules exist, what each one measures and what
version 1 of the platform can and cannot do. What has been *sent* is a different
kind of fact: it changes the moment anybody replays anything, and the charter is
ingested into the assistant's knowledge store, so every edit to it costs a
snapshot, a collection drop, a rebuild and a re-measurement. Four of those
happened on 2026-09-02: two were caused by charter sentences about runs, and the
fourth was this move, which is the last one that class will cost. This file is not
ingested. The run log belongs here.

Counted from the incident store on 2026-09-02, not from memory:

| Module | Incidents | Ids | Sent |
|---|---|---|---|
| `cmapss_rul` | 6 | `ARK-INC-00011` to `00016` | 2026-08-30, the deployment verification |
| `scania_aps` | 1 | `ARK-INC-00017` | 2026-08-30, first event of the second module |
| `casting_cv` | 1 | `ARK-INC-00018` | 2026-08-30, first event of the third module |
| `mvtec_anomaly` | 6 | `ARK-INC-00019` to `00023`, and `00029` | 2026-09-02, a five-event slice plus the one that verified the alert fix |
| `neu_surface` | 5 | `ARK-INC-00024` to `00028` | 2026-09-02, the run that found the alert defect |
| `gc10_detect` | 5 | `ARK-INC-00030` to `00034` | 2026-09-02, the sixth module, and the first whose events carry a list. **From the batch notebook 03 produced before it was re-run on 2026-09-03**, so these five are a record of a superseded batch: the module does not reproduce, and the re-run moved the detection threshold and with it which sheets publish. The record ids on them still name real sheets |
| `nhtsa_nlp` | 5 | `ARK-INC-00035` to `00039` | 2026-09-03, the seventh module, the only one in `field_quality`, and the first that needed no contract change at all. Three P2 answered `incident_created_alert_sent` and two P3 `incident_recorded` |
| live plant, all seven | 7 | `ARK-INC-00040` to `00046` | 2026-09-05, the first run of `live_plant/plant.py`: one real-model event per module, re-timed and labelled, two of them alerting (`00042`, `00045`), **both cards read by Sergey off the Telegram group at 17:38 and 17:39**; the crew then moved four of them. `live_plant/README.md` |

**All seven modules that publish the section 6 event contract have now been through
this webhook, and Phase 2 is closed.** There is no module left that has not.

**The seventh module cost the platform nothing either, and it is the first that
needed no contract change at all.** Every module from NEU onward has added a name to
the one closed enum in the section 6 contract. `nhtsa_nlp` was already in
`source_module` in both the schema and the validator, `field_quality` already in
`business_domain`, and the Field Quality Analyst already in `roster.json`, because
the reservation was made when the contract was written. Three P2 answered
`incident_created_alert_sent` and two P3 `incident_recorded`, with no workflow
touched.

**The status API needed nothing, for the third module running, and it carried a shape
it has not seen before.** A NHTSA incident is about a manufacturer-component-month
cell rather than a part, so its evidence carries `manufacturer`, `component`, `month`,
a trailing baseline and `label_reference_agrees`, and all of it comes back through
`GET /webhook/arkon-incident-status?source_module=nhtsa_nlp` exactly as published.
That is the Scania fix still paying: before it, the API projected
`evidence.prediction` into a named field and everything else was lost.

**And `evidence.prediction` and `evidence.threshold` are two counts on this module,
where every earlier one puts a model output and a decision boundary there.** 155
complaints observed against 65.5 the cell's own history predicted. The contract
permits it and the API passes it through unchanged, and it is worth knowing before
anybody compares `threshold` across modules. Charter section 6 records it.

**The alert bodies were tested before the batch was sent rather than after.**
`alert_body_probe.js` renders every alerting event in every batch through the real
Code node, and the NHTSA batch's 9 alerting events passed with the other 801. That
ordering is the whole point of the probe: the defect it exists for was found by
sending a batch and losing three alerts to an HTTP 200.

**And the three cards were confirmed to have arrived, which is a separate claim from
the workflow saying it sent them.** Sergey read them off the Telegram group:
`ARK-INC-00035`, `00036` and `00037`, all at 18:46 on 2026-09-03, each carrying the
priority, the incident id, the summary, the assignee, the recommended action and the
event id. That distinction is the whole of DEFECT-8: for three weeks the workflow
answered `incident_created_alert_sent` and HTTP 200 on every alert the messaging API
had refused, with the incident already written and its id consumed. **A run log that
records only what the workflow returned cannot tell the two apart**, so from here a
new module's slice is not finished until somebody has seen the cards.

**The sixth module cost the platform nothing at all, and it was the one expected to
cost something.** GC10 is a detector, so its `evidence` carries `detections`, a list
of located defects rather than the single measurement every earlier module
published. Three P2 answered `incident_created_alert_sent` and two P3 answered
`incident_recorded`, with no workflow touched. **The status API needed nothing
either**, and the reason is the Scania fix rather than luck: that fix stopped the API
projecting `evidence.prediction` into a named field and made it return the evidence
object as published, so a list rides through a path that was never designed for one.
Verified by querying `source_module=gc10_detect` and reading `detections` back out of
the store.

**And it exercised the alert fix on the hardest input the platform has seen.** Every
GC10 record id is a file stem like `GC10-IMG_01_SIS001577_00012`, three underscores
in the identifier alone, and the alert body carries several more in the defect class
names. Before 2026-09-02 every one of those three P2 alerts would have been refused
by Telegram while the incident was written and the caller answered 200.

Two things the table is careful about. **The store is not a complete history of
every id ever issued**: it holds 19 incidents while the counter stands at 29, and
ids below `ARK-INC-00011` were consumed by earlier deployment testing whose
records are not in the current file. And **the counter, not the store, is the
identity**: it lives in the workflow's static data, which is why re-importing this
workflow needs the care described further down.

**Module-agnostic as of 2026-08-30, and now measured.** The first Scania APS
event was posted to the intake webhook and created `ARK-INC-00017` with no
change to any workflow: intake validates a contract rather than a domain, and it
takes the assignee from the event's own `operational_context`. The status API
did need one fix, and it was not cosmetic. Its projection filled `predicted_rul`
from `evidence.prediction` whatever the module was, so a Scania failure
probability of 0.0373 was served as a remaining useful life of 0.0373 cycles and
the assistant read it out as one. The projection now returns the `evidence`
object as published and keeps the CMAPSS aliases only for record ids carrying
the `FD<n>-Unit-` marker. Three filters were added at the same time -
`record_id`, `source_module`, `business_domain` - because every module carries
those by contract, while `unit` only means something for CMAPSS.

**The fifth module went in on 2026-09-02, and the workflows were again not
touched.** Five MVTec component anomaly events created `ARK-INC-00019` through
`ARK-INC-00023`: three P2 above the sound-part ceiling took the alert branch and
answered `incident_created_alert_sent`, two P3 above the threshold answered
`incident_recorded`, and a re-post of the first came back `duplicate_suppressed`
with the store unchanged at thirteen. The status API needed nothing this time,
because the Scania fix already returns the `evidence` object as published: an
MVTec incident keeps its own `category`, `ceiling` and `threshold_basis` instead
of being read as a remaining useful life.

**And the replay found a defect in the events rather than in the workflows.** The
MVTec adapter built the part identity from the category and the image file name,
and MVTec numbers its test images from `000` inside *every* defect-type folder,
so `grid/test/bent/000.png` and `grid/test/broken/000.png` were both
`MVTEC-GRID-000`. 309 events carried 82 distinct record ids. Nothing rejects
that - the contract asks for a record id, not for a unique one - but intake
dedups on `record_id` plus `priority` for 24 hours, so a full replay would have
recorded 106 incidents and silently suppressed 203 flagged parts as duplicates of
each other. The adapter now carries the defect-type folder as well and the 309
events have 309 distinct ids. **The other four adapters were checked for the same
class and are clean**, one record id per event in all of casting, CMAPSS, NEU and
Scania. Worth keeping as a rule: a dedup key is a claim that two records describe
the same thing, and it is only as good as the identity the adapter builds.

**NEU went through the same day and completed the set**, and it is the module that
had been written but never posted. Its two P3 events were recorded as
`ARK-INC-00027` and `ARK-INC-00028` with nothing touched. Its three P2 events
created `ARK-INC-00024` to `00026` and **their alerts were refused by Telegram**,
which is the next section and is not a NEU problem. All modules built at that point
had then published into this webhook; GC10 and NHTSA followed.

## The alert branch was rejecting its own data, and answering 200

**Found 2026-09-02 by sending NEU, the fifth and last module to go through here.**
Three P2 events came back **HTTP 200 with an empty body**, which this file has
always said means the workflow failed after the webhook was answered. It did. The
execution record shows the Telegram node returning

```text
400 - {"ok":false,"error_code":400,
       "description":"Bad Request: can't parse entities: Can't find end of the entity starting at byte offset 89"}
```

Byte 89 of the rendered card is the underscore in `inclusion_244`. The alert body
was a Markdown template with six raw event values interpolated into it, and legacy
Telegram Markdown reads `_` as an italic marker, so one underscore in a record id
made Telegram refuse the whole message.

**What makes this the worst defect found in this system is not the 400.** By the
time Telegram refused, the incident had been written, its id consumed and its
dedup key stored, so a retry inside the 24-hour window is answered
`duplicate_suppressed` and the alert is gone for good. `ARK-INC-00024` through
`00026` are in the store, correct in every field, and **no alert for them reached
anybody**. The caller was told 200.

**And it was never NEU-specific.** Every alerting event in the repository was
counted, and the exposure is:

| Batch | P1 and P2 events | Would have been refused |
|---|---|---|
| `casting_events.jsonl` | 13 | **13, all of them** |
| `mvtec_events.jsonl` | 262 | **210** |
| `neu_events.jsonl` | 3 | **3, all of them** |
| `cmapss_events_full_fleet.jsonl` | 136 | 0 |
| `scania_events.jsonl` | 309 | 0 |

CMAPSS and Scania identifiers are digits and hyphens. **The branch was verified on
CMAPSS at deployment and has never been sent anything else that alerts**, so it
looked like a working alert channel for three weeks while it would have dropped
every casting alert and four out of five MVTec ones. The MVTec run earlier the
same day landed in the safe fifth by accident: `grid` and `bent` are the only
category and defect-type names in that dataset without an underscore.

**The fix moves the markup off the template and into the code.** The Code node now
builds the whole body, escapes every value that comes out of an event, and hands
the Telegram node one field; `parse_mode` is HTML rather than Markdown, because
HTML has exactly three characters to escape and none of them can be left unmatched
by accident. `alert_body_probe.js` renders all 738 alerting events through the real
node and checks each body, and it carries five cases whose answer is known so a
pass means something.

```bash
node n8n/alert_body_probe.js
```

### Deployed 2026-09-02, and the deploy is not a plain import

**This workflow cannot be updated by importing the tracked file.**
`import:workflow` rewrites the whole workflow row, and on **this** row that
includes `staticData`, which holds the incident counter and the dedup cache: a
naive import restarts the numbering at `ARK-INC-00001`. The tracked file also
carries the Telegram credential by name only, while n8n binds credentials by
internal id, so an import of it would leave the alert node unbound.

So the fix went in the other way round. The live workflow was exported, the two
changes were applied to **that** document, and the result was imported:

```bash
docker exec n8n n8n export:workflow --id=o0vXtlRWIs9yFrUJ --output=/tmp/exp.json
# apply the two changes to the export, then
docker exec n8n n8n import:workflow --input=/tmp/patched.json
docker exec n8n n8n publish:workflow --id=o0vXtlRWIs9yFrUJ
docker restart n8n
```

The Code node body was taken verbatim from the tracked file, so the running
workflow has exactly the code the probe executed. Three things were asserted on
the patched document before it was sent and again after: `counter` still 28, the
dedup cache still ten entries, and the credential id unchanged. The import
deactivates the workflow and says so, hence the publish; the restart is not
optional, because the running process holds its active workflows in memory.

**Verified by sending an event that would certainly have failed before.**
`arkon-2026-400037`, summary `Component grid-metal_contamination-000 ...`, one
underscore. It answered `incident_created_alert_sent` as `ARK-INC-00029` - the
counter continuing from 28, which is what says the static data survived the
import - and the execution record carries Telegram's own reply with a
`message_id` and parsed `entities`. The three failed NEU executions and this one
were read the same way, out of the `execution_entity` table, so the before and
the after are the same measurement.

**The general form is the one this project keeps meeting.** A path that is only
ever exercised with data that happens to be safe is an untested path, and it does
not announce itself: this one answered 200. The same sentence is already in this
file about the escalation endpoint's 503 branch, which survived because it could
not be reached. Here the branch could be reached; nobody had reached it with
anything but CMAPSS.

## Workflow ids, and the one that is not readable

Every workflow file carries a fixed `id`, so `n8n import:workflow` updates the
existing workflow instead of creating another copy. All but one read like
names. The exception does not, and the reason is worth keeping:

| File | id |
|---|---|
| `incident_status_api_v1.json` | `arkonStatusApi1` |
| `escalation_record_v1.json` | `arkonEscalate01` |
| `comparison_slice_v1.json` | `arkonSlice001` |
| `overdue_escalation_v1.json` | `arkonOverdue01` |
| `daily_digest_v1.json` | `arkonDigest001` |
| `incident_transition_v1.json` | `arkonTransit01` |
| `store_sync_v1.json` | `arkonStoreSync1` |
| `customer_status_api_v1.json` | `arkonCustDesk01` |
| `customer_desk_kb_v1.json` | `arkonCustDeskKB1` |
| `customer_desk_v1.json` | `arkonCustDesk02` |
| `customer_desk_failtest_v1.json` | `arkonCustDesk03` (tool-failure fixture, deleted before submission) |
| `quality_steering_cell_v1.json` | **`o0vXtlRWIs9yFrUJ`** |

**The steering cell keeps the id n8n generated for it, because that row is where
the incident counter lives.** `$getWorkflowStaticData("global")` on this workflow
holds `counter`, which produces the `ARK-INC-*` numbering, and `seen`, the 24-hour
duplicate-suppression window. Giving the file a readable id would mean importing
under a new id, which creates a **new** workflow with empty static data: the
counter would restart, so the next incident would be `ARK-INC-00001` against a
store whose ids already run past `ARK-INC-00028`, and the dedup memory would be
gone. The n8n CLI has `import`, `export`, `update` and
`unpublish` but **no delete**, so the old row could not be cleaned up afterwards
either, and the rename would leave exactly the extra copy the fixed id exists to
prevent.

So the identity of this workflow is not a string in a file, it is the row that
holds the counter, and the file points at it. Verified 2026-08-31: imported twice
in a row, no third workflow appeared, `counter` stayed at 18, and a replayed event
came back `duplicate_suppressed` with the incident store unchanged at 8 lines.

**One archived duplicate remains and is inert.** `ZdLNgYq3bDTxQswJ`, the first
import from before the id was fixed: inactive, `isArchived = 1`, no static data,
and no row in `webhook_entity`, so it cannot fire. Permanently removing it needs
the UI (Workflows, Archived, delete) or the public API, and no API key exists on
this instance. It is left rather than deleted through the database, because
`workflow_entity` is referenced by executions, history and sharing rows and that
is not a trade worth making for a hidden row.

## Event intake (write path)

**Status: deployed and verified 2026-08-30** on n8n 2.29.9. Sixteen incidents
created from replayed CMAPSS events, dedup confirmed across production runs,
Telegram cards delivered to the alert group.

### Flow

```
POST /webhook/arkon-event
  -> Validate against the event contract     (400 on contract violation)
  -> Dedup: record_id + priority, 24 h       (duplicate suppressed, no 2nd incident)
  -> Build incident line -> append to the JSONL store
  -> P1/P2 -> Telegram incident card + respond
  -> P3/P4 -> respond (recorded, no push alert)
  -> every outcome, one line in /data/arkon/intake_outcomes.jsonl   (charter 7.6, since 2026-09-06)
```

Incident numbering (`ARK-INC-00001`) and the dedup cache live in n8n workflow
static data. Static data persists for production executions of a published
workflow, not for editor test runs, so the workflow must be published before
dedup can be demonstrated. Observed during deployment: static data is written
even when a later node in the same execution fails, so a failed run still
consumes its dedup key.

The dedup cache prunes entries older than the 24 h window on every run, so
workflow static data does not grow without bound.

### Files

| File | Purpose |
|---|---|
| `quality_steering_cell_v1.json` | The intake workflow, importable into n8n |
| `incident_status_api_v1.json` | The status API workflow, importable into n8n |
| `replay_events.py` | Posts an events JSONL to the webhook for demos |
| `incident_status_probe.py` | Contract test for the status API |
| `alert_body_probe.js` | Contract test for the Telegram alert body, over every alerting event |
| `../live_plant/plant.py` | The demo engine, a mini-project of its own: real-model events on a clock, round-robin over the modules, plus the crew that moves them (`live_plant/README.md`) |

Seven modules publish into this one webhook. Every batch is replayed by the same
script, and the priority mix is the module's own, not a setting:

| Batch | Events | Priorities |
|---|---|---|
| `cmapss_events_full_fleet.jsonl` | 707 | 49 P1, 87 P2, 90 P3, 481 P4 |
| `scania_events.jsonl` | 778 | 240 P1, 69 P2, 469 P3 |
| `casting_events.jsonl` | 460 | 13 P2, 447 P3 |
| `neu_events.jsonl` | 360 | 3 P2, 357 P3 |
| `mvtec_events.jsonl` | 309 | 262 P2, 47 P3 |
| `gc10_events.jsonl` | 310 | 63 P2, 247 P3 |
| `nhtsa_events.jsonl` | 25 | 9 P2, 16 P3 |

The earlier `cmapss_events_FD001.jsonl` is kept because it is what the first
deployment was verified against; it comes from the superseded FD001-only model
and should not be used for new demos.

**Replay a slice, never a batch.** Every P1 and P2 sends a Telegram card to the
alert group, and the incident store is append-only with the counter in workflow
static data, so nothing here can be undone. `mvtec_events.jsonl` is the sharpest
case, 262 of its 309 events being P2. The MVTec, NEU and GC10 runs of 2026-09-02 and the NHTSA run of
2026-09-03 were five events each in two commands, and that is the size a new module
should go in at:

```bash
python n8n/replay_events.py http://AK2101:5678/webhook/arkon-event events/out/mvtec_events.jsonl --priority P2 --limit 3 --delay 1
python n8n/replay_events.py http://AK2101:5678/webhook/arkon-event events/out/mvtec_events.jsonl --priority P3 --limit 2 --delay 1
```

A P2 replayed now is overdue an hour later, per the charter 7.1 window, and turns
up in the OVERDUE block of the shift briefing. That is the store behaving
correctly, and it is a reason to keep the demo store small rather than a reason
to widen the window.

### Intake outcomes, charter 7.6 (since 2026-09-06)

Every event that reaches this webhook has exactly one of three outcomes: recorded
as an incident, rejected against the section 6 contract, or suppressed as a
duplicate inside the 24-hour window. Until 2026-09-06 only the first was written
anywhere, so duplicate suppression could not be counted and a validation
regression looked exactly like a quiet plant from every screen (charter 7.6).
Now every outcome is one line in `/data/arkon/intake_outcomes.jsonl`.

```text
Respond Invalid / Respond Duplicate / Respond Recorded / Respond Alerted
  -> Build Intake Outcome   (one Code node, runs once per event on every branch)
  -> Build Intake Outcome Line -> Append Intake Log
```

The node hangs off the four Respond nodes rather than off the branches before
them. The caller is answered first, so the log can never delay or fail an intake;
and on the alert branch it runs after the Telegram node has answered, so the line
for an alerted incident carries **Telegram's own `message_id`**, which the
platform had never recorded for an intake card. An alert that fails loses the
line and never the incident: the store already has it, and the failed execution
is the trace. The line: `received_at`, the n8n `execution_id`, the outcome
(`recorded`, `rejected`, `duplicate_suppressed`) with its reason (the validator's
errors joined, or the dedup rule), the event id, the record id and priority that
make the `dedup_key`, the module and domain, the incident id when one was
created, `alert_branch`, `telegram_message_id`, the `errors` list, the `emitter`
label and the context origin. Patch, check and deploy:

```bash
py n8n/build/add_intake_outcomes.py n8n/quality_steering_cell_v1.json   # the tracked file (idempotent)
py n8n/build/check_intake_outcome_js.py                                  # the node under node, 34 cases
python3 deploy_steering_cell.py add_intake_outcomes                      # ON THE NAS, see below
```

`n8n/build/deploy_steering_cell.py` is the "not a plain import" recipe of this
file as code: it exports the live row, applies the patch module to the export,
asserts that the counter, the dedup cache and the credential id did not move,
creates the log file inside the container, imports, publishes, restarts and
reads the live counter back against the highest id in the store. **It also waits
for the quiet minutes after a live-plant tick**, because the plant raises an
incident every ten minutes or so and an export taken before a tick and imported
after it would rewind the counter by one, silently.

**Verified 2026-09-06 on all three outcomes, with no card sent and no id
consumed.** Deployed at 23:24:31 through `deploy_steering_cell.py`, 176 s after
the plant tick that raised `ARK-INC-00222`: counter 222 and 144 dedup entries
before and after, 12 nodes to 15, restart 23:24:39, `healthz` in 4 s, all seven
Arkon workflows re-activated. Then, from the NAS: a body with only `event_id` and
`priority: P9` answered HTTP 400 with ten validator errors (execution 7901) and
left one `rejected` line with the ten errors as `reason` and `errors` and no
dedup key; the last incident's own embedded event (`arkon-2026-900183`,
`FD002-Unit-041`, P3) re-posted answered `duplicate_suppressed` (execution 7902)
and left one line with `dedup_key: FD002-Unit-041|P3` and `emitter: live_plant`,
the store unchanged at 00222; and the plant's next tick at 23:30
(`arkon-2026-900184`, `CASTING-CAST_DEF_0_108`, P3) was recorded as
`ARK-INC-00223` (execution 7905) and left one `recorded` line naming it,
`alert_branch: false`. The first alerted line, carrying a Telegram message id, is
the plant's next P1 or P2; read it out of the log rather than out of this
paragraph.

Boundaries. **Nothing reads the log back yet**: the cockpit, the status API and
the assistant still see recorded incidents only, so a rejection is countable
from the file and visible on no screen; a read path is the next step and is
named in charter 7.6. **It is not the unified notification log.** The intake
card's message id now exists here and the timer's and the digest's in
`incident_notifications.jsonl`; folding the intake cards into that log is not the
one-node change it looks like, because the overdue timer's dedup reads every
`incident_id` in that log as an incident already notified, and an intake-card
record there would silence the overdue card for every alerted incident. The
timer's selection would have to key on its own `trigger` first.

### Deployment steps (interactive)

Two of these need a human at a keyboard and cannot be scripted from here.

1. **Telegram bot** (manual): create a bot via BotFather, note the
   token; create a group for alerts, add the bot to it, and read the chat id
   from `https://api.telegram.org/bot<TOKEN>/getUpdates`. The token is entered
   only in the n8n credentials UI, never stored in this repo. Name the
   credential `Arkon Telegram Bot`.
2. **NAS compose** (`/volume1/docker/n8n/docker-compose.yml`), three additions:
   - Bind-mount the incident store: `/volume1/docker/arkon:/data/arkon`.
   - `N8N_RESTRICT_FILE_ACCESS_TO=~/.n8n-files;/data/arkon` - **required**, see
     the traps below.
   - Attach the container to the `msit-flowise_msit` network as well, so the
     agent front-end can reach n8n by name at `http://n8n:5678`.
   - Then `docker compose up -d` per the runbook. Back up `n8n_data` first.
3. **Create the store file**: `docker exec n8n touch /data/arkon/incidents.jsonl`.
   The file node cannot create it, see the traps below.
4. **Import**: n8n UI -> Create workflow -> the `...` menu -> Import from File
   -> `quality_steering_cell_v1.json`. Select the `Arkon Telegram Bot`
   credential on the Telegram node; import does not bind it automatically,
   because credentials are matched by internal id and not by name. Save, then
   **Publish** (n8n 2.x renamed the activation control).
5. **Smoke test** from the laptop, starting with a deliberate contract
   violation so the rejection path is exercised without consuming an incident
   id, then the real events:

```bash
python n8n/replay_events.py http://AK2101:5678/webhook/arkon-event events/out/cmapss_events_full_fleet.jsonl --priority P1,P2 --limit 5 --delay 1
```

Expected: HTTP 200 per event, `ARK-INC-*` ids in the response bodies, Telegram
cards for P1 and P2, one appended line per incident in the JSONL store.
Re-running the same events within 24 h must answer `duplicate_suppressed` and
must not create new ids.

An empty 200 response body means the workflow failed after the webhook was
answered. Read the execution in the n8n UI. Reading the SQLite database directly means
copying `database.sqlite-wal` too, since n8n runs it in WAL mode and the main
file alone can be a month stale.

### n8n 2.0 traps met during this deployment

All three are default changes between n8n 1.x and 2.x. Each one presents badly,
so they are recorded with their real cause.

1. **`ExecuteCommand` is disabled by default.** n8n 2.0 ships a
   `disabled-nodes` rule listing `n8n-nodes-base.executeCommand` and
   `n8n-nodes-base.localFileTrigger`. An imported workflow using either renders
   the node with a `?` icon and no explanation. The v1 draft appended the
   incident with a shell command and hit this. It was **not** re-enabled through
   `NODES_EXCLUDE`: the append was rebuilt from `Convert to File` (toText) plus
   `Read/Write Files from Disk` (write, append). That also removed a shell
   injection: the draft interpolated raw incident JSON inside a single-quoted
   shell string, so an apostrophe in an event summary broke the command.
2. **`N8N_RESTRICT_FILE_ACCESS_TO` now defaults to `~/.n8n-files`.** In 1.x the
   default was empty, meaning unrestricted. File nodes writing anywhere else
   fail with `The file "..." is not writable.`, which is misleading: filesystem
   permissions are irrelevant, the path is simply outside the allowlist. The
   entry in the compose file above is what makes the incident store work. The
   value is semicolon-separated, so the n8n default is kept as the first entry.
3. **The write node in append mode does not create the file.** In the node
   source the flag is `O_APPEND` alone for append, while the overwrite branch
   uses `O_WRONLY | O_CREAT | O_TRUNC`. A missing file therefore fails, again
   reported as "not writable". Create the file once at deployment (step 3).

### Known boundaries of v1

- Acknowledge and close buttons on the alert card are closed on this deployment:
  they need a Telegram Trigger node, and n8n's `WEBHOOK_URL` here is tailnet-only,
  so Telegram has nothing reachable to call. The escalation timer of charter 7.4
  is deployed since 2026-09-06 as its own scheduled workflow ("Overdue escalation"
  below) and needed no Wait-based branch in this one. **There is now something behind
  those buttons**, which there was not until 2026-09-03: the lifecycle write path
  below. This workflow itself still only ever writes an incident at `new`, and
  that is correct - raising is its job and moving is the other endpoint's.
- The incident store is append-only JSONL in v1, and the lifecycle keeps it that
  way: transitions go to a second append-only log rather than rewriting a line.
  Moving both to the n8n Data Table node (the charter 7.5 target, and now
  available natively with insert, get, update and upsert operations) happens when
  the Streamlit cockpit starts reading incidents.
- The alert group is a Telegram `group`, not a `supergroup`. If Telegram
  upgrades it, the chat id changes from `-548...` to a `-100...` form and
  alerts stop arriving silently. The chat id lives in the Telegram node.
- Operational context in the events (shift, assignee, escalation contact) is
  simulated and labelled `context_origin: simulated` per the charter.

## Incident store (the queryable projection, charter 7.5)

Eighth workflow, `store_sync_v1.json`, built and **deployed 2026-09-07**, workflow id
`arkonStoreSync1`. It is the queryable incident store the charter's section 7.5 named
from the start and the platform deviated from on 2026-08-30: three n8n data tables,
kept level with the two JSONL logs by one sub-workflow that runs after every write.
Not a second record of truth. The logs stay append-only and both write paths still
write only them; the tables are a projection of the logs and are rebuilt from them
by one call.

| Table | One row per | What it carries |
|---|---|---|
| `arkon_incidents` | incident | the flat projection the status API serves, with the folded lifecycle (`status`, the three milestones, the three response times, `transition_count`, `is_terminal`), the evidence and the history as JSON text, the log line the row came from |
| `arkon_transitions` | transition line | the record as the transition endpoint wrote it, plus its log line |
| `arkon_store_summary` | the store (one row) | the counts per priority and state, open and overdue, the response-time medians, the transition totals, and the two line counters (`incidents_lines`, `transitions_lines`) the next sync resumes from |

The schema is one file, `n8n/build/store_schema.py`, read by the sync's generator, by
the status API's generator and by the checkers, for the reason `lifecycle.py` is one
file.

```text
Execute Workflow Trigger (source, rebuild) | POST /webhook/arkon-store-sync
  -> Create the three tables if missing
  -> rebuild? wipe the three tables
  -> Read /data/arkon/incidents.jsonl and incident_transitions.jsonl (whole)
  -> Read the summary row
  -> Fold every incident (lifecycle.py, verbatim), compute the summary,
     pick the rows to write: new incident lines, incidents a new transition touched
  -> Upsert incident rows | upsert transition rows | upsert the summary row
  -> Append one line to /data/arkon/store_sync.jsonl
```

Four decisions, and the generator `n8n/build/build_store_sync_workflow.py` carries them
in its header.

- **A sync follows every write, not a clock.** The Steering Cell after `Append Incident
  Record` and the transition endpoint after `Append Transition Record` start this
  workflow through an Execute Sub-workflow node that does not wait and cannot fail its
  caller (`n8n/build/add_store_sync.py` puts the same node in the tracked JSONs and, by
  export-patch-import, in the live rows). The projection is current seconds after a
  line is appended and no request path ever waits for a fold. The webhook is for a
  person or a script; `n8n execute` cannot run it, see the boundaries.
- **Every run folds everything and writes only what changed.** The summary is
  recomputed from the full fold every time, so it cannot drift from the logs; the row
  writes are limited by the two line counters in the summary row. Reading both files
  whole per sync is the linear cost that remains, off the read path.
- **A rebuild is the same run from empty tables.** `{"rebuild": true}` on the webhook
  wipes the tables first; a plant reset (`live_plant/README.md`) is followed by one.
- **Successful runs are not kept as executions.** A run carries both logs as text, and
  the status API's stored executions had grown n8n's database to 3.6 GB in eight days.
  n8n soft-deletes such a run on completion (the row shows `running` with `deletedAt`
  set until the pruning's hourly hard delete; that is not a stuck execution) and the
  sync line is the record: mode, source, the counters, the numbers, the rows written.
  The status API got the same setting the same day. Failed runs are kept.

### Deploying it

```bash
docker exec n8n touch /data/arkon/store_sync.jsonl
docker exec n8n n8n import:workflow --input=/data/arkon/_deploy/store_sync_v1.json
docker exec n8n n8n publish:workflow --id=arkonStoreSync1 && docker restart n8n
curl -s -X POST -H 'Content-Type: application/json' -d '{"rebuild": true}' http://localhost:5678/webhook/arkon-store-sync
python3 ~/arkon-tmp/check_store.py
```

No credentials, no static data, so a plain import. The first call creates the tables.
The two callers are patched into their live rows with `n8n/build/deploy_live_patch.py`
(the transition endpoint, whose row carries `nextTransitionId`) and
`deploy_steering_cell.py` (the Steering Cell), both inside the quiet window after a
plant tick, both run on the NAS.

### The first sync, and what it measured

**2026-09-07 09:59 plant time, `sync_mode: initial`, through the webhook:** 275 incident
rows and 710 transition rows written from 275 and 710 log lines, `check_store.py`
level on the first pass. The fold took 7 ms; the run took 64 s, almost all of it the
985 upserts. The next call, with 4 new incident lines and 3 new transition lines,
took 0.99 s. The status API on the rows: a full `status=new&limit=500` page in 0.16
to 0.19 s against 0.31 to 0.42 s from the logs an hour earlier (276 incidents, 713
transitions), 25 of 25 probe cases, and the same numbers in the summary as the fold
gave before the move.

### Checking it

```bash
py n8n/build/check_store_sync_js.py        # the fold-to-rows node under node, 54 cases
py n8n/build/check_status_js.py            # the API's parser and answer node, fed the sync's own rows
py n8n/build/check_lifecycle_js.py         # the fold is verbatim in its three carriers
python3 ~/arkon-tmp/check_store.py         # on the NAS: the tables against the logs, row by row
```

`check_store.py` re-folds the logs in Python on purpose: a checker that reused the
sync's JS would agree with every mistake in it.

### Known boundaries

- **The sync reads both logs whole**, because n8n's file node has no offset read. The
  parse and the fold are the cost, 7 ms at 275 incidents, and they grow with the store;
  the next step, if a plant ever needs it, is a sync that reads a tail, and the two line
  counters in the summary row are already the bookmark it would start from.
- **Two syncs can overlap** (an intake and a crew move in the same second) and n8n has
  no per-workflow mutex. The row upserts are idempotent; the summary row is written by
  whichever finishes last, so it can be one write behind for a moment, and the next
  sync heals it. `check_store.py` is the ruler.
- **A write whose sync did not happen is invisible until the next one.** The caller
  never waits for the sync and never learns that it failed; the next write's sync
  redoes everything from the counters, and `store.sync_lag_seconds` on the API says
  how old the projection is.
- **`n8n execute` cannot run it.** The command starts from an Execute Workflow Trigger,
  which the sync has, but it does not load the data-table module (only `start` does),
  so every data table node fails with "the module is disabled". Measured twice, with
  and without `N8N_ENABLED_MODULES=data-table`. The webhook is the manual path.
- **The tables live in n8n's own database**, under its 200 MB default cap for data
  tables (`N8N_DATA_TABLES_MAX_SIZE_BYTES`). At 276 incidents they hold about a
  megabyte.
- **The transition endpoint and the escalation record still parse both logs** on every
  call. The same move is open for them and was deliberately not made today.

## Incident status API (read path)

Second workflow, `incident_status_api_v1.json`, built 2026-08-30. It answers
questions about incidents that already exist, so an assistant can report live
status instead of guessing it. It is the missing half of the last open MVP
criterion of charter section 10: this endpoint makes incident state available,
and the assistant that consumes it becomes the operational interface.

**Status: deployed and verified 2026-08-30** on n8n 2.29.9, workflow id
`arkonStatusApi1`. Twenty-four contract cases pass, plus the two the probe
cannot cover by itself: an unreadable store answers 503, and the endpoint is
reachable from the agent container by name. **Since 2026-09-07 it answers from the
queryable store** (the section above): the same id, the same contract, 25 probe
cases, and the deployment steps below need the store synced once first.

```text
GET /webhook/arkon-incident-status
  -> Parse and validate the query, pick the one table condition   (400, one reason per bad parameter)
  -> Simulated failure requested?                                  (503, test affordance)
  -> Read the summary row of arkon_store_summary                   (503 if the tables do not answer, 503 if never synced)
  -> Read the new rows of arkon_incidents                          (the live overdue count)
  -> Read the rows the condition names, newest first               (503 if the table does not answer)
  -> Apply the exact filters, page, project                        (200, status ok or no_match)
```

### Query contract

All parameters are optional. With none, the endpoint returns the five most
recent incidents plus the store summary.

| Parameter | Accepts | Notes |
|---|---|---|
| `incident_id` | `ARK-INC-00014`, `ark-inc-14`, `14` | normalised to the padded form |
| `unit` | `92`, `092`, `FD001-Unit-092`, `ATTRTEST` | matched against the unit token of `event.evidence.record_id` |
| `priority` | `P1`, `p1`, `P1,P2` | charter 7.1 levels |
| `status` | charter 7.2 lifecycle value | new, acknowledged, in_containment, resolved, closed, false_positive |
| `limit` | 1 to 500, default 5 | bounds the returned page, not `match_count`. Raised from 50 on 2026-09-06, when the live plant pushed closed incidents past it and the dashboards began reporting their own bands short. It never was a load limit: until 2026-09-07 this workflow read both JSONL files whole on every request whatever the caller asked for, so a small cap saved nothing and cost completeness; since then it reads the rows the query names. |
| `simulate_failure` | `true`, `1`, `yes` | test affordance, see below |

Four answers, deliberately distinct, so the caller can tell them apart:

| Situation | HTTP | `status` |
|---|---|---|
| query understood, at least one match | 200 | `ok` |
| query understood, nothing matches | 200 | `no_match` |
| query not understood | 400 | `rejected`, one `errors` entry per bad parameter |
| store unreadable, or failure simulated | 503 | `unavailable` |

The separation is the point. A `no_match` is a fact about the store and may be
reported as one; a 503 means the lookup itself failed and nothing about incident
state may be inferred from it. Collapsing the two into one empty result is what
makes an assistant invent a status.

Each incident is projected to a flat object rather than returned as stored: the
identifiers, summary and recommended action, the assignment and escalation
contact, the model evidence (`predicted_rul`, `priority_threshold`, `risk_score`,
`model_version`), and both origin labels. `operational_context_origin` rides on
every record so a simulated assignee can never be presented as real, per charter
section 5.

The response also carries a store summary computed over all incidents, not just
the returned page: counts per priority, open incidents, and `overdue_incidents`
measured against the charter 7.1 acknowledgement windows (P1 fifteen minutes, P2
one hour). That answers "is anything overdue" in a single call.
Since 2026-09-07 the summary comes from the summary row the store sync keeps, with
`overdue_incidents` still counted live from the `new` rows, and it names its own
freshness: `store.synced_at`, `store.sync_mode` and `store.sync_lag_seconds`.

### The simulate_failure affordance

`simulate_failure=true` returns the 503 path without touching the store. It
exists because the assistant's failure behaviour has to be demonstrable on
demand, and unpublishing the workflow mid-demo is slow and indistinguishable
from a real outage. A production deployment removes the parameter or puts it
behind an operator role; that trade belongs in the readiness account rather than
being left as an oversight.

### Deploying it

The workflow needs no credentials, so it can go in from the command line:

```bash
docker cp incident_status_api_v1.json n8n:/tmp/w.json && docker exec n8n n8n import:workflow --input=/tmp/w.json && docker exec n8n n8n publish:workflow --id=arkonStatusApi1 && docker restart n8n
```

Two things make that work. The JSON carries a fixed workflow `id`, so a
re-import updates the workflow instead of adding another copy - the steering
cell was imported twice through the UI and left a duplicate behind. And the
restart is not optional: `publish:workflow` writes the database and says so
itself, "changes will not take effect if n8n is running", because the running
process holds its active workflows in memory. `--activeState=fromJson` on the
import is not an alternative; it refuses outside queue or multi-main mode.
Importing through the UI and pressing Publish achieves the same without a
restart, and is the route to use on a fresh instance. Since 2026-09-07 the endpoint
reads the data tables, so the store sync has to have run once before the API is
published on a fresh instance; until then every call answers 503 `unavailable` with
"has not been synced yet", which is the designed answer and not an outage.

### Testing it

```bash
python n8n/incident_status_probe.py http://AK2101:5678/webhook/arkon-incident-status
```

The probe asserts invariants rather than a snapshot of the store: `returned`
never exceeds `limit` or `match_count`, every returned incident satisfies the
filter it was asked for, no incident loses its simulated-context label, and the
rejection message for a bad status still lists the charter 7.2 lifecycle. It
stays valid as incidents accumulate.

The two cases the probe cannot assert on its own were checked by hand on
2026-08-30. Moving the store aside answered 503 `unavailable`, and the file came
back byte-identical (same SHA-256, six lines). From inside the Langflow
container, `http://n8n:5678/webhook/arkon-incident-status?priority=P1&limit=2`
answered 200 with two P1 incidents.

### Reaching it from the agent

The n8n container is attached to `msit-flowise_msit` and carries the network
alias `n8n.arkon.internal` there. The laptop and the LAN use `AK2101` instead.

```text
http://n8n.arkon.internal:5678/webhook/arkon-incident-status?priority=P1&limit=3
http://AK2101:5678/webhook/arkon-incident-status?priority=P1&limit=3
```

**The dotted alias is required, not decoration.** Langflow's API Request
component validates its URL with `validators.url()`, which rejects any hostname
containing no dot, so `http://n8n:5678/...` fails as "Invalid URL provided"
before a request is made. That reads like a network fault and is not one:
verified inside the container, `n8n` and `AK2101` are both rejected while an IP
literal or any dotted name passes. The alias lives in the n8n compose file so it
survives a recreate, and it keeps the call inside the container network. The
caller also has to be allowed to make it: Langflow blocks outbound requests into
private IP ranges by default and needs
`LANGFLOW_SSRF_ALLOWED_HOSTS=n8n.arkon.internal`.

### Known boundaries of the status API

- Read-only, and it stays that way. Acknowledging or closing an incident is
  `POST /webhook/arkon-incident-transition`, escalating is
  `POST /webhook/arkon-escalation`.
- **It answers from the store sync's projection, since 2026-09-07.** Nothing is
  parsed per call any more; what a call reads is the summary row, the `new` rows and
  the rows its one condition names. The price is freshness rather than cost: a write
  is followed by a sync within seconds, and `store.sync_lag_seconds` says how long
  ago the last one ran, but a sync that failed leaves the projection behind until
  the next write or a manual `POST /webhook/arkon-store-sync`. The transition
  endpoint and the escalation record still parse both logs on every call.
- **A status it reports is a fold, not a field.** Reading `incidents.jsonl`
  directly gives `new` for every incident, for ever. `raised_as` is returned on
  every record so the two cannot be mistaken for a contradiction.
- No authentication. The endpoint sits on the LAN and the Tailscale network
  only. Anything beyond the demo needs at least a header credential, and that is
  a stated item in the readiness account.

## Customer status API (read path, the Customer Quality Desk)

Ninth workflow, `customer_status_api_v1.json`, built and **deployed 2026-09-08** on n8n
2.29.9, workflow id `arkonCustDesk01`. It is the read endpoint of the Customer Quality
Desk, the customer-facing agent built as the MSIT course project 2A (the coursework lives
outside this repository, the endpoint is platform): an OEM customer's quality engineer, or
the agent answering them, asks about one quality notice or complaint by its `ARK-INC`
reference and gets the customer projection back. Same store as the plant (charter 7.5),
eight fields of it.

The point is the boundary. The incident status API serves the whole record (assignee,
evidence, priority, thresholds, other incidents) to the plant's own people. A customer may
see none of that, and an agent's instructions can only ask the model not to repeat it. This
endpoint makes the restriction an infrastructure fact: the agent never receives what it
must not say.

```text
GET /webhook/arkon-customer-status?reference=ARK-INC-00348
  -> Parse the reference (the only parameter read; every other one is ignored)   (400, one reason)
  -> Simulated failure requested?                                                (503, test affordance)
  -> Read the summary row of arkon_store_summary                                 (503 if the tables do not answer, 503 if never synced)
  -> Read the one row of arkon_incidents the reference names                     (503 if the table does not answer)
  -> Project it for the customer                                                 (200, status ok or no_match)
```

### Contract

| Parameter | Accepts | Notes |
|---|---|---|
| `reference` | `ARK-INC-00348`, `ark-inc-348`, `348` | required; normalised to the padded form |
| `simulate_failure` | `true`, `1`, `yes` | test affordance, the same as on the incident status API |

The same four answers as the incident status API, for the same reason: `ok` (200) with a
`notice`; `no_match` (200, "No quality notice or complaint with reference ... is on
record.", `notice: null`); `rejected` (400, one `errors` entry); `unavailable` (503). A
`no_match` is a fact about the store; a 503 means the lookup failed and nothing may be
inferred from it. A customer told that their complaint is not on record because a table did
not answer is the one thing this endpoint must never do, so a store that cannot be read, or
that has never been synced, is a 503 before the reference is looked up.

The notice, and nothing else:

| Field | What it is |
|---|---|
| `reference` | the incident id |
| `type` | `quality_notice`: the plant's incidents are read as quality notices to the customer; a complaint intake of its own is the post-course extension |
| `received_at` | the intake time |
| `customer_status` | the customer's word for the folded lifecycle status, table below |
| `stage` | `{number, of: 5, name}` |
| `next_step` | `{name, due_at, overdue}`, or `null` on a closed notice; the commitment counts from the moment the current stage was entered (the last recorded transition, or intake) |
| `last_update_at` | the last recorded transition, or intake |
| `closed_at` | the closing transition, or `null` |

| Lifecycle status | Customer status | Stage | Next step | Arkon's commitment |
|---|---|---|---|---|
| `new` | Received | 1, Received and logged | Acknowledgement by the Arkon quality team | the charter 7.1 window: P1 15 min, P2 1 h; P3 and P4 one business day (24 h) |
| `acknowledged` | Under investigation | 2, Investigation opened | Containment decision | 24 h |
| `in_containment` | Containment in place | 3, Containment measures active | Root cause and corrective action | 240 h |
| `resolved` | Corrective action implemented | 4, Corrective action implemented | Effectiveness check and closure | 120 h |
| `closed` | Closed | 5, Closed | none | - |
| `false_positive` | Closed, no defect confirmed | 5, Closed | none | - |

The vocabulary and the windows live in one file, `n8n/build/customer_projection.py`, read
by the generator, by the checker and by the desk's customer documents, for the reason
`lifecycle.py` is one file. The acknowledgement commitment is taken from
`lifecycle.ACK_WINDOW_MINUTES`, so the customer is promised exactly what the plant is
measured on; the other three windows are the desk's own, decided 2026-09-08, and the
charter measures none of them yet.

### Checking it

```bash
python n8n/build/check_customer_status_js.py
python -m pytest tests/test_customer_projection.py tests/test_generators.py
```

The checker runs the two Code nodes under node: the generator reproduces the tracked file;
empty reads reach the answer and failed reads answer 503; the parser accepts the three
reference forms, refuses the rest, and ignores an internal filter rather than honouring it;
and, over rows the store sync's own fold produced from logs written by hand, every lifecycle
status gets its words, its stage and its commitment date (a reopened containment counts
from the reopening). Two checks carry the boundary claim. The answer node's code must not
name an internal field at all; the check is a string search, and on its first run it
caught the word "evidence" in a comment, which is the class of edit it exists for. And
every served notice is searched for the internal values of its record (the assignee, the
escalation contact, the record id, the module, the priority, a transition note) and must
contain none. The pytest module pins the vocabulary to the lifecycle and the served field
list against the row columns: the one name both share is `closed_at`, and it means the same
date on both sides.

### Deploying it

No credentials, no static data, so a plain import, inside the quiet window after a plant
tick because the restart is not optional (see the status API section):

```bash
docker exec n8n n8n import:workflow --input=/data/arkon/_deploy/customer_status_api_v1.json
docker exec n8n n8n publish:workflow --id=arkonCustDesk01 && docker restart n8n
python n8n/customer_status_probe.py http://AK2101:5678/webhook/arkon-customer-status
```

**Deployed 2026-09-08, 07:09:56 to 07:10:17 UTC**, 41 s after plant tick 382, which had
been recorded (`ARK-INC-00421`) and synced (07:09:19) before the restart began: import,
publish, restart, healthz ok after 6 s, all nine Arkon workflows re-activated (read from the
container log), the webhook row present in `webhook_entity`. The probe passed 14 of 14
against `ARK-INC-00421`, cross-checking every served value against the incident status
API's record of it, and the four answers were timed from the laptop: 400 in 0.09 s, 503 in
0.12 s, `no_match` in 0.52 s, `ok` in 0.18 to 0.25 s.

### Known boundaries

- Read-only, one reference per call, and it stays that way. There is no list, no filter
  and no search: a caller who does not hold a reference gets nothing.
- Every incident is readable as a quality notice, and the ids are sequential, so anyone
  who can reach the endpoint can enumerate them. The projection bounds what a guess
  returns to the eight customer fields; who may see which reference is the identity and
  per-customer scoping gap the desk's brief names, the same gap the course's public URL
  has.
- The commitment dates for stages 2 to 4 are the desk's, not the charter's, and the plant
  is not measured against them.
- No authentication, like the status API: LAN and Tailscale only. The desk's public page
  is a separate decision (a tunnel on the chat path, Basic Auth on the page), and this
  endpoint is never on it: the agent calls it from inside the container network.
- `simulate_failure` is the same test affordance as on the status API, and a production
  deployment removes it or puts it behind an operator role.

## Customer desk knowledge base (the collection a customer may read)

Tenth workflow, `customer_desk_kb_v1.json`, id `arkonCustDeskKB1`, built and **deployed
2026-09-08** together with the desk below. The document store of the Customer Quality Desk:
the three customer documents of `docs/customer/` (`n8n/build/customer_documents.py` owns the
set and the reason each of the other five candidates stays out), chunked at 500 characters
with a 50 overlap, embedded with `models/gemini-embedding-001` on the Google Gemini node and
held in the Qdrant collection `arkon-customer-desk`, plus a retrieval endpoint over the same
collection through the same embedding node the desk's retriever tool will use, so the
in-store retrieval test measures the path the agent takes.

```text
POST /webhook/arkon-customer-desk-ingest      drop the collection, ingest the three documents, answer with what was offered
GET  /webhook/arkon-customer-desk-search?q=   the top-4 passages for a query: rank, source, score, text
```

Both LAN and Tailscale only; neither is on the Funnel. The texts are injected into the
workflow verbatim by the generator, so the tracked file is the record of what the collection
holds and `tests/test_generators.py` fails when a document changes without a rebuild;
`tests/test_customer_documents.py` pins the documents to `customer_projection.py` (every
customer word and every commitment window, rendered from the numbers) and to the deny list
(no roster name, no underscored internal field name, no module or dataset name, no value of
the superseded 2025 guide). The two collections of the platform are its two trust
boundaries: the operators' assistant reads `arkon-knowledge`, the desk reads this one, and
neither reaches the other's.

### Measured, 2026-09-08

`python n8n/customer_desk_kb_probe.py --rebuild --suite`, reading Qdrant point by point rather
than the ingest answer: ingest 200 in 3.6 s; the collection created by the insert at 3072
dimensions, Cosine; 57 points (guide 29, commitments 16, checklist 12); chunk length 55 to
500, median 382; every point with `content` and `metadata.source`; no roster name and no
superseded value in any chunk. The retrieval suite, five queries with the expected source
written in the probe before the run: five of five to the expected document in 0.54 to 0.63 s
at top scores 0.70 to 0.85, and the "which engineer is working on my notice" query lands on
the paragraph that says employee names are not shared, the only place the store speaks of
engineers at all.

### Three things worth keeping

- **The insert appends, so the ingest drops first.** n8n's Qdrant insert writes every chunk
  under a fresh point id (Langflow's component hashed the chunk and overwrote), so a second
  run without a drop is a doubled store, silently. The ingest path starts with an HTTP
  `DELETE` of the collection at `http://qdrant:6333` with `neverError`, and the 404 of a
  collection that does not exist yet is the normal first run.
- **`collectionConfig` is passed raw.** The node hands that `json`-typed option straight to
  LangChain's `fromDocuments` (read in the container's `VectorStoreQdrant.node.js`), and a
  `json` parameter arrives as a string, so setting it would send a string to Qdrant's
  create-collection call. It is left empty; the insert creates the collection from the
  embedding's own vector size, and the probe reads the result back.
- **The payload key is `content` here and `page_content` in `arkon-knowledge`.** The desk's
  retriever over this collection keeps n8n's default. The comparison slice sets
  `page_content` because its collection was written by Langflow; copying that setting here
  retrieves empty passages without an error.

### Deploying it

```bash
python n8n/build/build_customer_desk_kb_workflow.py
python -m pytest tests/test_customer_documents.py tests/test_generators.py
tar cf - -C n8n customer_desk_kb_v1.json | ssh ResSak@AK2101 'tar xf - -C /volume1/docker/arkon/_deploy'
# on the NAS, from ~/arkon-tmp
python3 deploy_plain_workflows.py customer_desk_kb_v1.json
# back on the laptop
python n8n/customer_desk_kb_probe.py --rebuild --suite
```

`n8n/build/deploy_plain_workflows.py` is this README's plain-import recipe as code: import
each file, publish it by the id it carries, one restart inside the quiet window after a
plant tick (the Steering Cell's counter lives in the running row, `deploy_steering_cell.py`
explains), healthz, then the activation lines and the webhook rows read back, and a refusal
to call it done if one is missing. It deployed both desk workflows on 2026-09-08 at
10:34:54, 50 s after tick 390: healthz after 4 s, eleven Arkon workflows re-activated, the
four webhook rows present.

## Customer Quality Desk (the agent, sprints 1 and 3)

Eleventh workflow, `customer_desk_v1.json`, id `arkonCustDesk02`, **deployed 2026-09-08** with
the knowledge base and **re-deployed the same day at sprint 3** with its three tools. The customer-facing agent of the MSIT course project 2A, built sprint by
sprint on the platform the plant runs on. The coursework (the memory policy, the validation
runs, the brief) lives outside this repository; the workflow, its prompt
(`n8n/build/customer_desk_prompt.py`, one version per sprint) and its generator
(`n8n/build/build_customer_desk_workflow.py`) are platform and live here, and the git
history keeps each sprint's shape.

Sprint 1 shape: a Chat Trigger (hosted page, `public`, no authentication until sprint 4 puts
Basic Auth in front of the public route), the AI Agent with the sprint 1 prompt (the role,
what this version can and cannot do, the boundaries, the three memory rules of remember,
discard and consent; no retrieval, no tools), the OpenRouter chat model
`google/gemini-3.1-flash-lite` at temperature 0.3, and Buffer Window Memory keyed by the
chat session id with a window of six.

```text
GET  /webhook/arkon-customer-desk/chat   the hosted chat page
POST /webhook/arkon-customer-desk/chat   {"action": "sendMessage", "sessionId": "...", "chatInput": "..."}  ->  {"output": "..."}
```

The Chat Trigger's URL is `/webhook/<webhookId>/chat`: its own webhook path is the constant
`chat` and the node's `webhookId` is the segment in front of it. `responseMode` is
`lastNode`, so the agent's `{output}` is the reply body, which is what
`n8n/customer_desk_chat.py --session <id> --turns-file <turns.json>` reads back when it
sends a scripted conversation and prints the transcript as returned.

The sprint 1 validation passed seven of seven on 2026-09-08 at 10:35, 0.9 to 3.0 s per turn:
name, company and reference recalled three turns later; the consent question verbatim
before a health-linked communication preference is kept, and the preference honoured
unprompted two turns on; an IBAN and a private number refused without being repeated back;
a second session blind to the first. The record with the expectations written first and
the transcript is the coursework's.

### Sprint 3: the three tools

Same trigger, agent, model and memory; three tools added and the prompt replaced with the
course's six elements in its order (role and context, retrieval scope, notice action
boundary, tool invocation guidance, fallback behaviour, tool failure fallback), Max
Iterations 6.

| Tool | Node | Called when |
|---|---|---|
| `arkon_customer_documents` | Qdrant vector store, `retrieve-as-tool`, collection `arkon-customer-desk`, Top K 4, `contentPayloadKey` `content` | Documented information without notice data |
| `Calculator` | `toolCalculator` | Arithmetic on numbers the customer supplied or a tool verified |
| `complaint_status_lookup` | `n8n-nodes-base.httpRequestTool` 4.4, `GET http://127.0.0.1:5678/webhook/arkon-customer-status`, one `$fromAI` parameter `reference`, `neverError` | Only when the customer explicitly asks for the status of their own notice AND supplies the reference |

**The tool name is the NODE name.** At typeVersion 1.3 the Qdrant node dropped its
`toolName` field and the HTTP request tool never had one, so n8n derives the name the model
sees from the node name (`nodeNameToToolName` in `n8n-workflow`: everything outside
`[a-zA-Z0-9_-]` becomes an underscore, truncated at 64). The three node names above are
therefore the three names quoted in the prompt, and `tests/test_customer_desk.py` pins them
to each other.

**Do not use `@n8n/n8n-nodes-langchain.toolHttpRequest` on 2.29.** It is `hidden: true` in
this build and carries no `execute` method, so the execution engine refuses it the moment
the agent calls it - `The node "@n8n/n8n-nodes-langchain.toolHttpRequest" has a "supplyData"
method but no "execute" method` in `docker logs n8n`, once per attempted call - and the
agent tells the customer the system is unreachable. The supported path is the base node used
as a tool: any node with `usableAsTool` is registered a second time as `<type>Tool` by
`convertNodeToAiTool`, which appends `Tool` to the name and adds the `toolDescription`
property, and the model fills parameters through `$fromAI('name', 'description', 'type')`.

**Address n8n's own webhook as `127.0.0.1`, never `localhost`.** Inside the container
`localhost` resolves to `::1` first and n8n listens on IPv4 only. `fetch` (undici) tries both
families and succeeds, so a probe says the URL is fine; the HTTP node's client takes the
first answer and gets ECONNREFUSED. Measured in the container on 2026-09-08: `::1:5678`
refused, `127.0.0.1:5678` and the dotted alias `n8n.arkon.internal:5678` both 200.

`neverError` is on so that all four answers of the status endpoint reach the model as data -
`ok`, `no_match`, `rejected` (a malformed reference) and `unavailable` (the 503) are four
different things to say to a customer, and an exception is only one. Element 6 of the prompt
maps the four `status` values to the four answers.

The sprint 3 gate passed eight of eight (nineteen asserted checks) on 2026-09-08 at 11:22,
0.9 to 2.9 s per turn, on two consecutive runs of the same build; the Sprint 2 readiness
gate was re-run on the same build and passed thirteen of thirteen. The runner is
`n8n/customer_desk_sprint3.py` (`--sprint2`, `--failure`), which reads the expectations that
depend on the plant from the status endpoint at the start of every run, because the notice
under test is live. The record with the expectations written first is the coursework's.

`customer_desk_failtest_v1.json` (id `arkonCustDesk03`, chat path
`/webhook/arkon-customer-desk-failtest/chat`) is the same desk with the status endpoint's
`simulate_failure` affordance switched on as a fixed field value, so the prompt's tool
failure fallback can be tested through the agent instead of asserted. The shipped desk
carries no failure switch, the tests assert both halves, and the fixture is deleted before
submission.

### Known boundaries

- Closed at sprint 3: the retriever over `arkon-customer-desk`, the calculator and the
  lookup through the customer status API are in. Sprint 4 adds the Guardrails node, the
  three security instructions, the confirmation step and the public route.
- Top K 4 is the course's value and a real limit: a question whose answer is spread over
  more than four chunks is answerable only in part. The store carries a summary chunk for
  the one question a customer asks most.
- The prompt governs behaviour, not persistence: a refused IBAN is not repeated back, but
  the raw message is in the memory node's history for that session. The production answer
  is a Guardrails node in `sanitize` mode in front of the agent.
- Execution data is kept for every conversation (`saveDataSuccessExecution: all`) so a
  validation run can be read back; a chat desk does not produce the volume the status API
  did.

## Escalation record (write path, guarded)

Third workflow, `escalation_record_v1.json`, built 2026-08-30, workflow id
`arkonEscalate01`. It records that a human approved the escalation of an existing
incident. It is the action the Langflow assistant's approval gate guards, and it
is the only write the assistant can perform.

```text
POST /webhook/arkon-escalation
  -> Validate the request               (400, one reason per bad parameter)
  -> Read /data/arkon/incidents.jsonl   (503 on an unreadable store)
  -> Incident exists?                   (404 if not; nothing is recorded)
  -> Append the escalation record       (200 with the new ARK-ESC id)
```

| Parameter | Required | Notes |
|---|---|---|
| `incident_id` | yes | `ARK-INC-00014`, or a plain number |
| `reason` | yes | 5 to 500 characters |
| `requested_by` | no | defaults to `arkon-quality-assistant` |
| `approved_by` | no | defaults to `human approval gate` |

Parameters are read from the JSON body **or the query string**, and that is not
a convenience. Langflow's API Request component, in tool mode, exposes only the
URL to the model: its `body` field is not tool-mode capable, and `curl_input` is
parsed at design time by `update_build_config` while `make_api_request` reads
`url_input`, `method`, `headers` and `body` from the component and never looks at
it. So an agent cannot compose a request body at all. Turning this endpoint into
a GET would also have solved it and was rejected, because a GET that writes an
audit record lies about what it does. The method stays POST, fixed on the canvas
where the model cannot change it.

The escalation record captures the incident's priority, status and summary at the
moment of escalation, so the audit entry still reads correctly after the incident
moves on. Escalation ids come from workflow static data, the same mechanism the
intake workflow uses, so the same publish-before-you-test rule applies. Ids
`ARK-ESC-00001` to `00004` were consumed by the contract test and by the
query-string check on 2026-08-30; the store was emptied afterwards, so the log
starts at `00005`.

### The simulate_failure affordance, and why it arrived late

`simulate_failure=1` (also `true`, `yes`) returns the 503 path without opening
the store and without consuming an escalation id. It is read after validation and
before anything else, so a malformed request still gets its 400: the parameter
buys a failure, not a way past the contract. Same parameter, same accepted values
and same response shape as the status API, on purpose - two failure switches with
two spellings would be a third thing to remember.

It was added on 2026-08-31, and the reason is worth keeping. The status API had
this affordance from the start, so its 503 branch was exercised in the routing
validation. **The escalation endpoint did not, so its 503 branch could only be
reached by moving the incident store aside on the NAS - and therefore nobody
reached it.** The agent prompt for that branch had been dictating the status
API's sentence, telling the operator that a *lookup* had failed on the one path
where a *write* silently does not happen. It survived because the path was
untestable, not because it was subtle. The untestable path is the one that rots.

```bash
python n8n/escalation_probe.py
```

Thirteen cases, and every one of them is a case that must not reach the store:
the three spellings of the simulated failure, validation beating it, the
malformed forms, id normalisation checked against an absent incident, and the
unknown-incident refusal. The suite asserts that no answer ever carries an
`escalation_id`, so it is safe to re-run. The success path is deliberately absent:
it appends a record and consumes an id, and a test that changes the thing it
measures is not worth keeping. That path belongs to a human at the approval gate,
which is also the only way it is reached in normal use.

### Re-importing this workflow can reset the escalation counter

`n8n import:workflow` rewrites the whole workflow row, and the escalation ids
live in that row's `staticData`. Import the tracked file as-is and the counter
goes back to zero, so the next escalation is `ARK-ESC-00001` against a store that
already contains one. Read the live value first and carry it into the document
being imported:

```bash
docker exec n8n n8n export:workflow --id=arkonEscalate01 --output=/tmp/exp.json
```

Take `staticData` from that export, put it on the patched workflow JSON, and
import the result. Do not put the counter in the tracked file: it is runtime
state, and a file that carries it would silently rewind the counter on every
future deploy. Verified on 2026-08-31: carried forward as
`{"global": {"nextEscalationId": 12}}`, and the next real escalation came out as
`ARK-ESC-00013`.

### Known boundaries of the escalation record

- **It notifies nobody.** `notification_channel` is always `none`. The Telegram
  card to the Quality Manager is the obvious next step and is deliberately not
  wired: a test run of an approval gate should not put messages in front of a
  real person.
- **It cannot verify the approval.** The endpoint records the `approved_by` value
  its caller sends. The gate is enforced on the Langflow canvas, not on the wire.
  In production the gate would hand the agent a signed, single-use token that this
  endpoint checks.
- **It does not change the incident.** Escalating is a record that somebody asked
  for help, not a lifecycle state. Moving the incident is the transition endpoint
  below, and the two are deliberately separate: an escalated incident is still
  `acknowledged` or `in_containment`, and collapsing them would lose that.

## Incident lifecycle (write path)

Fourth workflow, `incident_transition_v1.json`, built 2026-09-03, workflow id
`arkonTransit01`. It is the write path of charter 7.2, and it is the piece
everything else in Phase 3 and Phase 4 was waiting on.

**What was missing, stated plainly.** The Steering Cell wrote an incident once, at
`new`, and there was no way to write any later state. So no incident had ever been
acknowledged, contained, resolved or closed; the response-time KPI the charter
asks for could not exist, because a KPI needs two timestamps and only one was ever
recorded; the `status` filter on the read API was a filter over a constant; and
`overdue_incidents` counted every P1 and P2 in the store for ever, since nothing
could ever stop being unacknowledged. On 2026-09-03 all 29 incidents in the store
read `new`, which is what a lifecycle with no write path looks like from the
outside: not an error, just a number that never moves.

```text
POST /webhook/arkon-incident-transition
  -> Validate the request                 (400, one reason per bad parameter)
  -> Simulated failure requested?         (503, test affordance)
  -> Read /data/arkon/incidents.jsonl     (503 on an unreadable store)
  -> Read the transition log              (503 on an unreadable log)
  -> Incident exists?                     (404 if not; nothing is recorded)
  -> Does the lifecycle allow this move?  (409 if not; nothing is recorded)
  -> Append the transition                (200 with the new ARK-TRN id)
```

### It appends a log rather than rewriting the incident

This is the design decision worth defending, because the obvious alternative is to
open `incidents.jsonl`, find the line and change its `status` field.

Three reasons against it, in order of weight. The incident store is append-only
and both existing write paths keep it that way. A read-modify-write of the whole
file would race the intake workflow, which appends to the same file with no lock,
so a burst of events during a rewrite loses whichever side finishes second. And a
response-time KPI needs the history: an overwritten record keeps one timestamp and
the charter asks for the interval between two.

So the store keeps the incident as it was raised, `/data/arkon/incident_transitions.jsonl`
keeps what happened to it, and **the current status is a fold**: the last
transition recorded against the incident, or `new` if there is none. The fold also
produces the milestone timestamps and the response times. It lives in
`n8n/build/lifecycle.py` and runs in the transition endpoint, the escalation record
and, since 2026-09-07, the store sync (the status API reads the sync's rows).

The cost is honest and worth naming: every consumer now reads two files instead of
one, and a consumer that reads only the incident store sees `new` for ever. The
status API returns `raised_as` on every incident for exactly that reason, so a
reader who opens the JSONL and finds a different word knows the two are not in
conflict.

### The lifecycle, and what it refuses

```text
new ---> acknowledged ---> in_containment ---> resolved ---> closed
 |            |                  |                |
 +------------+------------------+----------------+---> false_positive
                                 ^                |
                                 +----------------+  (reopen: containment did not hold)
```

`closed` and `false_positive` are terminal. `new` is the intake state and can
never be re-entered, so `to_status=new` is refused with its own reason rather than
the generic list. `resolved -> in_containment` is the only backward edge and it is
why every KPI is computed from the **first** time a milestone is reached: an
incident that bounces twice still reports the resolution that first happened.

| Parameter | Required | Notes |
|---|---|---|
| `incident_id` | yes | `ARK-INC-00014`, or a plain number |
| `to_status` | yes | `acknowledged`, `in_containment`, `resolved`, `closed`, `false_positive` |
| `actor` | no | defaults to `human operator` |
| `note` | no | up to 500 characters |
| `simulate_failure` | no | `true`, `1`, `yes`; same affordance as the other two endpoints |

Parameters are read from the JSON body **or the query string**, for the same
reason the escalation endpoint accepts both: Langflow's API Request component can
hand a model the URL and nothing else. The method stays POST.

Five answers, deliberately distinct:

| Situation | HTTP | `status` |
|---|---|---|
| transition recorded | 200 | `transition_recorded` |
| request not understood | 400 | `rejected`, one `errors` entry per bad parameter |
| incident not in the store | 404 | `rejected` |
| the lifecycle does not allow the move from where the incident is | 409 | `rejected`, with `current_status` and `allowed_next` |
| a store unreadable, or failure simulated | 503 | `unavailable` |

**409 is the one that earns its own code.** The request is well formed and the
incident is real; it has simply moved on. A caller has to be able to tell "you
asked wrong" from "you are too late", and the answer carries `current_status` and
`allowed_next` so it can retry correctly rather than guess. This is the same
separation the status API draws between `no_match` and `unavailable`.

**An unreadable transition log is a 503 on all three endpoints, never an empty
log.** Read as empty it would report every incident as `new` with a 200, which is
a wrong status served confidently, and that is the one answer this endpoint set
exists to prevent. The practical consequence is a deployment step: the file has to
exist before the status API is imported, or a working endpoint goes down.

### The transition record

```json
{
  "transition_id": "ARK-TRN-00001",
  "recorded_at": "2026-09-03T19:46:11.291Z",
  "incident_id": "ARK-INC-00013",
  "incident_priority": "P1",
  "incident_created_at": "2026-08-30T12:01:16.000Z",
  "from_status": "new",
  "to_status": "acknowledged",
  "actor": "M. Brandt",
  "note": "picked up by the assigned planner",
  "minutes_since_created": 6225.4,
  "minutes_since_previous_transition": null,
  "acknowledge_window_minutes": 15,
  "acknowledged_within_window": false,
  "context_origin": "simulated"
}
```

The timestamps are the record of truth. The three derived numbers are computed at
write time so a consumer reading this file alone, a Tableau extract for instance,
has the KPI without performing the fold. `acknowledged_within_window` is filled
only on the transition it describes and is null on every other one, including on
P3 and P4 where charter 7.1 defines no window. `context_origin: simulated` marks
the actor, the same boundary the escalation record draws; the timestamps and the
state machine are real.

### What the status API gained

The read path folds the log and now answers things it could not before. Per
incident: the current `status`, `raised_as`, and a `lifecycle` object with the
transition count, the three milestone timestamps, the three response times and the
full history. Over the store: `incidents_by_status`, a `transitions` block, and
`response_times` with the median time to acknowledge, the median time to close,
and the within-window and late counts. The median rather than the mean, because
one incident acknowledged the next morning would otherwise move the number more
than every incident acknowledged on time.

`overdue_incidents` finally measures something. It always meant "still
unacknowledged past the charter 7.1 window"; with no acknowledgement path it
counted the whole store. It dropped from 19 to 17 the moment two incidents were
acknowledged.

### Testing it

```bash
python n8n/build/check_lifecycle_js.py        # the fold and the machine, offline
python n8n/incident_transition_probe.py       # the contract, against the deployment
```

The first asserts that the JS in the generated workflow JSON is the JS in
`lifecycle.py` character for character, then runs the fold under node against
cases written out by hand: the full path, the reopen, `false_positive` counting as
a closing outcome, out-of-order log lines, damaged lines, and four properties of
the machine including that every open state can still reach a closing outcome.
That last one is there because a state an incident can enter and never leave is
not something anybody would notice from the outside.

The second is the live contract suite, and **every case in it is a case that must
not reach the store**, the same discipline as `escalation_probe.py`. It finds its
own subject for the 409 cases rather than naming one: it asks the status API for
an incident that is still `new` and then requests `closed`, which the machine
refuses from there. That keeps the suite valid as the store fills up, and if the
store holds no `new` incident those two cases are skipped and say so.

17 of 17 passed on 2026-09-03 against the deployment, and the transition log was
still 0 lines afterwards.

### Driving one incident, for the demo

```bash
python n8n/drive_incident.py ARK-INC-00013                    # the full path
python n8n/drive_incident.py ARK-INC-00016 false_positive     # the other outcome
python n8n/drive_incident.py 21 --delay 45 --dry-run          # print, write nothing
```

`drive_incident.py` is the counterpart of `replay_events.py`: that script raises
incidents, this one moves them. It is not a test and it is deliberately not part
of the probe suite, because every step is a real write that cannot be undone and
an incident can only be driven to a terminal state once. To rehearse the demo
again, raise a fresh incident first.

**Use `--delay` for a demo.** Without it the four steps land inside one second and
every response time comes out equal, which is true and reads as broken. That
happened on the first run of `ARK-INC-00013`, whose four transitions are 0.2
seconds apart and whose three KPIs are therefore all 6225.4 minutes.

### Deploying it

No credentials, so it goes in from the command line. **Create the transition log
first**: the write node in append mode does not create its file (trap 3 above),
and the status API now returns 503 without it.

```bash
docker exec n8n touch /data/arkon/incident_transitions.jsonl
docker cp incident_transition_v1.json n8n:/tmp/w.json && docker exec n8n n8n import:workflow --input=/tmp/w.json && docker exec n8n n8n publish:workflow --id=arkonTransit01 && docker restart n8n
```

The status API and the escalation record changed with it and are re-imported the
same way. **The escalation workflow carries its counter in `staticData` and a
plain import rewinds it**, so read the live value first and carry it into the
document being imported, per the section above. It was carried forward as
`{"global": {"nextEscalationId": 13}}` on 2026-09-03 and verified after the
restart. The transition workflow has the same trap and no exemption from it: once
`ARK-TRN` ids exist, a re-import of the tracked file resets `nextTransitionId` to
zero.

Deployed and verified 2026-09-03 on n8n 2.29.9. Three workflows imported and
published, one restart, and afterwards: 17 of 17 transition cases, 24 of 24 status
cases and 13 of 13 escalation cases pass, and one incident was driven from `new`
to `closed`.

### Known boundaries of the lifecycle write path

- **It notifies nobody and nothing calls it automatically.** The acknowledge and
  close buttons charter 7.4 describes on the Telegram card still do not exist:
  they need a Telegram Trigger node for callback handling, and there is now
  something behind them for the first time. The unacknowledged-incident timer and
  the manager notification exist since 2026-09-06 ("Overdue escalation" below);
  they read this endpoint's effect through the status API and never call it.
- **It cannot verify who the actor is.** The endpoint records the `actor` value
  its caller sends, exactly as the escalation record does with `approved_by`. In
  production this endpoint would check a signed token.
- **No authentication**, on the LAN and Tailscale only, same as the rest.
- **The whole transition log is parsed on every call** of this endpoint and of the
  escalation record; the status API stopped doing so on 2026-09-07, when the
  queryable store arrived ("Incident store" above). Correct at demo scale; the
  same move is open for the two write paths.
- **The assistant cannot call it.** It is not on the Langflow canvas as a tool and
  that is deliberate for now: the canvas has been untouched since 2026-09-01 and
  the assistant's one action stays the guarded escalation. What did change is what
  it can *report*, because the status API it already reads now returns real
  statuses and response times.

## Overdue escalation (scheduled reader)

Sixth workflow, `overdue_escalation_v1.json`, built 2026-09-05, workflow id
`arkonOverdue01`, **deployed 2026-09-06**. It is the timer half of charter 7.4: a
P1 or P2 that is still `new` past its charter 7.1 window puts a card in front of
the Quality Manager. It is a scheduled reader rather than an endpoint: every 15
minutes it answers nobody and writes one file.

```text
Schedule, every 15 minutes
  -> GET /webhook/arkon-incident-status?status=new&priority=P1,P2&limit=50
                                                 (halt on an unavailable API)
  -> Read /data/arkon/incident_notifications.jsonl   (halt if unreadable)
  -> Select: overdue per the API, not yet in the log, oldest wait first, at most 3
  -> Telegram card to the alert group, one per incident
  -> Append one record per card, carrying Telegram's own message_id
```

Three decisions are worth reading before the generator,
`n8n/build/build_overdue_workflow.py`.

- **The overdue decision is not made here.** The status API already computes
  `overdue` from the windows in `lifecycle.py`, so the timer reads that flag. A
  fourth copy of the rule is what `lifecycle.py` exists to prevent, and a timer
  that disagreed with the API about what is overdue would be the worse kind of
  wrong: both numbers would look reasonable.
- **Dedup is the notification log, not workflow static data.** An import rewrites
  `staticData`, and both counters this project keeps there have had to be carried
  across a deploy by hand; a log that is read back cannot be rewound by a deploy,
  and it is also the evidence. So a re-import of this workflow is safe, and the
  deploy copy below carries no counter.
- **Three cards per run, longest wait first.** The alert group is a real chat and
  the store can hold a backlog of never-acknowledged incidents, so a run works
  through the backlog rather than emptying it in one burst; the first live run
  found 14 waiting and sent three, and the record says so (`candidates_overdue`,
  `selection_capped`). The API pages at 50 and ranks by recency, so a store with
  more than 50 open alerting incidents would hide the oldest, the very ones this
  workflow exists to surface; that cannot be fixed from this side, so
  `selection_truncated` is written on every record of a truncated run instead.

The record, one JSON line per card in `/data/arkon/incident_notifications.jsonl`:
the notification id (`ARK-NTF-*`, continuing from the highest in the log), the
incident with its priority, raise time and status, the minutes unacknowledged and
overdue against its window, the notified role and the escalation contact, the
chat id and **Telegram's own `message_id` and `date`**, the run time, the three
selection facts above, and `context_origin: simulated` for the people named.

### Deploying it

It carries a credential, and that is the one thing a plain import cannot bind:
the tracked file names `Arkon Telegram Bot`, and n8n binds by internal id. So the
deploy copy carries the id, read out of the live steering cell rather than
guessed, and differs from the tracked file in exactly that one key:

```bash
# on the NAS, once: the export the id is read from, and the log the append node cannot create
docker exec n8n n8n export:workflow --id=o0vXtlRWIs9yFrUJ --output=/data/arkon/_predeploy_<date>/steering_cell.json
docker exec n8n touch /data/arkon/incident_notifications.jsonl
# on the laptop: overdue_escalation_v1.deploy.json is the tracked file with
#   "telegramApi": {"id": "<id from the export>", "name": "Arkon Telegram Bot"}
# copied under /volume1/docker/arkon/_deploy/ (the bind mount, so docker cp is not needed), then:
docker exec n8n n8n import:workflow --input=/data/arkon/_deploy/overdue_escalation_v1.deploy.json
docker exec n8n n8n publish:workflow --id=arkonOverdue01
docker restart n8n
```

`docker` runs without `sudo` for the NAS user, measured 2026-09-06, which is why
this deploy was scripted end to end over SSH where the earlier ones were typed in
a terminal on the NAS. The restart is the same non-optional step as for every CLI
import. Proof of activation is the line `Activated workflow "Arkon Overdue
Escalation v1"` in `docker logs n8n`; proof of function is the first quarter-hour
tick. Rollback is `docker exec n8n n8n unpublish:workflow --id=arkonOverdue01`
and a restart; the CLI has no delete.

### The first two runs, and the defect the first one found

**21:45, execution 7800, `success`, three cards.** `ARK-NTF-00001` to `00003` for
`ARK-INC-00014`, `00011` and `00021`, the three longest waits among the 14 overdue
P2 of the replayed batches of 30 August to 3 September (the live plant's crew
acknowledges its own incidents, so none of the plant's were waiting). Telegram
assigned them message ids 83, 84 and 85 in "Arkon Quality Alerts". **The three
records say `telegram_message_id: null`.** The Telegram node returns the Bot API
envelope, `{"ok": true, "result": {"message_id": ..., "chat": ..., "date": ...}}`,
and the record builder read `message_id` off the envelope; `sent_at` fell back to
the node's own clock, which is why all three carry one identical timestamp. Found
by reading execution 7800's node outputs out of `execution_data` (the flatted
JSON n8n stores), not by reading the record, which looked plausible. Fixed in the
generator the same evening: the envelope is unwrapped, a reply that already is the
result object still reads, six cases on exactly that shape were added to
`check_overdue_js.py` (which had checked the selection and never the record), and
the workflow was re-imported and published at 21:49. The three records are left as
written: the log is append-only evidence, and execution 7800 holds the ids they
lack.

**22:00, execution 7810, `success`, three cards.** `ARK-NTF-00004` to `00006` for
`ARK-INC-00020`, `00019` and `00026`, message ids 87, 88 and 89, each record carrying Telegram's
`message_id` and `date` (`candidates_overdue` fell from 14 to 11, the dedup reading the first run's records back; `sent_at` is now Telegram's `date`). Delivery is attested twice: by Telegram's own reply in both executions, one `message_id` per card, and by Sergey reading all six cards off the group at 22:07 on 2026-09-06 (his message and screenshot: `ARK-NTF-00002` to `00006` at 21:45 and 22:00, with the live plant's intake card for `ARK-INC-00213` at 21:52 between the two runs, which is where message id 86 went).

### Known boundaries

- **It notifies the group, not a person.** The card names the escalation contact
  taken from the incident (simulated, and labelled so) and goes to the same alert
  group the intake cards use; a corporate deployment would route it to the
  manager's own channel.
- **It does not repeat itself.** One card per incident, ever: an incident still
  unacknowledged an hour after its card gets no second card. A reminder cadence is
  a decision about the process before it is a node.
- **It sees only the first 50**, the status API's page cap, recorded rather than
  fixed, as above.
- **Its log and the intake ledger are two notification sources**, not one log
  (`live_plant/README.md`). Since 2026-09-06 the intake log of charter 7.6 records
  Telegram's `message_id` for every intake card too, so the evidence exists in two
  files. Folding the intake cards into this log is NOT the one-node change it looks
  like: the selection above treats every record carrying an `incident_id` as an
  incident already notified, so an intake-card record here would silence the
  overdue card for every alerted incident. Key the selection on its own `trigger`
  first.
- **The charter and the SOP describe the timer since 2026-09-06** (charter 7.4's
  deployment paragraph, SOP section 5 and step 6), edited together with the daily
  digest's arrival and followed by one rebuild of the assistant's knowledge store:
  245 to 247 chunks across the evening's two rebuilds (the second after the 7.6
  edit), every untouched document back at identical counts, the retired sentences
  returning no chunk (`langflow/README.md`).

## Daily digest (scheduled reader)

Seventh workflow, `daily_digest_v1.json`, built and **deployed 2026-09-06**,
workflow id `arkonDigest001`. It is the digest half of charter 7.4: once a day,
at 07:05 plant time, one card to the alert group with what is open, what is
overdue, how fast the cell has been responding, and the P3 queue that step 4 of
`docs/Incident_Process.md` promises to the daily review. A scheduled reader like
the timer: it answers nobody and writes one file.

```text
Schedule, daily at 07:05 Europe/Berlin (pinned in the workflow settings)
  -> GET /webhook/arkon-incident-status?status=new&limit=500       (halt on an unavailable API)
  -> the same for status=acknowledged and status=in_containment
  -> Read /data/arkon/incident_notifications.jsonl                  (halt if unreadable)
  -> Compose: counts per state and priority, the API's overdue count and medians,
     the overdue list and the P3 queue oldest first, capped rows, one item always
  -> Telegram card to the alert group
  -> Append one record, carrying Telegram's own message_id
```

Four decisions, and the generator `n8n/build/build_digest_workflow.py` carries
them in its header.

- **Three reads, one per open lifecycle state, rather than one read of the whole
  store.** `status` takes a single value, and an unfiltered read is ranked by
  recency and capped at 500, so on a store the live plant grows by about 144
  incidents a day it would start dropping the oldest incidents within days, the
  very P3s the queue exists to surface. A state is bounded by how fast the crew
  works it, every incident is in exactly one, and `tableau/build_extracts.py`
  already sweeps the store the same way. A page that truncates is recorded on
  the digest (`pages_truncated`) and named on the card, not fixed here.
- **Nothing is decided here that the API already decides.** `overdue` is the
  API's flag and the response-time medians are its summary; the digest counts,
  sorts and formats. Per state the count is the page's `match_count`, which is
  right even when the page is short; the split by priority and the two lists
  come from the returned incidents.
- **One log for every notification sent.** The record goes into
  `/data/arkon/incident_notifications.jsonl` beside the timer's, under
  `trigger: daily_digest` and with no incident id, so `docs/Incident_Process.md`
  has one place to point at for who was told what, when. The two writers cannot
  confuse each other: the timer's dedup is keyed on `incident_id`, which a digest
  record does not carry, and both take the next `ARK-NTF` number from the
  highest in the log, so the sequence is shared; and they never write in the same
  minute, the timer on the quarter hour and the digest at five past.
  `n8n/build/check_digest_js.py` runs the timer's own selection node against a
  log holding a digest record to hold that.
- **07:05 Europe/Berlin is pinned in the workflow settings**, because the
  container runs in UTC and n8n's default timezone with `GENERIC_TIMEZONE` unset
  is `America/New_York` (read out of `@n8n/config` in the running image): an
  unpinned 07:05 would have fired at 13:05 plant time. The Schedule Trigger reads
  `workflow.settings.timezone`, and the trigger item of a run prints the timezone
  it resolved, which is how the pin was verified.

The card: the open count with its priority split and its state split, the
overdue count with the longest waits (at most five rows), the response-time line
from the API's summary, the P3 queue with its oldest rows (at most ten) and "and
N more", a note if a page truncated, and the digest's own `ARK-NTF` id. Rows are
shed, overdue first, until the text is under Telegram's 4,096-character cap; the
counts never are. The record: the digest id, `trigger: daily_digest`, the API's
`as_of`, open per state and per priority beside the summary's own open count,
the overdue count and split, the response times, the queue size and how many rows
were listed, `pages_truncated`, and Telegram's `message_id` and `date`.

### Deploying it

Same recipe as the timer: the credential bound by id in a deploy copy under
`/volume1/docker/arkon/_deploy/`, `import:workflow`, `publish:workflow
--id=arkonDigest001`, `docker restart n8n`; the log already exists. Rollback is
`unpublish:workflow --id=arkonDigest001` and a restart. A manual run for a check
is the editor's "Execute workflow" button (recorded as `mode = manual`, a real
card); the CLI's `n8n execute` cannot start a schedule-triggered workflow, see
the first-run note below.

### The first run

**First run 2026-09-06 23:13, manual, execution 7887, `success`, one card.** Sergey
pressed "Execute workflow" in the editor, because the CLI cannot start it:
`n8n execute --id=arkonDigest001` refuses with "Missing node to start execution ...
contains an Execute Workflow Trigger node" (in n8n 2.x that command starts only from
an Execute Workflow Trigger, never from a schedule), and beside the live instance it
first needs its own task-broker port (`-e N8N_RUNNERS_BROKER_PORT=5680`), or it dies
on 5679 being in use; both measured that evening. The record is `ARK-NTF-00015`,
`trigger: daily_digest`, `telegram_message_id: 102`, `sent_at` Telegram's own
`2026-09-06T21:13:20Z`, `as_of` the API's `21:13:20.021Z`: open 50 (P1 0, P2 16,
P3 34; new 48, acknowledged 1, in containment 1), overdue 14 (all P2, five listed),
141 acknowledged at a median of 50.6 minutes (58 within the window, 9 late), 159
closed at 162.1, a P3 queue of 33 with ten listed, no page truncated. The card's
header read `2026-09-06 23:13 (Europe/Berlin)`, the timezone pin verified on a real
run. Read back from `execution_entity` and the log; the card itself was read by
Sergey off the group at 23:13, which is the delivery reading.

**First scheduled run 2026-09-07 07:05, execution 8333, `mode = trigger`, `success`, one
card.** The Schedule Trigger fired at `05:05:00.032` UTC in `execution_entity`, which is
07:05:00 Europe/Berlin to the second, so the timezone pin held on the tick itself and not
only on the manual run; the whole run took 1.3 s. The record is `ARK-NTF-00018`,
`telegram_message_id: 122`, `sent_at` Telegram's `2026-09-07T05:05:01Z`, `as_of` the API's
`05:05:00.432Z`: open 55 (P1 0, P2 17, P3 38; new 49, acknowledged 4, in containment 2),
overdue 14 (all P2, five listed), 182 acknowledged at a median of 64.9 minutes (71 within
the window, 12 late), 201 closed at 183.4, a P3 queue of 35 with ten listed, no page
truncated, no unreadable log line. The shared `ARK-NTF` sequence held across the two
writers overnight: the timer took `00016` at 00:45 and `00017` at 02:30 for two live-plant
P2s that sat unacknowledged past the hour, the digest took `00018`, and the timer's 47
quarter-hour runs since its deployment are all `success` with no gap. Read back from
`execution_entity` and the log over SSH at 09:16 on 2026-09-07; the card itself was not
read off the group by an agent.

### Known boundaries

- **It reports the store as the API reports it**, all incidents to date: the
  response-time medians are cumulative rather than yesterday's, because the API
  has no time filter and a digest computing its own window from `created_at`
  would be one more copy of a rule.
- **It sees only the first 500 per state.** Recorded on the digest and named on
  the card rather than fixed, as with the timer.
- **One card, one group, one fixed hour.** The hour is a constant in the
  generator; a second recipient or a per-role digest is a routing decision
  before it is a node.
- **Its log is still one of two notification sources**, with the live plant's
  ledger for the intake cards (`live_plant/README.md`).

## The live plant: the demo engine, a mini-project of its own

`live_plant/` (built 2026-09-05) raises one real-model incident every ten minutes
or so across all seven modules and runs a simulated crew that moves them through
the transition endpoint, so this Steering Cell, the Telegram group, the cockpit
and the executive view can be watched moving rather than described. It is not an
n8n workflow and deliberately so: it is a Python service beside the cockpit that
calls the three endpoints above like any other client, and what n8n shows of it
is its executions. Design, ledger contract, reset, deployment and the first run
with its confirmed cards are in `live_plant/README.md`; the offline suite is
`live_plant/check_plant.py`.

What it asks of this layer: nothing new. Every event it sends passes the section
6 contract, carries the `arkon-2026-9xxxxx` id series and an `emitter` label in
`operational_context`, and is answered by the same four intake outcomes as a
replayed batch. The one thing worth knowing here is that its ledger is the second
notification source on the platform, beside `/data/arkon/incident_notifications.jsonl`,
which the overdue timer and the daily digest write since 2026-09-06, and the two are
not one log yet; since the same evening the intake log of charter 7.6 carries Telegram's
message id for every intake card as well ("Intake outcomes" above).

## Comparison slice (evaluation artifact, not Arkon infrastructure)

`comparison_slice_v1.json`, workflow id `arkonSlice001`,
`POST /webhook/arkon-slice`. Twelve nodes: a webhook, a Text Classifier that
routes by meaning, a Qdrant retrieval over `arkon-knowledge`, one HTTP call to
the incident status API, and three response nodes.

**It exists for one reason and it is not an Arkon feature.** Choosing a visual
agent platform means defending the choice, and a defence read off vendor pages is
worth nothing. This is the same three capabilities as the Langflow assistant,
built once on n8n, so the comparison is first-hand. It answers from the same collection and calls the
same API, which is what makes it a comparison rather than a second demo. It has
no memory, no approval gate, no sub-flow and no model-composed tool call, and it
is deliberately not grown.

Three things it established that are worth keeping whatever happens to the
slice:

- **n8n has a one-node semantic router.** `Text Classifier` takes a language
  model as a sub-node, N named categories with descriptions, and creates one
  output branch per category, plus an optional `Other` branch and a multi-class
  switch. The published platform comparison this slice was built to test says n8n
  has no equivalent of Flowise's Condition Agent; on 2.29.9 that is not true.
- **A collection written by Langflow is readable from n8n.** The store was
  embedded with `google/gemini-embedding-001` through OpenRouter and is queried
  here with the stock Google Gemini embeddings node calling the same model
  directly. Retrieval returns the right passages. The two routes to one model
  land in the same vector space.
- **The content payload key is not the default.** Langflow's Qdrant component
  stores chunk text under `page_content`; n8n's node defaults to `content` and
  would retrieve empty passages **without failing**. It is set explicitly in the
  node's options.

### Rebuilding and deploying it

```bash
python n8n/build/build_comparison_slice.py
```

Then, on the NAS: `n8n import:workflow --input=<file>`,
`n8n publish:workflow --id=arkonSlice001`, and **restart the container** - the
running process holds its active workflows in memory, so a CLI import does not
take effect without one. It needs a `qdrantApi` credential named
`Arkon Qdrant (local)` pointing at `http://qdrant:6333`; it was created with
`n8n import:credentials`, which writes an encrypted credential with no UI step.

### What was measured

| Check | Result |
|---|---|
| Router, 4 questions x 3 repeats | 12 of 12 to the intended branch |
| Retrieval on a Langflow-built collection | 4 passages, correct answer on P1 and its 15-minute window |
| Underspecified question | `Other` branch, 3 of 3 |
| Live lookup | 200, 6 incidents, 3 P1 and 3 P2, matching the store |
