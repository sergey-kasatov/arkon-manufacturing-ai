"""Compose what the briefing agent reads, from four sources that arrive separately.

The briefing agent used to hold the status API as a tool and call it itself. It no
longer does: the retry chain and the per-incident loop both need the status body on
the flow path, and an agent that also calls the API would issue a second, unretried
request behind them.

So the agent becomes a formatter over supplied data, and this node assembles what it
formats. Four labelled sections, in a fixed order, because the agent's prompt refers
to them by name:

- the operator's own request, unchanged;
- the status body, or nothing when no attempt answered;
- one line saying which attempt answered, which the prompt turns into its own
  failure sentence when nothing did;
- the per-incident readings from the loop, which are input for the NOTE block only.

The four-block output contract is unchanged by all of this. OPEN, OVERDUE and WATCH
keep the fields they always had; the readings give NOTE something the counts cannot
show, which is what NOTE was defined to carry.

One line is computed here rather than left to the model: the open count per
priority. The store summary carries per-priority totals over the WHOLE store and a
single open count, and two runs of the same prompt read that pair two different
ways (one counted the open incidents by priority, the other printed the whole-store
totals beside the open count). Counting is not a job for a language model when the
list is right there, so the OPEN line's numbers are derived from the incident list
and handed over ready-made.
"""

import json

from lfx.custom.custom_component.component import Component
from lfx.io import MessageInput
from lfx.schema.message import Message
from lfx.template.field.base import Output

NO_STATUS = "(no status data: no attempt returned a readable answer)"
NO_NOTES = "(no per-incident readings)"


class ArkonBriefingInput(Component):
    display_name = "Briefing Input"
    description = "Assemble the request, the status body, the attempt note and the per-incident readings."
    icon = "layout-list"
    name = "ArkonBriefingInput"

    inputs = [
        MessageInput(name="request", display_name="Operator request"),
        MessageInput(name="status_payload", display_name="Status payload"),
        MessageInput(name="status_note", display_name="Attempt note"),
        MessageInput(name="incident_notes", display_name="Per-incident readings"),
    ]

    outputs = [
        Output(display_name="Briefing input", name="briefing_input", method="compose", types=["Message"]),
    ]

    @staticmethod
    def _text(value, fallback=""):
        if isinstance(value, Message):
            text = (value.text or "").strip()
        elif isinstance(value, str):
            text = value.strip()
        else:
            text = ""
        return text or fallback

    @staticmethod
    def _open_line(payload_text):
        """The OPEN line's numbers, counted from the incident list.

        Open means new, acknowledged or in_containment: the statuses the store's
        own `open_incidents` counter covers. Returns an empty string when the
        payload carries no incident list, so the model sees nothing to copy.
        """
        try:
            body = json.loads(payload_text)
        except (ValueError, TypeError):
            return ""
        incidents = body.get("incidents") if isinstance(body, dict) else None
        if not isinstance(incidents, list):
            return ""
        open_statuses = {"new", "acknowledged", "in_containment"}
        counts = {}
        for item in incidents:
            if isinstance(item, dict) and item.get("status") in open_statuses:
                key = item.get("priority") or "unset"
                counts[key] = counts.get(key, 0) + 1
        total = sum(counts.values())
        per_priority = ", ".join("%s: %d" % (key, counts[key]) for key in sorted(counts))
        return "%d open incidents (%s)" % (total, per_priority or "none by priority")

    def compose(self) -> Message:
        payload_text = self._text(self.status_payload)
        open_line = self._open_line(payload_text)
        parts = [
            "REQUEST:",
            self._text(self.request, "(no request text)"),
            "",
            "LOOKUP:",
            self._text(self.status_note, "(no attempt was recorded)"),
            "",
            "OPEN COUNT, computed from the incident list (use these numbers verbatim):",
            open_line or "(not computable: no incident list)",
            "",
            "STATUS DATA:",
            payload_text or NO_STATUS,
            "",
            "PER-INCIDENT READINGS (for the NOTE block only):",
            self._text(self.incident_notes, NO_NOTES),
        ]
        composed = "\n".join(parts)
        self.status = "%d characters" % len(composed)
        return Message(text=composed)
