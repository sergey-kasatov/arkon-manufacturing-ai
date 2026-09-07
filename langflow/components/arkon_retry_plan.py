"""Emit the attempt plan the status retry loop iterates over.

The retry is a Loop, not a cycle and not a branch chain, and that is forced by
three measurements on this Langflow build rather than chosen:

- a graph cycle does not execute at all;
- a node that merges one live input with inputs coming from a stopped branch does
  not execute either, which rules out three conditional attempts converging on one
  resolve node;
- a Loop body does execute, once per row, and aggregates.

So the attempts become rows. Each row carries its number and the URL to call, the
loop body calls it once per row, and the resolve step downstream takes the first
answer and ignores the rest.

**The cost of that is real and is not hidden: every briefing issues `attempts`
requests, not just the ones it needs.** It is acceptable here for reasons that do
not generalise. The status lookup is an idempotent read on a service in the same
Docker network, about a quarter of a second per call, against a briefing that
already spends half a minute reading incidents. The escalation record API is a
write and is NOT retried anywhere in this system, precisely because an
unconditional retry of a write is a different thing entirely.
"""

from lfx.custom.custom_component.component import Component
from lfx.io import IntInput, MessageTextInput
from lfx.schema.data import Data
from lfx.schema.dataframe import DataFrame
from lfx.schema.message import Message
from lfx.template.field.base import Output


class ArkonRetryPlan(Component):
    display_name = "Retry Plan"
    description = "One row per status attempt, for the retry loop to iterate over."
    icon = "list-checks"
    name = "ArkonRetryPlan"

    inputs = [
        MessageTextInput(
            name="url",
            display_name="URL",
            info="The endpoint every attempt calls.",
        ),
        IntInput(
            name="attempts",
            display_name="Attempts",
            info="Total attempts, so 3 means one call and two retries.",
            value=3,
        ),
    ]

    outputs = [
        Output(display_name="Plan", name="plan", method="plan_output", types=["DataFrame"]),
    ]

    def plan_output(self) -> DataFrame:
        url = self.url.text if isinstance(self.url, Message) else (self.url or "")
        total = max(1, int(self.attempts or 1))
        rows = [Data(data={"attempt": index, "of": total, "url": url})
                for index in range(1, total + 1)]
        self.status = "%d attempt(s) planned" % total
        return DataFrame(rows)
