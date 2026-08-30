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

**Status: deployed 2026-08-30**, endpoint `arkon-quality-assistant`. Sprints 1 and
2 complete and validated. The document store is not built yet; see Known gaps.

## Flow

```text
Chat Input
   |
Intent Router  (Smart Router, LLM categorisation)
   |-- Quality procedure  -> Procedure Specialist  -> Chat Output
   |-- Incident status    -> Incident Specialist   -> Chat Output
   |                            ^ API Request (tool mode) -> incident status API
   |-- Escalation request -> Escalation Specialist -> Chat Output
   `-- Out of scope       -------------------------> Chat Output
```

The out-of-scope branch carries a fixed Route Message on the router, so it
reaches its output with no agent in between and no second model call.

The incident specialist reaches the n8n incident status API at
`http://n8n.arkon.internal:5678/webhook/arkon-incident-status` and reports only
what that API returns. The four answers the API distinguishes stay distinct all
the way to the operator: incidents found, nothing matched, bad request, lookup
failed. An empty result and a failed lookup are different facts, and an assistant
that conflates them will invent a status for one of them.

## Files

| File | Purpose |
|---|---|
| `arkon_quality_assistant.json` | The flow, importable into Langflow |

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

## Known gaps

- **No document store yet.** The procedure specialist answers from its own
  prompt. The Qdrant collection needs an embedding provider key inside Langflow,
  and OpenRouter, the credential already configured there, serves no embedding
  models. Once retrieval is in, the procedural facts come out of the prompt and
  the same test questions must still be answered correctly; that is the only way
  to show retrieval is working rather than the model reciting its instructions.
- **Read-only.** The assistant cannot acknowledge, escalate or close anything,
  because the Steering Cell has no write path for those states in version 1. The
  escalation branch names who can act instead.
- **No authentication in front of it.** Langflow enforces login, but the flow
  endpoint is reachable by anyone holding an API key on the LAN or the Tailscale
  network. Anything beyond a demo needs a real identity in front of the operator
  interface.
