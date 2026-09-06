"""Who is at the screen, chosen once and shared by every page.

The cockpit knew who each incident was ASSIGNED to and never who was USING it, and
the two are not the same person. Two consequences, and neither is cosmetic.

The transition form defaulted "Recorded as" to the incident's assignee, so the
easiest thing an operator could do was record a move under somebody else's name.
The transition log is the evidence for every response-time number this platform
publishes, and a log whose actor column is a default rather than a person is not
evidence.

And the assistant did not know who it was talking to, so the one write it can
perform - the escalation record - went in as `requested_by: arkon-quality-assistant`,
`approved_by: operator via approval gate`. The platform's only audited action was
anonymous.

**This is a name, not an authentication.** There is no login anywhere in this
deployment, so what this module provides is attribution offered by the person
themselves: it makes the honest case easy and the careless case visible, and it
would not survive anyone who wanted to lie. That boundary is in `app/README.md`
under Known boundaries, and widening it means real authentication rather than a
better selector.
"""

import streamlit as st

from utils import api

STATE_KEY = "arkon_identity"

# Charter 7.2 puts closure with the Quality Manager and the other four moves with
# the assignee, so the role is not decoration: it decides what the person can do
# and what the assistant should tell them.
QUALITY_MANAGER = "Quality Manager"


def roster():
    """Everyone the store knows, as (name, role) pairs.

    Derived from the incidents themselves rather than typed into this file, so it
    follows the plant instead of going stale beside it. The escalation contact is
    added as the Quality Manager: charter 7.2 gives closure to that role alone, and
    they appear on every incident without ever being an assignee.
    """
    answer = api.incidents(limit=500)
    if not api.reachable(answer):
        return []

    people = {}
    for incident in answer.get("incidents", []):
        name, role = incident.get("assigned_to"), incident.get("assigned_role")
        if name and name != "unassigned":
            people.setdefault(name, role or "Steering Cell")
        contact = incident.get("escalation_contact")
        if contact:
            people.setdefault(contact, QUALITY_MANAGER)
    return sorted(people.items())


def current():
    """The chosen identity as {"name", "role"}, or None if nobody has chosen."""
    return st.session_state.get(STATE_KEY)


def name():
    chosen = current()
    return chosen["name"] if chosen else ""


def is_quality_manager():
    chosen = current()
    return bool(chosen) and chosen["role"] == QUALITY_MANAGER


def picker(container=None):
    """Render the identity selector. Called once per page, in the sidebar.

    The default is deliberately nobody: a pre-selected name is a name somebody
    else's transition gets recorded under, which is the defect this module exists
    to remove rather than to move somewhere quieter.
    """
    target = container or st.sidebar
    people = roster()
    if not people:
        target.caption("Signed in as: the store did not answer, so no roster.")
        return None

    labels = ["not set"] + ["%s - %s" % (n, r) for n, r in people]
    chosen = current()
    index = 0
    if chosen:
        wanted = "%s - %s" % (chosen["name"], chosen["role"])
        if wanted in labels:
            index = labels.index(wanted)

    picked = target.selectbox(
        "You are", labels, index=index,
        help="Used to attribute the transitions you record and the escalations you "
             "approve. This is a name you give, not a login: nothing here authenticates it.",
    )
    if picked == "not set":
        st.session_state.pop(STATE_KEY, None)
        target.caption("Set this before recording a transition.")
        return None

    person, role = picked.split(" - ", 1)
    st.session_state[STATE_KEY] = {"name": person, "role": role}
    return st.session_state[STATE_KEY]
