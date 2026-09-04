"""The Quality Steering Cell, live.

Charter 7.5, the operational cockpit. It reads incidents through the status API
and never opens the JSONL store, for a reason worth stating on the page itself:
the store holds the state an incident was raised in and holds it for ever, and
the API is what folds the transition log onto it. A cockpit reading the file
directly would show 29 new incidents and never anything else.
"""

import pandas as pd
import streamlit as st

from utils import api, config, modules, ui

ui.page("Quality Steering Cell", "Live incident state, read through the n8n status API")

# Controls

with st.sidebar:
    st.subheader("Filter")
    priority = st.multiselect("Priority", ["P1", "P2", "P3", "P4"])
    status_filter = st.selectbox("Status", ["any"] + config.LIFECYCLE)
    module_filter = st.selectbox(
        "Module", ["any"] + [modules.MODULES[k]["source_module"] for k in modules.ORDER]
    )
    limit = st.slider("Incidents to list", 1, 50, 25)
    if st.button("Refresh", width="stretch"):
        st.rerun()
    st.caption("Endpoint: " + config.STATUS_API)

answer = api.incidents(
    priority=priority,
    status=None if status_filter == "any" else status_filter,
    source_module=None if module_filter == "any" else module_filter,
    limit=limit,
)

# The store, before any filter. These counts describe every incident, so they
# stay on screen even when the filter matches nothing.

if not api.reachable(answer):
    ui.service_answer(answer)
    st.stop()

store = answer["store"]
transitions = answer.get("transitions", {})
times = answer.get("response_times", {})

st.subheader("The store")
ui.metric_row(
    [
        ("Incidents", "{:,}".format(store["total_incidents"])),
        ("Open", "{:,}".format(store["open_incidents"])),
        ("Overdue", "{:,}".format(store["overdue_incidents"])),
    ]
)
st.caption(
    "Overdue means still unacknowledged past the charter 7.1 window, 15 minutes for P1 and one "
    "hour for P2. Until the lifecycle write path was built on 2026-09-03 nothing could stop "
    "being unacknowledged, so this number counted the whole store and meant nothing."
)

def counts_chart(counts, order=None):
    """A small horizontal bar chart. The height is explicit because the default
    is "content", which resolves to nothing for a chart and draws an empty box."""
    series = pd.Series(counts)
    series = series.reindex(order) if order else series.sort_index()
    st.bar_chart(pd.DataFrame({"incidents": series}), horizontal=True, height=200)


left, right = st.columns(2)
with left:
    st.caption("By priority")
    counts_chart(store["incidents_by_priority"])
with right:
    st.caption("By lifecycle state")
    by_status = store.get("incidents_by_status", {})
    counts_chart(by_status, [s for s in config.LIFECYCLE if s in by_status])

# Response times, which is the thing that could not exist before the write path

st.subheader("Response times")
if times.get("acknowledged_incidents"):
    ui.metric_row(
        [
            ("Acknowledged", "{:,}".format(times["acknowledged_incidents"])),
            ("Median minutes to acknowledge", "{:,.1f}".format(times["median_minutes_to_acknowledge"])),
            ("Within the window", "{:,}".format(times["acknowledged_within_window"])),
            ("Late", "{:,}".format(times["acknowledged_late"])),
            ("Closed", "{:,}".format(times["closed_incidents"])),
            ("Median minutes to close",
             "{:,.1f}".format(times["median_minutes_to_close"]) if times.get("median_minutes_to_close") else "-"),
        ],
        per_row=3,
    )
    st.caption(
        "Median rather than mean: one incident acknowledged the next morning would otherwise "
        "move the number more than every incident acknowledged on time. Computed by the status "
        "API from the {:,} transitions recorded against {:,} incidents.".format(
            transitions.get("total_transitions", 0), transitions.get("incidents_with_transitions", 0)
        )
    )
else:
    st.info(
        "No incident has been acknowledged yet, so there is no response time to report. A KPI "
        "needs two timestamps and only the raising one exists so far."
    )

# The incidents themselves

st.subheader("Incidents")
if not ui.service_answer(answer, "No incident matches this filter. The store is readable; it "
                                 "simply holds nothing like that."):
    st.stop()

st.caption("{:,} match the filter, {:,} listed.".format(answer["match_count"], answer["returned"]))

rows = [
    {
        "Incident": item["incident_id"],
        "Priority": item["priority"],
        "Status": item["status"],
        "Overdue": item["overdue"],
        "Age (min)": item["age_minutes"],
        "To ack (min)": item["lifecycle"]["minutes_to_acknowledge"],
        "To close (min)": item["lifecycle"]["minutes_to_close"],
        "Steps": item["lifecycle"]["transition_count"],
        "Module": item["source_module"],
        "Assigned": item["assigned_to"],
        "Summary": item["summary"],
    }
    for item in answer["incidents"]
]
st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

# One incident in full, including the history the fold produces

st.subheader("One incident in full")
ids = [item["incident_id"] for item in answer["incidents"]]
chosen = st.selectbox("Incident", ids)
incident = next(item for item in answer["incidents"] if item["incident_id"] == chosen)

detail_left, detail_right = st.columns([2, 3])
with detail_left:
    st.markdown("**%s**, %s, %s" % (incident["incident_id"], incident["priority"], incident["status"]))
    st.write(incident["summary"])
    st.markdown("**Recommended action.** " + str(incident["recommended_action"]))
    st.markdown(
        "**Assigned** to %s as %s, escalation contact %s."
        % (incident["assigned_to"], incident["assigned_role"], incident["escalation_contact"])
    )
    if incident.get("operational_context_origin") == "simulated":
        st.caption(
            "The operational context on this incident is simulated: the shift, the assignee "
            "and the escalation contact are generated, and are labelled so wherever they are "
            "shown. The model evidence below is real."
        )

with detail_right:
    st.markdown("**Model evidence, as the module published it**")
    st.json(incident.get("evidence") or {}, expanded=False)
    st.caption(
        "Module %s, domain %s, event %s. `evidence` is open beyond its four required keys, so "
        "what is in it differs by module and no consumer has to know which one wrote it."
        % (incident["source_module"], incident["business_domain"], incident["event_id"])
    )

st.markdown("**Lifecycle**")
history = incident["lifecycle"]["history"]
if history:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Recorded": step["recorded_at"],
                    "From": step["from_status"],
                    "To": step["to_status"],
                    "By": step["actor"],
                    "Note": step["note"],
                    "Transition": step["transition_id"],
                }
                for step in history
            ]
        ),
        width="stretch",
        hide_index=True,
    )
else:
    st.info(
        "No transition has been recorded against this incident, so it is still in the state it "
        "was raised in."
    )
st.caption(
    "The incident record itself says `%s` and always will: it is written once, at intake, and "
    "never rewritten. The status above is the transition log folded onto it, which is why the "
    "history is the record rather than a display of one."
    % incident.get("raised_as", "new")
)

ui.source_note(
    "Every number on this page is computed by the n8n status API and read from it. This app "
    "performs no fold of its own.",
    "Contract, deployment record and boundaries: `n8n/README.md`. Process owner: "
    "`docs/Project_Charter.md` sections 7.1, 7.2 and 7.5.",
)
