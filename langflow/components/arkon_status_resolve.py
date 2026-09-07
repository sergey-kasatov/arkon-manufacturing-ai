"""Take the best answer out of the retry loop's attempts, and say which one it was.

The loop calls the status API once per planned attempt and aggregates one row per
call. This node reads that aggregate, keeps the first row that reports
``status: ok``, and writes one line saying which attempt answered. Everything
after it sees a single payload and never has to know how many calls it took.

Three answers are distinguished, and only the third one is silence:

- **ok** - a body reporting ``status: ok``. Used, and the attempt number reported.
- **outage** - a body reporting anything else. That is the status API saying in its
  own words that the store could not be read, which is a legible answer and is
  passed on as one. The system was built to tell this apart from silence.
- **nothing** - no body, or nothing that parses. Only this is worth another call.

The distinction survives the rebuild on purpose. The first version of this design
retried nothing at all and defended that choice; the retry added here does not undo
it, because retrying a 503 the backend deliberately made legible would still be a
regression.
"""

import json

from lfx.custom.custom_component.component import Component
from lfx.inputs.inputs import HandleInput
from lfx.schema.data import Data
from lfx.schema.dataframe import DataFrame
from lfx.schema.message import Message
from lfx.template.field.base import Output


class ArkonStatusResolve(Component):
    display_name = "Resolve Attempts"
    description = "Pick the answering attempt out of the retry loop, or report that none answered."
    icon = "check-check"
    name = "ArkonStatusResolve"

    inputs = [
        HandleInput(
            name="attempts",
            display_name="Attempts",
            info="The retry loop's Done output: one row per call.",
            input_types=["DataFrame", "Data", "Message"],
        ),
    ]

    # group_outputs=True renders BOTH outputs as handles. Without it the UI draws only the
    # selected (first) output and, on its next save, deletes every edge that left the other one:
    # the deployed sub-flow lost three such edges when it was opened on 2026-09-07 at 16:03.
    outputs = [
        Output(display_name="Payload", name="payload", method="payload_output", types=["Message"], group_outputs=True),
        Output(display_name="Note", name="note", method="note_output", types=["Message"], group_outputs=True),
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
        payload = row.data if isinstance(row.data, dict) else {}
        for key in ("text", "message", "result", "output", "parsed_text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        if isinstance(getattr(row, "text", None), str) and row.text.strip():
            return row.text.strip()
        return ""

    def _resolve(self):
        """Return (payload, note). Cached, because both outputs are built separately."""
        if self.ctx.get("%s_done" % self._id):
            return self.ctx.get("%s_payload" % self._id), self.ctx.get("%s_note" % self._id)

        texts = [self._text(row) for row in self._rows(self.attempts)]
        payload, note, outage = "", "", ""

        for index, text in enumerate(texts, start=1):
            if not text:
                continue
            try:
                body = json.loads(text)
            except (ValueError, TypeError):
                continue
            if not isinstance(body, dict) or "status" not in body:
                continue
            if body.get("status") == "ok":
                payload = text
                note = ("The incident lookup answered on the first attempt."
                        if index == 1 else
                        "The incident lookup answered on attempt %d of %d." % (index, len(texts)))
                break
            outage = outage or text

        if not payload:
            tried = len(texts) or 1
            if outage:
                payload = outage
                note = ("The incident status service reported itself unavailable on %d attempt(s). "
                        "The store could not be read." % tried)
            else:
                note = "The incident status service did not answer on %d attempt(s)." % tried

        self.update_ctx({
            "%s_payload" % self._id: payload,
            "%s_note" % self._id: note,
            "%s_done" % self._id: True,
        })
        return payload, note

    def payload_output(self) -> Message:
        payload, _ = self._resolve()
        return Message(text=payload)

    def note_output(self) -> Message:
        _, note = self._resolve()
        self.status = note
        return Message(text=note)
