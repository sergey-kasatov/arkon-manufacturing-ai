# n8n Quality Steering Cell

Operational layer of the Arkon platform: one workflow raises incidents and
alerts, one moves them along their lifecycle, one answers questions about them
and one records an approved escalation. Process owner:
`docs/Project_Charter.md` sections 7 and 8. All of them run on a self-hosted n8n
instance, pinned to `n8nio/n8n:2.29.9`.

| Workflow | Direction | Endpoint | Deployed |
|---|---|---|---|
| `quality_steering_cell_v1.json` | write | `POST /webhook/arkon-event` | 2026-08-30, alert body fixed 2026-09-02 |
| `incident_transition_v1.json` | write | `POST /webhook/arkon-incident-transition` | 2026-09-03 |
| `incident_status_api_v1.json` | read | `GET /webhook/arkon-incident-status` | 2026-08-30, folds transitions since 2026-09-03 |
| `escalation_record_v1.json` | write | `POST /webhook/arkon-escalation` | 2026-08-30, folds transitions since 2026-09-03 |
| `comparison_slice_v1.json` | read | `POST /webhook/arkon-slice` | 2026-08-30 |

**Three of the four share one piece of code.** The incident line is written once,
at `new`, and never rewritten, so the current status of an incident is the fold of
the transition log onto that line. That fold lives in `n8n/build/lifecycle.py` and
is injected verbatim into the three workflows that report a status; a state
machine copied into three generated JS bodies is a state machine that drifts.
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
existing workflow instead of creating another copy. Three of them read like
names. The fourth does not, and the reason is worth keeping:

| File | id |
|---|---|
| `incident_status_api_v1.json` | `arkonStatusApi1` |
| `escalation_record_v1.json` | `arkonEscalate01` |
| `comparison_slice_v1.json` | `arkonSlice001` |
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

- Acknowledge and close buttons on the alert card and the escalation timer are
  the next iteration: they need a Telegram Trigger node for callback handling and
  a Wait-based escalation branch (charter 7.4). **There is now something behind
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

## Incident status API (read path)

Second workflow, `incident_status_api_v1.json`, built 2026-08-30. It answers
questions about incidents that already exist, so an assistant can report live
status instead of guessing it. It is the missing half of the last open MVP
criterion of charter section 10: this endpoint makes incident state available,
and the assistant that consumes it becomes the operational interface.

**Status: deployed and verified 2026-08-30** on n8n 2.29.9, workflow id
`arkonStatusApi1`. Twenty-four contract cases pass, plus the two the probe
cannot cover by itself: an unreadable store answers 503, and the endpoint is
reachable from the agent container by name.

```text
GET /webhook/arkon-incident-status
  -> Parse and validate the query        (400, one reason per bad parameter)
  -> Simulated failure requested?        (503, test affordance)
  -> Read /data/arkon/incidents.jsonl    (503 on an unreadable store)
  -> Filter, rank, project               (200, status ok or no_match)
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
| `limit` | 1 to 50, default 5 | bounds the returned page, not `match_count` |
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
restart, and is the route to use on a fresh instance.

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
- **Two stores are now parsed on every call**, incidents and the transition log,
  and the fold runs over both. Correct at demo scale and wrong at plant scale; the
  fix is the same move to a queryable store, not a smarter parser.
- **A status it reports is a fold, not a field.** Reading `incidents.jsonl`
  directly gives `new` for every incident, for ever. `raised_as` is returned on
  every record so the two cannot be mistaken for a contradiction.
- No authentication. The endpoint sits on the LAN and the Tailscale network
  only. Anything beyond the demo needs at least a header credential, and that is
  a stated item in the readiness account.

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
`n8n/build/lifecycle.py` and runs in all three workflows that report a status.

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
  the manager notification are the same iteration.
- **It cannot verify who the actor is.** The endpoint records the `actor` value
  its caller sends, exactly as the escalation record does with `approved_by`. In
  production this endpoint would check a signed token.
- **No authentication**, on the LAN and Tailscale only, same as the rest.
- **The whole transition log is parsed on every call**, on all three endpoints.
  Correct at demo scale and wrong at plant scale; the fix is the move to a
  queryable store, not a smarter parser.
- **The assistant cannot call it.** It is not on the Langflow canvas as a tool and
  that is deliberate for now: the canvas has been untouched since 2026-09-01 and
  the assistant's one action stays the guarded escalation. What did change is what
  it can *report*, because the status API it already reads now returns real
  statuses and response times.

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
notification source on the platform, beside `/data/arkon/incident_notifications.jsonl`
once the overdue timer is deployed, and the two are not one log yet.

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
