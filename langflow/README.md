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
write the assistant can perform. Nothing reaches
`POST /webhook/arkon-escalation` unless a human picked Approve, and an approval
is not an authorisation to do something the system cannot do: an approved
"acknowledge this incident" is still refused, because there is no write path for
it.

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

## Files

| File | Purpose |
|---|---|
| `arkon_quality_assistant.json` | The main canvas, importable into Langflow |
| `arkon_shift_briefing.json` | The shift handover sub-flow, called through Run Flow and runnable on its own endpoint |
| `arkon_knowledge_ingest.json` | The ingestion flow: the Arkon documents into the Qdrant collection `arkon-knowledge`, one lane per document |
| `components/openrouter_embeddings.py` | A custom embedding component, because nothing Langflow ships can reach OpenRouter embeddings |

## How the flow JSON is generated

The canvas is not hand-edited. A Langflow flow is a ReactFlow graph whose edge
handles are JSON strings with every double quote replaced by U+0153, and getting
that wrong produces an edge that is present in the file but does not render or
execute. `build/lfbuild.py` owns that encoding; everything else builds on it.

The scripts run in order, each taking the previous one's output as its input,
which is how "one canvas refined across sprints" stays reproducible rather than
being a claim:

```bash
python langflow/build/fetch_specs.py           # component templates from the running instance
python langflow/build/build_arkon_flow.py      # first canvas, seed via ARKON_SEED_FLOW
python langflow/build/build_sprint2_flow.py    # adds routing and the live lookup
python langflow/build/build_sprint3_flow.py <briefing-flow-id>
python langflow/build/build_ingest_flow.py --deploy   # the document store, uploads and ingests
python langflow/build/build_retrieval.py       # the store as the procedure specialist's tool
python langflow/build/build_sprint4_flow.py <briefing-flow-id>   # the briefing gets its own branch
python langflow/build/build_sprint5_flow.py    # the sixth route, for a message it cannot place
python langflow/build/layout_flow.py           # positions, run last
```

`fetch_specs.py` comes first because every other script instantiates nodes from
the templates the running Langflow reports, and those templates are not in the
repository. It fetches them over ssh through `lf_api.py` on the NAS, so no
Langflow credential is ever needed on the workstation.

`layout_flow.py` must run last: the sprint scripts place each node as they add
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

**What the second module cost in total: one API projection.** The intake
workflow validated a `scania_aps` event and created an incident with no change
at all, because it validates a contract rather than a domain and takes the
assignee from the event's own `operational_context`. The escalation workflow,
the router's five intents and the shift briefing were untouched. That was the
claim, and it now has one measurement behind it instead of none.

## Known gaps

- **The document store holds six documents and is not coverage.** Charter, SOP,
  the three model cards and the event contract, 77 chunks as of 2026-08-30. The
  validation questions span all of them and one is deliberately unanswerable,
  which shows retrieval works and shows the refusal path holds. It does not show
  the store answers everything an operator will ask. A question outside those six
  documents gets the fallback sentence, which is the correct behaviour and still
  a gap in the knowledge base.
- **Re-ingestion is idempotent only while the documents are unchanged.** Point ids
  are a hash of chunk text plus metadata, so an edited document leaves its old
  chunks behind as orphans. Editing a source document means dropping the
  collection and re-running, which takes about a minute and is not automated.
  Measured on 2026-08-30 after the charter correction: drop, re-ingest, 42
  chunks; ingest again on the same documents, still 42.
- **One write, and only one.** After a human approves at the gate, the assistant
  can record an escalation. It cannot acknowledge, close or resolve an incident,
  because the Steering Cell has no write path for those states in version 1, and
  it declines those requests even when the gate approved them.
- **No authentication in front of it.** Langflow enforces login, but the flow
  endpoint is reachable by anyone holding an API key on the LAN or the Tailscale
  network. Anything beyond a demo needs a real identity in front of the operator
  interface.
- **The approval is not verifiable by the endpoint.** The gate is enforced on the
  canvas; the escalation API records the `approved_by` value it is sent and
  cannot check it. In production the gate would hand the agent a signed,
  single-use token.
- **An unanswered approval expires silently.** The Human Input timeout is one
  hour and the fallback output is off, so a request nobody answers is not routed
  anywhere. The fix is a fallback branch that tells the Quality Manager; it is
  not built because it cannot be tested without waiting out the window, and an
  untested branch on the path that pages a human is worse than a named gap.
- **Fixed in Sprint 5, kept here because the road to it is the useful part.** An
  underspecified question used to be answered as an off-topic one. The fix looked
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
