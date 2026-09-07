"""Split an incident status API answer into a verdict and its payload.

The retry loop needs two different things out of one API Request node: a short
token it can compare against, and the body it must hand on when the call
succeeded. A Conditional Router compares text and routes a message, so the two
have to arrive on separate handles or the router ends up testing the payload.

The verdict deliberately has three values, not two:

- ``ok`` - a parsed body reporting ``status: ok``. Retrying this is pointless.
- ``outage`` - a parsed body reporting anything else, which is the status API
  saying in its own words that the store could not be read. This is a legible
  answer and the system was built to distinguish it from silence, so it is NOT
  retried: it is reported. Retrying an error the backend made legible delays the
  operator to hammer a service that has already said it is down.
- ``unreachable`` - no body, an unparseable body, or a transport-level failure.
  Nothing was said, so nothing is known, and this is the one case a retry can
  actually change.

Only ``unreachable`` routes into the retry loop. That distinction is the whole
reason this component exists rather than a plain "did it return 200" check.
"""

import json

from lfx.custom.custom_component.component import Component
from lfx.inputs.inputs import HandleInput
from lfx.schema.data import Data
from lfx.schema.dataframe import DataFrame
from lfx.schema.message import Message
from lfx.template.field.base import Output

UNREACHABLE = "unreachable"
OUTAGE = "outage"
OK = "ok"


class ArkonStatusGate(Component):
    display_name = "Status Gate"
    description = "Classify an incident status API answer as ok, outage or unreachable, and pass its body on."
    icon = "shield-check"
    name = "ArkonStatusGate"

    inputs = [
        HandleInput(
            name="response",
            display_name="API response",
            info="The Incident Status API node's output.",
            input_types=["Data", "DataFrame", "Message"],
        ),
    ]

    # Payload is declared FIRST on purpose. When this node ends a Loop body, the
    # loop aggregates the end vertex's first declared output whatever the feedback
    # edge is named; with verdict first, the retry loop collected three "ok"s and
    # no body at all (measured 2026-09-07).
    # group_outputs=True renders BOTH outputs as handles. Without it the UI draws only the
    # selected (first) output and, on its next save, deletes every edge that left the other one:
    # the deployed sub-flow lost three such edges when it was opened on 2026-09-07 at 16:03.
    outputs = [
        Output(display_name="Payload", name="payload", method="payload_output", types=["Message"], group_outputs=True),
        Output(display_name="Verdict", name="verdict", method="verdict_output", types=["Message"], group_outputs=True),
    ]

    def _body(self):
        """Return the answer as a dict, or None when nothing usable arrived.

        The API Request component wraps its answer differently depending on
        whether the response parsed as JSON, so unwrap the known envelopes
        rather than assuming one of them.
        """
        value = self.response
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, DataFrame):
            rows = value.to_data_list()
            value = rows[0] if rows else None
        if isinstance(value, Message):
            text = value.text or ""
            try:
                return json.loads(text)
            except (ValueError, TypeError):
                return None
        if isinstance(value, Data):
            payload = value.data if isinstance(value.data, dict) else {}
            for key in ("result", "response", "body", "data"):
                inner = payload.get(key)
                if isinstance(inner, dict) and inner:
                    return inner
                if isinstance(inner, str):
                    try:
                        return json.loads(inner)
                    except (ValueError, TypeError):
                        continue
            return payload or None
        if isinstance(value, dict):
            return value
        return None

    def _classify(self):
        """Classify fresh on every call, never from flow state.

        This node runs once per iteration inside the retry loop, and flow state
        is shared across iterations: a result cached under the node id on
        attempt 1 would be handed back unchanged on attempts 2 and 3, so a
        lookup that failed once and then answered would still read as failed.
        Parsing the body twice costs nothing next to the request it describes.
        """
        body = self._body()
        if not isinstance(body, dict) or "status" not in body:
            return UNREACHABLE, ""
        if body.get("status") == OK:
            return OK, json.dumps(body, ensure_ascii=False)
        return OUTAGE, json.dumps(body, ensure_ascii=False)

    def verdict_output(self) -> Message:
        verdict, _ = self._classify()
        self.status = verdict
        return Message(text=verdict)

    def payload_output(self) -> Message:
        _, payload = self._classify()
        return Message(text=payload)
