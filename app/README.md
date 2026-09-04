# Arkon cockpit (Streamlit)

The operational surface of charter 7.5, Phase 3. Nine pages over two live
services and the repository's own tracked metrics: what is open in the Quality
Steering Cell right now, what each of the seven modules measures and cannot do,
and the deployed assistant with its approval gate.

Process owner: `docs/Project_Charter.md` section 7.5. The services it reads are
owned by `n8n/README.md` and `langflow/README.md`.

**Status: built and deployed 2026-09-04**, `http://AK2101:8303` on the NAS.

## What it is not

It does not train, load or score a model. No page opens a weight file and the
container carries none: the module pages read the tracked `*_meta.json` metrics
files that the notebooks wrote, and the figures the notebooks produced. That is
what keeps the image small enough to sit beside the services it reads, and it is
also the honest division of labour. The notebooks are where a number is made and
the model cards are where it is defended; this app shows it and points at both.

It also does not compute an incident's status. That is a fold of the transition
log onto the incident record and the n8n status API performs it, so the cockpit
and the assistant cannot disagree about what an incident is doing.

## The pages

| Page | What it answers |
|---|---|
| `main.py` | What the platform is, and its live pulse: incidents, open, overdue, closed, transitions |
| `01_steering_cell.py` | Charter 7.5. Counts by priority and lifecycle state, the response-time KPIs, a filterable incident list, and any one incident in full with the history of who moved it when |
| `02_assistant.py` | The deployed Langflow canvas, including the approval gate |
| `03` to `09` | One per module: headline metrics, the caveat that has to travel with them, what it runs on, how many incidents it has raised, and its figures |

## The one rule that is not presentation

`ui.service_answer` renders the status API's four outcomes as four different
things, and the reason is worth keeping in front of whoever edits this app.

The API separates "the store holds nothing like that" from "the lookup failed".
A dashboard that draws an empty table for both teaches its operator that an
outage looks like a quiet plant, which is the failure mode charter 7.6 names for
the intake path and the same one applies here. So a failed lookup gets an error
and stops the page; an empty result gets an ordinary note and does not.

## Seven module pages, one function

`utils/modules.py` holds one row per module and `ui.module_page` renders it, so
each of the seven page files is three lines. A module is added by writing a row.

Two fields in that row are not optional. `headline` is a list of dotted paths
into the metrics file, so every number is read at render time and none is typed
into this app. `caveat` is the sentence that has to travel with those numbers,
because a dashboard is exactly where such a sentence gets dropped: NEU's 1.0000
next to the 0.9750 an un-finetuned baseline reaches, GC10's mAP next to the fact
that it does not reproduce, casting's zero missed defects next to the four runs
that span 0 to 2.

## Running it

Locally, from the repository root:

```bash
streamlit run app/main.py
```

It reads `http://AK2101:5678` for incidents and needs no credential for them.
The assistant page needs a Langflow API key, which it takes from
`ARKON_LANGFLOW_API_KEY` in the environment or from `.streamlit/secrets.toml` in
the repository root, which is gitignored. Without one the assistant page says so
and every other page still works.

**`.streamlit/secrets.toml` is resolved from the repository root rather than
through `st.secrets`.** Streamlit finds that file relative to the process working
directory, so starting the app by absolute path from somewhere else silently
finds no secrets. `utils/config.py` reads it from `REPO` instead.

On the NAS:

```bash
cd /volume1/docker/arkon-cockpit
docker compose -f app/docker-compose.yml --env-file .env up -d --build
```

The build context is the repository root, because the app reads `assets/` and
the metrics files. `.dockerignore` excludes `models/**` and puts the metrics
files back, so the trained weights cannot end up in the image. The container
joins `msit-flowise_msit`, the network n8n and Langflow are already on, and
reaches them by alias rather than by host name. `.env` holds the Langflow key and
lives only on the NAS.

Redeploying after a change means shipping the context again; there is no git
checkout on the NAS.

## Known boundaries

- **No authentication**, like the two services behind it. LAN and Tailscale only,
  and it must not be port-forwarded.
- **It is read-only except through the assistant.** The lifecycle write path
  exists (`POST /webhook/arkon-incident-transition`) and this app deliberately
  does not call it: an acknowledge button here would be a second, unguarded way
  to change an incident, and the gate in front of a write is the pattern this
  project has committed to. The transition endpoint is driven by
  `n8n/drive_incident.py` or by an operator.
- **The assistant page polls.** A turn is a small state machine across Streamlit
  reruns, so a long answer redraws the page every two seconds. That is fine at
  demo scale and is not how a production chat would be built.
- **The figures are whatever the notebooks last wrote.** They are tracked files,
  so a stale figure is a stale commit rather than a stale cache, but nothing in
  this app checks that a figure and a metrics file came from the same run.
- **It shows the plant, not the platform's own health.** Whether the intake
  webhook is rejecting everything is invisible here for the reason charter 7.6
  gives: only recorded incidents are written anywhere, so a validation
  regression looks like a quiet plant on this page too.
