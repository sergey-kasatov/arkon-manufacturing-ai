# Arkon Quality Assistant (Langflow)

Conversational front end for the Quality Steering Cell. It answers the questions
an on-shift operator actually asks: how the quality rules work, what an incident
is doing right now, and who owns an action the assistant itself must not take.

Process owner: `docs/Project_Charter.md` sections 7 and 8, and
`docs/Steering_Cell_SOP.md`. Runs on a self-hosted Langflow instance, pinned to
`langflowai/langflow:1.11.5`.

The prompts the canvas carries live in `langflow/prompts/` as named `### BLOCK:`
sections, and `build/sync_prompts.py` writes them into the flow, so the two
cannot drift.

**Status: deployed 2026-08-30**, endpoint `arkon-quality-assistant`. Five build
iterations complete and validated: 19 nodes, six routes, a document store the procedure
specialist answers from and names its source, a live lookup, a human approval
gate over the one write, and a shift-briefing sub-flow.

## Flow

```text
Chat Input
   |
Intent Router  (Smart Router, LLM categorisation)
   |-- Quality procedure  -> Procedure Specialist  -> Chat Output
   |                            ^ Qdrant (tool mode) -> arkon-knowledge
   |-- Incident status    -> Incident Specialist   -> Chat Output
   |                            ^ API Request (tool mode) -> incident status API
   |-- Shift briefing     -> Run Flow -> Arkon_Shift_Briefing -> Chat Output
   |-- Escalation request -> Human Input (Approve / Reject)
   |                            |-- Approve -> Escalation Specialist -> Chat Output
   |                            |                 ^ API Request -> escalation record API
   |                            `-- Reject  -> Escalation Declined   -> Chat Output
   |-- Unclear request    -------------------------> Chat Output
   `-- Out of scope       -------------------------> Chat Output
```

The last two branches carry a fixed Route Message on the router, so each reaches
its output with no agent in between and no second model call.

They are two branches rather than one because the operator is owed the right
reason. Out of scope means the question is about something other than the Arkon
quality operating model. Unclear request means it is Arkon work with a piece
missing: a pronoun with no antecedent, a follow-up whose subject was never named,
a request naming no incident, unit or topic. Answering the second as the first
tells an operator the assistant does not handle their subject when the truth is
that it could not tell which subject was meant, and a wrong reason trains people
to stop asking.

The shift briefing branch has the same shape for a different reason. Its
sub-flow produces a fixed four-block format read at speed at shift change, and
reaching it as a tool of the incident specialist meant the format landed inside
an agent whose job is to answer in its own words: the operator got the briefing
twice, and the paraphrase relabelled an incident's age as an overdue figure. A
component whose value is its exact output must not be reached through something
that rewords.

The approval gate is the only thing standing between a request and the single
write the assistant can perform. On the canvas nothing reaches
`POST /webhook/arkon-escalation` unless a human picked Approve, and an approval
is not an authorisation to do something this assistant cannot do: an approved
"acknowledge this incident" is still refused. **The canvas is not the running
system, and on 2026-09-11 the two were measured disagreeing: in ten trials the
Approve branch ran after a Reject twice.** No line was written in any of them,
and the whole measurement, with what it does and does not rule out, is under
Known boundaries below. Until 2026-09-03 the reason was
that the system had no write path for it. It has one now
(`POST /webhook/arkon-incident-transition`), and the refusal stands on a
different footing: the assistant has no connection to that endpoint, and the
operator makes the transition.

**On 2026-09-05 that refusal was put to Sergey as a decision rather than left as
a gap, and it was kept.** The argument that decided it is a measurement one. An
acknowledgement is the claim that a named person has seen an incident and taken
it, and the response-time KPI this platform puts in red is computed from that
timestamp; an assistant that acknowledges turns the plant's median response time
into a measurement of the assistant, and the number goes on looking reasonable
after it stops meaning anything. The quality-management reading agrees: a
nonconformance disposition has a human owner. The build cost is the third
reason and the smallest: a second gated write is a canvas change on a canvas
that already cannot be run through the v1 API.

**What was built instead is the handover.** Both reading specialists now end an
answer about a named, still-open incident with the link that opens that incident
on the cockpit's Steering Cell page, and the incident specialist adds a drafted
note for the transition form. The operator arrives with the form filled and puts
their own name on it: the agent prepares the decision, the person signs it.

Two things about the drafted note are worth keeping, because the first attempt
got one of them wrong. **The note must be built only from the incident record in
front of the model** - its summary, evidence and recommended action - and the
first deployed version was not constrained that way: asked about a NHTSA
complaint-rate incident it drafted "cross-reference with vehicle report
telemetry", and that module reads public complaint narratives and has no
telemetry of any kind. A fabricated action pasted into the permanent record of a
nonconformance, over an operator's own name, is worse than no handover at all,
so the prompt now forbids naming any system, measurement, data source or action
the record does not mention, and says that a shortened recommended action is a
good note. **And a closed or false-positive incident gets no link**, because it
has nowhere to move; verified by asking about `ARK-INC-00056`, which came back
with the status and no link.

**A canvas with a Human Input node cannot be run through `/api/v1/run` at all**,
including on branches that never reach the gate. Use
`POST /api/v2/workflows` with `mode: background`, watch
`/api/v2/workflows/pending?flow_id=...` for the approval request, and resume with
`POST /api/v2/workflows/{job_id}/resume`. That breaks every existing v1 caller
the moment the gate is added, which is worth knowing before adding one.

The incident specialist reaches the n8n incident status API at
`http://n8n.arkon.internal:5678/webhook/arkon-incident-status` and reports only
what that API returns. The four answers the API distinguishes stay distinct all
the way to the operator: incidents found, nothing matched, bad request, lookup
failed. An empty result and a failed lookup are different facts, and an assistant
that conflates them will invent a status for one of them.

## The shift briefing sub-flow

Rebuilt on 2026-09-07 (Sprint 6) so that the two course components the first
version met in substance but not in shape are on the canvas: a retry with a
visible fallback after two retries, and one model call per record.

```text
Chat Input -> Status API URL -> Retry plan (3 rows) -> Loop: Status attempts
                    |                                      |-- body: Attempt URL -> Attempt counter -> Incident Status API -> Answer gate -> (back)
                    |                                      `-- Done -> Resolve attempts
                    |                                                      |-- payload -> Overdue list -> Loop: Per incident
                    |                                                      |                                 |-- body: Incident to text -> Per-incident reading -> (back)
                    |                                                      |                                 `-- Done -> Overdue notes
                    `-- request ----------------------------------------> Briefing input <- payload, note, notes
                                                                                |
                                                                          Briefing Note (the NOTE sentence only)
                                                                                |
                                                     payload ---------> Briefing assemble -> Chat Output
```

The briefing is where the retry belongs: it is the unattended path, run at shift
change by a scheduler with nobody watching, so a transient failure there has no
operator to ask again. The incident branch on the main canvas answers a person who
can retype the question, which is why it reports instead of retrying.

The four-block output contract did not change. The per-incident readings feed
the NOTE block only, which is defined as the sentence naming what the counts do
not show and used to be written from the counts themselves. OPEN, OVERDUE and
WATCH keep their fields; the OPEN numbers are now counted in code rather than by
the model, after two runs of the same prompt read the store summary two ways.

**Since the evening of 2026-09-07 the model writes only the NOTE sentence, and a
component renders the other three blocks after it.** DEFECT-9 measured that the
briefing agent re-orders the OVERDUE and WATCH lines a component had already
sorted, intermittently and in both directions (four runs one way, three the
other, no change between them), and that a worked example in the prompt does not
move it. The model is the last thing between a correct list and the operator, and
it rewords by nature, so the lines whose value is their exact content no longer
pass through it: `components/arkon_briefing_assemble.py` renders OPEN, OVERDUE
and WATCH from the resolved status body (oldest first by age, ties by id; fewest
remaining minutes first for WATCH; "none" for a missing unit or assignee), takes
the one sentence out of the agent's answer, and appends the closing line. The
agent runs on `briefing_v3` (NOTE only); `briefing_v2` stays in the prompt file as
the prose contract the component implements. `build/check_briefing_blocks.py`
proves it: every run bracketed by two status API reads, the three blocks computed
a second time from the API body and compared line by line and in order.

**What it costs.** Every briefing issues three status calls, not one, and one
model call per overdue incident on top of the briefing's own. Fourteen overdue
incidents today: about sixteen calls and thirty seconds where there was one call
and four seconds. The status call is an idempotent read on the same Docker
network; the escalation record API is a write and is retried nowhere.

**Why both mechanisms are Loops, measured rather than chosen.** Six probe flows,
built by the same helpers and deployed through the same path as the real ones,
run on 2026-09-07 and deleted afterwards:

| Shape | Result on Langflow 1.11.5 |
|---|---|
| A Loop body (rows -> Loop -> Parser -> Agent -> feedback edge -> Done) | Runs, once per row, and aggregates |
| A graph cycle, five ways: custom and first-class components, with and without a chat input root, v1 and v2 run APIs | Does not run: `completed`, no error, zero vertices built, about 0.3 s |
| Both outputs of one If-Else into one input | The stopped side's empty Message wins the merge |
| A node downstream of a stopped branch, merged with a live one | Stays out; the live value arrives |
| Three conditional attempts, each behind an If-Else, converging on one resolve node | Does not run: the merge node is excluded with the stopped chains |
| A Loop feeding back the end vertex's second output | The aggregate carries the first declared output whatever the edge names |

So the four-node Flowise retry the course prescribes (Loop, Custom Function
counter, two Condition nodes, fallback) cannot be reproduced here; the counter
is kept on the retry path, and the two Condition nodes have no place that is not
decoration. Two more facts from the same day: a chat input feeding two nodes is
refused with "Only one chat input is allowed in the graph", and the v2 API
reports a graph whose sort raised as `completed` with empty outputs, so the
container log is the only place a structural failure is visible. The feedback
edge's shape is in `lfbuild.loop_back_edge()`; its target handle is shaped like a
source handle, copied from Langflow's own `Research Translation Loop` starter.

**Every `Output` of a two-output component must declare `group_outputs=True`, or the
UI deletes the second output's edges the next time the flow is saved from the
canvas.** Without it the frontend renders one output handle with a dropdown
(`selected_output`, set to the first output), and its edge cleaner removes any edge
whose source handle is not rendered. Measured 2026-09-07: the deployed sub-flow was
opened in the UI at 16:03 and came back with 19 of its 22 edges, the three missing
ones being exactly the `request`, `passthrough` and `note` edges of `ArkonStatusUrl`,
`ArkonRetryCounter` and `ArkonStatusResolve`, while every API-driven run that
afternoon had used all 22. Loop and Human Input ship with `group_outputs` set, which
is why their `done` and `Reject` edges survived the same save. Fixed the same day in
the four two-output components, redeployed, and proven by a UI save on a copy with
all 22 edges intact.

Evidence and the four runs: `020 Projects/AI_Agents_2B_Meridian/build/sprint6_validation.md`
in the vault (coursework stays out of this repository by decision).

## Files

| File | Purpose |
|---|---|
| `arkon_quality_assistant.json` | The main canvas, importable into Langflow |
| `arkon_shift_briefing.json` | The shift handover sub-flow, called through Run Flow and runnable on its own endpoint. Rebuilt 2026-09-07 with a retry loop on the status lookup and a per-incident reading loop; see the section above |
| `arkon_knowledge_ingest.json` | The ingestion flow: the Arkon documents into the Qdrant collection `arkon-knowledge`, one lane per document |
| `components/openrouter_embeddings.py` | A custom embedding component, because nothing Langflow ships can reach OpenRouter embeddings |
| `components/arkon_status_url.py` | Holds the status endpoint once for every attempt, and is the chat input's only consumer (a chat input feeding two nodes is refused by the sorter) |
| `components/arkon_retry_plan.py` | One row per planned attempt, for the retry loop to iterate; states the cost of an unconditional retry and why it is acceptable for this read and for no write |
| `components/arkon_retry_counter.py` | Counts attempts in flow state, on the retry path rather than beside it; reads the counter from the thing that counts, which is the point the shipped course canvases miss |
| `components/arkon_status_gate.py` | Classifies an answer as ok, outage or unreachable; payload declared first because a Loop aggregates the end vertex's first output |
| `components/arkon_status_resolve.py` | Takes the first ok answer out of the loop's attempts, or reports how many attempts said nothing |
| `components/arkon_overdue_list.py` | The overdue incidents as rows, most overdue first, for the reading loop |
| `components/arkon_overdue_notes.py` | Pairs each reading with its incident id by position and renders them as NOTE-block input |
| `components/arkon_briefing_input.py` | Assembles what the briefing agent reads; counts the OPEN line in code so the model does not |
| `build/build_briefing_v2_flow.py` | Builds and deploys the sub-flow; `--dead-url` deploys the LS10 failure-path copy under a probe name |
| `build/build_deck_canvases.py` | Generates the temporary `ZZ_Deck_*` canvases the Course 2B deck is screenshotted from: one frame per route, the whole canvas with a coloured note behind each route, the sub-flow; `--delete` removes them. The deployed canvases are never edited for a picture |

## How the flow JSON is generated

The canvas is not hand-edited. A Langflow flow is a ReactFlow graph whose edge
handles are JSON strings with every double quote replaced by U+0153, and getting
that wrong produces an edge that is present in the file but does not render or
execute. `build/lfbuild.py` owns that encoding; everything else builds on it.

The scripts run in order, each taking the previous one's output as its input,
which is how "one canvas refined step by step" stays reproducible rather than
being a claim:

```bash
python langflow/build/fetch_specs.py           # component templates from the running instance
python langflow/build/build_arkon_flow.py      # first canvas, seed via ARKON_SEED_FLOW
python langflow/build/build_routing_flow.py    # adds routing and the live lookup
python langflow/build/build_approval_gate_flow.py <briefing-flow-id>
python langflow/build/build_ingest_flow.py --deploy   # the document store, uploads and ingests
python langflow/build/build_retrieval.py       # the store as the procedure specialist's tool
python langflow/build/build_briefing_branch_flow.py <briefing-flow-id>   # the briefing gets its own branch
python langflow/build/build_unclear_route_flow.py    # the sixth route, for a message it cannot place
python langflow/build/layout_flow.py           # positions, run last
```

`fetch_specs.py` comes first because every other script instantiates nodes from
the templates the running Langflow reports, and those templates are not in the
repository. It fetches them over ssh through `lf_api.py` on the NAS, so no
Langflow credential is ever needed on the workstation.

`layout_flow.py` must run last: the build scripts place each node as they add
it and do not know what the canvas ends up looking like. It also refuses to
finish silently, printing any pair of nodes whose boxes overlap.

`build_ingest_flow.py --deploy` deletes each document from the Langflow file
store before uploading it. `/api/v2/files` does not overwrite: a name that is
already there is stored as `<name> (1)`. Without the delete, every deploy added
another copy, rewrote the File paths in the flow JSON, and left the superseded
document in the store, which is the one place a stale Arkon document could come
back from after the source was corrected. The upload now asserts it got the plain
path, so a purge that silently failed stops the build instead of shipping a flow
pointed at a copy.

`build/lf_api.py` and `build/lf_v2.py` drive a running Langflow from the NAS.
The second one exists because a canvas holding a Human Input node cannot be run
through the v1 API at all. Both read the superuser credentials from the compose
`.env` on the NAS, so no secret travels with the repository.

Prompts are not stored in these scripts. They are read out of `langflow/prompts/`
by block name at generation time, so the prompt files and the canvas cannot
drift.

`build/sync_prompts.py` keeps that true after generation time. It rewrites only
the bound prompt fields on an existing canvas, adds nothing, and refuses a node
it cannot find, so fixing a prompt no longer means re-running the whole chain.
That matters because `build_retrieval.py` is not idempotent: a second run would
add the store nodes again.

## Deploying it

Import through the Langflow UI, or push it over the API. The API route needs the
login bearer token for `/api/v1/flows/` and a separate API key for
`/api/v1/run/`. `build/lf_api.py` handles both.

Two host settings are required, and both are already in the compose files on the
NAS. Neither is optional and neither is obvious from an error message:

- n8n carries the Docker network alias `n8n.arkon.internal`. Langflow's API
  Request component validates URLs with `validators.url()`, which rejects any
  hostname without a dot, so `http://n8n:5678` fails as "Invalid URL provided"
  before a request is ever made.
- Langflow runs with `LANGFLOW_SSRF_ALLOWED_HOSTS=n8n.arkon.internal,qdrant`.
  Outbound calls into private IP ranges are blocked by default, which covers
  every sibling container. The allow-list holds those two hosts and nothing else,
  which is what keeps a model-written URL from being a request-forgery surface.
  Qdrant needs its entry even though it is not an HTTP tool: the component runs
  the same guard on its own host before handing it to qdrant-client.

## Testing it

```bash
python n8n/incident_status_probe.py http://AK2101:5678/webhook/arkon-incident-status
```

Test the backend first: an assistant failing because its endpoint is down looks
exactly like an assistant failing because its prompt is wrong.

The failure path is tested by moving `/data/arkon/incidents.jsonl` aside so n8n
genuinely answers 503, not by telling the assistant to pretend. For a live demo,
where moving files on a NAS is not an option, the status API takes
`simulate_failure=true` and returns the same 503 without touching the store.

## What changes when a second module arrives

The assistant is a permanent part of Arkon, not a demonstration built around one
model. Scania, the casting-defect module and NHTSA all publish the same event
contract, so most of this build is already module-agnostic and stays untouched:

- The intake workflow validates a contract, not a domain, and its assignment
  table already covers all four business domains.
- The escalation workflow works from an incident id and knows nothing about
  modules.
- The router's four intents are about what the operator wants, not about what
  produced the incident. A new module adds no route.
- The shift briefing reports whatever is open.

Three things were CMAPSS-shaped, they were all called small, and **the second
module arrived on 2026-08-30 and showed that one of them was not.** All three
are now fixed. The record of what each one actually cost is worth keeping.

**The status API projected `predicted_rul` and `priority_threshold` by name, and
this one was serious.** Those keys live in the CMAPSS `evidence` object, and the
projection filled them from `evidence.prediction` whatever the module was. The
first Scania incident, `ARK-INC-00017`, therefore came back carrying
`predicted_rul: 0.0373` - an APS failure probability presented as a remaining
useful life - and the assistant told an operator the truck had 0.0373 cycles of
life left. Nothing failed: not the model, not the adapter, not the workflow, not
the API, not the prompt. Fixed by returning the `evidence` object as the module
published it and keeping the CMAPSS aliases only for CMAPSS record ids.

**The status API's `unit` filter parsed `evidence.record_id` as
`FD001-Unit-092`.** It read `SCANIA-APS-000056` as unit `000056`, which is not a
unit and does not exist. Fixed: `unit` now answers only for record ids carrying
the `FD<n>-Unit-` marker, and `record_id`, `source_module` and `business_domain`
are filterable because every module carries them by contract. `unit=92` still
works, so nothing on the canvas had to change.

**The procedure specialist's prompt carried the quality rules as text**,
including the CMAPSS threshold table. The rules now come from the document
store, so a second module is added by writing its model card and dropping it in
rather than by editing a prompt.

**That claim was tested on 2026-08-30 and it failed the first time.** The prompt
still enumerated "four documents" and scoped itself to "what the CMAPSS model
predicts and cannot do", so Phase 2 would have needed a prompt edit after all. It
names no document and no module now: which documents exist is a property of the
store, and the prompt says to search and see. The Scania and casting model cards
were then added by dropping them in, and the assistant answers about both, cites
them by name, and explains why their priority mappings differ from CMAPSS, with
nothing on the canvas changed. Fixing a prompt without rebuilding the canvas is
what `build/sync_prompts.py` is for. That is what turns a single-module assistant
into the platform's assistant, and it is why the store was worth building at all.

**The claim finally held with no edit at all, on 2026-09-02.** NEU still cost a
route-description edit, because the Quality procedure route enumerated the four
modules it knew and a fifth had nowhere to match. That edit ended the list with
"and any module added after this was written", and MVTec is the first module to
arrive since. It was added by putting its model card in `DOCUMENTS` and
re-ingesting, with no prompt, no route description and nothing on the canvas
touched, and three questions confirm it: what the module does and cannot do, a
specific measurement from deep in the card (the 5 per cent budget against the
9.8 to 22.7 per cent it realises), and a cross-document question the store had to
answer from two sources. The generic clause is doing the work the enumeration
used to do.

**What the second module cost in total: one API projection.** The intake
workflow validated a `scania_aps` event and created an incident with no change
at all, because it validates a contract rather than a domain and takes the
assignee from the event's own `operational_context`. The escalation workflow,
the router's five intents and the shift briefing were untouched. That was the
claim, and it now has one measurement behind it instead of none.

## What it needs to run at all

**An OpenRouter credential, and it is not optional.** Eight nodes across the three
flows hold one: the five LLM nodes and the embeddings on the assistant, the embeddings
on the ingest flow, and the briefing sub-flow. Without a working key the assistant
stops answering **and retrieval stops with it** - a question has to be embedded at
query time even though Qdrant already holds the vectors, so a valid key is needed to
search a store that is entirely on disk. The store cannot be rebuilt either.

The key lives as the Langflow global variable `OPENROUTER_API_KEY`, set on the NAS and
never in this repository.

**The key this deployment runs on belongs to a course and ends with it.** It was issued
by Masterschool and is disconnected when the course finishes, around 2026-09-14, which
is a date rather than a risk. Replacing it is one credential swap and no node changes;
any OpenRouter key covers both the chat models and the embeddings, which is why a
provider-specific key would be a worse answer here - it would leave the embeddings
without a provider and need a component change on six nodes.

**What does NOT stop**, and it is most of the platform: the n8n Quality Steering Cell,
the Streamlit cockpit, the executive view, the live plant and the Tableau layer. None
of them touches OpenRouter. So an expired key takes one of the two operator surfaces
dark and leaves the system running - which is why this paragraph exists rather than a
silent failure at some later date.

## Which model it runs on, and how that was decided

`google/gemini-2.5-flash` on the two reading specialists, `google/gemini-3.1-flash-lite`
on the router and the two escalation nodes, embeddings on
`google/gemini-embedding-001`. All through OpenRouter.

**The split is deliberate.** The router picks one of six branches from a short prompt,
which is the one job on this canvas the cheapest tier is genuinely sized for. The two
reading specialists are the nodes whose mistakes end up in an operator's permanent
record, so they get the better model.

**It was decided by measurement, and `langflow/build/compare_models.py` is the
measurement.** Five questions with mechanical checks: an open incident must come back
with the operator link and a note that invents no source, a closed one must come back
with no link, a procedure question must name the cockpit page and both acknowledgement
windows, a filter the API does not take must be handled without narrating the retries,
and a question outside the ten documents must produce the exact refusal sentence and
nothing after it. Check one is the NHTSA telemetry invention of 2026-09-05 kept as a
regression test.

**Result over three clean repeats:** `gemini-2.5-flash` scored 11, 11 and 11 of 11;
`gemini-3.1-flash-lite` scored 10, 10 and 8. On the battery as it now stands, with the
retry case added, the deployed pair scores 14 of 14. The price difference is
0.30 against 0.25 dollars per million input tokens, which is nothing at human-paced
usage: the assistant is asked questions by people, not by the plant.

**Three defects in that comparison are worth more than its result**, because each one
produced a confident wrong answer first.

1. **A checker that rewarded silence.** Two candidate models were blocked by OpenRouter
   and returned nothing at all, and the battery scored both at 4 of 11 - four of the
   checks are negative (invents no source, withholds the link, claims no button, adds
   nothing) and an empty string passes every one. The only hint was that two unrelated
   models had produced identical scores. An answer that did not arrive is now a hard
   failure of every check in its case, with the reason printed.
2. **A checker that accused a correct answer.** "Gives the window" demanded "60" or
   "one hour"; the model wrote "1 hour" and was marked wrong. A rule that matches one
   wording looks rigorous and is not.
3. **A session id that left out the model**, so two models shared Langflow's chat
   memory and the second one answered from the first one's turn. That run returned
   four BYTE-IDENTICAL answers from two different models, which is impossible, and it
   is the only reason the result was questioned at all. Two models scoring the same is
   a result; two models producing the same characters is a bug.

**The real constraint is not the model, it is the OpenRouter workspace guardrail.**
`gemini-3.6-flash`, `gemini-2.5-pro`, `gpt-5-mini` and `claude-sonnet-5` were all
refused with "0 endpoints out of N requested are available matching your guardrail
restrictions and data policy", so the choice above is the best of what the account
currently permits rather than the best available. Whoever widens that setting should
re-run the battery; the script takes model ids as arguments and restores the previous
model unless `--keep` is passed.

## Known gaps

- **The document store holds 10 documents and is not coverage.** Charter, SOP,
  the 7 model cards and the event contract. The chunk count is deliberately not
  repeated here: it changes on every re-ingest and
  `GET /collections/arkon-knowledge` is the only place that knows it. The
  validation questions span the documents and one is deliberately unanswerable,
  which shows retrieval works and shows the refusal path holds. It does not show
  the store answers everything an operator will ask. A question outside those
  10 documents gets the fallback sentence, which is the correct behaviour and
  still a gap in the knowledge base.
- **The model cards dominate the store by volume, and 2026-09-03 is the first day
  that stopped rising.** Measured on the live collection after the lifecycle
  rebuild: 245 chunks over the 10 documents, of which the 7 model cards are 162,
  or 66 per cent, against 69 after the NHTSA ingest that morning, 68 per cent when
  there were five cards and 65 when there were four. Charter, SOP and event
  contract together are the other 83, and they grew by 9 while no card moved,
  which is what a piece of platform work looks like in this store as against a
  piece of model work. A question spanning two documents was measured again
  on this store and answered from the event contract and the MVTec card together,
  naming all three modules in `visual_inspection` and the field that separates
  them, so the shift has not broken cross-document retrieval at this size. It is
  still a trend rather than a bound: nothing here says where it stops working.
  Rebuilt again on the evening of 2026-09-06, after the charter 7.4 and SOP edits for
  the escalation timer and the daily digest: 246, the cards still 162, charter 47,
  SOP 12, contract 25, every untouched document back at its previous count. Once
  more after the charter 7.6 edit the same evening: 247, the charter 48, nothing
  else moved. And on 2026-09-07, after the charter 7.5 edit for the queryable
  store: 248, the charter 49, the nine other documents at their previous counts.
- **A rebuild is verified by the documents that did not change.** The NHTSA ingest
  of 2026-09-03 dropped the collection and rebuilt it from ten documents. The seven
  untouched documents came back at byte-identical chunk counts, and the growth is
  entirely the new card plus the two documents that were edited in the same commit,
  so 196 plus 9 plus 31 closes on 236 with nothing left over. That arithmetic is the
  check for orphans, and it only works because the counts are taken by scrolling
  every point rather than from the ingest flow's own report.
- **Re-ingestion is idempotent only while the documents are unchanged.** Point ids
  are a hash of chunk text plus metadata, so an edited document leaves its old
  chunks behind as orphans. Editing a source document means dropping the
  collection and re-running, which takes about a minute and is not automated.
  Measured on 2026-08-30 after the charter correction: drop, re-ingest, 42
  chunks; ingest again on the same documents, still 42.
- **One write, and only one, and the reason for it changed on 2026-09-03.** After
  a human approves at the gate, the assistant can record an escalation. It still
  cannot acknowledge, close or resolve an incident and still declines those
  requests even when the gate approved them, but it now declines them because it
  has no connection to that endpoint rather than because the endpoint does not
  exist. The lifecycle write path is deployed (`n8n/README.md`), and wiring it in
  as a second guarded tool is a canvas change that has deliberately not been made:
  the canvas has been untouched since 2026-09-01, through three modules, and the
  escalation gate is the pattern a second write would copy rather than extend.
  The prompts were corrected so the refusal states the real reason; a refusal
  that gives a false reason is worse than the refusal itself.
- **What the assistant gained without a canvas change.** The status API it already
  reads now folds the transition log, so an incident's `status` is its real state
  and each one carries the times to acknowledge, resolve and close, plus the full
  history of who moved it when. The store summary carries the plant-wide medians.
  `overdue` finally measures something: it always meant "unacknowledged past the
  window" and, with no acknowledgement path, counted the whole store. The Incident
  Specialist prompt was extended to use those fields and to say that `raised_as`,
  which reads `new` on every incident, is not a contradiction of `status`.
- **No authentication in front of it.** Langflow enforces login, but the flow
  endpoint is reachable by anyone holding an API key on the LAN or the Tailscale
  network. Anything beyond a demo needs a real identity in front of the operator
  interface.
- **The approval is not verifiable by the endpoint.** The gate is enforced on the
  canvas; the escalation API records the `approved_by` value it is sent and
  cannot check it. In production the gate would hand the agent a signed,
  single-use token.
- **And on this deployment the gate itself leaks, which is what makes that token
  a requirement rather than a refinement.** On 2026-09-11 the Approve branch was
  observed running after a Reject: 2 of 5 trials in a two-turn shape (a status
  question, then "While you are there, acknowledge it and close it too.", then
  Reject) and 0 of 5 in a plain one-turn escalation request, all ten driven
  through the cockpit's own client with the three calls the assistant page makes
  (`start_turn`, `poll_turn`, `resume_turn`). In both leaking trials
  `Escalation Answer` and `Declined Answer` carried text and the message table
  has the two agents within 25 ms of each other, so both branches ran through to
  their own output. **The canvas is wired correctly** - `Agent-esc01` takes its
  input only from the gate's `branch_approve` and its tool only from
  `APIRequest-esc01` - so this is the Langflow runtime executing a branch it
  should have skipped, intermittently. **Nothing was ever recorded:**
  `escalations.jsonl` held the same 19 lines before and after all ten trials,
  because the shape that leaks asks for a move the escalation specialist declines
  by prompt and the escalation record is its only tool. **The combination that
  would write is not ruled out:** a real escalation request in the leaking shape
  was never tried, because that trial can put a false approved line into an
  append-only store, and the demo credential expires in mid-September 2026. So
  branch deactivation is not a safety property on this runtime; an endpoint that
  can check the approval itself would be.
- **An unanswered approval expires silently.** The Human Input timeout is one
  hour and the fallback output is off, so a request nobody answers is not routed
  anywhere. The fix is a fallback branch that tells the Quality Manager; it is
  not built because it cannot be tested without waiting out the window, and an
  untested branch on the path that pages a human is worse than a named gap.
- **Fixed by the sixth route, kept here because the road to it is the useful
  part.** An underspecified question used to be answered as an off-topic one. The fix looked
  like one field and was not. Read out of `llm_conditional_router.py` in the
  running container, after this gap had been described two different wrong ways:

  - Smart Router **does** have an Else output, `enable_else_output`, advanced and
    off by default. "The router has no fallback" was wrong.
  - Its Else branch returns the **user's own input text** when nothing matches,
    unless `Override Output` is set. Switching it on and wiring it to an output
    gives an assistant that repeats the question back.
  - `Override Output` does not fix that: its own help text says it replaces the
    output value **for all routes**. There is no per-branch fallback message.

  So the Else was rejected and a sixth route added instead, carrying its own
  fixed `output_value`, which is the shape the out-of-scope branch already used.
  The real cost was never the building: a sixth destination changes the
  classification surface for all five existing routes, so the whole protocol ran
  again. Six routes plus both gate paths, all correct, escalation store up by
  exactly one line.

- **Two paragraphs of the procedure prompt describe the deployment, not the
  quality system.** The simulated-context rule and the version-1 write boundary
  are in the prompt rather than the document store, because both have to hold
  when retrieval returns a document that reads as though they do not - the
  charter describes acknowledge and close buttons on the alert card that are not
  wired. Both paragraphs go stale the day the lifecycle write path lands, and
  nothing enforces that they are removed.

  **That sentence came true on 2026-09-05 and nothing in this repository noticed.**
  The cockpit's transition form was built at 19:15 that day, and the prompt went on
  telling operators to "never present a button, screen or menu as something the
  operator can use today" for the rest of the evening. A deployed assistant was
  therefore denying the existence of a screen that had just been built for it. What
  caught it was Sergey asking what the assistant is actually for, which made someone
  read the prompt; no checker here reads a prompt against the deployment it
  describes, and the gap that predicted the failure could not detect it either. The
  paragraph is corrected and now names the page, and the general form is the one
  this project keeps meeting: a claim about a neighbouring system is only as fresh
  as the last time a person compared them.

- **CLOSED 2026-09-06: the cockpit no longer throws away the key to its own
  history.** The session id is in the page URL, the way the Steering Cell page carries
  `?incident=`, and `api.history()` reads prior turns back from
  `/api/v1/monitor/messages?session_id=` on load. A reload resumes, and a link to a
  conversation can be handed to someone else. Verified by opening
  `/assistant?session=cockpit-b8a125e38ad9` and getting Sergey's conversation of the
  previous afternoon back in full. The gap it closed is worth keeping in view: the
  history was never lost, only unreachable, because the page minted a fresh uuid on
  every load and never read the table back. "Start a new session" still abandons
  rather than deletes, and the sidebar now says so.

- **CLOSED 2026-09-06: the conversation has a name in it.** `app/utils/identity.py`
  holds one identity per browser session, chosen from a roster derived from the store
  itself (8 people in 5 roles, on the day it was built), and every page shows the same
  picker. The assistant receives it as one line in front of the question,
  `[operator: A. Novak, QC Engineer]`, which the prompts are told to read and never to
  quote back. Two things follow. The escalation record - the one write this assistant
  can perform, and the platform's only audited action - now carries the operator's real
  name instead of `arkon-quality-assistant`. And an answer about an incident says
  whether the move is theirs, because charter 7.2 gives closure to the Quality Manager
  alone.

  **The instruction that does this was wrong twice before it was right, and both
  versions are worth knowing about.** The first told the specialists to use the role
  and nothing else, and asked whether a Maintenance Planner could close an incident it
  answered "as a Maintenance Planner, you are the assignee and can make this move" -
  two inventions in one sentence, from a role that cannot close anything and about an
  assignment it had no way to see, because the procedure specialist has no connection
  to the incident store. The prompt now states the role rule outright rather than
  hoping retrieval surfaces it, and says explicitly that the assistant does not know
  who an incident is assigned to. Verified in both directions: a Maintenance Planner
  is told closure is the Quality Manager's, and R. Ortiz is told it is his.

  **It is a name, not an authentication.** Nothing in this deployment logs anyone in,
  so this is attribution the person offers: it makes the honest case easy and the
  careless one visible, and it would not survive somebody who wanted to lie.
