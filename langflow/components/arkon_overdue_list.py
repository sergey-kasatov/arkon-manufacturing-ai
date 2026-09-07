"""Turn one incident status answer into the list the briefing iterates over.

The status API answers a whole query in one call, so the assistant's incident
branch needs no iteration and deliberately has none. The shift briefing is the
one place where a per-record action earns its cost: its OVERDUE block is one
line per overdue incident, and each line is about that incident alone.

This component is the boundary between the two shapes. It takes the parsed
status body, keeps the incidents the store itself marked ``overdue``, sorts them
by how far past their acknowledgement window they are, and emits one row per
incident carrying only the fields the OVERDUE line and its one-sentence summary
need.

``limit`` exists because the loop costs one model call per row and the store is
live: it is 0 (no cap) by default so the block stays complete, and a positive
value is there for a rehearsal that must fit a demo slot. When it truncates, the
row count is still reported so the caller can say so out loud.
"""

import json

from lfx.custom.custom_component.component import Component
from lfx.inputs.inputs import HandleInput
from lfx.io import IntInput
from lfx.schema.data import Data
from lfx.schema.dataframe import DataFrame
from lfx.schema.message import Message
from lfx.template.field.base import Output

# Everything an OVERDUE line states, plus what a one-sentence summary needs.
CARRIED = (
    "incident_id",
    "priority",
    "unit",
    "age_minutes",
    "assigned_to",
    "assigned_role",
    "acknowledge_due_minutes",
    "status",
    "source_module",
    "summary",
    "recommended_action",
)


class ArkonOverdueList(Component):
    display_name = "Overdue List"
    description = "Select the overdue incidents from a status answer, one row each, most overdue first."
    icon = "list-ordered"
    name = "ArkonOverdueList"

    inputs = [
        HandleInput(
            name="payload",
            display_name="Status payload",
            info="The status API body, as text or Data.",
            input_types=["Message", "Data", "DataFrame"],
        ),
        IntInput(
            name="limit",
            display_name="Maximum rows",
            info="0 keeps every overdue incident. A positive value caps the loop for a timed rehearsal.",
            value=0,
            advanced=True,
        ),
    ]

    outputs = [
        Output(display_name="Overdue", name="overdue", method="overdue_output", types=["DataFrame"]),
    ]

    def _body(self):
        value = self.payload
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

    def overdue_output(self) -> DataFrame:
        body = self._body()
        incidents = body.get("incidents") or []
        overdue = [item for item in incidents if isinstance(item, dict) and item.get("overdue")]

        def past_window(item):
            age = item.get("age_minutes")
            due = item.get("acknowledge_due_minutes")
            if isinstance(age, (int, float)) and isinstance(due, (int, float)):
                return age - due
            return age if isinstance(age, (int, float)) else 0

        overdue.sort(key=past_window, reverse=True)
        if self.limit and self.limit > 0:
            overdue = overdue[: self.limit]

        rows = []
        for item in overdue:
            row = {field: item.get(field) for field in CARRIED}
            row["minutes_past_window"] = past_window(item)
            rows.append(Data(data=row))
        self.status = "%d overdue incident(s)" % len(rows)
        return DataFrame(rows)
