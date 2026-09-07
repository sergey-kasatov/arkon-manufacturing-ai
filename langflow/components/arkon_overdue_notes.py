"""Collect the loop's per-incident readings into one block for the NOTE line.

The briefing's four blocks are a contract, and two known defects live in them, so
the iteration is not allowed to change what OPEN, OVERDUE and WATCH look like.
What it is allowed to do is give the briefing agent something the single status
call never had: a separate reading of each overdue incident, made one at a time.

Those readings feed the NOTE block only. NOTE is defined as the one sentence
naming what the counts do not show, and until now it was written from the counts
themselves, which is the one source that by definition cannot show it. Fourteen
individual readings can say "four of these are one NHTSA batch from ninety-one
hours ago, none of them assigned"; a total of fourteen cannot.

The join is positional. The loop iterates its input list in order and appends one
result per item, so row *n* of the aggregate belongs to row *n* of the incident
list. The incident list is passed in as well rather than parsed back out of the
model's answer, because an id read back out of generated text is an id the model
could have changed.
"""

from lfx.custom.custom_component.component import Component
from lfx.inputs.inputs import HandleInput
from lfx.schema.data import Data
from lfx.schema.dataframe import DataFrame
from lfx.schema.message import Message
from lfx.template.field.base import Output

EMPTY = "none: no overdue incident was read individually."


class ArkonOverdueNotes(Component):
    display_name = "Overdue Notes"
    description = "Pair each loop result with its incident and render them as input for the NOTE block."
    icon = "notebook-pen"
    name = "ArkonOverdueNotes"

    inputs = [
        HandleInput(
            name="summaries",
            display_name="Loop results",
            info="The Loop node's Done output: one row per incident read.",
            input_types=["DataFrame", "Data", "Message"],
        ),
        HandleInput(
            name="incidents",
            display_name="Overdue incidents",
            info="The same list the loop iterated, for the ids. Joined by position.",
            input_types=["DataFrame", "Data", "Message"],
        ),
    ]

    outputs = [
        Output(display_name="Notes", name="notes", method="notes_output", types=["Message"]),
    ]

    @staticmethod
    def _rows(value):
        if isinstance(value, DataFrame):
            return value.to_data_list()
        if isinstance(value, Data):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Data)]
        return []

    @staticmethod
    def _text(row):
        """Pull the sentence out of a loop result row, whatever the model wrapped it in."""
        payload = row.data if isinstance(row.data, dict) else {}
        for key in ("text", "message", "result", "output", "parsed_text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())
        if isinstance(getattr(row, "text", None), str) and row.text.strip():
            return " ".join(row.text.split())
        return ""

    def notes_output(self) -> Message:
        results = self._rows(self.summaries)
        sources = self._rows(self.incidents)
        lines = []
        for index, row in enumerate(results):
            sentence = self._text(row)
            if not sentence:
                continue
            source = sources[index].data if index < len(sources) else {}
            incident_id = source.get("incident_id") if isinstance(source, dict) else None
            lines.append("%s: %s" % (incident_id or "incident %d" % (index + 1), sentence))
        self.status = "%d reading(s)" % len(lines)
        return Message(text="\n".join(lines) if lines else EMPTY)
