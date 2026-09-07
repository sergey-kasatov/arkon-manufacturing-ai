"""Render the OPEN, OVERDUE and WATCH blocks in code, and place the model's NOTE beside them.

DEFECT-9 (found 2026-09-07): the briefing agent re-ordered the OVERDUE and WATCH lines
it was handed, intermittently and in both directions, although `arkon_overdue_list.py`
had sorted the rows before the model saw them. Two hypotheses were refuted the same
evening (not conversation context, not the main canvas re-rendering the sub-flow's
output), and a worked example in the prompt did not move WATCH. The model is the last
thing between a correct list and the operator, and it rewords by nature.

So the three blocks whose value is their exact content are rendered here, AFTER the
model, from the status body, and the model contributes exactly one thing: the NOTE
sentence. The rules are the contract `briefing_v2` stated in prose, now as code:

- OPEN: the open total and the count per priority, counted from the incident list
  (open = new, acknowledged, in_containment: the statuses the store's own
  `open_incidents` counter covers). The same count `arkon_briefing_input.py` hands
  the model, so the number the model reads and the number the operator reads cannot
  disagree.
- OVERDUE: one line per incident the store itself marked overdue, five fields in a
  fixed order, comma separated: id, priority, unit ("none" when the record carries
  none), age in minutes, assignee ("none" when unassigned). Oldest first by age, and
  a tie is broken by incident id, so two runs on the same store print the same block.
  "none" when nothing is overdue.
- WATCH: up to three incidents whose acknowledgement clock is still running and still
  has time left. A candidate passes three tests every record can answer: status is
  "new", the overdue flag is false, acknowledge_due_minutes is a number. Remaining
  minutes = acknowledge_due_minutes - age_minutes; fewest remaining first, ties by id;
  "none" when nothing qualifies. (The DEFECT-6 rule of the same day, unchanged.)
- NOTE: the model's sentence, taken as one line. A "NOTE:" label it may add and the
  closing line it may repeat are stripped; "nothing further" when it says nothing.

When the payload carries no incident list (no attempt answered, or the status API
reported itself unavailable), the briefing is the fixed lookup-failure sentence and
nothing else, which is what the prompt used to ask the model to write.
"""

import json

from lfx.custom.custom_component.component import Component
from lfx.inputs.inputs import HandleInput
from lfx.io import MessageInput
from lfx.schema.data import Data
from lfx.schema.dataframe import DataFrame
from lfx.schema.message import Message
from lfx.template.field.base import Output

FAILURE = ("The incident lookup failed, so I cannot tell you the current state. "
           "Please read the incident record directly.")
CLOSING = "Operational context is simulated."
NOTHING = "nothing further"
OPEN_STATUSES = ("new", "acknowledged", "in_containment")
WATCH_LIMIT = 3


def _num(value):
    """An integer prints as an integer; anything else prints as it is."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _field(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return "none"
    return str(value).strip()


def render_open(incidents):
    counts = {}
    for item in incidents:
        if isinstance(item, dict) and item.get("status") in OPEN_STATUSES:
            key = item.get("priority") or "unset"
            counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values())
    per_priority = ", ".join("%s: %d" % (key, counts[key]) for key in sorted(counts))
    return "%d open incidents (%s)" % (total, per_priority or "none by priority")


def render_overdue(incidents):
    rows = [item for item in incidents if isinstance(item, dict) and item.get("overdue")]

    def key(item):
        age = item.get("age_minutes")
        return (-(age if isinstance(age, (int, float)) else 0), str(item.get("incident_id") or ""))

    rows.sort(key=key)
    return [
        ", ".join([
            _field(item.get("incident_id")),
            _field(item.get("priority")),
            _field(item.get("unit")),
            _num(item.get("age_minutes")) if isinstance(item.get("age_minutes"), (int, float)) else "none",
            _field(item.get("assigned_to")),
        ])
        for item in rows
    ]


def render_watch(incidents):
    candidates = []
    for item in incidents:
        if not isinstance(item, dict):
            continue
        due, age = item.get("acknowledge_due_minutes"), item.get("age_minutes")
        if item.get("status") != "new" or item.get("overdue"):
            continue
        if not isinstance(due, (int, float)) or not isinstance(age, (int, float)):
            continue
        candidates.append((due - age, str(item.get("incident_id") or ""), _field(item.get("priority"))))
    candidates.sort(key=lambda row: (row[0], row[1]))
    return ["%s, %s, %s" % (row[1], row[2], _num(row[0])) for row in candidates[:WATCH_LIMIT]]


def render_note(text):
    lines = [" ".join(line.split()) for line in (text or "").splitlines()]
    lines = [line for line in lines if line and line != CLOSING]
    if not lines:
        return NOTHING
    note = " ".join(lines)
    if note.upper().startswith("NOTE:"):
        note = note[5:].strip()
    return note or NOTHING


def render_briefing(body, note_text):
    """The four blocks as one text, or the fixed failure sentence."""
    incidents = body.get("incidents") if isinstance(body, dict) else None
    if not isinstance(incidents, list):
        return FAILURE
    blocks = [
        "OPEN: " + render_open(incidents),
        "OVERDUE: " + "\n".join(render_overdue(incidents) or ["none"]),
        "WATCH: " + "\n".join(render_watch(incidents) or ["none"]),
        "NOTE: " + render_note(note_text),
        CLOSING,
    ]
    return "\n".join(blocks)


class ArkonBriefingAssemble(Component):
    display_name = "Briefing Assemble"
    description = "Render OPEN, OVERDUE and WATCH from the status body in code; take only the NOTE sentence from the model."
    icon = "list-checks"
    name = "ArkonBriefingAssemble"

    inputs = [
        HandleInput(
            name="status_payload",
            display_name="Status payload",
            info="The status API body the retry loop resolved, as text or Data.",
            input_types=["Message", "Data", "DataFrame"],
        ),
        MessageInput(
            name="note_text",
            display_name="Model NOTE",
            info="The briefing agent's answer; only its sentence is used.",
        ),
    ]

    outputs = [
        Output(display_name="Briefing", name="briefing", method="assemble", types=["Message"]),
    ]

    def _body(self):
        value = self.status_payload
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, DataFrame):
            rows = value.to_data_list()
            value = rows[0] if rows else None
        if isinstance(value, Message):
            try:
                return json.loads(value.text or "")
            except (ValueError, TypeError):
                return {}
        if isinstance(value, Data):
            return value.data if isinstance(value.data, dict) else {}
        if isinstance(value, dict):
            return value
        return {}

    def assemble(self) -> Message:
        note = self.note_text.text if isinstance(self.note_text, Message) else str(self.note_text or "")
        text = render_briefing(self._body(), note)
        self.status = "lookup failed" if text == FAILURE else "%d lines" % len(text.splitlines())
        return Message(text=text)
