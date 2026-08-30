# Arkon Quality Assistant (Langflow)

Conversational front end for the Quality Steering Cell. It answers the questions
an on-shift operator actually asks: how the quality rules work, what an incident
is doing right now, and who owns an action the assistant itself must not take.

Process owner: `docs/Project_Charter.md` sections 7 and 8, and
`docs/Steering_Cell_SOP.md`. Runs on the self-hosted Langflow instance on the NAS
(pinned `langflowai/langflow:1.11.5`, see the vault runbook
`100 Personal/Langflow_NAS_Runbook.md`).

This is also the graded artifact of the MSIT Term 12 course 2B project. The
course build record, prompts and test evidence live in the vault at
`020 Projects/AI_Agents_2B_Meridian/build/`.

**Status: deployed 2026-08-30**, endpoint `arkon-quality-assistant`. Sprints 1 to
3 complete and validated. The document store is not built yet; see Known gaps.

## Flow

```text
Chat Input
   |
Intent Router  (Smart Router, LLM categorisation)
   |-- Quality procedure  -> Procedure Specialist  -> Chat Output
   |-- Incident status    -> Incident Specialist   -> Chat Output
   |                            ^ API Request (tool mode) -> incident status API
   |                            ^ Run Flow (tool mode)    -> Arkon_Shift_Briefing
   |-- Escalation request -> Human Input (Approve / Reject)
   |                            |-- Approve -> Escalation Specialist -> Chat Output
   |                            |                 ^ API Request -> escalation record API
   |                            `-- Reject  -> Escalation Declined   -> Chat Output
   `-- Out of scope       -------------------------> Chat Output
```

The out-of-scope branch carries a fixed Route Message on the router, so it
reaches its output with no agent in between and no second model call.

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

## How the flow JSON is generated

The canvas is not hand-edited. A Langflow flow is a ReactFlow graph whose edge
handles are JSON strings with every double quote replaced by U+0153, and getting
that wrong produces an edge that is present in the file but does not render or
execute. `build/lfbuild.py` owns that encoding; everything else builds on it.

The scripts run in order, each taking the previous one's output as its input,
which is how "one canvas refined across sprints" stays reproducible rather than
being a claim:

```bash
python langflow/build/build_arkon_flow.py      # Sprint 1, from the course LS2 seed
python langflow/build/build_sprint2_flow.py    # Sprint 2, adds routing and the live lookup
python langflow/build/build_sprint3_flow.py <briefing-flow-id>
python langflow/build/layout_flow.py           # positions, run last
```

`layout_flow.py` must run last: the sprint scripts place each node as they add
it and do not know what the canvas ends up looking like. It also refuses to
finish silently, printing any pair of nodes whose boxes overlap.

`build/lf_api.py` and `build/lf_v2.py` drive a running Langflow from the NAS.
The second one exists because a canvas holding a Human Input node cannot be run
through the v1 API at all. Both read the superuser credentials from the compose
`.env` on the NAS, so no secret travels with the repository.

Prompts are not stored in these scripts. They are read out of the vault build
artifacts at generation time, so the documents and the canvas cannot drift.

## Deploying it

Import through the Langflow UI, or push it over the API. The API route needs the
login bearer token for `/api/v1/flows/` and a separate API key for
`/api/v1/run/`; both are covered in the vault runbook.

Two host settings are required, and both are already in the compose files on the
NAS. Neither is optional and neither is obvious from an error message:

- n8n carries the Docker network alias `n8n.arkon.internal`. Langflow's API
  Request component validates URLs with `validators.url()`, which rejects any
  hostname without a dot, so `http://n8n:5678` fails as "Invalid URL provided"
  before a request is ever made.
- Langflow runs with `LANGFLOW_SSRF_ALLOWED_HOSTS=n8n.arkon.internal`. Outbound
  calls into private IP ranges are blocked by default, which covers every sibling
  container. The allow-list holds that one host and nothing else, which is what
  keeps a model-written URL from being a request-forgery surface.

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

Three things are CMAPSS-shaped today, and they are all small.

**The status API's `unit` filter parses `evidence.record_id` as
`FD001-Unit-092`.** Another module has another id shape. The fix is a generic
`record_id` filter plus filters on `source_module` and `business_domain`, which
are contract fields every module already carries.

**The status API projects `predicted_rul` and `priority_threshold` by name.**
Those keys live in the CMAPSS `evidence` object; a vision module's evidence
holds something else. The fix is to return `evidence` as it stands and keep the
friendly aliases only when the keys are present.

**The procedure specialist's prompt carries the quality rules as text**,
including the CMAPSS threshold table. This is the one that matters, and it is
exactly what the document store removes. Once the rules are retrieved from the
Arkon documents rather than written into the prompt, a second module is added by
writing its model card and dropping it into the store. That is the real argument
for finishing the document store, beyond the course asking for it: it is what
turns a single-module assistant into the platform's assistant.

## Known gaps

- **No document store yet.** The procedure specialist answers from its own
  prompt, and the Qdrant collection has not been built. The embedding provider is
  not settled: OpenRouter, the credential already configured in Langflow, does
  serve embeddings including `google/gemini-embedding-001`, but they are listed
  at `/api/v1/embeddings/models` rather than in the general model catalogue, and
  whether a Langflow component can address them has not been tested. Once
  retrieval is in, the procedural facts come out of the prompt and the same test
  questions must still be answered correctly; that is the only way to show
  retrieval is working rather than the model reciting its instructions.
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
- **The briefing sub-flow gets paraphrased.** Reached through the incident
  specialist, its fixed four-block output is restated in the agent's own words,
  which duplicates it and has already turned an age into an overdue figure. The
  fix is to give the briefing its own router branch so it reaches its output
  without passing through anything that rewords.
