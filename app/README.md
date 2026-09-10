# Arkon cockpit (Streamlit)

The operational surface of charter 7.5, Phase 3. Ten pages over two live
services and the repository's own tracked metrics: what is open in the Quality
Steering Cell right now, what each of the seven modules measures and cannot do,
and the deployed assistant with its approval gate.

Process owner: `docs/Project_Charter.md` section 7.5. The services it reads are
owned by `n8n/README.md` and `langflow/README.md`.

**Status: built and deployed 2026-09-04**, `http://AK2101:8303` on the NAS. Since 2026-09-09
the assistant page alone is also reachable from the internet behind a login (the section
"The public assistant page" below).

## What it is not

It does not train, load or score a model. No page opens a weight file and the
container carries none: the module pages read the tracked `*_meta.json` metrics
files that the notebooks wrote, and the figures the notebooks produced. That is
what keeps the image small enough to sit beside the services it reads, and it is
also the honest division of labour. The notebooks are where a number is made and
the model cards are where it is defended; this app shows it and points at both.

It also does not compute an incident's status. That is a fold of the transition
log onto the incident record, performed once on the platform (since 2026-09-07 by
the store sync behind the n8n status API, charter 7.5) and served by that API, so
the cockpit and the assistant cannot disagree about what an incident is doing.

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

The same image carries the live plant, `live_plant/plant.py`, as the `live-plant`
service behind the `live` compose profile (`docker compose -f app/docker-compose.yml
--env-file .env --profile live up -d live-plant`, from the same directory). It is a
separate service on purpose: the cockpit reads and the plant writes, and a plain
`up -d` of the cockpit must never start something that sends Telegram cards. Its
ledger lives at `/volume1/docker/arkon/live_plant/` beside the store. It is a
mini-project of its own: `live_plant/README.md`.

## Who is at the screen

`utils/identity.py` holds one identity per browser session, picked from a roster the
app derives from the store itself rather than from a list in a file, so it follows
the plant. Every page shows the same picker at the top of the sidebar, and two
things read it.

The transition form fills "Recorded as" from it. It used to default to the
incident's ASSIGNEE, which made the easiest thing an operator could do a move
recorded under somebody else's name, in the log that every response-time figure on
this platform is computed from. It also now warns when the move is a closure and the
person is not the Quality Manager, and notes when the actor is not the assignee -
allowed, and worth seeing.

The assistant sends it to the canvas as one line in front of the question, so the
escalation record carries a real name where it used to carry
`arkon-quality-assistant`, and an answer can say whether a move is the reader's.

**It is a name, not an authentication**, and the distinction is the whole of the
next boundary. It is also why the assistant's conversation list is headed "All
conversations" rather than "Past conversations", and says under itself that it is
shared: with nothing signing anyone in, every conversation held with the assistant is
listed for everyone and its messages open too. Scoping that list to the name in the
picker was considered and rejected - it would look like privacy while providing none,
which is worse than saying so.

## The public assistant page

Since 2026-09-09 the assistant page, and only that page, is reachable from the internet at
`https://ugreen-nas.tail90586f.ts.net:10000/` behind a login, for people who are not on the
tailnet. It is `02_assistant.py` run as a single-page app from the same image (the `assistant`
service in `docker-compose.yml`), with Caddy in front of it holding an HTTP Basic Auth login
(`assistant-auth`, host port 8304), and Tailscale Funnel mapping port 10000 of the node to
that host port. Nothing else is published. The Steering Cell page writes transitions with no
login and stays on the LAN and the tailnet, and Funnel is enabled per port and accepts 443,
8443 and 10000 only, so the editor on 443 and the customer desk on 8443 are untouched.

The login is a demo credential, not an authentication of anyone: it stops a passer-by. It
lives on the NAS as a bcrypt hash in `/volume1/docker/arkon-assistant/Caddyfile`, beside
`.env` and like it outside this repository:

```
:8080 {
	basic_auth bcrypt "Arkon Quality Assistant demo" {
		arkon <the hash: docker run --rm caddy:2-alpine caddy hash-password --plaintext '<password>'>
	}
	reverse_proxy arkon-assistant:8501
}
```

Bringing it up, from `/volume1/docker/arkon-cockpit` on the NAS:

```bash
docker compose -f app/docker-compose.yml --env-file .env up -d assistant assistant-auth
docker exec tailscale tailscale funnel --bg --https=10000 http://localhost:8304
docker exec tailscale tailscale funnel status
```

`docker exec tailscale tailscale funnel --https=10000 off` takes it down again and leaves the
other ports alone. Three things about the page when it is public. An Approve at the gate
writes a real line into the escalation store, which is the point of the demo rather than a
side effect. The "All conversations" list is the same shared list as in the cockpit, so a
visitor sees every conversation held with the assistant, and the page says so under the list.
And the Langflow key stays in the container's environment: the browser never sees it. Streamlit
is started with `browser.serverAddress` set to the public host name, because its websocket
origin check compares the browser's origin with the host it believes it is served from, and
behind two proxies those can differ.

## Known boundaries

- **No authentication**, like the two services behind it. LAN and Tailscale only,
  and it must not be port-forwarded; the one page that is public sits behind a login of
  its own (the section above). The identity above is offered by the person,
  not verified: it makes attribution easy and its absence visible, and it would not
  survive anyone who wanted to lie. Real identity here means a login, not a better
  selector.
- **It writes one thing: lifecycle transitions, from the Steering Cell page.** Until
  2026-09-05 this app was read-only by design (an acknowledge button was judged a
  second, unguarded way to change an incident, the gate in front of a write being
  the project's pattern), and the consequence was that a person who received a
  card had no surface at all to acknowledge, contain, resolve or close it: only
  `n8n/drive_incident.py` from a terminal. Sergey decided that day that the
  operator's controls belong on the operational screen. "Move this incident"
  under the incident detail offers only the moves charter 7.2 allows from the
  current state, records the name typed in as the actor, and shows the endpoint's
  answer as it came, including a 409 when someone moved the incident first. What
  has not changed: the endpoint is the authority, the record is the transition
  log, and there is no authentication, so this is a LAN and Tailscale control like
  everything else here, not an audited one. The assistant's escalation stays
  behind its approval gate and remains the only write an agent can perform.
- **The assistant page polls.** A turn is a small state machine across Streamlit
  reruns, so a long answer redraws the page every two seconds. That is fine at
  demo scale and is not how a production chat would be built.
- **The figures are whatever the notebooks last wrote.** They are tracked files,
  so a stale figure is a stale commit rather than a stale cache, but nothing in
  this app checks that a figure and a metrics file came from the same run.
- **It shows the plant, not the platform's own health.** Whether the intake
  webhook is rejecting everything is invisible here: since 2026-09-06 every intake
  outcome is written to `/data/arkon/intake_outcomes.jsonl` (charter 7.6), but this
  app does not read that log yet, so a validation regression still looks like a
  quiet plant on this page.
