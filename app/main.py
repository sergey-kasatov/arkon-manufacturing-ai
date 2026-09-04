"""Arkon Manufacturing AI, the operational cockpit.

The entry page: what the platform is, what it is doing right now, and where the
rest of the app is. Everything live on this page comes from the n8n status API,
so if the Steering Cell is unreachable this page says so instead of showing a
plausible zero.
"""

import streamlit as st

from utils import api, config, modules

st.set_page_config(
    page_title="Arkon Manufacturing AI",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("Arkon Manufacturing AI")
st.caption(
    "Seven model modules publishing one event contract into an n8n Quality Steering Cell, "
    "with a grounded assistant and this cockpit over the result."
)

# The live pulse. One call, and it either answers or it says it did not.

pulse = api.incidents(limit=1)
if api.reachable(pulse):
    store = pulse["store"]
    times = pulse.get("response_times", {})
    columns = st.columns(5)
    columns[0].metric("Incidents", "{:,}".format(store["total_incidents"]))
    columns[1].metric("Open", "{:,}".format(store["open_incidents"]))
    columns[2].metric("Overdue", "{:,}".format(store["overdue_incidents"]))
    columns[3].metric("Closed", "{:,}".format(times.get("closed_incidents", 0)))
    columns[4].metric("Transitions", "{:,}".format(pulse.get("transitions", {}).get("total_transitions", 0)))
    st.caption("Read from the Steering Cell just now, at " + pulse.get("as_of", "an unknown time") + ".")
else:
    st.error(
        "The Steering Cell did not answer, so nothing here describes the plant. "
        + str(pulse.get("message", ""))
    )
    st.caption("Endpoint: " + config.STATUS_API)

st.divider()

# What the platform is

left, right = st.columns([3, 2])

with left:
    st.subheader("What this is")
    st.markdown(
        """
Arkon is a fictional heavy-manufacturing company built over **real public datasets only**.
Seven model modules run on different data and answer different questions, and each one
publishes the same **risk event** into one n8n workflow that validates it, suppresses
duplicates, assigns a role, records an incident and alerts a human.

The point of the platform is that last sentence. The modules have nothing to do with each
other: a turbofan test cell, a truck fleet, four kinds of visual inspection and the text of
consumer complaints. **One webhook takes all of it unedited**, because it validates a
contract rather than a domain.

Two things are deliberately visible in this cockpit rather than hidden.

**A status here is a fold, not a field.** The incident store records the state an incident
was raised in, once, and never rewrites it. The current state is the transition log applied
to that record, and the status API is what applies it. Every incident therefore shows
`raised_as: new` next to whatever it is now.

**Model evidence is real and operational context is not.** Metrics come from real held-out
records; the shift, the line, the assignee and the escalation contact are generated and are
labelled `simulated` wherever they appear.
        """
    )

with right:
    st.subheader("The seven modules")
    for key in modules.ORDER:
        module = modules.MODULES[key]
        st.markdown(
            "**%s**  \n`%s` in `%s`  \n%s"
            % (module["title"], module["source_module"], module["business_domain"], module["task"])
        )

st.divider()

st.subheader("Where things are")
st.markdown(
    """
| Page | What it answers |
|---|---|
| **Quality Steering Cell** | What is open right now, what is overdue, how long incidents take to acknowledge and close, and the full lifecycle history of any one of them |
| **Assistant** | The same questions in words, through the deployed Langflow agent, including the approval gate in front of the one write it can perform |
| **The module pages** | What each model measures, what it cannot do, and the figures behind both |

The operating documents live in the repository rather than in this app: the charter
(`docs/Project_Charter.md`), one model card per module (`docs/`), the event contract
(`events/README.md`) and the workflow record (`n8n/README.md`).
    """
)
st.caption(config.REPO_URL)
