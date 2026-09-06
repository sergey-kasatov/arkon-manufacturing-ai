"""The Arkon Quality Assistant, in the cockpit.

The same deployed canvas the Langflow Playground runs, reached through the v2
workflows API because a flow holding a Human Input node cannot be run through v1
at all, on any branch. Two things this surface does that the Playground does not.

It names the branch that answered. Which specialist replied is the execution
trace, and an operator is owed it as much as an examiner is.

And it does not reflow the answer. The shift briefing returns four blocks on
four lines because that is its contract, and a markdown renderer collapses a
single newline into a space, so the four blocks arrive as one paragraph. That is
the Playground's behaviour and it argues against the sub-flow's own point.
"""

import uuid

import streamlit as st

from utils import api, config, identity, ui

ui.page(
    "Arkon Quality Assistant",
    "The deployed Langflow canvas, including the approval gate in front of its one write",
)

MAX_POLLS = 90

# Session state. One Langflow session id per browser session, so the assistant
# keeps context across turns the way it does in a demo.

state = st.session_state

# The session id lives in the URL, not only in memory. It used to be minted fresh on
# every page load and never read back, so a reload started an empty conversation over
# a store that still held the last one: Langflow persists every message keyed by this
# id, so what was thrown away was the pointer rather than the history. Carrying it in
# the query string, the way the Steering Cell page carries ?incident=, means a reload
# resumes and a link to a conversation can be handed to somebody else.
from_url = str(st.query_params.get("session", "")).strip()
if from_url and state.get("session_id") != from_url:
    state.session_id = from_url
    state.pop("messages", None)
state.setdefault("session_id", "cockpit-" + uuid.uuid4().hex[:12])
if st.query_params.get("session") != state.session_id:
    st.query_params["session"] = state.session_id

state.setdefault("job", None)
state.setdefault("pending", None)
state.setdefault("polls", 0)
if "messages" not in state:
    # Reload the turns Langflow already holds for this session, so a refresh does not
    # look like an erased conversation.
    state.messages = [
        {"role": turn["role"], "branch": turn["branch"], "text": turn["text"]}
        for turn in api.history(state.session_id)
    ]

with st.sidebar:
    me = identity.picker()
    st.divider()
    st.subheader("Session")
    st.code(state.session_id, language=None)
    st.caption(
        "This id is in the page URL, so a reload resumes the conversation and the link "
        "can be shared. Starting a new session abandons this one; it is not deleted, and "
        "pasting the id back into the URL reopens it."
    )
    if st.button("Start a new session", width="stretch"):
        for key in ("messages", "job", "pending", "polls"):
            state.pop(key, None)
        state.session_id = "cockpit-" + uuid.uuid4().hex[:12]
        st.query_params["session"] = state.session_id
        st.rerun()
    st.caption("Flow `%s` on %s" % (config.ASSISTANT_FLOW, config.LANGFLOW_URL))

if not config.LANGFLOW_API_KEY:
    st.error(
        "This page needs a Langflow API key in `ARKON_LANGFLOW_API_KEY`. It is passed in by "
        "the environment and is deliberately not in the repository: on the NAS it belongs in "
        "the compose file beside the other secrets."
    )
    st.info(
        "The rest of the cockpit does not need it. The Steering Cell pages read n8n, which "
        "needs no credential on the LAN."
    )
    st.stop()


def render(message):
    with st.chat_message(message["role"]):
        if message.get("branch"):
            st.caption(message["branch"])
        # Two trailing spaces make a markdown hard break, so a line the agent put
        # on its own line stays on its own line. Prose is unaffected: it separates
        # paragraphs with a blank line, which survives either way.
        st.markdown(message["text"].replace("\n", "  \n"))


for message in state.messages:
    render(message)

# One turn is a small state machine across reruns: start it, poll it, and either
# answer its approval request or show what it returned.

if state.job:
    try:
        step = api.poll_turn(state.job["flow"], state.job["id"])
    except api.AssistantError as error:
        state.messages.append({"role": "assistant", "branch": "error", "text": str(error)})
        state.job = None
        state.pending = None
        st.rerun()

    if step["state"] == "done":
        answers = step["answers"]
        if not answers:
            state.messages.append(
                {"role": "assistant", "branch": step["status"],
                 "text": "The run finished with status `%s` and produced no answer." % step["status"]}
            )
        for branch, text in answers:
            state.messages.append({"role": "assistant", "branch": branch, "text": text})
        state.job = None
        state.pending = None
        state.polls = 0
        st.rerun()

    elif step["state"] == "paused":
        state.pending = step["request"]

    else:
        state.polls += 1
        if state.polls > MAX_POLLS:
            state.messages.append(
                {"role": "assistant", "branch": "timeout",
                 "text": "The run did not finish. Check the flow in Langflow."}
            )
            state.job = None
            state.polls = 0
            st.rerun()
        with st.chat_message("assistant"):
            st.caption("running, poll %d" % state.polls)
        st.rerun()

# The approval gate. Nothing reaches the escalation endpoint unless a human
# presses one of these, which is the point of the gate rather than a formality.

if state.pending:
    request = state.pending
    options = [option.get("label") for option in request.get("options", [])] or ["Approve", "Reject"]
    with st.chat_message("assistant"):
        st.warning(
            "The run has paused at the approval gate. It is asking for a decision before it "
            "records anything, and nothing is written until one is given."
        )
        columns = st.columns(len(options))
        for column, label in zip(columns, options):
            if column.button(label, key="decide_" + label, width="stretch"):
                api.resume_turn(state.job["id"], request.get("request_id"), label)
                state.messages.append({"role": "user", "branch": "at the approval gate", "text": label})
                state.pending = None
                st.rerun()

# Input, disabled while a turn is in flight so two runs cannot share a session.

question = st.chat_input("Ask about a rule, an incident, or request an escalation",
                         disabled=bool(state.job))
if question:
    state.messages.append({"role": "user", "text": question})
    try:
        flow = api.flow_id()
        # Who is asking travels with the question on its own first line, and the
        # prompts read it. It is not decoration: charter 7.2 gives closure to the
        # Quality Manager and the other four moves to the assignee, so an answer
        # about what to do next depends on which of them is reading it; and the
        # escalation record, the one write this assistant can make, carried
        # `requested_by: arkon-quality-assistant` until it had a name to put there.
        # The transcript shows the question the operator typed, not this line.
        sent = question
        if me:
            sent = "[operator: %s, %s]\n%s" % (me["name"], me["role"], question)
        state.job = {"id": api.start_turn(flow, sent, state.session_id), "flow": flow}
        state.polls = 0
    except api.AssistantError as error:
        state.messages.append({"role": "assistant", "branch": "error", "text": str(error)})
    st.rerun()

if not state.messages:
    st.info(
        "Six routes: a quality rule answered from the document store, live incident status, "
        "the shift briefing, an escalation request behind the approval gate, and two fixed "
        "replies for a request that is unclear or out of scope."
    )
    ui.source_note(
        "Try: what makes an incident P1, what is ARK-INC-00012 doing right now, or ask it to "
        "acknowledge and close an incident and watch it decline.",
        "Canvas, routes and known gaps: `langflow/README.md`.",
    )
