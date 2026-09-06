"""The Quality Steering Cell, live.

Charter 7.5, the operational cockpit. It reads incidents through the status API
and never opens the JSONL store, for a reason worth stating on the page itself:
the store holds the state an incident was raised in and holds it for ever, and
the API is what folds the transition log onto it. A cockpit reading the file
directly would show 29 new incidents and never anything else.
"""

import pandas as pd
import streamlit as st

from utils import api, config, identity, modules, ui

ui.page("Quality Steering Cell", "Live incident state, read through the n8n status API")

# Controls

with st.sidebar:
    me = identity.picker()
    st.divider()
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

# What needs a person now. Read across every open state, independent of the
# sidebar filter, so the operator's queue is never hidden by a filter or by the
# page size. Overdue first, then priority, then the oldest. Added 2026-09-05 on
# Sergey's instruction: a person who received a card has to find the incident at
# once, and the controls to move it have to be right there.

OPEN_STATES = ["new", "acknowledged", "in_containment", "resolved"]
RANK = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}

catalogue = {item["incident_id"]: item for item in answer["incidents"]}
queue, unreadable = [], []
for state in OPEN_STATES:
    page_of_state = api.incidents(status=state, limit=50)
    if not api.reachable(page_of_state):
        unreadable.append(state)
        continue
    for item in page_of_state["incidents"]:
        catalogue[item["incident_id"]] = item
        queue.append(item)
queue.sort(key=lambda i: (not i["overdue"], RANK.get(i["priority"], 9), -(i["age_minutes"] or 0)))


def window_text(item):
    """Minutes left in the acknowledgement window, or how far past it."""
    due = item.get("acknowledge_due_minutes")
    if item["status"] != "new" or due is None:
        return ""
    left = due - (item["age_minutes"] or 0)
    return "overdue by %d min" % -left if left < 0 else "%d min left" % left


st.subheader("Needs a person now")
if unreadable:
    st.warning(
        "The status API did not answer for %s, so this queue may be short. A failed lookup is "
        "not an empty queue." % ", ".join(unreadable)
    )
people = sorted({i["assigned_to"] for i in queue if i.get("assigned_to")})
who = st.selectbox("Assigned to", ["anyone"] + people)
mine = [i for i in queue if who == "anyone" or i["assigned_to"] == who]
if not mine:
    st.success("Nothing open%s." % ("" if who == "anyone" else " for " + who))
else:
    # "Waiting on a person" rather than "open", and the word matters. This queue
    # deliberately includes `resolved`, which is still waiting for the Quality
    # Manager to close it, while the store's own `open_incidents` does not - so
    # calling both of them "open" put 37 on this page beside 36 on the executive
    # view, two numbers for one word in one app. The queue's definition is the
    # useful one for an operator; it just is not the store's, so it does not
    # borrow the store's word.
    st.caption(
        "%d waiting on a person, %d overdue. The %d most urgent: overdue first, then priority, "
        "then the oldest. P3 and P4 carry no window and wait for the daily review. This count "
        "includes resolved incidents awaiting the Quality Manager's closure, which the store's "
        "own Open figure does not."
        % (len(mine), sum(1 for i in mine if i["overdue"]), min(10, len(mine)))
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Incident": i["incident_id"],
                    "Priority": i["priority"],
                    "Status": i["status"],
                    "Window": window_text(i),
                    "Assigned": i["assigned_to"],
                    "Module": i["source_module"],
                    "Summary": i["summary"],
                }
                for i in mine[:10]
            ]
        ),
        width="stretch",
        hide_index=True,
    )

ordered = [i["incident_id"] for i in mine] + [k for k in catalogue if k not in {i["incident_id"] for i in mine}]
if not ordered:
    st.info("The store holds nothing to work on and nothing matches the filter.")
    st.stop()
# A link can open the page on one incident (?incident=ARK-INC-00047), so a card or a
# chat answer can point straight at the record instead of at the page.
wanted = str(st.query_params.get("incident", "")).strip().upper()
chosen = st.selectbox("Work on", ordered, index=ordered.index(wanted) if wanted in ordered else 0)
incident = catalogue[chosen]

# The chosen incident in full, including the history the fold produces

st.subheader("The incident in full")

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

# Move this incident: the operator's controls, added 2026-09-05 on Sergey's decision.
# Until then this page was read-only and the only way to acknowledge or close an
# incident was a script; app/README.md records both the old reason and the new one.
# What is offered comes from the charter 7.2 machine, but the endpoint stays the
# authority: an illegal move is refused with 409 and the answer is shown as it came.

ALLOWED_NEXT = {
    "new": ["acknowledged", "false_positive"],
    "acknowledged": ["in_containment", "resolved", "false_positive"],
    "in_containment": ["resolved", "false_positive"],
    "resolved": ["closed", "in_containment", "false_positive"],
    "closed": [],
    "false_positive": [],
}
WHAT_IT_MEANS = {
    "acknowledged": "I have seen it and I am on it. The response window is measured against this step.",
    "in_containment": "The unit, part or coil is held so the condition cannot spread while it is looked at.",
    "resolved": "The work is done and the condition is gone. Closure review is still outstanding.",
    "closed": "Reviewed and closed by the Quality Manager. Final.",
    "false_positive": "Looked at, nothing found. Kept for threshold tuning. Final.",
}

st.subheader("Move this incident")
options = ALLOWED_NEXT.get(incident["status"], [])
if not options:
    st.info("`%s` is final. Nothing moves out of it." % incident["status"])
else:
    st.caption(
        "The four moves are the assignee's; closing is the Quality Manager's (%s). Every move is "
        "recorded with the time and the name you give, and the response-time KPIs are computed "
        "from those timestamps." % incident["escalation_contact"]
    )
    with st.form("move_" + incident["incident_id"]):
        to_status = st.selectbox(
            "Next state", options, format_func=lambda s: "%s. %s" % (s, WHAT_IT_MEANS[s])
        )
        # Defaulted to whoever is at the screen, NOT to the incident's assignee.
        # It used to default to the assignee, which made the easiest thing an
        # operator could do a move recorded under someone else's name - in the log
        # that every response-time number on this platform is computed from.
        actor = st.text_input(
            "Recorded as", value=identity.name(),
            help="Set who you are in the sidebar and this fills itself.",
        )
        note = st.text_input("Note", placeholder="what was done, in one line")
        submitted = st.form_submit_button("Record transition")
    if submitted:
        if not actor.strip():
            st.warning("Say who you are, in the sidebar or in the field, before recording a move.")
            st.stop()
        if to_status == "closed" and me and not identity.is_quality_manager():
            st.warning(
                "Charter 7.2 gives closure to the Quality Manager (%s). Recording it as %s "
                "anyway; the log will say so."
                % (incident["escalation_contact"], actor.strip())
            )
        if actor.strip() != (incident["assigned_to"] or "") :
            st.caption(
                "Recorded as %s, who is not this incident's assignee (%s). That is allowed and "
                "the log keeps both names." % (actor.strip(), incident["assigned_to"])
            )
        reply = api.transition(
            incident["incident_id"], to_status, actor.strip() or "human operator", note.strip()
        )
        code = reply.get("http_status")
        if reply.get("status") == "transition_recorded":
            window = reply.get("acknowledged_within_window")
            st.success(
                "%s: %s -> %s, %s min after the raise%s."
                % (reply.get("transition_id"), reply.get("from_status"), reply.get("to_status"),
                   reply.get("minutes_since_created"),
                   "" if window is None else (", inside the window" if window else ", OUTSIDE the window"))
            )
            st.rerun()
        elif code == 409:
            st.warning(
                "Refused: the incident is `%s` now and can only move to %s. Someone moved it since "
                "this page was read; refresh."
                % (reply.get("current_status"), ", ".join(reply.get("allowed_next") or []))
            )
        elif code in (400, 404):
            st.error("Refused: %s" % "; ".join(reply.get("errors") or [reply.get("message", "rejected")]))
        else:
            st.error(
                "Not recorded: the transition endpoint did not answer (%s). Nothing changed; do "
                "not assume the move happened." % reply.get("message", code)
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

ui.source_note(
    "Every number on this page is computed by the n8n status API and read from it. This app "
    "performs no fold of its own.",
    "Contract, deployment record and boundaries: `n8n/README.md`. Process owner: "
    "`docs/Project_Charter.md` sections 7.1, 7.2 and 7.5.",
)
